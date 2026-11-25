"""
Нативное окно приложения VeloxVPN.

Раньше интерфейс открывался в Edge в app-режиме: адресной строки не видно,
но в фоне жил целый браузерный процесс (~150–200 МБ RAM) и окно зависело от
Edge (его первого запуска, «открыть в браузере» и т.п.).

Теперь используется нативное окно Windows на движке WebView2 (pywebview):
  • то же самое окно без адресной строки и вкладок;
  • никакого Edge в процессах — экономия 150–200 МБ RAM;
  • если WebView2 недоступен или pywebview не запустился — автоматический
    откат на Edge app-режим (старое поведение).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

from core.applog import log_line

APP_TITLE = "VeloxVPN — Быстрый конфигуратор VPN"
BG_COLOR = "#e8eaef"


def _icon_path() -> Optional[str]:
    """Иконка приложения (рядом с EXE или в корне проекта)."""
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "app.ico")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "app.ico")
    else:
        candidates.append(Path(__file__).resolve().parent.parent / "app.ico")
    for path in candidates:
        try:
            if path.exists():
                return str(path)
        except Exception:
            continue
    return None


def webview_available() -> bool:
    """Установлен ли pywebview."""
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def find_edge() -> Optional[str]:
    """Путь к Edge или Chrome (запасной вариант запуска окна)."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                return path
        except Exception:
            continue
    return None


def open_edge_window(url: str) -> Optional[subprocess.Popen]:
    """Запасной вариант: окно Edge в app-режиме (как раньше)."""
    browser = find_edge()
    if browser:
        args = [
            browser,
            f"--app={url}",
            "--window-size=1150,780",
            "--window-position=120,80",
            "--disable-features=Translate",
        ]
        try:
            return subprocess.Popen(args)
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return None


class AppWindow:
    """
    Нативное окно WebView2.

    Поведение как у HAPP/Incy:
      • закрытие окна не завершает программу, а сворачивает её в трей;
      • из трея окно можно открыть снова одним кликом;
      • «Выход» в трее действительно закрывает приложение.
    """
    def __init__(self, app_url: str, on_quit: Optional[Callable[[], None]] = None) -> None:
        self.app_url = app_url
        self.on_quit = on_quit
        self.window: Any = None
        self.tray_available = True
        self._hidden_notified = False
        self._allow_close = False

    # -------------------------------------------------- вызовы из потока трея
    def show(self) -> None:
        """Показать окно (из трея)."""
        if self.window is None:
            open_edge_window(self.app_url)
            return
        try:
            self.window.show()
        except Exception as exc:
            log_line(f"[GUI] Не удалось показать окно: {exc}")
            return
        try:
            self.window.restore()
        except Exception:
            pass
        try:
            self.window.set_title(APP_TITLE)
        except Exception:
            pass
        try:
            import ctypes
            hwnd = None
            if hasattr(self.window, 'native') and hasattr(self.window.native, 'Handle'):
                hwnd = int(self.window.native.Handle)
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def destroy(self) -> None:
        """Закрыть окно окончательно (выход из приложения)."""
        if self.window is None:
            return
        # Разрешаем закрытие: обработчик закрытия по умолчанию сворачивает
        # окно в трей, а тут нам нужно именно закрыть.
        self._allow_close = True
        try:
            self.window.destroy()
        except Exception as exc:
            log_line(f"[GUI] Не удалось закрыть окно: {exc}")

    def hide(self) -> None:
        """Свернуть окно в трей (без закрытия)."""
        if self.window is None:
            return
        try:
            self.window.hide()
        except Exception as exc:
            log_line(f"[GUI] Не удалось свернуть окно: {exc}")

    # ------------------------------------------------------------- внутреннее
    def _hide_later(self) -> None:
        # Скрываем окно из отдельного потока: вызов Hide() прямо из обработчика
        # закрытия deadlock-ится на WinForms (Invoke ждёт UI-поток, который
        # сейчас занят этим же обработчиком).
        time.sleep(0.3)
        try:
            if self.window is not None:
                self.window.hide()
        except Exception as exc:
            log_line(f"[GUI] Не удалось скрыть окно: {exc}")

    def _on_closing(self) -> bool:
        """Обработчик закрытия окна. True — разрешить закрыть, False — отменить."""
        if self._allow_close:
            # Явный выход из приложения — закрываем по-настоящему
            return True

        # Проверяем настройку сворачивания в трей
        try:
            from core.storage import storage
            minimize_to_tray = storage.get_settings().get("minimize_to_tray", True)
        except Exception:
            minimize_to_tray = True

        if self.tray_available and minimize_to_tray:
            threading.Thread(target=self._hide_later, daemon=True).start()
            if not self._hidden_notified:
                self._hidden_notified = True
                log_line("Окно закрыто — приложение свернуто в системный трей")
                try:
                    from core.tray import notify_minimized
                    notify_minimized()
                except Exception:
                    pass
            return False
        if self.on_quit:
            try:
                self.on_quit()
            except Exception:
                pass
        return True

    def run(self) -> None:
        """
        Создаёт окно и запускает GUI-цикл. Блокирующий вызов — только из
        главного потока. Возвращается, когда окно уничтожено.
        """
        import webview

        kwargs = dict(
            title=APP_TITLE,
            url=self.app_url,
            width=1150,
            height=780,
            x=120,
            y=80,
            min_size=(940, 640),
            resizable=True,
            frameless=False,
            easy_drag=True,
            shadow=True,
            background_color=BG_COLOR,
            confirm_close=False,
            text_select=True,
        )
        self.window = webview.create_window(**kwargs)

        icon = _icon_path()
        start_kwargs = {
            "private_mode": False,
            "debug": False,
        }
        if icon:
            start_kwargs["icon"] = icon
        try:
            webview_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VeloxVPN" / "webview"
            webview_dir.mkdir(parents=True, exist_ok=True)
            start_kwargs["storage_path"] = str(webview_dir)
        except Exception:
            pass

        self.window.events.closing += self._on_closing
        set_current_window(self)
        webview.start(**start_kwargs)


# Текущее окно приложения — чтобы сервер мог управлять им из веб-интерфейса
_current_window: Optional[AppWindow] = None


def set_current_window(window: Optional[AppWindow]) -> None:
    global _current_window
    _current_window = window


def minimize_to_tray() -> bool:
    """Свернуть окно в трей (вызывается из интерфейса)."""
    if _current_window is None:
        return False
    try:
        _current_window.hide()
        return True
    except Exception as exc:
        log_line(f"[GUI] Не удалось свернуть окно: {exc}")
        return False


def show_window() -> bool:
    """Показать окно (например, из трея или по внешнему запросу)."""
    if _current_window is None:
        return False
    try:
        _current_window.show()
        return True
    except Exception:
        return False
