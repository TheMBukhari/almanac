@echo off
setlocal
cd /d "%~dp0"
title Building Almanac

set "PY=python"
where py >nul 2>nul && set "PY=py -3"

echo.
echo  You normally don't need this: every release on GitHub comes with a ready-made Almanac.exe.
echo  This builds one yourself from these files.
echo.
echo  [1/3] Installing what the app needs...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt "pyinstaller>=6.10"
if errorlevel 1 goto :fail

echo.
echo  [2/3] Making the icon and build info...
%PY% almanac_app.py --write-icon almanac.ico
if errorlevel 1 goto :fail
%PY% almanac_app.py --write-build-info build_info.py
if errorlevel 1 goto :fail

echo.
echo  [3/3] Building Almanac.exe (takes a minute or two)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name Almanac --icon almanac.ico ^
    --collect-data customtkinter --collect-all curl_cffi ^
    --hidden-import pystray._win32 --hidden-import PIL._tkinter_finder --hidden-import PIL.ImageTk ^
    --hidden-import almanac_app --hidden-import build_info ^
    launcher.py
if errorlevel 1 goto :fail

echo.
echo  Done!  Your app is here:  %~dp0dist\Almanac.exe
echo  Put it in the folder where your data lives (next to almanac_data.json or scheduler_db.json).
echo.
pause
exit /b 0

:fail
echo.
echo  Something went wrong. Make sure Python 3.10+ is installed from python.org
echo  (tick "Add python.exe to PATH" in the installer), then run this again.
echo.
pause
exit /b 1
