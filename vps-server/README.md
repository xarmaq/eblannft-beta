# eblanNFT Beta — VPS Sync Server

Это серверная часть бета-плагина `eblanNFT 1.0.2`. Эту папку
заливаем целиком на VPS и запускаем — больше ничего не нужно.

## Что синхронизирует

Любой клиент с тем же URL/ключом при заходе в чужой профиль может
подтянуть с этого сервера:

- `nft gifts` (список визуальных подарков)
- `wear status` (надетый коллекционный статус)
- `nft username` (визуальный коллекционный юзер)
- `nft number` (визуальный коллекционный номер)

Всё работает локально и визуально, никакие настоящие тг-аккаунты
не модифицируются.

## Требования

- Python 3.10+ (`python3 --version`)
- открытый порт (по умолчанию 8787)

Сторонних зависимостей нет — только стандартная библиотека.

## Быстрый старт

### Linux / VPS

```bash
# на VPS
cd /opt
git clone <твой-репо> eblannft-beta
cd eblannft-beta/vps-server

# вариант 1 — просто запустить:
PLUGIN_KEY="ПРИДУМАЙ_СЕКРЕТ" sh run.sh

# вариант 2 — systemd (см. ниже)
```

### Windows (для тестов)

```cmd
cd vps-server
set PLUGIN_KEY=ПРИДУМАЙ_СЕКРЕТ
run.bat
```

## Параметры

| флаг | env | дефолт | назначение |
|------|-----|--------|------------|
| `--host` | `EBLANNFT_HOST` | `0.0.0.0` | интерфейс |
| `--port` | `EBLANNFT_PORT` | `8787` | порт |
| `--data-dir` | `EBLANNFT_DATA_DIR` | `./data` | где хранить json |
| `--plugin-key` | `EBLANNFT_PLUGIN_KEY` | пусто | секрет для записи |

Если `plugin-key` не задан, любой может писать. На прод — обязательно ставь.

## Эндпоинты

- `GET  /health` — `{ ok, version, users }`
- `GET  /api/v1/users/{user_key}/state` — публичное чтение
- `PUT  /api/v1/users/{user_key}/state` — запись (нужен `X-Plugin-Key`)
- `GET  /updates/manifest.json` — манифест последней версии плагина
- `GET  /updates/files/<rel>` — байты файла плагина/рантайма
- `PUT  /updates/files/<rel>` — заливка файла (нужен `X-Plugin-Key`)
- `PUT  /updates/manifest.json` — заливка манифеста (нужен `X-Plugin-Key`)

`user_key = "tg:" + telegram_user_id`.

## Публикация апдейтов через бота

GitHub в РФ блокируют, поэтому файлы плагина клиенты тянут с этого VPS.
Заливать новые версии удобнее всего через бота — лезть в SSH не нужно.

1. В DM с ботом (`badge_bot.py`) → `/publish`.
2. Прислать как **документы** (не сжатые) свежие файлы:
   - `eblannft_beta.plugin`
   - `plugin.py`, `__init__.py`, `sync_client.py`, `legacy_gifts.py` (любые из изменённых)
3. Бот сам:
   - выдернет `__version__` из `.plugin`;
   - попросит release notes (или `-` чтобы пропустить);
   - сделает `PUT /updates/files/...` + `PUT /updates/manifest.json`.
4. Клиенты при следующей проверке апдейтов увидят новую версию и подтянут файлы.

Где это лежит на диске: `--updates-dir` (env `EBLANNFT_UPDATES_DIR`, дефолт `./updates`).
В systemd-юните стоит зафиксировать его, например, на `/var/lib/eblannft-beta/updates`.

## URL обновлений в плагине

В `eblannft_beta.plugin` есть константа `_UPDATE_BASE_URL_DEFAULT` — поставь
туда адрес своего VPS (`http://host:8787` или с nginx/HTTPS). Можно
переопределять без пересборки `.plugin` через настройку плагина
`eblannft_beta_update_base_url`.

## systemd unit

Положить в `/etc/systemd/system/eblannft-beta.service`:

```ini
[Unit]
Description=eblanNFT Beta sync server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/eblannft-beta/vps-server
Environment=EBLANNFT_HOST=0.0.0.0
Environment=EBLANNFT_PORT=8787
Environment=EBLANNFT_DATA_DIR=/var/lib/eblannft-beta
Environment=EBLANNFT_PLUGIN_KEY=ПРИДУМАЙ_СЕКРЕТ
ExecStart=/usr/bin/python3 server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Запуск:

```bash
sudo mkdir -p /var/lib/eblannft-beta
sudo systemctl daemon-reload
sudo systemctl enable --now eblannft-beta
sudo journalctl -u eblannft-beta -f
```

## Подключение клиента

В плагине (по умолчанию из `_sync_get_settings`):

- `server_url` = `http://твой-vps:8787`
- `plugin_key` = тот же секрет, что в env

После старта клиент сам:

1. раз в ~60 сек пушит твой публичный NFT-снимок;
2. при просмотре чужого профиля делает фоновой `GET` и кеширует ответ.

## Хранение

`data/users/<sha256(user_key)>.json`. Атомарная запись через `.tmp`.

## Безопасность

- читать может кто угодно (так и задумано — иначе чужой плагин
  не увидит твои визуальные NFT)
- писать — только с заголовком `X-Plugin-Key`
- хочешь жёстче — закрой чтение через nginx/firewall
- лимит тела запроса: 12 MiB
- никаких пользовательских данных кроме того, что присылает плагин,
  сервер не собирает
