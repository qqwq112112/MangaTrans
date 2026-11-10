@echo off
chcp 936 >nul
title 构建 MangaTrans.exe
cd /d "%~dp0"

echo ============================================
echo   MangaTrans 打包脚本（精简版 ~170MB）
echo ============================================
echo.

set "PY=python"
"%PY%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [1/3] 安装 PyInstaller...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 goto :fail
) else (
    echo [1/3] PyInstaller 已安装
)

echo.
echo [2/3] 清理旧的构建产物...
if exist build rmdir /s /q build
if exist dist\MangaTrans rmdir /s /q dist\MangaTrans

echo.
echo [3/3] 开始打包，首次约需 1-3 分钟...
"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name MangaTrans ^
    --add-data "tools\win_ocr.ps1;tools" ^
    --add-data "tools\ocr_worker.py;tools" ^
    --collect-all zhconv ^
    --exclude-module tkinter ^
    --exclude-module numpy ^
    --exclude-module cv2 ^
    --exclude-module fitz ^
    --exclude-module torch ^
    --exclude-module transformers ^
    --exclude-module manga_ocr ^
    --exclude-module unidic_lite ^
    --exclude-module PySide6.Qt3DAnimation ^
    --exclude-module PySide6.Qt3DCore ^
    --exclude-module PySide6.Qt3DExtras ^
    --exclude-module PySide6.Qt3DInput ^
    --exclude-module PySide6.Qt3DLogic ^
    --exclude-module PySide6.Qt3DRender ^
    --exclude-module PySide6.QtBluetooth ^
    --exclude-module PySide6.QtCharts ^
    --exclude-module PySide6.QtDataVisualization ^
    --exclude-module PySide6.QtDesigner ^
    --exclude-module PySide6.QtGraphs ^
    --exclude-module PySide6.QtHelp ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtMultimediaWidgets ^
    --exclude-module PySide6.QtNetworkAuth ^
    --exclude-module PySide6.QtNfc ^
    --exclude-module PySide6.QtPdf ^
    --exclude-module PySide6.QtPdfWidgets ^
    --exclude-module PySide6.QtPositioning ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtQuick ^
    --exclude-module PySide6.QtQuick3D ^
    --exclude-module PySide6.QtQuickControls2 ^
    --exclude-module PySide6.QtQuickWidgets ^
    --exclude-module PySide6.QtRemoteObjects ^
    --exclude-module PySide6.QtScxml ^
    --exclude-module PySide6.QtSensors ^
    --exclude-module PySide6.QtSerialBus ^
    --exclude-module PySide6.QtSerialPort ^
    --exclude-module PySide6.QtSpatialAudio ^
    --exclude-module PySide6.QtSql ^
    --exclude-module PySide6.QtStateMachine ^
    --exclude-module PySide6.QtTest ^
    --exclude-module PySide6.QtTextToSpeech ^
    --exclude-module PySide6.QtUiTools ^
    --exclude-module PySide6.QtWebChannel ^
    --exclude-module PySide6.QtWebEngineCore ^
    --exclude-module PySide6.QtWebEngineQuick ^
    --exclude-module PySide6.QtWebEngineWidgets ^
    --exclude-module PySide6.QtWebSockets ^
    main.py

if errorlevel 1 goto :fail

echo.
echo ============================================
echo   打包完成: dist\MangaTrans\MangaTrans.exe
echo ============================================
echo 可双击 exe 直接运行；分发给他人时请整个
echo dist\MangaTrans 文件夹打包，不要只发 exe。
echo.
echo 日文 OCR 由外部 Python 提供（tools\ocr_worker.py），
echo 主程序不含 torch，因此改 OCR 逻辑无需重新打包。
echo.
pause
exit /b 0

:fail
echo.
echo [失败] 打包出错，请查看上面的日志。
pause
exit /b 1
