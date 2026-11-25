import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DESKTOP = Path(os.path.expanduser('~/Desktop'))
LNK_PATH = DESKTOP / "VeloxVPN.lnk"
TARGET_BAT = BASE_DIR / "start_admin.bat"
ICON_PATH = BASE_DIR / "app.ico"

ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{str(LNK_PATH).replace('\\', '\\\\')}')
$s.TargetPath = '{str(TARGET_BAT).replace('\\', '\\\\')}'
$s.WorkingDirectory = '{str(BASE_DIR).replace('\\', '\\\\')}'
$s.IconLocation = '{str(ICON_PATH).replace('\\', '\\\\')}'
$s.Description = 'VeloxVPN Configurator'
$s.Save()

$bytes = [System.IO.File]::ReadAllBytes('{str(LNK_PATH).replace('\\', '\\\\')}')
$bytes[0x15] = $bytes[0x15] -bor 0x20
[System.IO.File]::WriteAllBytes('{str(LNK_PATH).replace('\\', '\\\\')}', $bytes)
"""

subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script], check=True)
print("Desktop shortcut created successfully at:", LNK_PATH)
