import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BOT_TOKEN = os.environ.get("EBLANNFT_BOT_TOKEN", "").strip()
SERVER_URL = os.environ.get("EBLANNFT_SERVER_URL", "http://127.0.0.1:8787").rstrip("/")
PLUGIN_KEY = os.environ.get("EBLANNFT_PLUGIN_KEY", "").strip()
ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("EBLANNFT_BOT_ADMINS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
STATES = {}

ALLOWED_UPDATE_FILES = {
    "eblannft_beta.plugin": "eblannft_beta.plugin",
    "__init__.py": "eblannft_beta_runtime/__init__.py",
    "plugin.py": "eblannft_beta_runtime/plugin.py",
    "sync_client.py": "eblannft_beta_runtime/sync_client.py",
    "legacy_gifts.py": "eblannft_beta_runtime/legacy_gifts.py",
}
PUBLISH_MAX_FILE_BYTES = 16 * 1024 * 1024


def now_ts():
    return int(time.time())


def http_json(method, url, body=None, headers=None, timeout=12):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        h["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=data, method=method, headers=h)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def tg(method, payload=None):
    return http_json("POST", f"{API}/{method}", body=payload or {})


def server(method, path, body=None):
    headers = {}
    if PLUGIN_KEY:
        headers["X-Plugin-Key"] = PLUGIN_KEY
    return http_json(method, f"{SERVER_URL}{path}", body=body, headers=headers)


def server_raw(method, path, raw_body, content_type="application/octet-stream"):
    headers = {"Content-Type": content_type}
    if PLUGIN_KEY:
        headers["X-Plugin-Key"] = PLUGIN_KEY
    req = Request(f"{SERVER_URL}{path}", data=raw_body or b"", method=method, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_tg_file(file_id):
    res = tg("getFile", {"file_id": file_id})
    file_path = (((res or {}).get("result") or {}).get("file_path") or "").strip()
    if not file_path:
        raise RuntimeError("no file_path in getFile response")
    req = Request(f"{FILE_API}/{file_path}")
    with urlopen(req, timeout=60) as resp:
        return resp.read()


VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def extract_version_from_plugin_bytes(data):
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = VERSION_RE.search(text)
    return m.group(1).strip() if m else ""


def send(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return tg("sendMessage", payload)
    except Exception:
        return None


def answer_callback(callback_id, text=""):
    try:
        tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
    except Exception:
        pass


def is_admin(user_id):
    if not ADMIN_IDS:
        return True
    try:
        return int(user_id) in ADMIN_IDS
    except Exception:
        return False


def normalize_target(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        uid = int(raw)
        return {"entity_type": "user" if uid > 0 else "chat", "entity_id": uid, "title": raw}
    m = re.search(r"(?:https?://)?t\.me/(?:c/)?([A-Za-z0-9_+\-]+)", raw)
    username = ""
    if raw.startswith("@"):
        username = raw[1:]
    elif m:
        username = m.group(1)
    if username:
        if username.startswith("+"):
            return None
        try:
            res = tg("getChat", {"chat_id": "@" + username})
            chat = (res or {}).get("result") or {}
            cid = int(chat.get("id") or 0)
            ctype = str(chat.get("type") or "")
            title = chat.get("title") or chat.get("username") or username
            return {
                "entity_type": "chat" if ctype in {"channel", "supergroup", "group"} or cid < 0 else "user",
                "entity_id": cid,
                "title": str(title),
            }
        except Exception:
            return None
    return None


def extract_custom_emoji_id(message):
    text = message.get("text") or message.get("caption") or ""
    m = re.search(r'emoji-id=["\']?(\d{8,})["\']?', text)
    if m:
        return int(m.group(1))
    for ent in message.get("entities") or message.get("caption_entities") or []:
        cid = ent.get("custom_emoji_id")
        if cid:
            try:
                return int(cid)
            except Exception:
                pass
    if text.strip().isdigit():
        return int(text.strip())
    return 0


def badge_key(entity):
    return f"{entity['entity_type']}:{int(entity['entity_id'])}"


def upsert_badge(chat_id, state):
    entity = state["entity"]
    payload = {
        "entity_type": entity["entity_type"],
        "entity_id": int(entity["entity_id"]),
        "icon_emoji_id": int(state["icon_emoji_id"]),
        "text": state["text"],
        "text_markdown": state["text_markdown"],
        "enabled": True,
        "updated_at": now_ts(),
        "updated_by": int(chat_id),
    }
    res = server("PUT", f"/api/v1/badges/{quote(badge_key(entity), safe='')}", payload)
    return res.get("ok")


def delete_badge(key):
    return server("DELETE", f"/api/v1/badges/{quote(key, safe='')}").get("ok")


def list_badges():
    res = server("GET", "/api/v1/badges")
    return res.get("badges") or []


def start_flow(chat_id):
    STATES[chat_id] = {"step": "target"}
    send(chat_id, "Пришли <b>user id</b>, <b>@username</b> или ссылку <code>https://t.me/...</code> на канал/аккаунт.")


def start_publish_flow(chat_id):
    STATES[chat_id] = {
        "mode": "publish",
        "step": "collect",
        "files": {},        # rel_path -> bytes
        "version": "",
        "notes": "",
    }
    send(
        chat_id,
        (
            "Пришли новые файлы плагина <b>как документы</b> (не сжатые).\n"
            "Принимаются:\n"
            "• <code>eblannft_beta.plugin</code>\n"
            "• <code>plugin.py</code>, <code>__init__.py</code>, <code>sync_client.py</code>, <code>legacy_gifts.py</code> (попадут в <code>eblannft_beta_runtime/</code>)\n\n"
            "Когда всё пришлёшь — отправь <code>/done</code>. Отмена: <code>/cancel</code>."
        ),
    )


def publish_handle_document(chat_id, state, msg):
    doc = msg.get("document") or {}
    raw_name = (doc.get("file_name") or "").strip()
    file_id = doc.get("file_id") or ""
    size = int(doc.get("file_size") or 0)
    if not raw_name or not file_id:
        send(chat_id, "Документ без имени — пропускаю. Пришли как файл, не как фото/архив.")
        return
    if size > PUBLISH_MAX_FILE_BYTES:
        send(chat_id, f"Файл {raw_name} слишком большой ({size} байт).")
        return
    rel = ALLOWED_UPDATE_FILES.get(raw_name)
    if not rel:
        send(
            chat_id,
            f"Не понял <code>{raw_name}</code>. Допустимые имена: " + ", ".join(f"<code>{k}</code>" for k in ALLOWED_UPDATE_FILES),
        )
        return
    try:
        data = fetch_tg_file(file_id)
    except Exception as e:
        send(chat_id, f"Не смог скачать <code>{raw_name}</code>: <code>{str(e)[:200]}</code>")
        return
    state["files"][rel] = data
    if rel == "eblannft_beta.plugin":
        ver = extract_version_from_plugin_bytes(data)
        if ver:
            state["version"] = ver
    have = "\n".join(f"• <code>{r}</code> ({len(b)}b)" for r, b in state["files"].items())
    ver_line = f"\n\nверсия из .plugin: <b>{state['version']}</b>" if state.get("version") else ""
    send(chat_id, f"Принял <code>{rel}</code>.\n\nСейчас в очереди:\n{have}{ver_line}\n\nЕщё файлы — пришли. Готово — <code>/done</code>.")


def publish_finalize(chat_id, state):
    files = state.get("files") or {}
    if not files:
        send(chat_id, "Ничего не прислал — нечего публиковать. /cancel чтобы выйти.")
        return
    version = (state.get("version") or "").strip()
    if not version:
        state["step"] = "version"
        send(chat_id, "Пришли строку версии (например <code>1.0.9</code>):")
        return
    state["step"] = "notes"
    send(chat_id, f"Версия: <b>{version}</b>. Пришли release notes одной репликой (или <code>-</code> чтобы оставить пустыми):")


def publish_upload_all(chat_id, state):
    files = state.get("files") or {}
    version = (state.get("version") or "").strip()
    notes = (state.get("notes") or "").strip()
    if not files or not version:
        send(chat_id, "Состояние сломалось, начни /publish заново.")
        STATES.pop(chat_id, None)
        return
    uploaded = []
    for rel, data in files.items():
        try:
            server_raw("PUT", f"/updates/files/{quote(rel, safe='/')}", data)
            uploaded.append(rel)
        except Exception as e:
            send(chat_id, f"Не смог залить <code>{rel}</code>: <code>{str(e)[:200]}</code>")
            return
    manifest = {
        "version": version,
        "notes": notes,
        "files": list(files.keys()),
    }
    try:
        server("PUT", "/updates/manifest.json", manifest)
    except Exception as e:
        send(chat_id, f"Файлы залиты, но manifest упал: <code>{str(e)[:200]}</code>")
        return
    STATES.pop(chat_id, None)
    files_block = "\n".join(f"• <code>{r}</code>" for r in uploaded)
    notes_block = f"\n\nnotes:\n<code>{notes}</code>" if notes else ""
    send(chat_id, f"✓ Опубликовано <b>v{version}</b>\n\n{files_block}{notes_block}")


def handle_message(msg):
    chat_id = int(msg["chat"]["id"])
    user_id = int((msg.get("from") or {}).get("id") or 0)
    text = msg.get("text") or ""
    if not is_admin(user_id):
        send(chat_id, "Нет доступа.")
        return
    if text.startswith("/start"):
        send(chat_id, "Бот eblanNFT.", {
            "inline_keyboard": [
                [{"text": "Выдать / изменить бейдж", "callback_data": "new"}],
                [{"text": "Список бейджей", "callback_data": "list"}],
                [{"text": "Опубликовать апдейт", "callback_data": "publish"}],
            ]
        })
        return
    if text.startswith("/cancel"):
        if STATES.pop(chat_id, None) is not None:
            send(chat_id, "Отменено.")
        else:
            send(chat_id, "Активной операции нет.")
        return
    if text.startswith("/publish"):
        start_publish_flow(chat_id)
        return
    if text.startswith("/done"):
        st = STATES.get(chat_id)
        if st and st.get("mode") == "publish":
            publish_finalize(chat_id, st)
        else:
            send(chat_id, "Активной публикации нет.")
        return
    if text.startswith("/new"):
        start_flow(chat_id)
        return
    if text.startswith("/list"):
        show_list(chat_id)
        return
    state = STATES.get(chat_id)
    if state and state.get("mode") == "publish":
        step = state.get("step")
        if msg.get("document"):
            publish_handle_document(chat_id, state, msg)
            return
        if step == "version":
            v = text.strip()
            if not v:
                send(chat_id, "Пустая версия. Пришли строку вида <code>1.0.9</code>.")
                return
            state["version"] = v
            publish_finalize(chat_id, state)
            return
        if step == "notes":
            notes = text.strip()
            if notes == "-":
                notes = ""
            state["notes"] = notes
            publish_upload_all(chat_id, state)
            return
        if step == "collect":
            send(chat_id, "Жду документы. Когда всё пришлёшь — <code>/done</code>, отмена — <code>/cancel</code>.")
            return
    if not state:
        send(chat_id, "Команды: /new, /list, /publish")
        return
    step = state.get("step")
    if step == "target":
        entity = normalize_target(text)
        if not entity:
            send(chat_id, "Не смог распознать цель. Пришли user id, @username или ссылку t.me.")
            return
        state["entity"] = entity
        state["step"] = "emoji"
        send(chat_id, f"Цель: <code>{badge_key(entity)}</code>\nТеперь пришли premium emoji или tg-emoji tag.")
        return
    if step == "emoji":
        emoji_id = extract_custom_emoji_id(msg)
        if emoji_id <= 0:
            send(chat_id, "Не увидел custom_emoji_id. Пришли premium emoji или <code>&lt;tg-emoji emoji-id=\"...\"&gt;</code>.")
            return
        state["icon_emoji_id"] = emoji_id
        state["step"] = "text"
        send(chat_id, "Теперь пришли надпись. Markdown сохраняется в записи; для Telegram verification будет использован чистый текст.")
        return
    if step == "text":
        raw = text.strip()
        if not raw:
            send(chat_id, "Надпись пустая.")
            return
        plain = re.sub(r"[*_`~\[\]()]", "", raw).strip()
        state["text_markdown"] = raw
        state["text"] = plain or raw
        try:
            ok = upsert_badge(chat_id, state)
        except Exception as e:
            send(chat_id, f"Ошибка сохранения: <code>{str(e)[:200]}</code>")
            return
        STATES.pop(chat_id, None)
        if ok:
            send(chat_id, f"Бейдж сохранен: <code>{badge_key(state['entity'])}</code>\nicon: <code>{state['icon_emoji_id']}</code>\ntext: <code>{state['text']}</code>")
        else:
            send(chat_id, "Сервер не принял бейдж.")


def show_list(chat_id):
    try:
        badges = list_badges()
    except Exception as e:
        send(chat_id, f"Ошибка списка: <code>{str(e)[:200]}</code>")
        return
    if not badges:
        send(chat_id, "Бейджей пока нет.")
        return
    rows = []
    lines = []
    for b in badges[:50]:
        if not b.get("enabled", True):
            continue
        key = b.get("key", "")
        lines.append(f"<code>{key}</code> icon=<code>{b.get('icon_emoji_id')}</code> text=<code>{b.get('text','')}</code>")
        rows.append([{"text": f"Удалить {key}", "callback_data": f"del:{key}"}])
    if not lines:
        send(chat_id, "Активных бейджей пока нет.")
        return
    send(chat_id, "\n".join(lines), {"inline_keyboard": rows})


def handle_callback(cb):
    chat_id = int(cb["message"]["chat"]["id"])
    user_id = int((cb.get("from") or {}).get("id") or 0)
    data = cb.get("data") or ""
    if not is_admin(user_id):
        answer_callback(cb["id"], "Нет доступа")
        return
    if data == "new":
        answer_callback(cb["id"])
        start_flow(chat_id)
        return
    if data == "list":
        answer_callback(cb["id"])
        show_list(chat_id)
        return
    if data == "publish":
        answer_callback(cb["id"])
        start_publish_flow(chat_id)
        return
    if data.startswith("del:"):
        key = data[4:]
        try:
            delete_badge(key)
            answer_callback(cb["id"], "Удалено")
            show_list(chat_id)
        except Exception as e:
            answer_callback(cb["id"], str(e)[:120])


def main():
    if not BOT_TOKEN:
        raise SystemExit("Set EBLANNFT_BOT_TOKEN")
    offset = 0
    while True:
        try:
            res = tg("getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]})
            for upd in res.get("result") or []:
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
        except (HTTPError, URLError, TimeoutError):
            time.sleep(2)
        except KeyboardInterrupt:
            return
        except Exception as e:
            print(f"bot loop error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
