@echo off
title vyro
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Python environment was not found: .venv
    echo Install the project dependencies first.
    pause
    exit /b 1
)

if /i "%~1"=="--check" (
    echo Launcher OK
    exit /b 0
)

echo Starting vyro...
".venv\Scripts\python.exe" main.py

if errorlevel 1 (
    echo.
    echo vyro stopped with an error.
    pause
)
