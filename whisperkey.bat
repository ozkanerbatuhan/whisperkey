@echo off
rem Run with a console - for first setup and debugging
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONPATH=%~dp0src
".venv\Scripts\python.exe" -m whisperkey %*
pause
