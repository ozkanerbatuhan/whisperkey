@echo off
rem Run without a console - daily use
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0src
start "" ".venv\Scripts\pythonw.exe" -m whisperkey
