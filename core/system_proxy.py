import atexit
import ctypes
import json
import logging
import time
import winreg
from typing import Optional, Tuple

from core.paths import PROXY_BACKUP_FILE, ensure_data_dir

logger = logging.getLogger(__name__)

INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37

PROXY_HOST = "127.0.0.1"
PROXY_HTTP_PORT = 20809
PROXY_SOCKS_PORT = 20808

wininet = ctypes.windll.wininet

def notify_wininet():
    """Notify Windows system that internet settings have changed."""
    try:
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception as e:
        logger.error(f"Failed to notify wininet: {e}")

def _open_key(access=winreg.KEY_QUERY_VALUE):
    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        0,
        access
    )

def _read_proxy_values() -> dict:
    """Читает текущие настройки системного прокси (без изменений)."""
    values = {"enabled": False, "server": "", "override": ""}
    try:
        key = _open_key()
    except Exception:
        return values
    try:
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            values["enabled"] = bool(enabled)
        except FileNotFoundError:
            pass
        try:
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            values["server"] = str(server)
        except FileNotFoundError:
            pass
        try:
            override, _ = winreg.QueryValueEx(key, "ProxyOverride")
            values["override"] = str(override)
        except FileNotFoundError:
            pass
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    return values

def _save_proxy_backup() -> None:
    """
    Запоминает настройки прокси, которые были ДО включения нашего прокси.
    Нужно, чтобы после выключения вернуть пользователю его собственные
    настройки (например, если до нас работал Clash/V2Ray).
    """
    current = _read_proxy_values()
    if current["server"] == f"{PROXY_HOST}:{PROXY_HTTP_PORT}":
        # Прокси уже наш — перезаписывать резервную копию не нужно
        return
    try:
        ensure_data_dir()
        current["saved_at"] = time.time()
        with open(PROXY_BACKUP_FILE, "w", encoding="utf-8") as fh:
            json.dump(current, fh, ensure_ascii=False)
    except Exception as exc:
        logger.debug(f"Не удалось сохранить резервную копию прокси: {exc}")

def _load_proxy_backup() -> Optional[dict]:
    try:
        if not PROXY_BACKUP_FILE.exists():
            return None
        with open(PROXY_BACKUP_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _clear_proxy_backup() -> None:
    try:
        if PROXY_BACKUP_FILE.exists():
            PROXY_BACKUP_FILE.unlink()
    except Exception:
        pass

def enable_system_proxy(http_port: int = PROXY_HTTP_PORT, socks_port: int = PROXY_SOCKS_PORT) -> bool:
    """
    Enables Windows system proxy for all web traffic (HTTP/HTTPS).
    Uses standard host:port format identical to v2rayN and Clash.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_SET_VALUE
        )
        
        # Standard format used by all modern Windows VPN clients
        proxy_string = f"{PROXY_HOST}:{http_port}"
        bypass_string = "<local>;localhost;127.*;10.*;192.168.*;*.local"

        _save_proxy_backup()

        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_string)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass_string)
        winreg.CloseKey(key)

        notify_wininet()
        logger.info(f"System proxy enabled: {proxy_string}")
        return True
    except PermissionError:
        logger.warning("Permission denied accessing Windows proxy registry.")
        return False
    except Exception as e:
        logger.error(f"Error enabling system proxy: {e}")
        return False

def disable_system_proxy(restore: bool = True) -> bool:
    """
    Disables Windows system proxy and refreshes settings.

    restore=True — если мы сами включали прокси и до нас был включён чужой
    рабочий прокси, вернём его обратно. Если чужой прокси не работает
    (порт мёртв) — просто выключаем прокси, чтобы интернет не пропал.
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

        # Если в реестре остался адрес нашего прокси — убираем его, чтобы
        # другие программы не пытались подключаться к мёртвому порту.
        try:
            current, _ = winreg.QueryValueEx(key, "ProxyServer")
            if str(current).strip() == f"{PROXY_HOST}:{PROXY_HTTP_PORT}":
                winreg.DeleteValue(key, "ProxyServer")
        except FileNotFoundError:
            pass
        except Exception:
            pass

        winreg.CloseKey(key)

        if restore:
            backup = _load_proxy_backup()
            if backup and backup.get("enabled"):
                server = str(backup.get("server") or "")
                if server and _proxy_target_alive(server):
                    try:
                        key = winreg.OpenKey(
                            winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                            0,
                            winreg.KEY_SET_VALUE
                        )
                        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
                        if backup.get("override"):
                            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, str(backup["override"]))
                        winreg.CloseKey(key)
                        logger.info(f"Восстановлен прежний прокси пользователя: {server}")
                    except Exception as exc:
                        logger.debug(f"Не удалось вернуть прежний прокси: {exc}")
                else:
                    logger.info("Прежний прокси пользователя не работает — оставляем прокси выключенным.")

        _clear_proxy_backup()

        notify_wininet()
        logger.info("System proxy disabled")
        return True
    except PermissionError:
        return False
    except Exception as e:
        logger.debug(f"Error disabling system proxy: {e}")
        return False

def _proxy_target_alive(server: str) -> bool:
    """Проверяет, отвечает ли локальный порт из строки вида host:port."""
    from core.recovery import is_port_listening, parse_proxy_server

    host, port = parse_proxy_server(server)
    if not host or not port:
        return False
    return is_port_listening(host, port, timeout=0.5)

def get_system_proxy_status() -> Tuple[bool, str]:
    """Check if system proxy is currently enabled in registry."""
    values = _read_proxy_values()
    return values["enabled"], values["server"]

# Safety hook: make sure proxy is cleaned up on exit
atexit.register(disable_system_proxy)
