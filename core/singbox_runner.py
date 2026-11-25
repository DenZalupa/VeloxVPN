import asyncio
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List
import aiohttp

from core.parser import node_to_singbox_outbound
from core.system_proxy import enable_system_proxy, disable_system_proxy
from core.bypass import parse_bypass_entries, is_empty as bypass_is_empty, describe as describe_bypass

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    BIN_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "bin"
    if not (BIN_DIR / "sing-box.exe").exists():
        BIN_DIR = BASE_DIR / "bin"
    DATA_DIR = BASE_DIR / "data"
    CONFIG_FILE = DATA_DIR / "singbox_active.json"
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    BIN_DIR = BASE_DIR / "bin"
    DATA_DIR = BASE_DIR / "data"
    CONFIG_FILE = DATA_DIR / "singbox_active.json"

class SingboxRunner:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.active_node: Optional[Dict[str, Any]] = None
        self.routing_mode: str = "bypass_ru" # "bypass_ru", "global", "direct"
        self.tun_mode: bool = False
        self.bypass_entries: List[str] = []
        self.bypass_rules: Dict[str, List[str]] = {
            "domain_suffix": [], "domain_keyword": [], "ip_cidr": [], "process_name": []
        }
        self.status: str = "stopped" # "stopped", "starting", "running", "error"
        self.started_at: Optional[float] = None
        self.logs: List[str] = []
        self.max_logs: int = 150
        self.core_path: Optional[Path] = self._locate_core()
        self.wintun_path: Optional[Path] = self._locate_wintun()
        self.downloading_core: bool = False
        self.download_progress: int = 0
        self.download_status: str = ""
        self.downloading_wintun: bool = False
        self.wintun_status: str = ""
        self.clash_api_port: int = 20810
        self.speed_down: int = 0
        self.speed_up: int = 0
        self.total_down: int = 0
        self.total_up: int = 0
        self.kill_switch_active: bool = False

    def _locate_core(self) -> Optional[Path]:
        """Locate sing-box.exe binary."""
        local_exe = BIN_DIR / "sing-box.exe"
        if local_exe.exists():
            return local_exe
        
        path_exe = shutil.which("sing-box") or shutil.which("sing-box.exe")
        if path_exe:
            return Path(path_exe)
        
        common_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "sing-box" / "sing-box.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "sing-box" / "sing-box.exe",
        ]
        for p in common_paths:
            if p.exists():
                return p
        return None

    def _locate_wintun(self) -> Optional[Path]:
        """Locate or recover wintun.dll driver."""
        local_dll = BIN_DIR / "wintun.dll"
        if local_dll.exists():
            return local_dll
        
        # Check known apps on the system (Happ, Incy, WireGuard)
        known_sources = [
            Path(os.environ.get("APPDATA", "")) / "Happ" / "tun2" / "wintun.dll",
            Path(os.environ.get("ProgramFiles", "")) / "INCY" / "wintun.dll",
            Path(os.environ.get("ProgramFiles", "")) / "INCY" / "app" / "resources" / "bin" / "wintun.dll",
            Path(os.environ.get("ProgramFiles", "")) / "WireGuard" / "wintun.dll",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Happ" / "wintun.dll",
        ]
        for src in known_sources:
            if src.exists():
                try:
                    BIN_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, local_dll)
                    return local_dll
                except Exception:
                    pass
        return None

    def has_core(self) -> bool:
        return self.core_path is not None and self.core_path.exists()

    def has_wintun(self) -> bool:
        if self.wintun_path and self.wintun_path.exists():
            return True
        self.wintun_path = self._locate_wintun()
        return self.wintun_path is not None and self.wintun_path.exists()

    @staticmethod
    def is_admin() -> bool:
        """Check if current process has Windows Administrator privileges."""
        if os.name == "nt":
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False

    async def download_wintun(self) -> bool:
        """Download official wintun.dll for Windows amd64."""
        if self.downloading_wintun:
            return False
        
        self.downloading_wintun = True
        self.wintun_status = "Скачивание драйвера Wintun..."
        url = "https://www.wintun.net/builds/wintun-0.14.1.zip"
        headers = {"User-Agent": "VeloxVPN-Configurator"}

        try:
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        self.wintun_status = f"Ошибка скачивания Wintun: {resp.status}"
                        self.downloading_wintun = False
                        return False
                    content = await resp.read()
                    
                    with zipfile.ZipFile(io.BytesIO(content)) as z:
                        for filename in z.namelist():
                            if filename.endswith("bin/amd64/wintun.dll") or filename.endswith("amd64/wintun.dll"):
                                target_file = BIN_DIR / "wintun.dll"
                                with z.open(filename) as source, open(target_file, "wb") as dest:
                                    shutil.copyfileobj(source, dest)
                                self.wintun_path = target_file
                                self.wintun_status = "Wintun успешно установлен!"
                                self.downloading_wintun = False
                                return True
            self.wintun_status = "wintun.dll не найден в архиве."
            self.downloading_wintun = False
            return False
        except Exception as e:
            self.wintun_status = f"Ошибка: {e}"
            self.downloading_wintun = False
            return False

    async def download_official_core(self) -> bool:
        """Download the official sing-box release from GitHub for Windows x64."""
        if self.downloading_core:
            return False
        
        self.downloading_core = True
        self.download_progress = 5
        self.download_status = "Поиск последнего релиза sing-box..."

        api_url = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
        headers = {"User-Agent": "FastVPN-Configurator"}

        try:
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.download_status = f"Ошибка GitHub API: {resp.status}"
                        self.downloading_core = False
                        return False
                    data = await resp.json()
                
                assets = data.get("assets", [])
                target_asset = None
                for asset in assets:
                    name = asset.get("name", "")
                    if "windows-amd64.zip" in name and not "alpha" in name and not "beta" in name:
                        target_asset = asset
                        break
                
                if not target_asset:
                    for asset in assets:
                        if "windows-amd64" in asset.get("name", ""):
                            target_asset = asset
                            break

                if not target_asset:
                    self.download_status = "Не найден подходящий архив для Windows x64."
                    self.downloading_core = False
                    return False

                download_url = target_asset["browser_download_url"]
                self.download_status = f"Скачивание {target_asset['name']}..."
                self.download_progress = 20

                async with session.get(download_url, timeout=aiohttp.ClientTimeout(total=60)) as file_resp:
                    if file_resp.status != 200:
                        self.download_status = f"Ошибка скачивания: {file_resp.status}"
                        self.downloading_core = False
                        return False

                    content = await file_resp.read()
                    self.download_progress = 75
                    self.download_status = "Распаковка ядра..."

                    with zipfile.ZipFile(io.BytesIO(content)) as z:
                        for filename in z.namelist():
                            if filename.endswith("sing-box.exe"):
                                target_file = BIN_DIR / "sing-box.exe"
                                with z.open(filename) as source, open(target_file, "wb") as dest:
                                    shutil.copyfileobj(source, dest)
                                self.core_path = target_file
                                self.download_progress = 100
                                self.download_status = "Ядро sing-box успешно установлено!"
                                self.downloading_core = False
                                return True

            self.download_status = "sing-box.exe не найден в скачанном архиве."
            self.downloading_core = False
            return False
        except Exception as e:
            self.download_status = f"Ошибка установки: {e}"
            self.downloading_core = False
            return False

    def build_config(self, node: Dict[str, Any], routing_mode: str = "bypass_ru", tun_mode: bool = False,
                     bypass_entries: Any = None, kill_switch: bool = False, doh_protection: bool = True) -> Dict[str, Any]:
        """
        Generate high-performance sing-box JSON configuration.
        Supports both TUN mode (system-wide adapter for all apps/games) and Proxy mode.

        bypass_entries — список доменов / IP / приложений, трафик по которым
        идёт напрямую мимо VPN.
        """
        outbound_proxy = node_to_singbox_outbound(node)
        bypass = parse_bypass_entries(bypass_entries)
        
        ru_domains = [
            ".ru", ".su", ".рф", ".xn--p1ai",
            "yandex.ru", "ya.ru", "vk.com", "vkvideo.ru", "gosuslugi.ru",
            "tbank.ru", "tinkoff.ru", "sberbank.ru", "sber.ru", "alfabank.ru",
            "mail.ru", "ozon.ru", "wildberries.ru", "avito.ru", "kinopoisk.ru",
            "rutube.ru", "2gis.ru", "hh.ru", "dzen.ru"
        ]

        inbounds: List[Dict[str, Any]] = []

        if tun_mode:
            inbounds.append({
                "type": "tun",
                "tag": "tun-in",
                "interface_name": "VeloxVPN",
                "address": ["172.19.0.1/30"],
                "auto_route": True,
                "strict_route": False,
                "stack": "mixed"
            })

        inbounds.extend([
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": 20809
            },
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": 20808
            }
        ])

        config: Dict[str, Any] = {
            "log": {
                "level": "info",
                "timestamp": True
            },
            "inbounds": inbounds,
            "outbounds": [
                outbound_proxy,
                {
                    "type": "direct",
                    "tag": "direct"
                },
                {
                    "type": "block",
                    "tag": "block"
                }
            ],
            "route": {
                "auto_detect_interface": True,
                "rules": []
            },
            "experimental": {
                "clash_api": {
                    "external_controller": f"127.0.0.1:{self.clash_api_port}"
                }
            }
        }

        # Поиск процесса нужен только если есть правила вида "имя.exe"
        if bypass.get("process_name"):
            config["route"]["find_process"] = True

        if tun_mode:
            # Modern Sing-box 1.14 DNS and domain resolution
            # Encrypted DNS-over-HTTPS (DoH) Zero-Leak Hijacking
            if doh_protection:
                remote_dns = [
                    {
                        "tag": "dns-remote",
                        "type": "https",
                        "server": "1.1.1.1",
                        "server_port": 443,
                        "detour": "proxy"
                    },
                    {
                        "tag": "dns-backup",
                        "type": "https",
                        "server": "8.8.8.8",
                        "server_port": 443,
                        "detour": "proxy"
                    }
                ]
            else:
                remote_dns = [
                    {
                        "tag": "dns-remote",
                        "type": "tcp",
                        "server": "1.1.1.1",
                        "detour": "proxy"
                    }
                ]
            config["dns"] = {
                "servers": remote_dns + [
                    {
                        "tag": "dns-direct",
                        "type": "local"
                    }
                ],
                "rules": [],
                "final": "dns-remote" if routing_mode != "direct" else "dns-direct",
                "strategy": "prefer_ipv4"
            }
            if routing_mode == "bypass_ru":
                config["dns"]["rules"].append({
                    "domain_suffix": ru_domains,
                    "server": "dns-direct"
                })

            # Домены из «мимо VPN» резолвим локально, иначе получим неверные IP
            if routing_mode != "direct":
                if bypass.get("domain_suffix"):
                    config["dns"]["rules"].append({
                        "domain_suffix": bypass["domain_suffix"],
                        "server": "dns-direct"
                    })
                if bypass.get("domain_keyword"):
                    config["dns"]["rules"].append({
                        "domain_keyword": bypass["domain_keyword"],
                        "server": "dns-direct"
                    })

            config["route"]["default_domain_resolver"] = "dns-direct"
            config["route"]["rules"].append({"action": "sniff"})
            config["route"]["rules"].append({"protocol": "dns", "action": "hijack-dns"})

        rules = config["route"]["rules"]

        # Правила «мимо VPN» — всегда до общего правила "весь трафик в прокси"
        direct_rules = self._bypass_route_rules(bypass)

        if routing_mode == "bypass_ru":
            rules.append({
                "ip_is_private": True,
                "outbound": "direct"
            })
            rules.append({
                "domain_suffix": ru_domains,
                "outbound": "direct"
            })
            rules.extend(direct_rules)
            rules.append({
                "network": ["tcp", "udp"],
                "outbound": "proxy"
            })
        elif routing_mode == "global":
            rules.append({
                "ip_is_private": True,
                "outbound": "direct"
            })
            rules.extend(direct_rules)
            rules.append({
                "network": ["tcp", "udp"],
                "outbound": "proxy"
            })
        elif routing_mode == "direct":
            rules.append({
                "network": ["tcp", "udp"],
                "outbound": "direct"
            })

        if kill_switch and routing_mode in ("bypass_ru", "global"):
            rules.append({
                "network": ["tcp", "udp"],
                "outbound": "block"
            })

        return config

    @staticmethod
    def _bypass_route_rules(bypass: Dict[str, List[str]]) -> List[Dict[str, Any]]:
        """Правила маршрутизации для трафика, который идёт мимо VPN."""
        rules: List[Dict[str, Any]] = []
        if bypass.get("process_name"):
            rules.append({
                "process_name": list(bypass["process_name"]),
                "outbound": "direct"
            })
        if bypass.get("ip_cidr"):
            rules.append({
                "ip_cidr": list(bypass["ip_cidr"]),
                "outbound": "direct"
            })
        if bypass.get("domain_suffix"):
            rules.append({
                "domain_suffix": list(bypass["domain_suffix"]),
                "outbound": "direct"
            })
        if bypass.get("domain_keyword"):
            rules.append({
                "domain_keyword": list(bypass["domain_keyword"]),
                "outbound": "direct"
            })
        return rules

    def start(self, node: Dict[str, Any], routing_mode: str = "bypass_ru", enable_sys_proxy: bool = True,
              tun_mode: bool = True, bypass_entries: Any = None, kill_switch: bool = False,
              doh_protection: bool = True) -> bool:
        """Start sing-box with the selected node."""
        if not self.has_core():
            self._log_line("[ОШИБКА] Ядро sing-box.exe не найдено! Нажмите 'Установить ядро'.")
            self.status = "error"
            return False

        if tun_mode:
            if not self.has_wintun():
                self._log_line("[ОШИБКА] Драйвер wintun.dll не найден! Пожалуйста, установите драйвер в настройках.")
                self.status = "error"
                return False
            if not self.is_admin():
                self._log_line("[ВНИМАНИЕ] TUN-режим требует прав Администратора. При ошибке 'Access is denied' перезапустите от Администратора.")

        if self.process and self.process.poll() is None:
            self.stop()
        else:
            # Clean up any lingering background sing-box processes on Windows
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/F", "/IM", "sing-box.exe"], capture_output=True, creationflags=0x08000000)
                except Exception:
                    pass

        self.status = "starting"
        self.active_node = node
        self.routing_mode = routing_mode
        self.tun_mode = tun_mode
        self.bypass_entries = bypass_entries or []
        self.bypass_rules = parse_bypass_entries(self.bypass_entries)
        self.speed_down = 0
        self.speed_up = 0
        self.total_down = 0
        self.total_up = 0
        self.kill_switch_active = False
        self._log_line(f"[СТАРТ] Подключение к узлу: {node.get('name')} ({node.get('type')})")
        self._log_line(f"[РЕЖИМ] Маршрутизация: {routing_mode} | Охват: {'Весь ПК (игры, Discord, браузеры)' if tun_mode else 'Системный прокси'}")
        if kill_switch:
            self._log_line("[ЗАЩИТА] Kill Switch активен: интернет будет заблокирован при внезапном обрыве VPN.")
        if not bypass_is_empty(self.bypass_rules):
            self._log_line(f"[ПРАВИЛА] Мимо VPN: {describe_bypass(self.bypass_rules)}")
        else:
            self._log_line("[ПРАВИЛА] Мимо VPN: список пуст, весь трафик идёт по правилам режима.")

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            cfg = self.build_config(node, routing_mode=routing_mode, tun_mode=tun_mode,
                                    bypass_entries=bypass_entries, kill_switch=kill_switch,
                                    doh_protection=doh_protection)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)

            # Check config validity with sing-box check before running
            check_res = subprocess.run(
                [str(self.core_path), "check", "-c", str(CONFIG_FILE)],
                capture_output=True,
                text=True,
                creationflags=0x08000000 if os.name == "nt" else 0
            )
            if check_res.returncode != 0:
                err_msg = check_res.stderr.strip() or "Синтаксическая ошибка конфигурации sing-box"
                self._log_line(f"[ОШИБКА ВАЛИДАЦИИ] {err_msg}")
                self.status = "error"
                return False

            creation_flags = 0x08000000 if os.name == "nt" else 0

            self.process = subprocess.Popen(
                [str(self.core_path), "run", "-c", str(CONFIG_FILE)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags
            )

            # Give process a moment to verify it didn't immediately crash
            time.sleep(0.3)
            if self.process.poll() is not None:
                err_out = ""
                try:
                    err_out = self.process.stdout.read()
                except Exception:
                    pass
                self.status = "error"
                if "Access is denied" in err_out and tun_mode:
                    self._log_line("[ВНИМАНИЕ] Для сетевого адаптера всего ПК требуются права Администратора.")
                    self._log_line("[АВТО-ПЕРЕХОД] Переключаюсь на системный прокси (127.0.0.1:20809), чтобы интернет работал без сбоев...")
                    # Seamless fallback to system proxy mode
                    return self.start(node, routing_mode=routing_mode, enable_sys_proxy=True,
                                      tun_mode=False, bypass_entries=bypass_entries, kill_switch=kill_switch)
                else:
                    self._log_line(f"[СБОЙ ЗАПУСКА] sing-box аварийно завершился: {err_out.strip()}")
                return False

            self.started_at = time.time()
            self.status = "running"

            # PID-файл: по нему guardian найдёт осиротевшее ядро после падения
            try:
                from core.recovery import write_pid_file
                write_pid_file(self.process.pid)
            except Exception:
                pass

            # Background thread to read stdout/stderr logs
            threading.Thread(target=self._read_logs, daemon=True).start()

            # Background thread to poll traffic speed & totals via clash_api
            threading.Thread(target=self._traffic_poller, daemon=True).start()

            # Enable Windows system proxy if requested
            if enable_sys_proxy:
                enable_system_proxy(http_port=20809, socks_port=20808)
                self._log_line("[СИСТЕМА] Системный прокси Windows включен (127.0.0.1:20809)")

            if tun_mode:
                self._log_line("[ЗАЩИТА] Защита от утечки DNS активна: запросы шифруются через DoH (Cloudflare 1.1.1.1 / Google 8.8.8.8).")
                self._log_line("[УСПЕХ] Защита всего ПК активна! Весь сетевой трафик (Telegram, Discord, игры, браузеры) направлен в VPN.")
            else:
                self._log_line("[УСПЕХ] VPN соединение активно!")
            return True
        except Exception as e:
            self.status = "error"
            self._log_line(f"[ОШИБКА] Не удалось запустить sing-box: {e}")
            return False

    def stop(self) -> bool:
        """Stop sing-box process and disable system proxy."""
        self._log_line("[ОСТАНОВКА] Отключение VPN...")
        
        disable_system_proxy()
        self._log_line("[СИСТЕМА] Системный прокси Windows отключен.")

        try:
            from core.recovery import clear_pid_file
            clear_pid_file()
        except Exception:
            pass

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

        self.status = "stopped"
        self.active_node = None
        self.started_at = None
        self.speed_down = 0
        self.speed_up = 0
        self.kill_switch_active = False
        self._log_line("[ОСТАНОВКА] VPN успешно отключен.")
        return True

    def _traffic_poller(self):
        """Poll live speed and byte metrics from sing-box clash_api."""
        import urllib.request
        url = f"http://127.0.0.1:{self.clash_api_port}/traffic"
        conn_url = f"http://127.0.0.1:{self.clash_api_port}/connections"
        time.sleep(0.6)
        while self.status == "running" and self.process and self.process.poll() is None:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=3) as resp:
                    while self.status == "running" and self.process and self.process.poll() is None:
                        line = resp.readline()
                        if not line:
                            break
                        data = json.loads(line.decode("utf-8", errors="replace"))
                        self.speed_up = int(data.get("up", 0))
                        self.speed_down = int(data.get("down", 0))
                        self.total_up += self.speed_up
                        self.total_down += self.speed_down
            except Exception:
                # Fallback: query /connections for totals
                try:
                    with urllib.request.urlopen(conn_url, timeout=1.5) as c_resp:
                        c_data = json.loads(c_resp.read().decode("utf-8", errors="replace"))
                        self.total_down = int(c_data.get("downloadTotal", self.total_down))
                        self.total_up = int(c_data.get("uploadTotal", self.total_up))
                except Exception:
                    pass
                time.sleep(1.0)
        self.speed_down = 0
        self.speed_up = 0

    def _read_logs(self):
        """Read logs from sing-box process."""
        proc = self.process
        if not proc or not proc.stdout:
            return
        
        while proc.poll() is None:
            line = proc.stdout.readline()
            if line:
                self._log_line(line.strip())
            else:
                break
        
        if self.status == "running" and proc.poll() is not None:
            code = proc.poll()
            self.status = "stopped"
            self._log_line(f"[ИНФО] Процесс sing-box завершился с кодом {code}")
            ks = False
            try:
                from core.storage import storage
                ks = bool(storage.get_settings().get("kill_switch", False))
            except Exception:
                pass
            if ks:
                self.kill_switch_active = True
                self._log_line("[KILL SWITCH] 🛡️ Аварийная остановка! VPN разорван. Kill Switch активен: интернет заблокирован во избежание утечки IP.")
            else:
                # Ядро умерло — гасим прокси и убираем TUN, чтобы интернет не пропал
                try:
                    from core.recovery import full_cleanup
                    full_cleanup(reason="ядро sing-box завершилось неожиданно", kill_core=False)
                except Exception:
                    disable_system_proxy()

    def _log_line(self, line: str):
        if not line:
            return
        ts = time.strftime("%H:%M:%S")
        formatted = f"[{ts}] {line}"
        self.logs.append(formatted)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]

    def get_info(self) -> Dict[str, Any]:
        """Get current state of sing-box."""
        uptime = 0
        if self.started_at and self.status == "running":
            uptime = round(time.time() - self.started_at)

        rules = getattr(self, "bypass_rules", {}) or {}
        bypass_count = sum(len(rules.get(k, [])) for k in ("domain_suffix", "domain_keyword", "ip_cidr", "process_name"))

        extra: Dict[str, Any] = {}
        try:
            from core.recovery import guardian_alive, proxy_state
            extra["proxy_state"] = proxy_state()
            extra["guardian_alive"] = guardian_alive()
        except Exception:
            pass

        info = {
            "status": self.status,
            "has_core": self.has_core(),
            "core_path": str(self.core_path) if self.core_path else None,
            "has_wintun": self.has_wintun(),
            "wintun_path": str(self.wintun_path) if self.wintun_path else None,
            "is_admin": self.is_admin(),
            "tun_mode": self.tun_mode,
            "active_node": self.active_node,
            "routing_mode": self.routing_mode,
            "bypass_count": bypass_count,
            "bypass_rules": rules,
            "uptime_seconds": uptime,
            "downloading_core": self.downloading_core,
            "download_progress": self.download_progress,
            "download_status": self.download_status,
            "downloading_wintun": self.downloading_wintun,
            "wintun_status": self.wintun_status,
            "speed_down": self.speed_down,
            "speed_up": self.speed_up,
            "total_down": self.total_down,
            "total_up": self.total_up,
            "kill_switch_active": self.kill_switch_active,
            "logs": self.logs[-50:]
        }
        info.update(extra)
        return info

runner = SingboxRunner()
