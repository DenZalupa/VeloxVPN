import base64
import hashlib
import ipaddress
import json
import re
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
from core.country_detector import detect_country

WHITELIST_PATTERN = re.compile(
    r'(?i)(?:бел(?:ый|ые|ых|ого|ом|ому)?\s*список|белые\s*списки|whitelist|white\s*list|\bбс\b|\bwl\b)',
    re.UNICODE
)

def is_whitelist_node(name: str) -> bool:
    """True if node name indicates whitelist bypass server."""
    return bool(WHITELIST_PATTERN.search(name or ""))

def safe_b64decode(s: str) -> str:
    """Decode base64 string handling padding and url-safe characters."""
    s = s.strip()
    s = s.replace("-", "+").replace("_", "/")
    padding = len(s) % 4
    if padding:
        s += "=" * (4 - padding)
    try:
        return base64.b64decode(s).decode("utf-8", errors="ignore")
    except Exception:
        return ""

def generate_node_id(uri: str) -> str:
    """Generate deterministic short id for node."""
    return hashlib.sha256(uri.strip().encode("utf-8")).hexdigest()[:12]


DEFAULT_PORTS = {
    "vless": 443,
    "vmess": 443,
    "trojan": 443,
    "shadowsocks": 8388,
    "ss": 8388,
    "hysteria2": 443,
    "hy2": 443,
    "tuic": 443,
    "wireguard": 51820,
    "http": 80,
    "https": 443,
}

def normalize_host(host: str) -> str:
    """
    Normalizes a host string:
    - Strips whitespace
    - Lowercase
    - Strips IPv6 brackets (e.g. [::1] -> ::1)
    - Strips trailing dots (e.g. example.com. -> example.com)
    - Compresses standard IPv6 addresses via ipaddress
    """
    if not host:
        return ""
    h = str(host).strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    h = h.rstrip(".")
    try:
        ip = ipaddress.ip_address(h)
        return ip.compressed
    except ValueError:
        return h

def normalize_port(port: Any, node_type: str = "") -> int:
    """Returns normalized integer port, defaulting according to protocol."""
    try:
        p = int(port)
        if 1 <= p <= 65535:
            return p
    except (ValueError, TypeError):
        pass
    return DEFAULT_PORTS.get((node_type or "").lower(), 443)

def get_canonical_node_key(node: Dict[str, Any]) -> str:
    """
    Calculates a unique canonical connection key for a VPN node.
    
    Includes only connection-defining parameters:
    - protocol (type)
    - normalized host
    - normalized port
    - transport/network
    - security & SNI
    - protocol-specific authentication credentials & routing paths
    
    Excludes display name, ping, and local metadata.
    """
    if not isinstance(node, dict):
        return ""

    ntype = str(node.get("type", "")).strip().lower()
    host = normalize_host(node.get("server", ""))
    port = normalize_port(node.get("port"), ntype)
    network = str(node.get("network", "tcp")).strip().lower()
    security = str(node.get("security", "none")).strip().lower()
    sni = normalize_host(node.get("sni", ""))

    # Protocol-specific connection params
    cred_params: Dict[str, Any] = {}

    if ntype == "vless":
        cred_params = {
            "uuid": str(node.get("uuid", "")).strip().lower(),
            "flow": str(node.get("flow", "")).strip().lower(),
            "pbk": str(node.get("reality_pubkey", "")).strip(),
            "sid": str(node.get("reality_short_id", "")).strip().lower(),
            "spx": str(node.get("reality_spider_x", "")).strip(),
            "fp": str(node.get("fingerprint", "chrome")).strip().lower(),
            "path": str(node.get("path", "")).strip(),
            "service_name": str(node.get("service_name", "")).strip(),
            "host": normalize_host(node.get("host", ""))
        }
    elif ntype == "vmess":
        cred_params = {
            "uuid": str(node.get("uuid", "")).strip().lower(),
            "aid": int(node.get("alter_id", 0)),
            "path": str(node.get("path", "")).strip(),
            "host": normalize_host(node.get("host", ""))
        }
    elif ntype == "trojan":
        cred_params = {
            "password": str(node.get("password", "")).strip(),
            "path": str(node.get("path", "")).strip()
        }
    elif ntype in ["shadowsocks", "ss"]:
        cred_params = {
            "method": str(node.get("method", "chacha20-ietf-poly1305")).strip().lower(),
            "password": str(node.get("password", "")).strip()
        }
    elif ntype in ["hysteria2", "hy2"]:
        cred_params = {
            "password": str(node.get("password", "")).strip(),
            "insecure": bool(node.get("insecure", False))
        }
    else:
        for k in ["uuid", "password", "method", "path"]:
            if k in node:
                cred_params[k] = str(node[k]).strip()

    canonical_dict = {
        "t": ntype,
        "h": host,
        "p": port,
        "net": network,
        "sec": security,
        "sni": sni,
        "c": cred_params
    }

    serialized = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return f"{ntype}://{host}:{port}#" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]

