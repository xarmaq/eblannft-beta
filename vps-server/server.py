import argparse
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


VERSION = "1.0.3"
MAX_BODY_BYTES = 12 * 1024 * 1024
UPDATES_MAX_FILE_BYTES = 16 * 1024 * 1024
UPDATES_ALLOWED_FILES = {
    "eblannft_beta.plugin",
    "eblannft_beta_runtime/__init__.py",
    "eblannft_beta_runtime/plugin.py",
    "eblannft_beta_runtime/sync_client.py",
    "eblannft_beta_runtime/legacy_gifts.py",
}
ENTRY_ALLOWED_KEYS = {
    "key",
    "b64",
    "title",
    "slug",
    "num",
    "base_gift_id",
    "unique_id",
    "saved_id",
    "inject",
    "gift_kind",
    "updated_at",
    "created_at",
    "wear_status_data",
    "build_config",
    "identity_config",
    "standard_price_stars",
    "avail_total",
    "avail_issued",
    "limit_total",
    "limited_flag",
    "pinned_override",
    "hidden_override",
    "order_hint",
}


def now_ts():
    return int(time.time())


def clean_str(value, max_len=4096):
    if value is None:
        return ""
    out = str(value)
    if len(out) > max_len:
        out = out[:max_len]
    return out


def clean_bool(value):
    return bool(value)


def clean_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def normalize_entity_type(value):
    value = clean_str(value, 24).strip().lower()
    if value in {"user", "users", "tg"}:
        return "user"
    if value in {"chat", "channel", "channels"}:
        return "chat"
    return ""


def make_badge_key(entity_type, entity_id):
    entity_type = normalize_entity_type(entity_type)
    entity_id = clean_int(entity_id, 0)
    if not entity_type or entity_id == 0:
        return ""
    return f"{entity_type}:{entity_id}"


def clean_list(value, max_items=64):
    if not isinstance(value, list):
        return []
    return value[:max_items]


def clean_simple_dict(value, max_keys=64):
    if not isinstance(value, dict):
        return {}
    out = {}
    for idx, (k, v) in enumerate(value.items()):
        if idx >= max_keys:
            break
        key = clean_str(k, 96)
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[key] = v
        elif isinstance(v, dict):
            out[key] = clean_simple_dict(v, max_keys=24)
        elif isinstance(v, list):
            out[key] = [x for x in v[:32] if isinstance(x, (str, int, float, bool)) or x is None]
    return out


def sanitize_tokens(values, normalizer=None, max_items=12):
    out = []
    for raw in clean_list(values, max_items=max_items):
        token = clean_str(raw, 128).strip()
        if normalizer:
            token = normalizer(token)
        if token and token not in out:
            out.append(token)
    return out


def normalize_username(token):
    token = clean_str(token, 64).strip().lstrip("@").lower()
    keep = []
    for ch in token:
        if ch.isalnum() or ch == "_":
            keep.append(ch)
    return "".join(keep)[:32]


def normalize_number(token):
    token = clean_str(token, 64).strip()
    digits = []
    for ch in token:
        if ch.isdigit():
            digits.append(ch)
    num = "".join(digits)
    if num.startswith("888"):
        return num
    if num:
        return "888" + num
    return ""


class UpdatesStore:
    """File-backed store for plugin self-update artifacts. The structure on
    disk is:
        <updates_dir>/manifest.json
        <updates_dir>/files/eblannft_beta.plugin
        <updates_dir>/files/eblannft_beta_runtime/plugin.py
        ...
    Manifest is read on every request so the bot can hot-swap it without
    a server restart."""

    def __init__(self, updates_dir):
        self.root_dir = Path(updates_dir)
        self.files_dir = self.root_dir / "files"
        self.manifest_path = self.root_dir / "manifest.json"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _safe_rel(self, rel_path):
        rel = clean_str(rel_path, 256).strip().replace("\\", "/").lstrip("/")
        if not rel:
            return ""
        if rel not in UPDATES_ALLOWED_FILES:
            return ""
        return rel

    def file_disk_path(self, rel_path):
        rel = self._safe_rel(rel_path)
        if not rel:
            return None
        target = (self.files_dir / rel).resolve()
        try:
            base = self.files_dir.resolve()
        except Exception:
            return None
        try:
            target.relative_to(base)
        except Exception:
            return None
        return target

    def read_file(self, rel_path):
        path = self.file_disk_path(rel_path)
        if path is None or not path.exists() or not path.is_file():
            return None
        try:
            with path.open("rb") as fh:
                return fh.read()
        except Exception:
            return None

    def write_file(self, rel_path, data):
        path = self.file_disk_path(rel_path)
        if path is None:
            return False
        if not isinstance(data, (bytes, bytearray)):
            return False
        if len(data) > UPDATES_MAX_FILE_BYTES:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            with tmp.open("wb") as fh:
                fh.write(bytes(data))
            os.replace(tmp, path)
        return True

    def read_manifest(self):
        if not self.manifest_path.exists():
            return {}
        try:
            with self.manifest_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def write_manifest(self, payload):
        if not isinstance(payload, dict):
            return False
        version = clean_str(payload.get("version", ""), 64).strip()
        if not version:
            return False
        files = []
        for raw in clean_list(payload.get("files", []), max_items=32):
            rel = self._safe_rel(raw)
            if rel and rel not in files:
                files.append(rel)
        if not files:
            return False
        manifest = {
            "version": version,
            "notes": clean_str(payload.get("notes", ""), 4096).strip(),
            "files": files,
            "updated_at": now_ts(),
        }
        tmp = self.manifest_path.with_suffix(".json.tmp")
        with self._lock:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.manifest_path)
        return True


