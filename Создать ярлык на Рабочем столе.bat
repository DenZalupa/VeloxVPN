@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Создание ярлыка VeloxVPN на Рабочем столе

echo ===================================================
echo     Создание ярлыка VeloxVPN на Рабочем столе...
echo ===================================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut(\"$d\VeloxVPN.lnk\"); $s.TargetPath = '%~dp0dist\VeloxVPN\VeloxVPN.exe'; $s.WorkingDirectory = '%~dp0dist\VeloxVPN'; $s.IconLocation = '%~dp0dist\VeloxVPN\app.ico'; $s.Description = 'VeloxVPN Configurator'; $s.Save(); Write-Host 'Ярлык успешно создан на Рабочем столе!'"

echo.
echo Готово! На вашем Рабочем столе появился ярлык VeloxVPN.
echo.
pause
