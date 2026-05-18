# Badge API and bot

Additional sync-server endpoints:

- `GET  /api/v1/badges` - public badge list.
- `PUT  /api/v1/badges/{entity_type}:{entity_id}` - create/update badge, requires `X-Plugin-Key`.
- `DELETE /api/v1/badges/{entity_type}:{entity_id}` - disable badge, requires `X-Plugin-Key`.

`entity_type` is `user` or `chat`. Examples: `user:5406195402`, `chat:-1001234567890`.

`badge_bot.py` uses Telegram Bot API long polling and has no third-party Python dependencies.

Required env:

- `EBLANNFT_BOT_TOKEN` - token from BotFather.
- `EBLANNFT_BOT_ADMINS` - comma-separated Telegram user ids allowed to manage badges.
- `EBLANNFT_SERVER_URL` - for example `http://127.0.0.1:8787`.
- `EBLANNFT_PLUGIN_KEY` - same write key as the server.

Run:

```bash
EBLANNFT_BOT_TOKEN="123:abc" \
EBLANNFT_BOT_ADMINS="5406195402" \
SERVER_URL="http://127.0.0.1:8787" \
PLUGIN_KEY="secret" \
sh run-badge-bot.sh
```

Bot flow:

1. `/new`
2. Send user id, `@username`, or `https://t.me/...` link.
3. Send premium emoji or `<tg-emoji emoji-id="...">`.
4. Send badge caption text.

The caption is stored as plain text for Telegram verification rendering and as
markdown text for future plugin surfaces.
