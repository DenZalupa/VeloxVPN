import concurrent.futures
import os
import socket
import struct
import time
from typing import Dict, Any, List, Optional, Callable, Tuple

def get_physical_interface() -> Tuple[Optional[str], int]:
    """
    Get (physical_ip, if_index) of the physical network adapter on Windows.
    Bypasses virtual VPN adapters (172.19.x = VeloxVPN TUN, 26.x = Radmin, 127.x = loopback, 169.254.x = link-local).
    Ensures ping measurements always test real ISP round-trip time directly to servers, even when TUN mode is active.
    """
    if os.name != "nt":
        return (None, 0)
    try:
        import ctypes
        from ctypes import wintypes

        class MIB_IPADDRROW(ctypes.Structure):
            _fields_ = [
                ('dwAddr', wintypes.DWORD),
                ('dwIndex', wintypes.DWORD),
                ('dwMask', wintypes.DWORD),
                ('dwBCastAddr', wintypes.DWORD),
                ('dwReasmSize', wintypes.DWORD),
                ('unused1', wintypes.WORD),
                ('wType', wintypes.WORD),
            ]

        iphlpapi = ctypes.windll.iphlpapi
        size = wintypes.ULONG(0)
        iphlpapi.GetIpAddrTable(None, ctypes.byref(size), False)
        if size.value == 0:
            return (None, 0)
        buf = ctypes.create_string_buffer(size.value)
        if iphlpapi.GetIpAddrTable(ctypes.cast(buf, ctypes.c_void_p), ctypes.byref(size), False) != 0:
            return (None, 0)

        num_entries = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
        p_rows = ctypes.cast(ctypes.byref(buf, 4), ctypes.POINTER(MIB_IPADDRROW))
        
        candidates = []
        for i in range(num_entries):
            row = p_rows[i]
            ip_str = socket.inet_ntoa(struct.pack('<L', row.dwAddr))
            if ip_str.startswith("127.") or ip_str.startswith("169.254.") or ip_str.startswith("172.19.") or ip_str.startswith("26."):
                continue
            candidates.append((ip_str, int(row.dwIndex)))

        for ip, if_idx in candidates:
            if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
                return (ip, if_idx)
        if candidates:
            return candidates[0]
    except Exception:
        pass
    return (None, 0)

def sync_tcp_ping(host: str, port: int, timeout_sec: float = 1.2, bind_ip: Optional[str] = None, if_index: int = 0) -> int:
    """
    High-performance, reliable TCP handshake ping on Windows.
    Bypasses local TUN loopback by binding to physical NIC (IP_UNICAST_IF) to measure actual ISP latency.
    Returns latency in milliseconds, or -1 if unreachable/timeout.
    """
    if not host or not port:
        return -1
    
    t0 = time.perf_counter()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout_sec)

    # Bypass TUN adapter on Windows to measure real ISP round-trip time directly to the node
    if os.name == "nt":
        if bind_ip:
            try:
                s.bind((bind_ip, 0))
            except Exception:
                pass
        if if_index > 0:
            try:
                # IP_UNICAST_IF (31) sets outgoing interface index, bypassing TUN default route
                s.setsockopt(socket.IPPROTO_IP, 31, socket.htonl(if_index))
            except Exception:
                pass

    try:
        s.connect((host, port))
        latency = round((time.perf_counter() - t0) * 1000)
        return max(5, latency)
    except Exception:
        return -1
    finally:
        try:
            s.close()
        except Exception:
            pass

def ping_node(node: Dict[str, Any], timeout_sec: float = 1.2) -> Dict[str, Any]:
    """Test ping for a single node object."""
    host = node.get("server", "")
    port = int(node.get("port", 443))
    bind_ip, if_idx = get_physical_interface()
    
    latency = sync_tcp_ping(host, port, timeout_sec, bind_ip=bind_ip, if_index=if_idx)
    node["ping"] = latency
    node["last_ping_time"] = time.time()
    return node

def ping_all_nodes(
    nodes: List[Dict[str, Any]], 
    concurrency: int = 80, 
    timeout_sec: float = 1.2,
    on_node_pinged: Optional[Callable[[Dict[str, Any]], None]] = None
) -> List[Dict[str, Any]]:
    """
    Ultra-fast concurrent ping test across all nodes simultaneously.
    Uses a high-performance thread pool to ping 100-300 nodes in ~1.2s flat!
    Automatically bypasses local TUN loopback to measure true server latency.
    """
    if not nodes:
        return []

    bind_ip, if_idx = get_physical_interface()
    workers = min(concurrency, max(1, len(nodes)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_node = {
            executor.submit(sync_tcp_ping, n.get("server", ""), int(n.get("port", 443)), timeout_sec, bind_ip, if_idx): n
            for n in nodes
        }
        for future in concurrent.futures.as_completed(future_to_node):
            node = future_to_node[future]
            try:
                latency = future.result()
            except Exception:
                latency = -1
            node["ping"] = latency
            node["last_ping_time"] = time.time()
            if on_node_pinged:
                try:
                    on_node_pinged(node)
                except Exception:
                    pass

    return nodes

async def real_http_delay_test(proxy_port: int = 20809, target_url: str = "http://cp.cloudflare.com/generate_204", timeout_sec: float = 3.0) -> int:
    """
    Tests actual HTTP connectivity through the local running proxy.
    Returns HTTP delay in ms or -1 if failed.
    """
    import aiohttp
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    start = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(target_url, proxy=proxy_url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
                if resp.status in [200, 204]:
                    return max(1, round((time.perf_counter() - start) * 1000))
                return -1
    except Exception:
        return -1

async def real_speedtest(proxy_port: int = 20809, duration_sec: float = 3.0) -> Dict[str, Any]:
    """
    Measures real download throughput (in Mbps) through the active VPN proxy using Cloudflare CDN.
    Downloads chunks for up to `duration_sec` seconds and calculates bandwidth.
    """
    import aiohttp
    proxy_url = f"http://127.0.0.1:{proxy_port}"
    # Cloudflare CDN global speed test endpoint (50 MB chunk)
    target_url = "https://speed.cloudflare.com/__down?bytes=50000000"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://speed.cloudflare.com/"
    }

    total_bytes = 0
    start_time = time.monotonic()
    try:
        timeout = aiohttp.ClientTimeout(total=duration_sec + 2.5, sock_connect=3.0)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(target_url, proxy=proxy_url) as resp:
                if resp.status != 200:
                    return {"success": False, "error": f"HTTP {resp.status}"}
                while True:
                    chunk = await resp.content.read(65536)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    elapsed = time.monotonic() - start_time
                    if elapsed >= duration_sec:
                        break

        elapsed = max(0.2, time.monotonic() - start_time)
        mbps = (total_bytes * 8) / (elapsed * 1_000_000)
        return {
            "success": True,
            "speed_mbps": round(mbps, 1),
            "bytes": total_bytes,
            "duration": round(elapsed, 2)
        }
    except Exception as exc:
        elapsed = max(0.2, time.monotonic() - start_time)
        if total_bytes > 200000:
            mbps = (total_bytes * 8) / (elapsed * 1_000_000)
            return {
                "success": True,
                "speed_mbps": round(mbps, 1),
                "bytes": total_bytes,
                "duration": round(elapsed, 2)
            }
        return {"success": False, "error": str(exc)}

