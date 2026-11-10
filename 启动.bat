@echo off
chcp 936 >nul
title MangaTrans 漫画汉化工作台
cd /d "%~dp0"

set "PY=python"
if exist "%~dp0runtime\python.exe" set "PY=%~dp0runtime\python.exe"

"%PY%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo [错误] 找不到 PySide6。
    echo 请先执行: pip install PySide6 pillow requests
    echo.
    pause
    exit /b 1
)

"%PY%" main.py %*

if errorlevel 1 (
    echo.
    echo 程序异常退出，错误码 %errorlevel%。
    pause
)
