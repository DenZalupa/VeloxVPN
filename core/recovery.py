"""
Самовосстановление сетевых настроек VeloxVPN.

Проблема, которую решает модуль:
после подключения приложение включает системный прокси Windows (и/или TUN-адаптер).
Если приложение упало или было убито принудительно (taskkill / F, краш, выключение),
система оставалась с прокси на «мёртвый» локальный порт — интернет переставал работать
до повторного запуска конфигуратора.

Что здесь есть:
  • proxy_state() / is_proxy_stale() — диагностика «зависшего» прокси;
  • full_cleanup() — полная очистка: прокси + осиротевшее ядро + TUN-адаптер;
  • Watchdog — фоновый поток, следящий за живостью ядра и прокси;
  • Guardian (см. core/guardian.py) — отдельный процесс-перехватчик, который
    переживает гибель основного приложения и чистит систему.
"""

from __future__ import annotations

import ctypes
import logging
import os
import socket
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from core.applog import log_line
from core.paths import (
    DATA_DIR,
    GUARDIAN_PID_FILE,
    MAIN_PID_FILE,
    PID_FILE,
    ensure_data_dir,
)

logger = logging.getLogger(__name__)

# Порты, которые занимает VeloxVPN (mixed-in и socks-in в конфиге sing-box)
OWN_PROXY_PORTS = {20809, 20808}
TUN_INTERFACE_NAME = "VeloxVPN"
SINGBOX_IMAGE = "sing-box.exe"


# ---------------------------------------------------------------------------
# Низкоуровневые помощники Windows
# ---------------------------------------------------------------------------

def _run(cmd: List[str], timeout: int = 12) -> Tuple[int, str]:
    """Запускает команду и возвращает (код возврата, вывод)."""
    try:
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            timeout=timeout,
        )
        return res.returncode, ((res.stdout or "") + (res.stderr or ""))
    except Exception as exc:
        return -1, str(exc)


