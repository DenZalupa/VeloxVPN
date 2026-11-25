"""
Создаёт ярлык "VeloxVPN Gothic" на рабочем столе,
который запускает собранный EXE из папки VeloxVPN-Gothic-2.

Запуск:  python create_shortcut_gothic.py
"""

import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DESKTOP = Path(os.path.expanduser("~/Desktop"))
LNK_PATH = DESKTOP / "VeloxVPN Gothic.lnk"


def find_build_dir() -> Path | None:
    """Приоритет — папка VeloxVPN, иначе самая свежая из VeloxVPN-*."""
    canonical = BASE_DIR / "VeloxVPN"
    if (canonical / "VeloxVPN.exe").exists():
        return canonical

    candidates = []
    for folder in BASE_DIR.glob("VeloxVPN-*"):
        if not folder.is_dir():
            continue
        exe = folder / "VeloxVPN.exe"
        if exe.exists():
            candidates.append((exe.stat().st_mtime, folder))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


DIST_DIR = find_build_dir()
EXE = (DIST_DIR / "VeloxVPN.exe") if DIST_DIR else (BASE_DIR / "VeloxVPN-Gothic-3" / "VeloxVPN.exe")
ICON_PATH = (DIST_DIR / "app.ico") if DIST_DIR else (BASE_DIR / "app.ico")


def main() -> None:
    if not EXE.exists():
        print(f"[ОШИБКА] Не найден исполняемый файл: {EXE}")
        print("Сначала собери приложение: pyinstaller ... (см. build_exe.bat)")
        return

    icon_path = ICON_PATH
    if not icon_path.exists():
        icon_path = BASE_DIR / "app.ico"

    ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{str(LNK_PATH).replace('\\', '\\\\')}')
$s.TargetPath = '{str(EXE).replace('\\', '\\\\')}'
$s.WorkingDirectory = '{str(DIST_DIR).replace('\\', '\\\\')}'
$s.IconLocation = '{str(icon_path).replace('\\', '\\\\')}'
$s.Description = 'VeloxVPN Configurator — Gothic build'
$s.Save()

# Флаг "запускать от имени администратора" (0x20 в байте 0x15)
$bytes = [System.IO.File]::ReadAllBytes('{str(LNK_PATH).replace('\\', '\\\\')}')
$bytes[0x15] = $bytes[0x15] -bor 0x20
[System.IO.File]::WriteAllBytes('{str(LNK_PATH).replace('\\', '\\\\')}', $bytes)
"""

    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        check=True,
    )
    print("Desktop shortcut created successfully at:", LNK_PATH)


if __name__ == "__main__":
    main()
