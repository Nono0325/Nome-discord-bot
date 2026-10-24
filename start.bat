@echo off
chcp 65001 >nul
title Discord Bot
cd /d "%~dp0"

echo [1/2] 檢查虛擬環境...
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo [2/2] 啟動機器人主程序...
"%PYTHON_EXE%" main.py

if errorlevel 1 (
    echo.
    echo =======================================================
    echo [提示] 機器人異常退出，請檢查上述錯誤訊息。
    echo =======================================================
    pause
)
