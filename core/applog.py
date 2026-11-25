"""
Небольшой файловый лог запуска: помогает понять, что происходило с приложением,
даже если оно было убито принудительно.
"""

import time

from core.paths import APP_LOG_FILE, ensure_data_dir


def log_line(text: str) -> None:
    try:
        ensure_data_dir()
        with open(APP_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except Exception:
        pass
