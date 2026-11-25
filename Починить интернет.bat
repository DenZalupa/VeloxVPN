@echo off
title VeloxVPN - восстановление интернета
setlocal

echo ============================================================
echo    VeloxVPN - восстановление системных настроек сети
echo ============================================================
echo.
echo  Эта утилита сбрасывает настройки, которые могли "зависнуть"
echo  после аварийного завершения конфигуратора:
echo    - системный прокси Windows;
echo    - оставшиеся процессы sing-box;
echo    - осиротевший TUN-адаптер VeloxVPN.
echo.

echo [1/4] Выключаем системный прокси Windows...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "" /f >nul 2>&1
if exist "%~dp0data\proxy_backup.json" (
    echo       - восстанавливаем ваш прежний прокси, если он был...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore_proxy.ps1" 2>nul
)
echo       готово.

echo [2/4] Останавливаем оставшиеся процессы sing-box...
taskkill /F /IM sing-box.exe >nul 2>&1
echo       готово.

echo [3/4] Удаляем TUN-адаптер VeloxVPN...
netsh interface delete interface name="VeloxVPN" >nul 2>&1
if errorlevel 1 (
    echo       - адаптер не найден или удаление требует прав Администратора.
) else (
    echo       готово.
)

echo [4/4] Сообщаем системе об изменении настроек сети...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\refresh_internet.ps1" 2>nul
echo       готово.

echo.
echo ============================================================
echo   Готово! Интернет должен заработать снова.
echo ============================================================
echo.
ping -n 7 127.0.0.1 >nul
endlocal
