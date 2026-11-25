import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "app_config.json"
BACKUP_CONFIG_PATH = DATA_DIR / "app_config.backup.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "subscriptions": [],
    "nodes": [],
    "favorites": [],
    "settings": {
        "routing_mode": "bypass_ru",
        "system_proxy": True,
        "tun_mode": True,
        "kill_switch": False,
        "doh_protection": True,
        "minimize_to_tray": True,
        "ping_timeout": 1.2,
        "ping_concurrency": 80,
        "selected_node_id": None,
        "bypass_list": []
    }
}

class Storage:
    """
    Хранилище настроек, узлов и подписок.

    Пути к файлу можно переопределить (например, для автотестов),
    чтобы тесты никогда не трогали реальные данные пользователя.
    """

    def __init__(self, config_path=None, backup_path=None):
        self._lock = threading.RLock()
        self.data: Dict[str, Any] = {}
        self.config_path = Path(config_path) if config_path else CONFIG_PATH
        self.backup_path = Path(backup_path) if backup_path else BACKUP_CONFIG_PATH
        # Счётчики дедупликации: сколько дубликатов исключено за всё время
        # и сколько — в последней операции (показывается в интерфейсе).
        self.dedup_removed_total = 0
        self.dedup_removed_last = 0
        self.load()

    def _note_dedup(self, stats: Dict[str, Any]) -> None:
        """Запоминает результат дедупликации для отображения счётчика."""
        removed = int(stats.get("duplicates_removed", 0) or 0)
        self.dedup_removed_last = removed
        self.dedup_removed_total += removed

    def get_dedup_stats(self) -> Dict[str, Any]:
        """Сводка по дедупликации: для панели настроек и /api/status."""
        with self._lock:
            return {
                "removed_total": self.dedup_removed_total,
                "removed_last": self.dedup_removed_last,
                "servers": len(self.data.get("nodes", []) or [])
            }

    def load(self):
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            for path in (self.config_path, self.backup_path):
                if path.exists() and path.stat().st_size > 0:
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            if isinstance(loaded, dict):
                                self.data = loaded
                                for k, v in DEFAULT_CONFIG.items():
                                    if k not in self.data:
                                        self.data[k] = v
                                if "settings" in self.data:
                                    for sk, sv in DEFAULT_CONFIG["settings"].items():
                                        if sk not in self.data["settings"]:
                                            self.data["settings"][sk] = sv
                                if "nodes" in self.data and isinstance(self.data["nodes"], list):
                                    from core.parser import deduplicate_nodes
                                    sel_id = self.data.get("settings", {}).get("selected_node_id")
                                    favs = self.data.get("favorites", [])
                                    clean_nodes, stats = deduplicate_nodes(
                                        self.data["nodes"],
                                        selected_node_id=sel_id,
                                        favorites=favs
                                    )
                                    self._note_dedup(stats)
                                    self.data["nodes"] = clean_nodes
                                    if stats["remapped_selected_id"]:
                                        self.data.setdefault("settings", {})["selected_node_id"] = stats["remapped_selected_id"]
                                    self.data["favorites"] = stats["favorites"]
                                # Подписки: убираем повторы (одна ссылка — одна запись),
                                # иначе сводка по трафику удваивается.
                                if isinstance(self.data.get("subscriptions"), list):
                                    deduped_subs = self._dedupe_subscriptions(self.data["subscriptions"])
                                    if len(deduped_subs) != len(self.data["subscriptions"]):
                                        self.data["subscriptions"] = deduped_subs
                                        self.save()
                                return
                    except Exception:
                        continue
            self.data = json.loads(json.dumps(DEFAULT_CONFIG))
            self.save()

    def save(self):
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.config_path.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                # Atomic replace on Windows
                os.replace(tmp_path, self.config_path)
                # Keep a backup of the successfully saved config
                try:
                    shutil.copy2(self.config_path, self.backup_path)
                except Exception:
                    pass
            except Exception:
                # Direct fallback write
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.data.get("subscriptions", []))

    def set_subscriptions(self, subs: List[Dict[str, Any]]):
        with self._lock:
            self.data["subscriptions"] = self._dedupe_subscriptions(subs)
            self.save()

    @staticmethod
    def _dedupe_subscriptions(subs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Убирает повторяющиеся подписки.

        Ключ подписки — её id (он же выводится из URL). Одна и та же ссылка,
        добавленная дважды, не должна удваивать трафик и срок в сводке.
        При совпадении сохраняем первую запись и дописываем в неё
        сводку usage, если она появилась у второй.
        """
        result: List[Dict[str, Any]] = []
        by_id: Dict[str, Dict[str, Any]] = {}
        for sub in subs or []:
            if not isinstance(sub, dict):
                continue
            key = sub.get("id") or sub.get("url")
            if not key:
                result.append(sub)
                continue
            existing = by_id.get(key)
            if existing is None:
                by_id[key] = sub
                result.append(sub)
                continue
            # Дубль: переносим сводку, если у дубля она есть, а у первого — нет
            if not existing.get("usage") and sub.get("usage"):
                existing["usage"] = sub["usage"]
        return result

    def update_subscription_usage(self, usage_by_name: Dict[str, Dict[str, Any]]) -> None:
        """
        Записывает сводку по трафику и сроку подписки (из заголовков провайдера).

        usage_by_name — словарь {имя подписки: {used, total, remaining, expire, ...}}.
        Подписки, для которых провайдер не отдал данные, не трогаем —
        лучше показать старые значения, чем «нет данных» после каждого обновления.
        """
        if not usage_by_name:
            return
        with self._lock:
            changed = False
            for sub in self.data.get("subscriptions", []) or []:
                info = usage_by_name.get(sub.get("name"))
                if not info:
                    continue
                sub["usage"] = dict(info)
                changed = True
            if changed:
                self.save()

    def get_subscription_usage_summary(self) -> Dict[str, Any]:
        """
        Сводная статистика по всем подпискам для главного экрана.

        Возвращает:
          has_data     — есть ли вообще данные от провайдера;
          used/total   — суммарно израсходовано и выдано байт;
          remaining    — сколько осталось;
          percent      — процент расхода;
          expire       — ближайшее окончание подписки (unix);
          expire_days_left — дней до ближайшего окончания;
          subscriptions — список по подпискам (имя + сводка).
        """
        with self._lock:
            subs = list(self.data.get("subscriptions", []) or [])
            per_sub = []
            total_used = 0
            total_limit = 0
            expires = []

            for sub in subs:
                usage = sub.get("usage")
                if not usage:
                    continue
                used = int(usage.get("used", 0) or 0)
                limit = int(usage.get("total", 0) or 0)
                entry = {
                    "id": sub.get("id"),
                    "name": sub.get("name", "Подписка"),
                    "used": used,
                    "total": limit,
                    "remaining": int(usage.get("remaining", max(0, limit - used)) or 0),
                    "percent": float(usage.get("percent", 0) or 0),
                }
                if usage.get("expire"):
                    entry["expire"] = usage["expire"]
                    entry["expire_days_left"] = usage.get("expire_days_left")
                    expires.append(usage["expire"])
                if usage.get("refill_date"):
                    entry["refill_date"] = usage["refill_date"]
                per_sub.append(entry)

                # Суммируем только подписки с известным лимитом,
                # иначе «безлимит» исказит общий процент.
                if limit > 0:
                    total_used += used
                    total_limit += limit

            summary: Dict[str, Any] = {
                "has_data": bool(per_sub),
                "used": total_used,
                "total": total_limit,
                "remaining": max(0, total_limit - total_used),
                "percent": round(total_used / total_limit * 100, 1) if total_limit else 0.0,
                "subscriptions": per_sub,
            }
            if expires:
                nearest = min(expires)
                summary["expire"] = nearest
                summary["expire_days_left"] = max(0, (nearest - int(time.time())) // 86400)
            return summary

    def get_nodes(self) -> List[Dict[str, Any]]:
        with self._lock:
            nodes = self.data.get("nodes", [])
            from core.parser import is_whitelist_node
            for n in nodes:
                if "is_whitelist" not in n:
                    n["is_whitelist"] = is_whitelist_node(n.get("name", ""))
            return nodes

    def set_nodes(self, nodes: List[Dict[str, Any]], active_node_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Сохраняет список узлов, предварительно исключая дубликаты
        по каноническому ключу подключения (протокол/host/порт/транспорт/
        учётные данные). Идемпотентно: повторный вызов не меняет список.

        active_node_id — id текущего подключения: если он оказался дубликатом,
        выбор переносится на оставшийся экземпляр, и соединение не рвётся.
        """
        with self._lock:
            from core.parser import deduplicate_nodes
            sel_id = self.data.get("settings", {}).get("selected_node_id")
            favs = self.data.get("favorites", [])
            clean_nodes, stats = deduplicate_nodes(
                nodes,
                active_node_id=active_node_id,
                selected_node_id=sel_id,
                favorites=favs
            )
            self._note_dedup(stats)
            self.data["nodes"] = clean_nodes
            if stats["remapped_selected_id"] and stats["remapped_selected_id"] != sel_id:
                self.data.setdefault("settings", {})["selected_node_id"] = stats["remapped_selected_id"]
            if stats["favorites"] != favs:
                self.data["favorites"] = stats["favorites"]
            self.save()
            return stats

    def get_favorites(self) -> List[str]:
        with self._lock:
            return list(self.data.get("favorites", []))

    def toggle_favorite(self, node_id: str) -> bool:
        with self._lock:
            favs = self.data.get("favorites", [])
            if node_id in favs:
                favs.remove(node_id)
                is_fav = False
            else:
                favs.append(node_id)
                is_fav = True
            self.data["favorites"] = favs
            self.save()
            return is_fav

    def get_settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.data.get("settings", DEFAULT_CONFIG["settings"]))

    def update_settings(self, new_settings: Dict[str, Any]):
        with self._lock:
            self.data["settings"].update(new_settings)
            self.save()

storage = Storage()
