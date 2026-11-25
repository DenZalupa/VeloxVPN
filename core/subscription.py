import asyncio
import base64
import json
import logging
import re
import time
import urllib.parse
from typing import List, Dict, Any, Tuple, Optional
import aiohttp

from core.parser import parse_node, safe_b64decode, generate_node_id

logger = logging.getLogger(__name__)

# Headers that mimic popular clients so VPN panels and Cloudflare don't block
DEFAULT_HEADERS = {
    "User-Agent": "v2rayN/6.45 Happ/1.2.5 clash-verge/1.7.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}


# --- Метаданные подписки: трафик и срок действия ---------------------------
#
# Стандарт XRay/v2rayN: панель отдаёт заголовок
#   Subscription-Userinfo: upload=<байт>; download=<байт>; total=<байт>; expire=<unix>
# Не все панели его отдают — тогда метаданных просто не будет, и мы
# ничего не показываем (вместо того чтобы выдумывать цифры).

USERINFO_HEADER = "subscription-userinfo"
REFILL_HEADER = "subscription-refill-date"


def parse_subscription_userinfo(raw: Optional[str]) -> Dict[str, Any]:
    """
    Разбирает заголовок Subscription-Userinfo в словарь с байтами и сроком.

    Возвращает пустой словарь, если заголовка нет или он не разбирается:
    лучше показать «нет данных», чем показать неверные.
    """
    if not raw:
        return {}

    values: Dict[str, int] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key not in ("upload", "download", "total", "expire"):
            continue
        try:
            values[key] = int(value)
        except (TypeError, ValueError):
            continue

    if not values:
        return {}

    upload = max(0, values.get("upload", 0))
    download = max(0, values.get("download", 0))
    total = max(0, values.get("total", 0))
    used = upload + download

    info: Dict[str, Any] = {
        "upload": upload,
        "download": download,
        "used": used,
        "total": total,
        "remaining": max(0, total - used) if total else 0,
        "percent": round(used / total * 100, 1) if total else 0.0,
    }

    # Срок действия — unix-время в секундах
    expire = values.get("expire")
    if expire and expire > 0:
        info["expire"] = expire
        info["expire_days_left"] = max(0, (expire - int(time.time())) // 86400)

    return info


def _header_lookup(headers, name: str) -> Optional[str]:
    """
    Ищет заголовок без учёта регистра.

    aiohttp отдаёт CIMultiDict (регистр не важен), но в тестах и при
    ручной обработке headers может быть обычным dict — тогда нужен
    перебор с приведением к нижнему регистру.
    """
    if not headers:
        return None
    try:
        value = headers.get(name)
        if value is not None:
            return value
    except AttributeError:
        pass
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return value
    return None


def build_usage_info(headers, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Собирает сводку по подписке из HTTP-заголовков ответа.

    headers — aiohttp CIMultiDict или любой dict с заголовками.
    extra  — дополнительные поля (например, дата обновления пакета).
    """
    usage = parse_subscription_userinfo(_header_lookup(headers, USERINFO_HEADER))
    if not usage:
        return {}

    refill = _header_lookup(headers, REFILL_HEADER)
    if refill:
        try:
            usage["refill_date"] = int(str(refill).strip())
        except (TypeError, ValueError):
            pass

    if extra:
        usage.update(extra)
    return usage


async def fetch_subscription_usage(url: str, timeout_sec: float = 8.0) -> Dict[str, Any]:
    """
    Запрашивает только метаданные подписки (трафик и срок).

    Тело ответа не читается — нужен только заголовок, поэтому запрос лёгкий.
    """
    if not url:
        return {}
    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as response:
                if response.status != 200:
                    return {}
                return build_usage_info(response.headers, {"fetched_at": int(time.time())})
    except Exception as e:
        logger.debug("Не удалось получить метаданные подписки: %s", e)
        return {}


def extract_nodes_from_text(raw_text: str, subscription_name: str = "") -> List[Dict[str, Any]]:
    """
    Parses nodes from raw text.
    Handles Base64 blobs, line-by-line URIs, and JSON/YAML fragments.
    """
    raw_text = raw_text.strip()
    nodes: List[Dict[str, Any]] = []

    # First check if the entire text is base64 encoded
    if not (raw_text.startswith("vless://") or raw_text.startswith("vmess://") or raw_text.startswith("trojan://") or raw_text.startswith("ss://")):
        decoded = safe_b64decode(raw_text)
        if decoded and ("vless://" in decoded or "vmess://" in decoded or "trojan://" in decoded or "ss://" in decoded):
            raw_text = decoded

    # Split into lines
    lines = raw_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Check if line is a valid protocol URI
        node = parse_node(line)
        if node:
            if subscription_name:
                node["subscription"] = subscription_name
            nodes.append(node)
            continue
        
        # Check if single line is base64 encoded
        if len(line) > 20 and not " " in line:
            line_decoded = safe_b64decode(line)
            node = parse_node(line_decoded)
            if node:
                if subscription_name:
                    node["subscription"] = subscription_name
                nodes.append(node)

    return nodes

async def fetch_subscription_url(url: str, name: str, timeout_sec: float = 8.0) -> Tuple[str, List[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Asynchronously fetch subscription URL and extract nodes.
    Returns (subscription_name, nodes, error_message, usage_info).

    usage_info — сводка по трафику и сроку подписки из HTTP-заголовков
    (пустой словарь, если провайдер их не отдаёт).
    """
    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as response:
                if response.status != 200:
                    return name, [], f"HTTP {response.status}: {response.reason}", {}
                
                content = await response.text()
                nodes = extract_nodes_from_text(content, subscription_name=name)
                usage = build_usage_info(response.headers, {"fetched_at": int(time.time())})
                return name, nodes, "", usage
    except asyncio.TimeoutError:
        return name, [], "Таймаут подключения (сервер подписки не отвечает)", {}
    except Exception as e:
        return name, [], f"Ошибка загрузки: {str(e)}", {}

async def fetch_all_subscriptions(subscriptions: List[Dict[str, Any]], timeout_sec: float = 8.0) -> Dict[str, Any]:
    """
    Parallel fetch of all user subscriptions in under 1-2 seconds.

    Вместе с узлами возвращает usage — сводку по трафику и сроку каждой
    подписки (ключ — имя подписки).
    """
    tasks = [
        fetch_subscription_url(sub["url"], sub.get("name", "Подписка"), timeout_sec=timeout_sec)
        for sub in subscriptions if sub.get("url") and sub.get("enabled", True)
    ]
    
    if not tasks:
        return {"nodes": [], "errors": {}, "usage": {}}

    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_nodes: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    usage: Dict[str, Dict[str, Any]] = {}
    seen_ids = set()

    for res in results:
        if isinstance(res, Exception):
            continue
        sub_name, nodes, err, sub_usage = res
        if err:
            errors[sub_name] = err
        if sub_usage:
            usage[sub_name] = sub_usage
        for n in nodes:
            nid = n.get("id")
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                all_nodes.append(n)

    from core.parser import deduplicate_nodes
    clean_nodes, _ = deduplicate_nodes(all_nodes)
    return {"nodes": clean_nodes, "errors": errors, "usage": usage}