def is_port_listening(host: str = "127.0.0.1", port: int = 20809, timeout: float = 0.6) -> bool:
    """True, если на указанном локальном порту кто-то принимает соединения."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def process_alive(pid: int) -> bool:
    """True, если процесс с указанным PID существует и ещё работает."""
    if not pid or int(pid) <= 0:
        return False
    pid = int(pid)

    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    code = ctypes.c_ulong()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                        return code.value == STILL_ACTIVE
                    return True
                finally:
                    kernel32.CloseHandle(handle)
            return _pid_in_tasklist(pid)
        except Exception:
            return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _pid_in_tasklist(pid: int) -> bool:
    code, out = _run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"])
    if code != 0:
        return False
    return f'"{int(pid)}"' in out


def process_image_name(pid: int) -> str:
    """Полный путь к исполняемому файлу процесса (пустая строка, если не вышло)."""
    if os.name != "nt" or not pid:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(520)
            buf = ctypes.create_unicode_buffer(520)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value
            return ""
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def process_has_exited(pid: int) -> bool:
    """
    True, если процесс уже завершился (в том числе если он умер аварийно).
    На Windows используем WaitForSingleObject — это однозначнее GetExitCodeProcess.
    """
    if not pid or int(pid) <= 0:
        return True
    pid = int(pid)

    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                try:
                    result = kernel32.WaitForSingleObject(handle, 0)
                    return result == 0  # WAIT_OBJECT_0 — процесс завершён
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass

    return not process_alive(pid)


# ---------------------------------------------------------------------------
# Разбор настроек прокси
# ---------------------------------------------------------------------------

def parse_host_port(value: str) -> Tuple[str, Optional[int]]:
    """Разбирает "host:port" (в т.ч. "[::1]:8080")."""
    value = (value or "").strip()
    if not value:
        return "", None
    if value.startswith("["):
        host, _, rest = value.partition("]")
        host = host.lstrip("[")
        port_s = rest.lstrip(":")
        try:
            return host, int(port_s)
        except ValueError:
            return host, None
    if ":" in value:
        host, _, port_s = value.rpartition(":")
        try:
            return host.strip(), int(port_s.strip())
        except ValueError:
            return host.strip(), None
    return value, None


def parse_proxy_server(raw: str) -> Tuple[str, Optional[int]]:
    """
    Разбирает значение реестра ProxyServer.
    Поддерживает форматы "127.0.0.1:20809" и "http=127.0.0.1:20809;https=...".
    """
    text = (raw or "").strip()
    if not text:
        return "", None
    if "=" in text:
        for part in text.split(";"):
            if "=" not in part:
                continue
            _, _, value = part.partition("=")
            host, port = parse_host_port(value)
            if host:
                return host, port
        return "", None
    return parse_host_port(text)


def proxy_state() -> Dict[str, Any]:
    """Текущее состояние системного прокси Windows."""
    from core.system_proxy import get_system_proxy_status

    enabled, raw = get_system_proxy_status()
    host, port = parse_proxy_server(raw)
    listening = False
    if enabled and host and port:
        listening = is_port_listening(host, port)
    return {
        "enabled": bool(enabled),
        "server": raw or "",
        "host": host,
        "port": port,
        "listening": listening,
        "own": bool(port in OWN_PROXY_PORTS) if port else False,
    }


def is_proxy_stale(state: Optional[Dict[str, Any]] = None) -> bool:
    """
    True, если прокси включён, указывает на наш порт, но там никто не слушает.
    Чужие прокси (Clash, v2rayN и т.п.) мы не трогаем.
    """
    state = state or proxy_state()
    if not state.get("enabled"):
        return False
    port = state.get("port")
    if port not in OWN_PROXY_PORTS:
        return False
    return not state.get("listening")


# ---------------------------------------------------------------------------
# PID-файлы
# ---------------------------------------------------------------------------

def write_pid_file(pid: int) -> None:
    try:
        ensure_data_dir()
        with open(PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(int(pid)))
    except Exception as exc:
        logger.debug(f"Не удалось записать PID-файл: {exc}")


def read_pid_file() -> Optional[int]:
    try:
        if not PID_FILE.exists():
            return None
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def clear_pid_file() -> None:
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def write_guardian_pid(pid: int) -> None:
    try:
        ensure_data_dir()
        with open(GUARDIAN_PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(int(pid)))
    except Exception:
        pass


def read_guardian_pid() -> Optional[int]:
    try:
        if not GUARDIAN_PID_FILE.exists():
            return None
        return int(GUARDIAN_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def clear_guardian_pid() -> None:
    try:
        if GUARDIAN_PID_FILE.exists():
            GUARDIAN_PID_FILE.unlink()
    except Exception:
        pass


def write_main_pid(pid: int) -> None:
    try:
        ensure_data_dir()
        with open(MAIN_PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(int(pid)))
    except Exception:
        pass


def read_main_pid() -> Optional[int]:
    """PID основного приложения (если файл есть и читается)."""
    try:
        if not MAIN_PID_FILE.exists():
            return None
        return int(MAIN_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def guardian_alive() -> bool:
    """Жив ли сторожевой процесс."""
    pid = read_guardian_pid()
    return bool(pid and process_alive(pid))


# ---------------------------------------------------------------------------
# Уборка: ядро sing-box и TUN-адаптер
# ---------------------------------------------------------------------------

def kill_singbox_pid(pid: int) -> bool:
    """Принудительно завершает процесс sing-box по PID (с проверкой имени файла)."""
    if not pid or int(pid) <= 0:
        return False
    pid = int(pid)
    if not process_alive(pid):
        return False

    image = process_image_name(pid)
    if image and SINGBOX_IMAGE.lower() not in image.lower():
        logger.warning(f"PID {pid} не sing-box ({image}) — не трогаем.")
        return False

    _run(["taskkill", "/F", "/PID", str(pid)])
    return True


def find_our_singbox_pids() -> List[int]:
    """Ищет процессы sing-box, запущенные с НАШИМ конфигом (осиротевшие)."""
    pids: List[int] = []
    if os.name != "nt":
        return pids
    config_name = "singbox_active.json"
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='sing-box.exe'\" | "
        "Where-Object { $_.CommandLine -like '*" + config_name + "*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=15)
    if code != 0:
        return pids
    for chunk in out.replace("\r", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk.isdigit():
            pids.append(int(chunk))
    return pids


def kill_orphan_singbox() -> bool:
    """
    Убивает ядро sing-box, оставшееся после падения приложения.
    Сначала — по PID-файлу, затем — поиск по командной строке.
    """
    killed = False

    pid = read_pid_file()
    if pid and kill_singbox_pid(pid):
        killed = True
    clear_pid_file()

    for orphan in find_our_singbox_pids():
        if orphan == os.getpid():
            continue
        if kill_singbox_pid(orphan):
            killed = True

    return killed


def tun_interface_exists(name: str = TUN_INTERFACE_NAME) -> bool:
    """Существует ли TUN-адаптер с таким именем."""
    if os.name != "nt":
        return False
    code, out = _run(["netsh", "interface", "show", "interface"])
    if code != 0:
        return False
    return name.lower() in out.lower()


def any_singbox_running() -> bool:
    """Запущен ли в системе хоть один процесс sing-box."""
    if os.name != "nt":
        return False
    code, out = _run(["tasklist", "/FI", "IMAGENAME eq sing-box.exe", "/NH"])
    if code != 0:
        return False
    return "sing-box.exe" in out.lower()


def remove_tun_interface(name: str = TUN_INTERFACE_NAME) -> bool:
    """
    Удаляет осиротевший TUN-адаптер. Требует прав администратора.
    Возвращает True, если адаптер был удалён.
    """
    if os.name != "nt":
        return False
    if not tun_interface_exists(name):
        return False
    code, out = _run(["netsh", "interface", "delete", "interface", f'name="{name}"'])
    if code == 0:
        logger.info(f"TUN-адаптер {name} удалён")
        return True
    logger.warning(f"Не удалось удалить TUN-адаптер {name}: {out.strip()[:200]}")
    return False


# ---------------------------------------------------------------------------
# Полная очистка
# ---------------------------------------------------------------------------

def full_cleanup(
    reason: str = "",
    kill_core: bool = True,
    remove_tun: bool = True,
    disable_proxy: bool = True,
) -> Dict[str, Any]:
    """
    Приводит систему в рабочее состояние:
      • выключает системный прокси Windows;
      • убивает осиротевшее ядро sing-box;
      • удаляет осиротевший TUN-адаптер.
    """
    from core.system_proxy import disable_system_proxy

    report: Dict[str, Any] = {
        "reason": reason,
        "proxy_disabled": False,
        "core_killed": False,
        "tun_removed": False,
        "at": time.time(),
    }

    if disable_proxy:
        try:
            report["proxy_disabled"] = bool(disable_system_proxy())
        except Exception as exc:
            logger.debug(f"Ошибка отключения прокси: {exc}")

    if kill_core:
        try:
            report["core_killed"] = bool(kill_orphan_singbox())
        except Exception as exc:
            logger.debug(f"Ошибка остановки ядра: {exc}")

    if remove_tun:
        try:
            report["tun_removed"] = bool(remove_tun_interface())
        except Exception as exc:
            logger.debug(f"Ошибка удаления TUN: {exc}")

    if reason:
        log_line(f"[ВОССТАНОВЛЕНИЕ] {reason} | прокси: {report['proxy_disabled']} | "
                 f"ядро: {report['core_killed']} | TUN: {report['tun_removed']}")
        logger.info(f"Восстановление: {reason} -> {report}")

    return report


def repair_network() -> Dict[str, Any]:
    """
    «Восстановить интернет»: сбрасывает зависший прокси и подчищает осиротевшее
    ядро/TUN. Возвращает подробный отчёт для интерфейса.
    """
    state = proxy_state()
    report = full_cleanup(reason="ручная кнопка «Восстановить интернет»")
    report["proxy_before"] = state
    report["proxy_after"] = proxy_state()
    report["ok"] = not report["proxy_after"]["enabled"]
    return report


# ---------------------------------------------------------------------------
# Watchdog — следит за живостью ядра и прокси прямо внутри приложения
# ---------------------------------------------------------------------------

class Watchdog(threading.Thread):
    """
    Фоновый поток: если ядро sing-box умерло (а приложение ещё живо) —
    гасит системный прокси и удаляет TUN-адаптер, чтобы интернет не пропал.
    """

    def __init__(self, runner, interval: float = 3.0):
        super().__init__(daemon=True, name="velox-watchdog")
        self.runner = runner
        self.interval = interval
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._check()
            except Exception:
                pass

    def _check(self) -> None:
        status = getattr(self.runner, "status", "stopped")
        proc = getattr(self.runner, "process", None)

        # 1) Ядро умерло, а приложение ещё работает
        if status == "running" and proc is not None and proc.poll() is not None:
            ks = False
            try:
                from core.storage import storage
                ks = bool(storage.get_settings().get("kill_switch", False))
            except Exception:
                pass
            if ks:
                logger.warning("Watchdog: ядро sing-box завершилось, но Kill Switch активен — блокируем прямой трафик от утечки")
                try:
                    self.runner.status = "stopped"
                    self.runner.kill_switch_active = True
                except Exception:
                    pass
                return

            logger.info("Watchdog: ядро sing-box завершилось — гасим прокси")
            full_cleanup(reason="watchdog: ядро sing-box неожиданно завершилось", kill_core=False)
            try:
                self.runner.status = "stopped"
            except Exception:
                pass
            return

        # 2) Прокси включён, но наш порт никто не слушает и VPN не активен
        if status in ("stopped", "error"):
            state = proxy_state()
            if is_proxy_stale(state):
                logger.info("Watchdog: обнаружен зависший системный прокси — выключаем")
                full_cleanup(reason="watchdog: зависший системный прокси", kill_core=False, remove_tun=False)
