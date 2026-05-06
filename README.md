# eblanNFT Beta

Бета-ветка плагина `eblanNFT` для exteraGram / AyuGram. Этот репозиторий —
полная копия [`xarmaq/eblannft`](https://github.com/xarmaq/eblannft) +
обновление **1.0.2** с серверной синхронизацией.

> ⚠️ Всё работает локально. Плагин ничего не пишет в реальные тг-объекты на
> сервере Telegram — он только подменяет визуал в клиенте.

## Что нового в 1.0.2 (Beta)

- Появился отдельный VPS-сервер синхронизации (`vps-server/`).
- Клиент в фоне пушит на сервер свой публичный NFT-снимок:
  - подарки (`gifts`), включая `wear_status_data`,
  - надетый коллекционный статус,
  - NFT-юзернеймы и NFT-номер.
- При просмотре чужого профиля плагин фоном спрашивает у сервера
  состояние того пользователя — если у него стоит та же бета и он
  пушит свои данные, клиент увидит его NFT/номер/юзернейм визуально.
- Сетевой слой полностью изолирован (`eblannft_runtime/sync_client.py`)
  и обёрнут в `try/except` — даже если сервер недоступен, плагин
  работает в локальном режиме.

## Структура

```
eblannft-beta/
├── eblannft.plugin                 ← бутстрап-loader (как в основном репо)
├── eblannft_runtime/
│   ├── __init__.py
│   ├── plugin.py                   ← основная логика + интеграция sync
│   └── sync_client.py              ← НОВЫЙ: HTTP-клиент к VPS-серверу
├── eblannft_update.json            ← манифест автообновления (1.0.2)
└── vps-server/                     ← заливаем эту папку на VPS
    ├── server.py
    ├── run.sh / run.bat
    ├── Dockerfile
    ├── eblannft-beta.service       ← systemd unit
    └── README.md
```

## Установка плагина

1. Скопировать `eblannft.plugin` в exteraGram → Plugins.
2. Перезапустить клиент.
3. По умолчанию клиент уже настроен на основной VPS:
   `http://35.242.218.223:8787`. Если хочешь свой сервер —
   укажи свой `server_url` и `plugin_key` в настройках плагина.

## Поднятие сервера

См. [`vps-server/README.md`](vps-server/README.md). Минимум:

```bash
scp -r vps-server/  root@vps:/opt/eblannft-beta/vps-server
ssh root@vps
cd /opt/eblannft-beta/vps-server
PLUGIN_KEY="секрет" sh run.sh
```

## Версии

- основной репо `xarmaq/eblannft` — стабильная ветка
- этот репо `xarmaq/eblannft-beta` — бета с экспериментами,
  текущая версия **1.0.2**
