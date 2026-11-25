import asyncio
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from aiohttp import web

from server import FastVPNServer
from core.applog import log_line
from core.gui import AppWindow, open_edge_window, webview_available
from core.singbox_runner import runner
from core.system_proxy import disable_system_proxy
from core.tray import TrayManager

def find_available_port(start_port: int = 54321) -> int:
    """Find available TCP port."""
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port

def startup_repair() -> None:
    """
    При старте приложения убираем следы прошлого аварийного завершения:
      • прокси, оставшийся включённым на мёртвый порт;
      • осиротевший TUN-адаптер (если ядро уже не работает).
    """
    from core.recovery import (
        any_singbox_running,
        is_proxy_stale,
        proxy_state,
        remove_tun_interface,
    )

    try:
        state = proxy_state()
        if is_proxy_stale(state):
            print("[ВОССТАНОВЛЕНИЕ] Обнаружен зависший системный прокси — отключаю.", flush=True)
            log_line("[ВОССТАНОВЛЕНИЕ] При старте обнаружен зависший прокси — отключён")
            disable_system_proxy()
    except Exception:
        pass

    try:
        if not any_singbox_running():
            if remove_tun_interface():
                print("[ВОССТАНОВЛЕНИЕ] Удалён осиротевший TUN-адаптер.", flush=True)
                log_line("[ВОССТАНОВЛЕНИЕ] При старте удалён осиротевший TUN-адаптер")
    except Exception:
        pass


def main():
    # --- Режим стража: отдельный процесс, переживающий гибель приложения ---
    args = sys.argv[1:]
    if "--guardian" in args:
        from core.guardian import run_guardian

        parent_pid = 0
        if "--parent-pid" in args:
            try:
                parent_pid = int(args[args.index("--parent-pid") + 1])
            except Exception:
                parent_pid = 0
        if parent_pid <= 0:
            parent_pid = os.getppid()
        sys.exit(run_guardian(parent_pid))

    from core.guardian import (
        clear_clean_exit_marker,
        spawn_guardian,
        stop_guardian,
    )
    from core.guardian import _mark_clean_exit
    from core.recovery import Watchdog, full_cleanup, write_main_pid

    clear_clean_exit_marker()
    write_main_pid(os.getpid())

    # --- Убираем следы прошлого аварийного завершения ---
    startup_repair()

    port = find_available_port(54321)
    app_url = f"http://127.0.0.1:{port}"

    print("=" * 60, flush=True)
    print(f" ⚡ VeloxVPN Configurator (Быстрый VPN клиент)", flush=True)
    print(f" 🚀 Сервер запущен: {app_url}", flush=True)
    print("=" * 60, flush=True)

    server = FastVPNServer()
    quit_event = threading.Event()

    # --- Сервер живёт в отдельном потоке, чтобы трей держал главный ---
    def run_server():
        try:
            web.run_app(
                server.app,
                host="127.0.0.1",
                port=port,
                print=print,
                handle_signals=False,
            )
        except Exception as exc:  # pragma: no cover
            print(f"[ОШИБКА] Сервер: {exc}", flush=True)

    server_thread = threading.Thread(target=run_server, daemon=True, name="velox-server")
    server_thread.start()
    time.sleep(0.6)

    # --- Сторож: переживёт гибель приложения и починит интернет ---
    guardian_pid = spawn_guardian(os.getpid())

    # --- Watchdog: следит за живостью ядра и прокси ---
    watchdog = Watchdog(runner)
    watchdog.start()

    # --- Иконка в системном трее ---
    app_window = AppWindow(app_url, on_quit=lambda: quit_event.set())
    server.app_window = app_window

    def open_window():
        app_window.show()

    def quit_app():
        quit_event.set()
        app_window.destroy()

    tray = TrayManager(app_url, on_open_window=open_window, on_quit=quit_app)
    import core.tray as tray_mod
    tray_mod.tray = tray
    tray_started = tray.start()
    if not tray_started:
        print("[ПРЕДУПРЕЖДЕНИЕ] Системный трей недоступен (не установлен pystray).", flush=True)
    app_window.tray_available = tray_started
    log_line(
        f"Запуск: порт {port} | трей: {'да' if tray_started else 'нет'} | "
        f"страж: {'да' if guardian_pid else 'нет'} | {app_url}"
    )

    # --- Обработка сигналов: Ctrl+C, закрытие консоли, завершение сессии ---
    def request_quit(signum=None, frame=None):
        quit_event.set()
        app_window.destroy()

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, request_quit)
        except Exception:
            pass

    # --- Окно приложения ---
    if os.environ.get("VELOX_NO_WINDOW") == "1":
        # Режим без окна (автотесты, фоновый запуск)
        pass
    elif webview_available():
        try:
            # Нативное окно WebView2 — блокирует до закрытия окна/выхода
            app_window.run()
        except Exception as exc:
            print(f"[ПРЕДУПРЕЖДЕНИЕ] Нативное окно не запустилось: {exc}", flush=True)
            log_line(f"[GUI] Нативное окно не запустилось: {exc}")
            open_edge_window(app_url)
    else:
        print("[ПРЕДУПРЕЖДЕНИЕ] pywebview не установлен — открываем окно в Edge.", flush=True)
        log_line("[GUI] pywebview недоступен — используется Edge app-режим")
        open_edge_window(app_url)

    try:
        while not quit_event.is_set():
            time.sleep(0.4)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        print("\nЗавершение работы и очистка прокси...", flush=True)
        log_line("Завершение работы")
        watchdog.stop()
        tray.stop()
        runner.stop()
        # Помечаем выход штатным — сторож ничего не будет трогать
        _mark_clean_exit(os.getpid())
        full_cleanup(reason="штатное завершение приложения", kill_core=False)
        disable_system_proxy()
        stop_guardian()
        print("Готово.", flush=True)
        # После закрытия окна остаются фоновые потоки .NET/WebView2 —
        # завершаем процесс принудительно, всё важное уже сделано.
        os._exit(0)

if __name__ == "__main__":
    main()
