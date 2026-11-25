# Оповещает Windows об изменении настроек интернета (InternetSetOptionW).
# Нужен, чтобы браузеры и системные службы сразу подхватили новые параметры прокси.

$signature = @'
[DllImport("wininet.dll", SetLastError = true)]
public static extern bool InternetSetOptionW(IntPtr hInternet, int dwOption, IntPtr lpBuffer, int dwBufferLength);
'@

try {
    $type = Add-Type -MemberDefinition $signature -Name WinInetHelper -Namespace Velox -PassThru
    [Velox.WinInetHelper]::InternetSetOptionW([IntPtr]::Zero, 39, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # SETTINGS_CHANGED
    [Velox.WinInetHelper]::InternetSetOptionW([IntPtr]::Zero, 37, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # REFRESH
    exit 0
} catch {
    exit 0
}
