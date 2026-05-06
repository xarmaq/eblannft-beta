#!/usr/bin/env sh

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8787}"
DATA_DIR="${DATA_DIR:-./data}"
PLUGIN_KEY="${PLUGIN_KEY:-changeme}"

python3 server.py --host "$HOST" --port "$PORT" --data-dir "$DATA_DIR" --plugin-key "$PLUGIN_KEY"
