"""
Правила «мимо VPN» — трафик, который не должен идти через прокси.

Поддерживаются три типа записей:
  • домен       — youtube.com, *.vk.com, https://site.com/path  → domain_suffix
  • IP / CIDR   — 192.168.1.10, 192.168.0.0/16                  → ip_cidr
  • процесс     — steam.exe, Discord.exe (Windows)              → process_name
"""

import ipaddress
import re
from typing import Any, Dict, List

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_PROCESS_SUFFIXES = (".exe", ".app", ".bin", ".bat", ".cmd")


def _normalize(raw: Any) -> str:
    """Приводит запись к чистому виду: убирает схему, путь, порт, пробелы."""
    s = str(raw or "").strip()
    if not s or s.startswith("#"):
        return ""
    s = _SCHEME_RE.sub("", s)
    s = s.split("?")[0].split("#")[0].strip()

    # Подсеть вида 10.0.0.0/8 — слеш тут часть адреса, а не путь
    if "/" in s:
        head, _, tail = s.partition("/")
        if head and tail and _is_ip_like(f"{head}/{tail}"):
            return f"{head}/{tail}"

    return s.split("/")[0].strip()


def _is_ip_like(value: str) -> bool:
    try:
        if "/" in value:
            ipaddress.ip_network(value, strict=False)
        else:
            ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def parse_bypass_entries(entries: Any) -> Dict[str, List[str]]:
    """
    Разбирает пользовательский список и возвращает готовые списки для sing-box.

    Возвращает: {"domain_suffix": [...], "domain_keyword": [...],
                  "ip_cidr": [...], "process_name": [...]}
    """
    result: Dict[str, List[str]] = {
        "domain_suffix": [],
        "domain_keyword": [],
        "ip_cidr": [],
        "process_name": [],
    }

    if isinstance(entries, str):
        entries = entries.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not isinstance(entries, (list, tuple)):
        return result

    for raw in entries:
        entry = _normalize(raw)
        if not entry:
            continue

        low = entry.lower()

        # 1. Приложение / процесс
        if low.endswith(_PROCESS_SUFFIXES):
            if entry not in result["process_name"]:
                result["process_name"].append(entry)
            continue

        # 2. IP-адрес или подсеть
        if _is_ip_like(entry):
            if entry not in result["ip_cidr"]:
                result["ip_cidr"].append(entry)
            continue

        # 3. Домен (возможен префикс "*.")
        if low.startswith("*."):
            domain = low[2:].lstrip(".")
            if domain and domain not in result["domain_suffix"]:
                result["domain_suffix"].append(domain)
            continue

        # 4. Домен с wildcard внутри — ищем по ключевому слову
        if "*" in low:
            keyword = low.replace("*", "").strip(".")
            if keyword and keyword not in result["domain_keyword"]:
                result["domain_keyword"].append(keyword)
            continue

        # 5. Обычный домен
        domain = low.lstrip(".").split(":")[0]
        if domain:
            if domain not in result["domain_suffix"]:
                result["domain_suffix"].append(domain)

    return result


def is_empty(rules: Dict[str, List[str]]) -> bool:
    """Есть ли хоть одно правило."""
    return not any(rules.get(k) for k in ("domain_suffix", "domain_keyword", "ip_cidr", "process_name"))


def describe(rules: Dict[str, List[str]], limit: int = 12) -> str:
    """Короткое человекочитаемое описание правил для логов и подсказок."""
    parts: List[str] = []
    for key in ("process_name", "ip_cidr", "domain_suffix", "domain_keyword"):
        for item in rules.get(key, []):
            parts.append(item)
    if not parts:
        return "нет"
    if len(parts) > limit:
        return ", ".join(parts[:limit]) + f" и ещё {len(parts) - limit}"
    return ", ".join(parts)
