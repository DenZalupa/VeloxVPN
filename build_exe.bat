@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Сборка VeloxVPN.exe

echo ===================================================
echo           Сборка автономного VeloxVPN.exe
echo ===================================================

echo Закрытие запущенных процессов VeloxVPN перед сборкой...
taskkill /F /IM "VeloxVPN.exe" >nul 2>&1
taskkill /F /IM "sing-box.exe" >nul 2>&1
taskkill /F /IM "msedgewebview2.exe" >nul 2>&1
timeout /t 1 /nobreak >nul

pyinstaller --noconfirm --onedir --windowed --uac-admin --name "VeloxVPN" --icon "app.ico" --add-data "static;static" --add-data "bin;bin" main.py

if %errorlevel% equ 0 (
    echo Копирование data и bin в папку dist\VeloxVPN...
    if not exist "dist\VeloxVPN\data" mkdir "dist\VeloxVPN\data"
    copy /Y "data\app_config.json" "dist\VeloxVPN\data\" >nul 2>&1
    if not exist "dist\VeloxVPN\bin" mkdir "dist\VeloxVPN\bin"
    copy /Y "bin\*" "dist\VeloxVPN\bin\" >nul 2>&1
    copy /Y "app.ico" "dist\VeloxVPN\" >nul 2>&1
    echo.
    echo [УСПЕХ] Сборка успешно завершена!
    echo Файл: %~dp0dist\VeloxVPN\VeloxVPN.exe
) else (
    echo.
    echo [ОШИБКА] Сборка завершилась с ошибкой.
)

pause
