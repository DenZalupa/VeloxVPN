@echo off
rem Публикация VeloxVPN на GitHub через обычный git + GitHub CLI (gh).
rem Требуется один раз пройти: gh auth login --hostname github.com --git-protocol https --web
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
title VeloxVPN - публикация на GitHub через git

where git >nul 2>&1
if %errorlevel% neq 0 goto :no_git
where gh >nul 2>&1
if %errorlevel% neq 0 goto :no_gh

gh auth status >nul 2>&1
if %errorlevel% neq 0 goto :need_login

set /p REPO=Имя репозитория [VeloxVPN]:
if "%REPO%"=="" set "REPO=VeloxVPN"

git add -A
git diff --cached --quiet
if %errorlevel% equ 0 goto :no_changes

set /p MSG=Описание изменений:
if "%MSG%"=="" set "MSG=Обновление VeloxVPN"
git commit -m "%MSG%"
if %errorlevel% neq 0 goto :commit_failed
goto :push

:no_changes
echo [i] Изменений нет - коммит не требуется.

:push
git remote get-url origin >nul 2>&1
if %errorlevel% neq 0 goto :create_repo
echo.
echo [1/2] Отправляю изменения в origin...
git push -u origin main
goto :check_push

:create_repo
echo.
echo [1/2] Создаю репозиторий %REPO% на GitHub...
gh repo create "%REPO%" --public --source=. --remote=origin --push

:check_push
if %errorlevel% neq 0 goto :push_failed
echo.
echo [2/2] Готово.
for /f "delims=" %%u in ('gh repo view --json url -q .url') do echo     %%u
echo.
pause
exit /b 0

:need_login
echo [i] Требуется вход в GitHub. Откроется браузер - подтвердите вход.
gh auth login --hostname github.com --git-protocol https --web
if %errorlevel% neq 0 goto :login_failed
goto :main_start

:login_failed
echo [ОШИБКА] Не удалось авторизоваться.
pause
exit /b 1

:commit_failed
echo [ОШИБКА] Не удалось создать коммит.
pause
exit /b 1

:push_failed
echo [ОШИБКА] Не удалось отправить изменения в GitHub.
pause
exit /b 1

:no_git
echo [ОШИБКА] Git не найден. Установите: winget install --id Git.Git -e --source winget
pause
exit /b 1

:no_gh
echo [ОШИБКА] GitHub CLI не найден. Установите: winget install --id GitHub.cli -e --source winget
pause
exit /b 1

:main_start
set /p REPO=Имя репозитория [VeloxVPN]:
if "%REPO%"=="" set "REPO=VeloxVPN"
git add -A
git diff --cached --quiet
if %errorlevel% equ 0 goto :no_changes
set /p MSG=Описание изменений:
if "%MSG%"=="" set "MSG=Обновление VeloxVPN"
git commit -m "%MSG%"
if %errorlevel% neq 0 goto :commit_failed
goto :push