def _score_node_name(name: str, host: str) -> int:
    """Scores how descriptive and user-friendly a node name is."""
    if not name:
        return 0
    score = len(name)
    if re.search(r'[🇦-🇿]{2}', name):
        score += 50
    if re.search(r'[а-яА-ЯёЁ]', name):
        score += 30
    if host and name.strip() == host.strip():
        score -= 20
    if name.startswith("vless-") or name.startswith("vmess-") or name.startswith("ss-"):
        score -= 10
    return score

def deduplicate_nodes(
    nodes: List[Dict[str, Any]],
    active_node_id: Optional[str] = None,
    selected_node_id: Optional[str] = None,
    favorites: Optional[List[str]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Idempotent, near O(n) deduplication of VPN server nodes.
    
    Preserves:
    - Best display name (prefers human-readable names with country/description)
    - Latest/best ping measurements
    - Whitelist status
    - Favorite status (remapped if duplicate was favorited)
    - Active/selected node ID (remapped so active VPN connection isn't dropped)
    """
    if not nodes:
        return [], {
            "duplicates_removed": 0,
            "remapped_selected_id": selected_node_id,
            "remapped_active_id": active_node_id,
            "favorites": list(favorites or [])
        }

    seen_keys: Dict[str, Dict[str, Any]] = {}
    deduped: List[Dict[str, Any]] = []
    dropped_count = 0

    cur_selected_id = selected_node_id
    cur_active_id = active_node_id
    fav_set = set(favorites or [])

    for node in nodes:
        if not isinstance(node, dict):
            continue

        key = get_canonical_node_key(node)
        node_id = node.get("id")

        if key not in seen_keys:
            seen_keys[key] = node
            deduped.append(node)
        else:
            dropped_count += 1
            survivor = seen_keys[key]
            survivor_id = survivor.get("id")

            # 1. Remap selected / active node if the duplicate was chosen
            if node_id and node_id == cur_selected_id:
                cur_selected_id = survivor_id
            if node_id and node_id == cur_active_id:
                cur_active_id = survivor_id

            # 2. Remap favorite status
            if node_id and node_id in fav_set:
                fav_set.discard(node_id)
                if survivor_id:
                    fav_set.add(survivor_id)

            # 3. Preserve best name and country
            cand_score = _score_node_name(node.get("name", ""), node.get("server", ""))
            surv_score = _score_node_name(survivor.get("name", ""), survivor.get("server", ""))
            if cand_score > surv_score:
                survivor["name"] = node.get("name")
                if node.get("country"):
                    survivor["country"] = node.get("country")

            # 4. Preserve whitelist flag
            if node.get("is_whitelist"):
                survivor["is_whitelist"] = True

            # 5. Preserve best/latest ping
            cand_ping = node.get("ping")
            surv_ping = survivor.get("ping")
            if cand_ping is not None:
                if surv_ping is None or (cand_ping > 0 and (surv_ping <= 0 or cand_ping < surv_ping)):
                    survivor["ping"] = cand_ping
                    survivor["last_ping_time"] = node.get("last_ping_time")

            # 6. Preserve subscription name if survivor didn't have one
            if not survivor.get("subscription") and node.get("subscription"):
                survivor["subscription"] = node.get("subscription")

    stats = {
        "duplicates_removed": dropped_count,
        "remapped_selected_id": cur_selected_id,
        "remapped_active_id": cur_active_id,
        "favorites": list(fav_set)
    }

    return deduped, stats

def parse_vless(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "vless":
        return None
    
    uuid = parsed.username or ""
    server = parsed.hostname or ""
    port = parsed.port or 443
    name = urllib.parse.unquote(parsed.fragment or server)
    query = urllib.parse.parse_qs(parsed.query)

    def qget(key: str, default: str = "") -> str:
        vals = query.get(key)
        return vals[0] if vals else default

    network = qget("type", "tcp").lower()
    security = qget("security", "none").lower()
    sni = qget("sni", "") or qget("peer", "")
    fp = qget("fp", "chrome")
    flow = qget("flow", "")
    pbk = qget("pbk", "")
    sid = qget("sid", "")
    spx = qget("spx", "")
    path = qget("path", "")
    service_name = qget("serviceName", "") or qget("service_name", "")
    host_header = qget("host", "")

    country = detect_country(name, server)

    return {
        "id": generate_node_id(uri),
        "name": name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "network": network,
        "security": security,
        "sni": sni,
        "fingerprint": fp,
        "flow": flow,
        "reality_pubkey": pbk,
        "reality_short_id": sid,
        "reality_spider_x": spx,
        "path": path,
        "service_name": service_name,
        "host": host_header,
        "country": country,
        "raw_uri": uri,
        "ping": None,
        "last_ping_time": None
    }

def parse_vmess(uri: str) -> Optional[Dict[str, Any]]:
    if not uri.startswith("vmess://"):
        return None
    raw = uri[8:]
    decoded = safe_b64decode(raw)
    if not decoded:
        return None
    try:
        data = json.loads(decoded)
    except Exception:
        return None

    name = data.get("ps", data.get("add", "VMess"))
    server = data.get("add", "")
    try:
        port = int(data.get("port", 443))
    except Exception:
        port = 443
    uuid = data.get("id", "")
    network = str(data.get("net", "tcp")).lower()
    security = str(data.get("tls", "none")).lower()
    sni = data.get("sni", data.get("host", ""))
    path = data.get("path", "")
    aid = int(data.get("aid", 0))

    country = detect_country(name, server)

    return {
        "id": generate_node_id(uri),
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "network": network,
        "security": "tls" if security in ["tls", "reality"] else "none",
        "sni": sni,
        "fingerprint": "chrome",
        "flow": "",
        "alter_id": aid,
        "path": path,
        "host": data.get("host", ""),
        "country": country,
        "raw_uri": uri,
        "ping": None,
        "last_ping_time": None
    }

def parse_trojan(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "trojan":
        return None

    password = parsed.username or ""
    server = parsed.hostname or ""
    port = parsed.port or 443
    name = urllib.parse.unquote(parsed.fragment or server)
    query = urllib.parse.parse_qs(parsed.query)

    def qget(key: str, default: str = "") -> str:
        vals = query.get(key)
        return vals[0] if vals else default

    sni = qget("sni", "") or server
    network = qget("type", "tcp").lower()
    path = qget("path", "")
    security = qget("security", "tls").lower()

    country = detect_country(name, server)

    return {
        "id": generate_node_id(uri),
        "name": name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "network": network,
        "security": security,
        "sni": sni,
        "fingerprint": qget("fp", "chrome"),
        "path": path,
        "country": country,
        "raw_uri": uri,
        "ping": None,
        "last_ping_time": None
    }

def parse_shadowsocks(uri: str) -> Optional[Dict[str, Any]]:
    if not uri.startswith("ss://"):
        return None
    raw = uri[5:]
    name = ""
    if "#" in raw:
        raw, fragment = raw.split("#", 1)
        name = urllib.parse.unquote(fragment)

    method, password, server, port = "", "", "", 8388

    # SIP002 style: ss://[base64(method:password)]@host:port
    if "@" in raw:
        user_info, host_info = raw.split("@", 1)
        decoded_user = safe_b64decode(user_info)
        if ":" in decoded_user:
            method, password = decoded_user.split(":", 1)
        elif ":" in user_info:
            method, password = user_info.split(":", 1)
        
        host_parsed = urllib.parse.urlparse(f"//{host_info}")
        server = host_parsed.hostname or ""
        port = host_parsed.port or 8388
    else:
        # Legacy base64: ss://[base64(method:password@host:port)]
        decoded = safe_b64decode(raw)
        if "@" in decoded:
            user_info, host_info = decoded.split("@", 1)
            if ":" in user_info:
                method, password = user_info.split(":", 1)
            if ":" in host_info:
                server, p = host_info.split(":", 1)
                port = int(p.split("/")[0])

    if not server:
        return None

    if not name:
        name = f"SS-{server}:{port}"

    country = detect_country(name, server)

    return {
        "id": generate_node_id(uri),
        "name": name,
        "type": "shadowsocks",
        "server": server,
        "port": port,
        "method": method or "chacha20-ietf-poly1305",
        "password": password,
        "country": country,
        "raw_uri": uri,
        "ping": None,
        "last_ping_time": None
    }

def parse_hysteria2(uri: str) -> Optional[Dict[str, Any]]:
    if not (uri.startswith("hysteria2://") or uri.startswith("hy2://")):
        return None
    
    # normalize scheme
    norm_uri = uri
    if norm_uri.startswith("hy2://"):
        norm_uri = "hysteria2://" + norm_uri[6:]

    parsed = urllib.parse.urlparse(norm_uri)
    password = parsed.username or ""
    server = parsed.hostname or ""
    port = parsed.port or 443
    name = urllib.parse.unquote(parsed.fragment or server)
    query = urllib.parse.parse_qs(parsed.query)

    def qget(key: str, default: str = "") -> str:
        vals = query.get(key)
        return vals[0] if vals else default

    sni = qget("sni", "") or server
    insecure = qget("insecure", "0") in ["1", "true"]

    country = detect_country(name, server)

    return {
        "id": generate_node_id(uri),
        "name": name,
        "type": "hysteria2",
        "server": server,
        "port": port,
        "password": password,
        "sni": sni,
        "insecure": insecure,
        "country": country,
        "raw_uri": uri,
        "ping": None,
        "last_ping_time": None
    }

def parse_node(uri: str) -> Optional[Dict[str, Any]]:
    """Parse any supported VPN protocol URI."""
    uri = uri.strip()
    if not uri:
        return None
    
    node = None
    if uri.startswith("vless://"):
        node = parse_vless(uri)
    elif uri.startswith("vmess://"):
        node = parse_vmess(uri)
    elif uri.startswith("trojan://"):
        node = parse_trojan(uri)
    elif uri.startswith("ss://"):
        node = parse_shadowsocks(uri)
    elif uri.startswith("hysteria2://") or uri.startswith("hy2://"):
        node = parse_hysteria2(uri)

    if node:
        node["is_whitelist"] = is_whitelist_node(node.get("name", ""))
    return node

def node_to_singbox_outbound(node: Dict[str, Any]) -> Dict[str, Any]:
    """Convert node dictionary to sing-box outbound configuration object."""
    ntype = node.get("type")
    tag = "proxy"
    server = node.get("server")
    port = int(node.get("port", 443))

    if ntype == "vless":
        outbound = {
            "type": "vless",
            "tag": tag,
            "server": server,
            "server_port": port,
            "uuid": node.get("uuid", ""),
            "flow": node.get("flow", "") or None
        }
        # Clean null values
        if not outbound["flow"]:
            del outbound["flow"]

        sec = node.get("security", "none")
        if sec in ["reality", "tls"]:
            tls_cfg: Dict[str, Any] = {
                "enabled": True,
                "server_name": node.get("sni") or server,
                "utls": {
                    "enabled": True,
                    "fingerprint": node.get("fingerprint", "chrome") or "chrome"
                },
                "fragment": True
            }
            if sec == "reality":
                reality_cfg = {
                    "enabled": True,
                    "public_key": node.get("reality_pubkey", ""),
                    "short_id": node.get("reality_short_id", "")
                }
                tls_cfg["reality"] = reality_cfg
            outbound["tls"] = tls_cfg

        net = node.get("network", "tcp")
        if net == "ws":
            ws_cfg: Dict[str, Any] = {
                "type": "ws",
                "path": node.get("path", "/"),
            }
            if node.get("host"):
                ws_cfg["headers"] = {"Host": node.get("host")}
            outbound["transport"] = ws_cfg
        elif net == "grpc":
            outbound["transport"] = {
                "type": "grpc",
                "service_name": node.get("service_name", "")
            }

        return outbound

    elif ntype == "vmess":
        outbound = {
            "type": "vmess",
            "tag": tag,
            "server": server,
            "server_port": port,
            "uuid": node.get("uuid", ""),
            "security": "auto",
            "alter_id": node.get("alter_id", 0)
        }
        if node.get("security") == "tls":
            outbound["tls"] = {
                "enabled": True,
                "server_name": node.get("sni") or server
            }
        net = node.get("network", "tcp")
        if net == "ws":
            ws_cfg = {
                "type": "ws",
                "path": node.get("path", "/"),
            }
            if node.get("host"):
                ws_cfg["headers"] = {"Host": node.get("host")}
            outbound["transport"] = ws_cfg
        return outbound

    elif ntype == "trojan":
        outbound = {
            "type": "trojan",
            "tag": tag,
            "server": server,
            "server_port": port,
            "password": node.get("password", "")
        }
        if node.get("security") != "none":
            outbound["tls"] = {
                "enabled": True,
                "server_name": node.get("sni") or server
            }
        return outbound

    elif ntype == "shadowsocks":
        return {
            "type": "shadowsocks",
            "tag": tag,
            "server": server,
            "server_port": port,
            "method": node.get("method", "chacha20-ietf-poly1305"),
            "password": node.get("password", "")
        }

    elif ntype == "hysteria2":
        return {
            "type": "hysteria2",
            "tag": tag,
            "server": server,
            "server_port": port,
            "password": node.get("password", ""),
            "tls": {
                "enabled": True,
                "server_name": node.get("sni") or server,
                "insecure": bool(node.get("insecure", False))
            }
        }

    # Fallback to direct
    return {"type": "direct", "tag": tag}