class JsonStorage:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.users_dir = self.root_dir / "users"
        self.badges_path = self.root_dir / "badges.json"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _file_path(self, user_key):
        digest = hashlib.sha256(user_key.encode("utf-8", "ignore")).hexdigest()
        return self.users_dir / f"{digest}.json"

    def load(self, user_key):
        path = self._file_path(user_key)
        if not path.exists():
            return self.empty_record(user_key)
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return self.empty_record(user_key)
            rec = self.empty_record(user_key)
            rec.update(data)
            return sanitize_record(rec, user_key)
        except Exception:
            return self.empty_record(user_key)

    def save(self, user_key, payload):
        record = sanitize_record(payload, user_key)
        path = self._file_path(user_key)
        tmp_path = path.with_suffix(".json.tmp")
        with self._lock:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, path)
        return record

    def count_users(self):
        try:
            return len(list(self.users_dir.glob("*.json")))
        except Exception:
            return 0

    def load_badges(self):
        if not self.badges_path.exists():
            return {}
        try:
            with self.badges_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            out = {}
            for key, raw in data.items():
                item = sanitize_badge(raw)
                if not item:
                    continue
                out[item["key"]] = item
            return out
        except Exception:
            return {}

    def save_badges(self, badges):
        if not isinstance(badges, dict):
            badges = {}
        tmp_path = self.badges_path.with_suffix(".json.tmp")
        with self._lock:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(badges, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, self.badges_path)
        return badges

    def upsert_badge(self, payload):
        item = sanitize_badge(payload)
        if not item:
            return None
        badges = self.load_badges()
        badges[item["key"]] = item
        self.save_badges(badges)
        return item

    def delete_badge(self, key):
        key = clean_str(key, 128).strip()
        if not key:
            return False
        badges = self.load_badges()
        item = badges.get(key)
        existed = item is not None
        if existed:
            item["enabled"] = False
            item["updated_at"] = now_ts()
            badges[key] = item
            self.save_badges(badges)
        return existed

    @staticmethod
    def empty_record(user_key):
        return {
            "user_key": clean_str(user_key, 256),
            "plugin_id": "eblannft_beta",
            "updated_at": 0,
            "gifts": [],
            "wear_active": False,
            "wear_collectible_id": 0,
            "wear_status_data": {},
            "username_state": {
                "enabled": False,
                "tokens": [],
                "price_ton": "0",
                "price_usd": "0",
                "purchase_date": "",
            },
            "number_state": {
                "enabled": False,
                "tokens": [],
                "price_ton": "0",
                "price_usd": "0",
                "purchase_date": "",
            },
        }


def sanitize_gift_entry(src):
    if not isinstance(src, dict):
        return None
    b64 = clean_str(src.get("b64", ""), 2_000_000).strip()
    if len(b64) < 16:
        return None
    out = {}
    for key in ENTRY_ALLOWED_KEYS:
        if key not in src:
            continue
        val = src.get(key)
        if key in {"num", "base_gift_id", "unique_id", "saved_id", "updated_at", "created_at", "standard_price_stars", "avail_total", "avail_issued", "limit_total", "order_hint"}:
            out[key] = clean_int(val, 0)
        elif key in {"inject", "limited_flag", "pinned_override", "hidden_override"}:
            out[key] = clean_bool(val)
        elif key in {"wear_status_data", "build_config", "identity_config"}:
            out[key] = clean_simple_dict(val, max_keys=64)
        else:
            out[key] = clean_str(val, 4096)
    if "b64" not in out:
        out["b64"] = b64
    if "updated_at" not in out:
        out["updated_at"] = now_ts()
    if "created_at" not in out:
        out["created_at"] = now_ts()
    if "gift_kind" not in out:
        out["gift_kind"] = "nft"
    return out


