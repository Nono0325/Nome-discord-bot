@echo off
chcp 65001 >nul
title Discord Bot
cd /d "%~dp0"

echo =======================================================
echo           Discord Bot - One-Click Launcher
echo =======================================================
echo.

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo [INFO] Created .env from .env.example
    )
)

echo [INFO] Starting Discord Bot using: %PYTHON_EXE%
echo [INFO] Web Dashboard: http://localhost:5000
echo [INFO] System logs:   logs\bot.log
echo [INFO] Press Ctrl+C anytime to safely stop the bot.
echo =======================================================
echo.

"%PYTHON_EXE%" main.py

if errorlevel 1 (
    echo.
    echo =======================================================
    echo [ERROR] Bot exited with error code %ERRORLEVEL%.
    echo Please check the message above or view logs\bot.log.
    echo =======================================================
    pause
)
