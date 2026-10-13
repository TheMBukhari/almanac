@echo off
rem Runs Almanac straight from the source files (no .exe, and no self-updates).
cd /d "%~dp0"
set "PY=python"
set "PYW=pythonw"
where py >nul 2>nul && set "PY=py -3"
where pyw >nul 2>nul && set "PYW=pyw -3"
%PY% -m pip install -r requirements.txt >nul
start "" %PYW% almanac_app.py
