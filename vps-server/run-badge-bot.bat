@echo off
if "%SERVER_URL%"=="" set SERVER_URL=http://127.0.0.1:8787
if "%PLUGIN_KEY%"=="" set PLUGIN_KEY=changeme

set EBLANNFT_SERVER_URL=%SERVER_URL%
set EBLANNFT_PLUGIN_KEY=%PLUGIN_KEY%
python badge_bot.py