def sanitize_state_block(src, kind):
    if not isinstance(src, dict):
        src = {}
    normalizer = normalize_username if kind == "username" else normalize_number
    return {
        "enabled": clean_bool(src.get("enabled", False)),
        "tokens": sanitize_tokens(src.get("tokens", []), normalizer=normalizer, max_items=12),
        "price_ton": clean_str(src.get("price_ton", "0"), 64),
        "price_usd": clean_str(src.get("price_usd", "0"), 64),
        "purchase_date": clean_str(src.get("purchase_date", ""), 128),
    }


def sanitize_record(payload, user_key):
    if not isinstance(payload, dict):
        payload = {}
    gifts = []
    for row in clean_list(payload.get("gifts", []), max_items=128):
        item = sanitize_gift_entry(row)
        if item is not None:
            gifts.append(item)
    wear_active = clean_bool(payload.get("wear_active", False))
    wear_collectible_id = clean_int(payload.get("wear_collectible_id", 0), 0)
    if wear_collectible_id <= 0:
        wear_active = False
    return {
        "user_key": clean_str(user_key, 256),
        "plugin_id": clean_str(payload.get("plugin_id", "eblannft2"), 64),
        "updated_at": clean_int(payload.get("updated_at", now_ts()), now_ts()),
        "gifts": gifts,
        "wear_active": wear_active,
        "wear_collectible_id": wear_collectible_id if wear_active else 0,
        "wear_status_data": clean_simple_dict(payload.get("wear_status_data", {}), max_keys=64) if wear_active else {},
        "username_state": sanitize_state_block(payload.get("username_state", {}), "username"),
        "number_state": sanitize_state_block(payload.get("number_state", {}), "number"),
    }


