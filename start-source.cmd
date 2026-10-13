@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo Please install Python 3.12 with the Python Launcher, then run this file again.
        pause
        exit /b 1
    )
)
if not exist ".venv\screen-auto-clicker-ready" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check your connection and try again.
        pause
        exit /b 1
    )
    echo ready>".venv\screen-auto-clicker-ready"
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
