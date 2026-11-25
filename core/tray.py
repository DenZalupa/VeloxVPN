"""
Системный трей VeloxVPN.

Позволяет контролировать подключение, не открывая окно приложения:
  • иконка в трее отражает статус (зелёный — подключено, серый — отключено, янтарный — подключение);
  • клик по иконке открывает окно приложения;
  • правая кнопка — меню: подключить, отключить, открыть окно, выход.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

# Безопасный патч ChangeWindowMessageFilterEx для Windows (исправляет PermissionError WinError 5)
try:
    import pystray._util.win32 as _puw
    import pystray._win32 as _pw
    def _safe_msg_filter(*args, **kwargs):
        return True
    _puw.ChangeWindowMessageFilterEx = _safe_msg_filter
    if hasattr(_pw, 'win32'):
        _pw.win32.ChangeWindowMessageFilterEx = _safe_msg_filter
except Exception:
    pass

from core.singbox_runner import runner

STATUS_COLORS: Dict[str, Any] = {
    "running": ((34, 155, 75, 255), (52, 199, 89, 255)),
    "starting": ((220, 130, 20, 255), (255, 165, 30, 255)),
    "connecting": ((220, 130, 20, 255), (255, 165, 30, 255)),
    "error": ((220, 45, 35, 255), (255, 65, 55, 255)),
    "stopped": ((45, 45, 50, 255), (90, 90, 100, 255)),
}

STATUS_LABELS: Dict[str, str] = {
    "running": "Подключено",
    "starting": "Подключение...",
    "connecting": "Подключение...",
    "error": "Ошибка",
    "stopped": "Отключено",
}


def _render_icon(status: str, size: int = 64):
    """Рисует современную чёткую иконку щита с молнией (VeloxVPN)."""
    from PIL import Image, ImageDraw

    s = size * 4  # 4x суперсэмплинг для идеальной четкости
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    bg, border = STATUS_COLORS.get(status, STATUS_COLORS["stopped"])

    # Сглаженный скругленный щит
    r = s * 0.22
    d.rounded_rectangle(
        (s * 0.06, s * 0.06, s * 0.94, s * 0.94),
        radius=r,
        fill=bg,
        outline=border,
        width=max(2, s // 22)
    )

    # Белая молния внутри щита
    bolt = [
        (s * 0.54, s * 0.18),
        (s * 0.30, s * 0.52),
        (s * 0.48, s * 0.52),
        (s * 0.42, s * 0.82),
        (s * 0.70, s * 0.46),
        (s * 0.52, s * 0.46)
    ]
    d.polygon(bolt, fill=(255, 255, 255, 255))

    return img.resize((size, size), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)


class TrayManager:
    """Иконка в системном трее с живым статусом подключения."""

    def __init__(self, app_url: str, on_open_window: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self.app_url = app_url.rstrip("/")
        self.on_open_window = on_open_window
        self.on_quit = on_quit
        self.icon = None
        self._stop_event = threading.Event()
        self._state_key: Optional[str] = None
        self._status = "stopped"
        self._node_name = ""

    # ------------------------------------------------------------------ API
    def _api(self, path: str, payload: Optional[dict] = None, timeout: int = 20) -> Optional[dict]:
        url = f"{self.app_url}{path}"
        try:
            if payload is None:
                req = urllib.request.Request(url, method="GET")
            else:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    # --------------------------------------------------------------- Меню
    def _build_menu(self):
        import pystray

        connected = self._status == "running"
        node = self._node_name or ""

        if connected:
            header = f"🟢 Подключено: {node}" if node else "🟢 Подключено"
        elif self._status in ("starting", "connecting"):
            header = "🟠 Подключение..."
        elif self._status == "error":
            header = "🔴 Ошибка подключения"
        else:
            header = "⚪ Отключено"

        items = [
            pystray.MenuItem(lambda _item: header, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Открыть VeloxVPN", self._on_open_window, default=True),
            pystray.MenuItem(
                "Отключиться" if connected else "Подключиться",
                self._on_toggle_connect,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Починить интернет", self._on_repair_network),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._on_quit),
        ]
        return pystray.Menu(*items)

    # ------------------------------------------------------------- Действия
    def _on_open_window(self, *_args) -> None:
        try:
            self.on_open_window()
        except Exception:
            pass

    def _on_quit(self, *_args) -> None:
        self._stop_event.set()
        try:
            self.on_quit()
        except Exception:
            pass

    def _on_toggle_connect(self, *_args) -> None:
        if self._status == "running":
            self._api("/api/disconnect", {})
        else:
            self._api("/api/connect", {})
        self._refresh(force=True)

    def _on_repair_network(self, *_args) -> None:
        """Сбрасывает зависший прокси и чистит осиротевшее ядро/TUN-адаптер."""
        result = self._api("/api/repair-network", {})
        if not result or not result.get("success"):
            return
        try:
            if self.icon:
                self.icon.notify(
                    "Системные настройки сброшены — интернет восстановлен.",
                    "VeloxVPN",
                )
        except Exception:
            pass
        self._refresh(force=True)

    # ------------------------------------------------------------ Обновление
    def _refresh(self, force: bool = False) -> None:
        if self.icon is None:
            return
        try:
            info = runner.get_info() or {}
        except Exception:
            info = {}

        status = str(info.get("status") or "stopped")
        node = ""
        active = info.get("active_node") or {}
        if isinstance(active, dict):
            node = str(active.get("name") or "")

        key = f"{status}|{node}"
        if not force and key == self._state_key:
            return

        self._state_key = key
        self._status = status
        self._node_name = node

        try:
            self.icon.icon = _render_icon(status)
            self.icon.title = f"VeloxVPN — {STATUS_LABELS.get(status, 'Отключено')}{(' (' + node + ')') if node and status == 'running' else ''}"
            self.icon.update_menu()
        except Exception:
            pass

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._refresh()
            time.sleep(1.2)

    # --------------------------------------------------------------- Старт
    def start(self) -> bool:
        """Запускает иконку в трее. Возвращает False, если трей недоступен."""
        try:
            import pystray
        except Exception:
            return False

        try:
            self.icon = pystray.Icon(
                "veloxvpn",
                _render_icon("stopped"),
                "VeloxVPN — Отключено",
                menu=self._build_menu(),
            )
        except Exception:
            self.icon = None
            return False

        try:
            self.icon.run_detached()
        except Exception:
            # run_detached может не поддерживаться — запускаем цикл в потоке
            thread = threading.Thread(target=self.icon.run, daemon=True)
            thread.start()

        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._refresh(force=True)
        return True

    def stop(self) -> None:
        self._stop_event.set()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass


tray: Optional[TrayManager] = None


def notify_minimized():
    """Показывает уведомление о сворачивании в трей."""
    global tray
    if tray and tray.icon:
        try:
            tray.icon.notify(
                "Приложение свёрнуто в трей и продолжает работать в фоне.\nНажмите на значок возле часов, чтобы открыть окно.",
                "VeloxVPN"
            )
        except Exception:
            pass
