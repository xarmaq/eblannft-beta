import argparse
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


VERSION = "1.0.2"
MAX_BODY_BYTES = 12 * 1024 * 1024
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


class JsonStorage:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.users_dir = self.root_dir / "users"
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


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "eblannft-beta-server"

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

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {
                "ok": True,
                "version": VERSION,
                "users": self.server.storage.count_users(),
            })
            return
        user_key, route = self._extract_user_key()
        if not user_key:
            self._error(404, "not found")
            return
        record = self.server.storage.load(user_key)
        self._json(200, record)

    def do_PUT(self):
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
    parser.add_argument("--plugin-key", default=os.environ.get("EBLANNFT_PLUGIN_KEY", ""))
    return parser.parse_args()


def main():
    args = parse_args()
    storage = JsonStorage(args.data_dir)
    server = ThreadingHTTPServer((args.host, args.port), ApiHandler)
    server.storage = storage
    server.plugin_key = clean_str(args.plugin_key, 256)
    print(f"eblanNFT Beta server v{VERSION} listening on http://{args.host}:{args.port}")
    print(f"data dir: {Path(args.data_dir).resolve()}")
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
