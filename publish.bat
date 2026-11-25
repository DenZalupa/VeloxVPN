@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title VeloxVPN — публикация на GitHub

echo ===================================================
echo     VeloxVPN — публикация исходников на GitHub
echo ===================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден в PATH.
    pause
    exit /b 1
)

if not exist "%USERPROFILE%\.velox_github_token" (
    echo [i] Токен не найден: %USERPROFILE%\.velox_github_token
    echo.
    echo Создай Personal Access Token (classic) на GitHub:
    echo   Settings -^> Developer settings -^> Personal access tokens
    echo   -^> Generate new token (classic)
    echo   Галочка "public_repo" (для публичного репозитория).
    echo.
    echo Затем создай файл %USERPROFILE%\.velox_github_token
    echo и вставь в него токен (одна строка, без пробелов).
    echo.
    pause
    exit /b 1
)

set /p REPO=Имя репозитория [VeloxVPN]:
if "%REPO%"=="" set "REPO=VeloxVPN"

echo.
echo [1/2] Публикуем исходники...
python "publish_github.py" --repo "%REPO%" --visibility public
if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Не удалось опубликовать. Проверь токен и доступ к GitHub.
    pause
    exit /b 1
)

echo.
echo [2/2] Собираем релиз со сборкой (если папка VeloxVPN есть)...
if exist "VeloxVPN\VeloxVPN.exe" (
    python "publish_github.py" --repo "%REPO%" --visibility public --release
) else (
    echo [i] Папка сборки не найдена — релиз пропущен.
)

echo.
echo ===================================================
echo  Готово. Открой свой профиль GitHub, чтобы увидеть репозиторий.
echo ===================================================
echo.
pause
