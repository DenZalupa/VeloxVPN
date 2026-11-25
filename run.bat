@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title VeloxVPN Configurator
cd /d "%~dp0"

echo ===================================================
echo           VeloxVPN Configurator Launcher
echo ===================================================
echo.

:: 1. Check Administrator Rights
net session >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Запущено от имени Администратора (TUN-режим доступен)
) else (
    echo [i] Обычный запуск (Прокси доступен)
    echo     Для TUN-режима: ПКМ по run.bat -^> "Запуск от имени администратора"
)
echo.

:: 2. Terminate any orphan sing-box processes
taskkill /F /IM sing-box.exe >nul 2>&1

:: 3. Locate Python
set "PY_BIN="

where python >nul 2>&1
if %errorlevel% equ 0 set "PY_BIN=python"

if not defined PY_BIN (
    where py >nul 2>&1
    if %errorlevel% equ 0 set "PY_BIN=py"
)

if not defined PY_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PY_BIN=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    )
)

if not defined PY_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY_BIN=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
)

if not defined PY_BIN (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_BIN=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    )
)

if not defined PY_BIN (
    if exist "C:\Python313\python.exe" set "PY_BIN=C:\Python313\python.exe"
    if exist "C:\Python312\python.exe" set "PY_BIN=C:\Python312\python.exe"
)

if not defined PY_BIN (
    echo [ОШИБКА] Python не найден на компьютере!
    echo Убедитесь, что Python установлен.
    echo.
    pause
    exit /b 1
)

echo [*] Используется Python: !PY_BIN!
echo [*] Запуск VeloxVPN...
echo.

!PY_BIN! main.py

echo.
echo ===================================================
echo  Приложение завершило работу.
echo ===================================================
pause