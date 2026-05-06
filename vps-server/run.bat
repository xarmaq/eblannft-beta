@echo off
REM eblanNFT Beta sync server — quick launch for Windows
if "%HOST%"==""        set HOST=0.0.0.0
if "%PORT%"==""        set PORT=8787
if "%DATA_DIR%"==""    set DATA_DIR=.\data
if "%PLUGIN_KEY%"==""  set PLUGIN_KEY=changeme

python server.py --host %HOST% --port %PORT% --data-dir %DATA_DIR% --plugin-key %PLUGIN_KEY%