def sanitize_badge(payload):
    if not isinstance(payload, dict):
        return None
    entity_type = normalize_entity_type(payload.get("entity_type", ""))
    entity_id = clean_int(payload.get("entity_id", 0), 0)
    key = clean_str(payload.get("key", ""), 128).strip()
    if not key:
        key = make_badge_key(entity_type, entity_id)
    if ":" in key:
        parts = key.split(":", 1)
        entity_type = normalize_entity_type(parts[0])
        entity_id = clean_int(parts[1], entity_id)
    key = make_badge_key(entity_type, entity_id)
    icon = clean_int(payload.get("icon_emoji_id", payload.get("icon", 0)), 0)
    text = clean_str(payload.get("text", payload.get("description", "")), 512).strip()
    text_markdown = clean_str(payload.get("text_markdown", payload.get("markdown", text)), 1024).strip()
    if not key or icon <= 0 or not text:
        return None
    now = now_ts()
    return {
        "key": key,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "icon_emoji_id": icon,
        "text": text,
        "text_markdown": text_markdown or text,
        "enabled": clean_bool(payload.get("enabled", True)),
        "updated_at": clean_int(payload.get("updated_at", now), now),
        "created_at": clean_int(payload.get("created_at", now), now),
        "updated_by": clean_int(payload.get("updated_by", 0), 0),
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "eblannft-beta-server"

    def _send_bytes(self, status, data, content_type):
        body = data or b""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _extract_update_path(self):
        """Returns ('manifest', '') / ('file', rel) / (None, None)."""
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] != "updates":
            return None, None
        if len(parts) == 2 and parts[1] == "manifest.json":
            return "manifest", ""
        if len(parts) >= 3 and parts[1] == "files":
            rel = "/".join(parts[2:])
            return "file", unquote(rel)
        return None, None

    def _read_raw_body(self):
        length = clean_int(self.headers.get("Content-Length", "0"), 0)
        if length <= 0:
            return b""
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        return self.rfile.read(length) or b""

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status, message):
        self._json(status, {"ok": False, "error": clean_str(message, 512)})

    def _check_auth(self):
        expected = getattr(self.server, "plugin_key", "")
        if not expected:
            return True
        got = clean_str(self.headers.get("X-Plugin-Key", ""), 256)
        return got == expected

    def _read_json_body(self):
        length = clean_int(self.headers.get("Content-Length", "0"), 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("json body must be object")
        return data

    def _extract_user_key(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if len(parts) != 5:
            return None, None
        if parts[0] != "api" or parts[1] != "v1" or parts[2] != "users":
            return None, None
        route = parts[4]
        if route not in {"state", "gifts"}:
            return None, None
        user_key = unquote(parts[3]).strip()
        if not user_key:
            return None, None
        return user_key, route

    def _extract_badge_key(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "v1" and parts[2] == "badges":
            return ""
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "v1" and parts[2] == "badges":
            return unquote(parts[3]).strip()
        return None

    def do_GET(self):
        path = urlparse(self.path).path
        upd_kind, upd_rel = self._extract_update_path()
        if upd_kind == "manifest":
            manifest = self.server.updates.read_manifest()
            self._json(200 if manifest else 404, manifest or {"ok": False, "error": "no manifest"})
            return
        if upd_kind == "file":
            data = self.server.updates.read_file(upd_rel)
            if data is None:
                self._error(404, "file not found")
                return
            self._send_bytes(200, data, "application/octet-stream")
            return
        if path == "/health":
            self._json(200, {
                "ok": True,
                "version": VERSION,
                "users": self.server.storage.count_users(),
                "badges": len(self.server.storage.load_badges()),
            })
            return
        badge_key = self._extract_badge_key()
        if badge_key is not None:
            badges = self.server.storage.load_badges()
            if badge_key:
                item = badges.get(badge_key)
                if item is None:
                    self._error(404, "badge not found")
                    return
                self._json(200, {"ok": True, "badge": item})
                return
            self._json(200, {
                "ok": True,
                "updated_at": max([int(v.get("updated_at", 0) or 0) for v in badges.values()] or [0]),
                "badges": list(badges.values()),
            })
            return
        user_key, route = self._extract_user_key()
        if not user_key:
            self._error(404, "not found")
            return
        record = self.server.storage.load(user_key)
        self._json(200, record)

    def do_PUT(self):
        upd_kind, upd_rel = self._extract_update_path()
        if upd_kind is not None:
            if not self._check_auth():
                self._error(401, "invalid plugin key")
                return
            try:
                raw = self._read_raw_body()
            except Exception as e:
                self._error(400, str(e))
                return
            if upd_kind == "manifest":
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except Exception as e:
                    self._error(400, f"bad json: {e}")
                    return
                if not isinstance(payload, dict):
                    self._error(400, "manifest must be an object")
                    return
                if not self.server.updates.write_manifest(payload):
                    self._error(400, "invalid manifest")
                    return
                self._json(200, {"ok": True, "manifest": self.server.updates.read_manifest()})
                return
            if not raw:
                self._error(400, "empty body")
                return
            if not self.server.updates.write_file(upd_rel, raw):
                self._error(400, "rejected (unknown path or too large)")
                return
            self._json(200, {"ok": True, "path": upd_rel, "size": len(raw)})
            return
        badge_key = self._extract_badge_key()
        if badge_key is not None:
            if not self._check_auth():
                self._error(401, "invalid plugin key")
                return
            try:
                payload = self._read_json_body()
            except Exception as e:
                self._error(400, str(e))
                return
            if badge_key:
                payload["key"] = badge_key
            item = self.server.storage.upsert_badge(payload)
            if item is None:
                self._error(400, "invalid badge")
                return
            self._json(200, {"ok": True, "badge": item})
            return
        user_key, route = self._extract_user_key()
        if not user_key:
            self._error(404, "not found")
            return
        if not self._check_auth():
            self._error(401, "invalid plugin key")
            return
        try:
            payload = self._read_json_body()
        except Exception as e:
            self._error(400, str(e))
            return
        record = self.server.storage.save(user_key, payload)
        self._json(200, {
            "ok": True,
            "user_key": record["user_key"],
            "count": len(record.get("gifts", []) or []),
            "updated_at": record.get("updated_at", 0),
        })

    def do_DELETE(self):
        badge_key = self._extract_badge_key()
        if badge_key is None or not badge_key:
            self._error(404, "not found")
            return
        if not self._check_auth():
            self._error(401, "invalid plugin key")
            return
        ok = self.server.storage.delete_badge(badge_key)
        self._json(200, {"ok": True, "deleted": bool(ok), "key": badge_key})

    def log_message(self, fmt, *args):
        msg = "%s - - [%s] %s\n" % (
            self.client_address[0],
            self.log_date_time_string(),
            fmt % args,
        )
        print(msg, end="")


def parse_args():
    parser = argparse.ArgumentParser(description="eblanNFT Beta sync server")
    parser.add_argument("--host", default=os.environ.get("EBLANNFT_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EBLANNFT_PORT", "8787")))
    parser.add_argument("--data-dir", default=os.environ.get("EBLANNFT_DATA_DIR", "./data"))
    parser.add_argument("--updates-dir", default=os.environ.get("EBLANNFT_UPDATES_DIR", "./updates"))
    parser.add_argument("--plugin-key", default=os.environ.get("EBLANNFT_PLUGIN_KEY", ""))
    return parser.parse_args()


def main():
    args = parse_args()
    storage = JsonStorage(args.data_dir)
    updates = UpdatesStore(args.updates_dir)
    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    server.storage = storage
    server.updates = updates
    server.plugin_key = clean_str(args.plugin_key, 256)
    print(f"eblanNFT Beta server v{VERSION} listening on http://{args.host}:{args.port}")
    print(f"data dir: {Path(args.data_dir).resolve()}")
    print(f"updates dir: {Path(args.updates_dir).resolve()}")
    if server.plugin_key:
        print("plugin key: enabled")
    else:
        print("plugin key: disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
