import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict
from aiohttp import web, WSMsgType

from core.country_detector import detect_country
from core.parser import parse_node, generate_node_id
from core.pinger import ping_node, ping_all_nodes, real_http_delay_test, real_speedtest
from core.subscription import fetch_all_subscriptions, extract_nodes_from_text, fetch_subscription_usage
from core.singbox_runner import runner
from core.storage import storage
from core.system_proxy import get_system_proxy_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FastVPN")

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "static"
    if not STATIC_DIR.exists():
        STATIC_DIR = BASE_DIR / "static"
else:
    BASE_DIR = Path(__file__).resolve().parent
    STATIC_DIR = BASE_DIR / "static"

class FastVPNServer:
    def __init__(self):
        self.app = web.Application()
        self.websockets = set()
        self.is_pinging = False
        self.is_updating_subs = False
        self.app_window = None
        self._setup_routes()
        self.app.on_startup.append(self._on_startup)

    async def _on_startup(self, app):
        asyncio.create_task(self._traffic_broadcast_loop())
        asyncio.create_task(self._subscription_usage_loop())

    async def _subscription_usage_loop(self):
        """
        Периодически обновляет сводку по трафику и сроку подписки.

        Запрашиваются только HTTP-заголовки (тело не читается), поэтому
        фоновая задача почти не нагружает сеть и сервер провайдера.
        Первый запрос делаем сразу после старта, дальше — раз в 30 минут.
        """
        interval_sec = 1800
        while True:
            try:
                await asyncio.sleep(60)  # даём приложению подняться
                subs = storage.get_subscriptions()
                if subs:
                    tasks = [
                        fetch_subscription_usage(sub["url"], timeout_sec=8.0)
                        for sub in subs if sub.get("url") and sub.get("enabled", True)
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    usage_by_name: Dict[str, Dict[str, Any]] = {}
                    active_subs = [s for s in subs if s.get("url") and s.get("enabled", True)]
                    for sub, res in zip(active_subs, results):
                        if isinstance(res, Exception) or not res:
                            continue
                        usage_by_name[sub.get("name", "Подписка")] = res
                    if usage_by_name:
                        storage.update_subscription_usage(usage_by_name)
                        await self.broadcast_ws("subscription_usage_updated",
                                                storage.get_subscription_usage_summary())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"Фоновое обновление сводки подписки: {e}")
            try:
                await asyncio.sleep(interval_sec)
            except asyncio.CancelledError:
                raise

    async def _traffic_broadcast_loop(self):
        while True:
            try:
                await asyncio.sleep(1.0)
                if self.websockets and runner.status == "running":
                    uptime = round(time.time() - runner.started_at) if runner.started_at else 0
                    await self.broadcast_ws("traffic_update", {
                        "speed_down": runner.speed_down,
                        "speed_up": runner.speed_up,
                        "total_down": runner.total_down,
                        "total_up": runner.total_up,
                        "uptime_seconds": uptime
                    })
                elif self.websockets and runner.kill_switch_active:
                    await self.broadcast_ws("kill_switch_triggered", {
                        "active": True
                    })
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def _setup_routes(self):
        # API routes
        self.app.router.add_get("/api/status", self.handle_get_status)
        self.app.router.add_get("/api/nodes", self.handle_get_nodes)
        self.app.router.add_get("/api/favorites", self.handle_get_favorites)
        self.app.router.add_post("/api/favorites/toggle", self.handle_toggle_favorite)
        self.app.router.add_post("/api/nodes/delete", self.handle_delete_node)
        self.app.router.add_post("/api/nodes/clear", self.handle_clear_nodes)
        self.app.router.add_post("/api/ping-all", self.handle_ping_all)
        self.app.router.add_post("/api/ping-single", self.handle_ping_single)
        self.app.router.add_post("/api/test-real-delay", self.handle_test_real_delay)
        self.app.router.add_post("/api/speedtest", self.handle_speedtest)
        
        self.app.router.add_post("/api/connect", self.handle_connect)
        self.app.router.add_post("/api/disconnect", self.handle_disconnect)
        
        self.app.router.add_get("/api/subscriptions", self.handle_get_subscriptions)
        self.app.router.add_post("/api/subscriptions/refresh-usage", self.handle_refresh_subscription_usage)
        self.app.router.add_post("/api/subscriptions/add", self.handle_add_subscription)
        self.app.router.add_post("/api/subscriptions/delete", self.handle_delete_subscription)
        self.app.router.add_post("/api/subscriptions/update-all", self.handle_update_all_subscriptions)
        self.app.router.add_post("/api/subscriptions/import-keys", self.handle_import_keys)
        
        self.app.router.add_post("/api/core/download", self.handle_download_core)
        self.app.router.add_post("/api/tun/toggle", self.handle_toggle_tun)
        self.app.router.add_post("/api/tun/install-wintun", self.handle_install_wintun)
        self.app.router.add_post("/api/restart-elevated", self.handle_restart_elevated)
        self.app.router.add_post("/api/repair-network", self.handle_repair_network)
        self.app.router.add_post("/api/window/minimize", self.handle_minimize_window)
        self.app.router.add_post("/api/window/show", self.handle_show_window)
        self.app.router.add_get("/api/settings", self.handle_get_settings)
        self.app.router.add_post("/api/settings", self.handle_update_settings)
        
        # WebSocket for live real-time events
        self.app.router.add_get("/ws", self.handle_websocket)
        
        # Static files and root page
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_static("/static", path=str(STATIC_DIR), name="static")

    async def broadcast_ws(self, event_type: str, data: dict):
        """Send message to all connected web clients."""
        if not self.websockets:
            return
        msg = json.dumps({"type": event_type, "data": data})
        closed = []
        for ws in self.websockets:
            try:
                await ws.send_str(msg)
            except Exception:
                closed.append(ws)
        for ws in closed:
            self.websockets.discard(ws)

    async def handle_index(self, request):
        index_file = STATIC_DIR / "index.html"
        return web.FileResponse(index_file)

    async def handle_websocket(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.websockets.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get("action") == "ping":
                            await ws.send_json({"type": "pong"})
                    except Exception:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket closed with exception {ws.exception()}")
        finally:
            self.websockets.discard(ws)
        return ws

    def _active_node_id(self):
        """id текущего подключения — дедупликация не должна его потерять."""
        try:
            active = runner.get_info().get("active_node")
            if isinstance(active, dict):
                return active.get("id")
        except Exception:
            pass
        return None

    async def handle_get_status(self, request):
        info = runner.get_info()
        sys_proxy_enabled, sys_proxy_server = get_system_proxy_status()
        info["system_proxy_enabled"] = sys_proxy_enabled
        info["system_proxy_server"] = sys_proxy_server
        info["is_pinging"] = self.is_pinging
        info["is_updating_subs"] = self.is_updating_subs
        # Счётчик исключённых дубликатов (без секретов — только числа)
        info["dedup"] = storage.get_dedup_stats()
        # Сводка по подписке: израсходовано / осталось / срок действия
        info["subscription"] = storage.get_subscription_usage_summary()
        return web.json_response(info)

    async def handle_get_nodes(self, request):
        nodes = storage.get_nodes()
        return web.json_response({"nodes": nodes})

    async def handle_get_favorites(self, request):
        favs = storage.get_favorites()
        return web.json_response({"favorites": favs})

    async def handle_toggle_favorite(self, request):
        data = await request.json()
        node_id = data.get("id")
        if not node_id:
            return web.json_response({"error": "ID обязателен"}, status=400)
        is_fav = storage.toggle_favorite(node_id)
        favs = storage.get_favorites()
        return web.json_response({"success": True, "id": node_id, "is_favorite": is_fav, "favorites": favs})

    async def handle_delete_node(self, request):
        data = await request.json()
        node_id = data.get("id")
        nodes = [n for n in storage.get_nodes() if n.get("id") != node_id]
        storage.set_nodes(nodes, active_node_id=self._active_node_id())
        return web.json_response({"success": True, "count": len(nodes)})

    async def handle_clear_nodes(self, request):
        storage.set_nodes([])
        return web.json_response({"success": True})

    async def handle_ping_all(self, request):
        """Ultra-fast concurrent parallel ping."""
        if self.is_pinging:
            return web.json_response({"error": "Тест пинга уже выполняется"}, status=400)
        
        nodes = storage.get_nodes()
        if not nodes:
            return web.json_response({"error": "Список узлов пуст"}, status=400)

        self.is_pinging = True
        settings = storage.get_settings()
        timeout = float(settings.get("ping_timeout", 1.2))
        concurrency = int(settings.get("ping_concurrency", 80))
        loop = asyncio.get_running_loop()

        import threading
        def run_pings():
            def on_pinged(n):
                try:
                    asyncio.run_coroutine_threadsafe(self.broadcast_ws("node_pinged", {
                        "id": n.get("id"),
                        "ping": n.get("ping"),
                        "last_ping_time": n.get("last_ping_time")
                    }), loop)
                except Exception:
                    pass

            try:
                start_t = time.perf_counter()
                updated_nodes = ping_all_nodes(
                    nodes, 
                    concurrency=concurrency, 
                    timeout_sec=timeout,
                    on_node_pinged=on_pinged
                )
                duration = round(time.perf_counter() - start_t, 2)
                storage.set_nodes(updated_nodes, active_node_id=self._active_node_id())
                try:
                    asyncio.run_coroutine_threadsafe(self.broadcast_ws("ping_all_finished", {
                        "nodes": updated_nodes,
                        "duration": duration,
                        "count": len(updated_nodes)
                    }), loop)
                except Exception:
                    pass
            finally:
                self.is_pinging = False

        threading.Thread(target=run_pings, daemon=True).start()
        return web.json_response({"status": "started", "node_count": len(nodes)})

    async def handle_ping_single(self, request):
        data = await request.json()
        node_id = data.get("id")
        nodes = storage.get_nodes()
        target = next((n for n in nodes if n.get("id") == node_id), None)
        if not target:
            return web.json_response({"error": "Узел не найден"}, status=404)

        settings = storage.get_settings()
        timeout = float(settings.get("ping_timeout", 1.5))
        ping_node(target, timeout_sec=timeout)
        storage.set_nodes(nodes, active_node_id=self._active_node_id())
        
        await self.broadcast_ws("node_pinged", {
            "id": target.get("id"),
            "ping": target.get("ping")
        })
        return web.json_response({"success": True, "node": target})

    async def handle_test_real_delay(self, request):
        """Test real HTTP traffic delay through active VPN."""
        delay = await real_http_delay_test(proxy_port=20809, timeout_sec=3.0)
        return web.json_response({"delay": delay})

    async def handle_speedtest(self, request):
        """Test real download speed through active VPN (Cloudflare CDN 3-sec test)."""
        if runner.status != "running":
            return web.json_response({"success": False, "error": "VPN не подключен"}, status=400)
        from core.pinger import real_speedtest
        res = await real_speedtest(proxy_port=20809, duration_sec=3.0)
        return web.json_response(res)

    async def handle_connect(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        node_id = data.get("id") or data.get("node_id")
        routing_mode = data.get("routing_mode")

        settings = storage.get_settings()
        if not node_id:
            node_id = settings.get("selected_node_id")
        if not routing_mode:
            routing_mode = settings.get("routing_mode", "bypass_ru")

        nodes = storage.get_nodes()
        node = next((n for n in nodes if n.get("id") == node_id), None)
        if not node and nodes:
            node = nodes[0]
            node_id = node.get("id")
        if not node:
            return web.json_response({"error": "Узел не найден"}, status=404)

        settings = storage.get_settings()
        settings["selected_node_id"] = node_id
        settings["routing_mode"] = routing_mode
        if "tun_mode" in data:
            settings["tun_mode"] = bool(data["tun_mode"])
        storage.update_settings(settings)

        enable_sys_proxy = settings.get("system_proxy", True)
        tun_mode = settings.get("tun_mode", True)
        bypass_entries = settings.get("bypass_list", [])
        kill_switch = settings.get("kill_switch", False)
        doh_protection = settings.get("doh_protection", True)
        success = runner.start(node, routing_mode=routing_mode, enable_sys_proxy=enable_sys_proxy,
                               tun_mode=tun_mode, bypass_entries=bypass_entries, kill_switch=kill_switch,
                               doh_protection=doh_protection)
        
        await self.broadcast_ws("connection_changed", runner.get_info())
        return web.json_response({"success": success, "info": runner.get_info()})

    async def handle_disconnect(self, request):
        success = runner.stop()
        await self.broadcast_ws("connection_changed", runner.get_info())
        return web.json_response({"success": success, "info": runner.get_info()})

    async def handle_get_subscriptions(self, request):
        return web.json_response({
            "subscriptions": storage.get_subscriptions(),
            "usage": storage.get_subscription_usage_summary(),
        })

    async def handle_refresh_subscription_usage(self, request):
        """
        Обновляет сводку по трафику и сроку подписки без обновления списка узлов.

        Запрашивает только HTTP-заголовки (тело не читается), поэтому запрос лёгкий.
        """
        subs = storage.get_subscriptions()
        tasks = [
            fetch_subscription_usage(sub["url"], timeout_sec=8.0)
            for sub in subs if sub.get("url") and sub.get("enabled", True)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        usage_by_name: Dict[str, Dict[str, Any]] = {}
        for sub, res in zip([s for s in subs if s.get("url") and s.get("enabled", True)], results):
            if isinstance(res, Exception) or not res:
                continue
            usage_by_name[sub.get("name", "Подписка")] = res

        storage.update_subscription_usage(usage_by_name)
        return web.json_response({
            "success": bool(usage_by_name),
            "usage": storage.get_subscription_usage_summary(),
        })

    async def handle_add_subscription(self, request):
        data = await request.json()
        url = data.get("url", "").strip()
        name = data.get("name", "").strip() or "Подписка"
        if not url:
            return web.json_response({"error": "URL подписки обязателен"}, status=400)

        subs = storage.get_subscriptions()
        sub_id = generate_node_id(url)
        # Одна и та же ссылка не добавляется дважды: иначе сводка по
        # трафику и сроку удваивалась бы.
        if any(s.get("id") == sub_id or s.get("url") == url for s in subs):
            return web.json_response({"error": "Эта подписка уже добавлена"}, status=400)

        new_sub = {
            "id": sub_id,
            "name": name,
            "url": url,
            "enabled": True,
            "node_count": 0,
            "last_updated": None
        }
        subs.append(new_sub)
        storage.set_subscriptions(subs)

        # Trigger background update
        asyncio.create_task(self._update_subscriptions_task())
        return web.json_response({"success": True, "subscription": new_sub})

    async def handle_delete_subscription(self, request):
        data = await request.json()
        sub_id = data.get("id")
        subs = [s for s in storage.get_subscriptions() if s.get("id") != sub_id]
        storage.set_subscriptions(subs)
        return web.json_response({"success": True})

    async def handle_update_all_subscriptions(self, request):
        if self.is_updating_subs:
            return web.json_response({"error": "Обновление уже выполняется"}, status=400)
        
        asyncio.create_task(self._update_subscriptions_task())
        return web.json_response({"status": "started"})

    async def _update_subscriptions_task(self):
        self.is_updating_subs = True
        await self.broadcast_ws("subs_update_started", {})
        try:
            subs = storage.get_subscriptions()
            existing_nodes = storage.get_nodes()
            # Keep manual nodes (nodes without subscription)
            manual_nodes = [n for n in existing_nodes if not n.get("subscription")]

            res = await fetch_all_subscriptions(subs, timeout_sec=8.0)
            fetched_nodes = res.get("nodes", [])
            errors = res.get("errors", {})
            usage = res.get("usage", {})

            # Update sub metadata
            now_str = time.strftime("%d.%m %H:%M")
            for sub in subs:
                sub["last_updated"] = now_str
                count = sum(1 for n in fetched_nodes if n.get("subscription") == sub.get("name"))
                sub["node_count"] = count
                if sub.get("name") in errors:
                    sub["error"] = errors[sub.get("name")]
                else:
                    sub.pop("error", None)
            storage.set_subscriptions(subs)

            # Сводка по трафику и сроку подписки (из HTTP-заголовков провайдера).
            # Сохраняем её отдельно, чтобы не потерять старые значения,
            # если провайдер временно не отдал заголовки.
            storage.update_subscription_usage(usage)

            # Preserve existing ping measurements for nodes
            existing_pings = {n["id"]: (n.get("ping"), n.get("last_ping_time")) for n in existing_nodes if "id" in n}
            for n in fetched_nodes:
                nid = n.get("id")
                if nid in existing_pings:
                    p, lpt = existing_pings[nid]
                    if p is not None:
                        n["ping"] = p
                        n["last_ping_time"] = lpt

            all_combined = manual_nodes + fetched_nodes
            stats = storage.set_nodes(all_combined, active_node_id=self._active_node_id())
            clean_nodes = storage.get_nodes()

            await self.broadcast_ws("subs_update_finished", {
                "nodes_count": len(clean_nodes),
                "duplicates_removed": stats.get("duplicates_removed", 0),
                "errors": errors
            })
        finally:
            self.is_updating_subs = False

    async def handle_import_keys(self, request):
        data = await request.json()
        raw_text = data.get("text", "")
        if not raw_text.strip():
            return web.json_response({"error": "Текст пуст"}, status=400)

        imported = extract_nodes_from_text(raw_text, subscription_name="")
        if not imported:
            return web.json_response({"error": "Не удалось распознать ключи VPN (поддерживаются vless, vmess, trojan, ss, hysteria2)"}, status=400)

        existing = storage.get_nodes()
        combined = existing + imported
        stats = storage.set_nodes(combined, active_node_id=self._active_node_id())
        final_nodes = storage.get_nodes()
        added_count = len(final_nodes) - len(existing)
        if added_count < 0:
            added_count = 0

        await self.broadcast_ws("nodes_imported", {
            "added": added_count,
            "total": len(final_nodes),
            "duplicates_removed": stats.get("duplicates_removed", 0)
        })
        return web.json_response({
            "success": True,
            "added": added_count,
            "total": len(final_nodes),
            "duplicates_removed": stats.get("duplicates_removed", 0)
        })

    async def handle_download_core(self, request):
        if runner.downloading_core:
            return web.json_response({"error": "Скачивание уже в процессе"}, status=400)
        
        async def dl():
            success = await runner.download_official_core()
            await self.broadcast_ws("core_download_finished", {"success": success, "info": runner.get_info()})

        asyncio.create_task(dl())
        return web.json_response({"status": "started"})

    async def handle_toggle_tun(self, request):
        data = await request.json()
        tun_mode = bool(data.get("tun_mode", True))
        settings = storage.get_settings()
        settings["tun_mode"] = tun_mode
        storage.update_settings(settings)

        # If currently running, restart with the new mode
        if runner.status == "running" and runner.active_node:
            enable_sys_proxy = settings.get("system_proxy", True)
            routing_mode = settings.get("routing_mode", "bypass_ru")
            bypass_entries = settings.get("bypass_list", [])
            runner.start(runner.active_node, routing_mode=routing_mode, enable_sys_proxy=enable_sys_proxy,
                         tun_mode=tun_mode, bypass_entries=bypass_entries)
            await self.broadcast_ws("connection_changed", runner.get_info())

        return web.json_response({"success": True, "tun_mode": tun_mode, "info": runner.get_info()})

    async def handle_install_wintun(self, request):
        if runner.downloading_wintun:
            return web.json_response({"error": "Скачивание уже выполняется"}, status=400)
        
        async def dl():
            success = await runner.download_wintun()
            await self.broadcast_ws("wintun_download_finished", {"success": success, "info": runner.get_info()})

        asyncio.create_task(dl())
        return web.json_response({"status": "started"})

    async def handle_restart_elevated(self, request):
        if os.name == "nt":
            import subprocess
            run_bat = BASE_DIR / "run.bat"
            try:
                cmd = f'powershell -Command "Start-Process cmd -ArgumentList \'/c cd /d \\\"\"{BASE_DIR}\\\"\" && call run.bat admin\' -Verb RunAs"'
                subprocess.Popen(cmd, shell=True)
                def exit_later():
                    time.sleep(1.2)
                    runner.stop()
                    os._exit(0)
                import threading
                threading.Thread(target=exit_later, daemon=True).start()
                return web.json_response({"success": True})
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"error": "Поддерживается только на Windows"}, status=400)

    async def handle_repair_network(self, request):
        """«Восстановить интернет»: сбросить зависший прокси, убить осиротевшее ядро/TUN."""
        from core.recovery import repair_network

        try:
            report = repair_network()
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

        await self.broadcast_ws("network_repaired", report)
        return web.json_response({"success": True, "report": report, "info": runner.get_info()})

    async def handle_minimize_window(self, request):
        from core.gui import minimize_to_tray
        success = minimize_to_tray()
        if not success and self.app_window:
            try:
                self.app_window.hide()
                success = True
            except Exception as e:
                logger.error(f"Не удалось свернуть окно: {e}")
        return web.json_response({"success": success})

    async def handle_show_window(self, request):
        from core.gui import show_window
        success = show_window()
        if not success and self.app_window:
            try:
                self.app_window.show()
                success = True
            except Exception as e:
                logger.error(f"Не удалось показать окно: {e}")
        return web.json_response({"success": success})

    async def handle_get_settings(self, request):
        return web.json_response(storage.get_settings())

    async def handle_update_settings(self, request):
        data = await request.json()
        if "bypass_list" in data:
            raw = data["bypass_list"]
            if isinstance(raw, str):
                raw = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if not isinstance(raw, list):
                raw = []
            data["bypass_list"] = [str(x).strip() for x in raw if str(x).strip()]
        storage.update_settings(data)
        return web.json_response({"success": True, "settings": storage.get_settings()})

def create_app():
    server = FastVPNServer()
    return server.app

if __name__ == "__main__":
    port = 54321
    server = FastVPNServer()
    logger.info(f"Запуск FastVPN Configurator на http://127.0.0.1:{port}")
    web.run_app(server.app, host="127.0.0.1", port=port)
