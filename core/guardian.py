"""
Guardian-процесс VeloxVPN (сторож).

Запускается вместе с основным приложением отдельным процессом и переживает его
гибель. Пока основной процесс жив — guardian молча спит. Как только основной
процесс умер (убит через taskkill / F, упал с ошибкой, вылетел) — guardian
приводит систему в рабочее состояние:

  • выключает системный прокси Windows (иначе интернет «мёртв» до перезапуска);
  • убивает осиротевший процесс sing-box;
  • удаляет осиротевший TUN-адаптер.

Особенности:
  • если приложение завершилось ШТАТНО — guardian ничего не трогает
    (приложение само всё убрало);
  • если приложение перезапустили — guardian переключается на новый PID
    и продолжает присматривать за ним, ничего не ломая.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from core.applog import log_line
from core.paths import (
    EXIT_MARKER_FILE,
    GUARDIAN_PID_FILE,
    MAIN_PID_FILE,
    ensure_data_dir,
)
from core.recovery import (
    clear_guardian_pid,
    full_cleanup,
    process_alive,
    process_has_exited,
    read_guardian_pid,
    read_main_pid,
    write_guardian_pid,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0
RESTART_GRACE = 3.0  # сколько секунд ждём перезапуск приложения


def _clean_exit_was_planned(pid: int) -> bool:
    """True, если приложение с таким PID завершилось штатно (мы сами убрали прокси)."""
    try:
        if not EXIT_MARKER_FILE.exists():
            return False
        return EXIT_MARKER_FILE.read_text(encoding="utf-8").strip() == str(int(pid))
    except Exception:
        return False


def _mark_clean_exit(pid: int) -> None:
    """Помечает, что приложение завершается штатно (guardian не должен ничего трогать)."""
    try:
        ensure_data_dir()
        EXIT_MARKER_FILE.write_text(str(int(pid)), encoding="utf-8")
    except Exception:
        pass


def clear_clean_exit_marker() -> None:
    """Снимает метку штатного выхода (вызывается при старте приложения)."""
    try:
        if EXIT_MARKER_FILE.exists():
            EXIT_MARKER_FILE.unlink()
    except Exception:
        pass


def run_guardian(parent_pid: int) -> int:
    """Цикл стража. Возвращает код выхода процесса."""
    ensure_data_dir()
    write_guardian_pid(os.getpid())
    log_line(f"[GUARDIAN] Сторож запущен, слежу за процессом {parent_pid}")

    watch_pid = int(parent_pid)
    started = time.time()

    try:
        while True:
            time.sleep(POLL_INTERVAL)

            # Приложение могло перезапуститься — переключаемся на новый PID
            main_pid = read_main_pid()
            if main_pid and main_pid != watch_pid and process_alive(main_pid):
                log_line(f"[GUARDIAN] Приложение перезапущено (PID {main_pid}) — продолжаю следить")
                watch_pid = main_pid
                continue

            if not process_has_exited(watch_pid):
                continue

            # Основной процесс умер. Даём шанс на перезапуск.
            time.sleep(RESTART_GRACE)
            main_pid = read_main_pid()
            if main_pid and process_alive(main_pid):
                log_line(f"[GUARDIAN] Приложение перезапущено (PID {main_pid}) — очистка не требуется")
                watch_pid = main_pid
                continue

            if _clean_exit_was_planned(watch_pid):
                log_line("[GUARDIAN] Приложение завершилось штатно — очистка не требуется")
                break

            log_line(f"[GUARDIAN] Основной процесс {watch_pid} погиб — восстанавливаю интернет")
            full_cleanup(reason=f"guardian: основной процесс {watch_pid} завершён аварийно")
            break

        log_line(f"[GUARDIAN] Сторож завершился (работал {int(time.time() - started)} с)")
    finally:
        clear_guardian_pid()
    return 0


def spawn_guardian(parent_pid: Optional[int] = None) -> Optional[int]:
    """
    Запускает сторожа. Если сторож уже работает — возвращаем его PID
    (старый сторож сам подхватит новый PID приложения из файла).
    """
    parent_pid = int(parent_pid or os.getpid())

    existing = read_guardian_pid()
    if existing and existing != os.getpid() and process_alive(existing):
        log_line(f"[GUARDIAN] Сторож уже запущен (PID {existing})")
        return existing

    try:
        ensure_data_dir()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--guardian", "--parent-pid", str(parent_pid)]
        else:
            main_py = Path(__file__).resolve().parent.parent / "main.py"
            cmd = [sys.executable, str(main_py), "--guardian", "--parent-pid", str(parent_pid)]

        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parent.parent),
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_guardian_pid(proc.pid)
        log_line(f"[GUARDIAN] Сторож запущен (PID {proc.pid}), следит за {parent_pid}")
        return proc.pid
    except Exception as exc:
        logger.warning(f"Не удалось запустить сторожа: {exc}")
        log_line(f"[GUARDIAN] Ошибка запуска сторожа: {exc}")
        return None


def stop_guardian() -> None:
    """Останавливает сторожа (при штатном выходе приложения)."""
    pid = read_guardian_pid()
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(int(pid))],
                capture_output=True,
                creationflags=0x08000000,
            )
        else:
            os.kill(int(pid), 15)
    except Exception:
        pass
    clear_guardian_pid()
