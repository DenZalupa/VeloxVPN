"""
Общие пути приложения VeloxVPN.

Работает одинаково и в исходниках, и в собранном EXE:
  • в исходниках  — корень проекта;
  • в EXE         — папка рядом с VeloxVPN.exe (там же живут data/ и bin/).
"""

import sys
from pathlib import Path


def _detect_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR: Path = _detect_base_dir()
DATA_DIR: Path = BASE_DIR / "data"

# Файлы состояния для самовосстановления
PID_FILE: Path = DATA_DIR / "singbox.pid"       # PID запущенного ядра sing-box
GUARDIAN_PID_FILE: Path = DATA_DIR / "guardian.pid"  # PID сторожевого процесса
MAIN_PID_FILE: Path = DATA_DIR / "main.pid"     # PID основного приложения
PROXY_BACKUP_FILE: Path = DATA_DIR / "proxy_backup.json"  # резервная копия настроек прокси
APP_LOG_FILE: Path = DATA_DIR / "velox_app.log"
EXIT_MARKER_FILE: Path = DATA_DIR / "exit_ok"   # метка «приложение завершилось штатно»


def ensure_data_dir() -> Path:
    """Создаёт папку data (если возможно) и возвращает её путь."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return DATA_DIR
