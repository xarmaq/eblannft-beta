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
STATES = {}


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


def handle_message(msg):
    chat_id = int(msg["chat"]["id"])
    user_id = int((msg.get("from") or {}).get("id") or 0)
    text = msg.get("text") or ""
    if not is_admin(user_id):
        send(chat_id, "Нет доступа.")
        return
    if text.startswith("/start"):
        send(chat_id, "Бот бейджей eblanNFT.", {
            "inline_keyboard": [
                [{"text": "Выдать / изменить бейдж", "callback_data": "new"}],
                [{"text": "Список бейджей", "callback_data": "list"}],
            ]
        })
        return
    if text.startswith("/new"):
        start_flow(chat_id)
        return
    if text.startswith("/list"):
        show_list(chat_id)
        return
    state = STATES.get(chat_id)
    if not state:
        send(chat_id, "Команды: /new, /list")
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
