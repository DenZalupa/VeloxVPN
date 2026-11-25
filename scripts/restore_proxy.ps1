# Возвращает пользователю тот системный прокси, который был включён ДО запуска VeloxVPN.
# Если прежний прокси не отвечает - оставляем прокси выключенным, чтобы интернет работал.

$backupFile = Join-Path $PSScriptRoot "..\data\proxy_backup.json"

try {
    if (-not (Test-Path $backupFile)) { exit 0 }

    $backup = Get-Content -Path $backupFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $backup.enabled) { exit 0 }

    $server = [string]$backup.server
    if ([string]::IsNullOrWhiteSpace($server)) { exit 0 }

    # Проверяем, отвечает ли прежний прокси
    $parts = $server -split ':'
    $host_ = $parts[0]
    $port_ = 0
    if ($parts.Count -gt 1) { [void][int]::TryParse($parts[-1], [ref]$port_) }

    $alive = $false
    if ($port_ -gt 0) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $task = $client.ConnectAsync($host_, $port_)
            $alive = $task.Wait(700) -and $client.Connected
            $client.Close()
        } catch { $alive = $false }
    }

    if ($alive) {
        $key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        Set-ItemProperty -Path $key -Name "ProxyEnable" -Value 1 -Type DWord
        Set-ItemProperty -Path $key -Name "ProxyServer" -Value $server -Type String
        if ($backup.override) {
            Set-ItemProperty -Path $key -Name "ProxyOverride" -Value ([string]$backup.override) -Type String
        }
        Write-Host "  - прежний прокси восстановлен: $server"
    } else {
        Write-Host "  - прежний прокси не отвечает, оставляем прокси выключенным"
    }

    Remove-Item -Path $backupFile -Force -ErrorAction SilentlyContinue
} catch {
    exit 0
}

exit 0
