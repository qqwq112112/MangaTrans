@echo off
chcp 936 >nul
title 构建 MangaTrans.exe（含日文 OCR）
cd /d "%~dp0"

echo ============================================
echo   MangaTrans 打包脚本（含 manga-ocr）
echo ============================================
echo.
echo 这个版本会把 PyTorch 一起打包，体积约 2.4 GB，
echo 但打出来的 exe 可以直接识别日文竖排漫画。
echo.

set "PY=python"

"%PY%" -c "import torch, manga_ocr" >nul 2>nul
if errorlevel 1 (
    echo [错误] 缺少日文 OCR 依赖。请先执行：
    echo     pip install manga-ocr
    echo.
    pause
    exit /b 1
)

echo [1/3] 检查 OCR 模型缓存...
"%PY%" -c "import os,sys; p=os.path.expanduser('~/.cache/huggingface/hub/models--kha-white--manga-ocr-base'); sys.exit(0 if os.path.isdir(p) else 1)"
if errorlevel 1 (
    echo     模型尚未下载，首次运行时程序会自动下载约 400 MB。
) else (
    echo     模型已缓存，无需联网。
)

echo.
echo [2/3] 清理旧的构建产物...
if exist build rmdir /s /q build
if exist dist\MangaTrans-OCR rmdir /s /q dist\MangaTrans-OCR

echo.
echo [3/3] 开始打包，首次约需 5-10 分钟...
"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name MangaTrans-OCR ^
    --add-data "tools\win_ocr.ps1;tools" ^
    --collect-all zhconv ^
    --collect-all manga_ocr ^
    --collect-all unidic_lite ^
    --collect-submodules transformers ^
    --exclude-module tkinter ^
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
echo   打包完成: dist\MangaTrans-OCR\MangaTrans-OCR.exe
echo ============================================
echo 体积较大（约 2.4 GB），日文 OCR 已内置。
echo.
pause
exit /b 0

:fail
echo.
echo [失败] 打包出错，请查看上面的日志。
pause
exit /b 1
