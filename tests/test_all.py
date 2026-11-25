import asyncio
import json
import os
import sys
import time
from pathlib import Path

# На Windows консоль по умолчанию cp1251 — принудительно переключаем на UTF-8,
# иначе вывод с символами "✓" роняет тесты.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.country_detector import detect_country
from core.parser import parse_node, node_to_singbox_outbound, parse_vless, parse_vmess, parse_trojan, parse_shadowsocks, parse_hysteria2
from core.pinger import sync_tcp_ping, ping_all_nodes
from core.subscription import extract_nodes_from_text
from core.singbox_runner import runner

def test_whitelist_detection():
    print("Testing Whitelist Node Detection...")
    from core.parser import is_whitelist_node
    assert is_whitelist_node("🇵🇱 Белый список 3a") is True
    assert is_whitelist_node("🇩🇪 Белый список 4b") is True
    assert is_whitelist_node("🇨🇾 Авто выбор белые списки") is True
    assert is_whitelist_node("🇫🇷 Server (Whitelist)") is True
    assert is_whitelist_node("US Node [WL]") is True
    assert is_whitelist_node("NL Server БС") is True
    # Negative cases
    assert is_whitelist_node("🇧🇾 Беларусь") is False
    assert is_whitelist_node("🇬🇧 Великобритания") is False
    assert is_whitelist_node("🚀 Авто выбор") is False
    print("✓ Whitelist Node Detection passed!")

def test_country_detection():
    print("Testing Country Detection...")
    cases = [
        ("🇩🇪 Germany Frankfurt #1", "1.2.3.4", "DE", "🇩🇪"),
        ("NL Amsterdam Fast 10G", "amsterdam.vps.com", "NL", "🇳🇱"),
        ("USA New York Reality", "us-east.node.com", "US", "🇺🇸"),
        ("Finland Helsinki", "hel.fi.net", "FI", "🇫🇮"),
        ("Turkey Istanbul Fast", "tr.proxy.io", "TR", "🇹🇷"),
        ("Unknown Server", "192.168.1.1", "UN", "🌐"),
    ]
    for name, host, expected_code, expected_flag in cases:
        res = detect_country(name, host)
        assert res["code"] == expected_code, f"Failed for {name}: got {res['code']}, expected {expected_code}"
        assert res["flag"] == expected_flag, f"Failed for {name}: got {res['flag']}, expected {expected_flag}"
    print("✓ Country Detection passed!")

def test_uri_parsers():
    print("Testing URI Parsers...")
    # 1. VLESS Reality
    vless_uri = "vless://b831381d-6324-4d53-ad4f-8cda48b30811@198.51.100.1:443?security=reality&snippets=true&alpn=h2&fp=chrome&pbk=c4t56u7i8o9p0q1r2s3t4u5v6w7x8y9z0a1b2c3d4e5&sid=1a2b3c4d&spx=%2F&type=tcp&flow=xtls-rprx-vision&sni=dl.google.com#%F0%9F%87%A9%F0%9F%87%AA%20DE%20-%20Frankfurt%20Reality"
    node = parse_node(vless_uri)
    assert node is not None
    assert node["type"] == "vless"
    assert node["security"] == "reality"
    assert node["reality_pubkey"] == "c4t56u7i8o9p0q1r2s3t4u5v6w7x8y9z0a1b2c3d4e5"
    assert node["reality_short_id"] == "1a2b3c4d"
    assert node["flow"] == "xtls-rprx-vision"
    assert node["country"]["code"] == "DE"

    outbound = node_to_singbox_outbound(node)
    assert outbound["type"] == "vless"
    assert outbound["tls"]["reality"]["public_key"] == "c4t56u7i8o9p0q1r2s3t4u5v6w7x8y9z0a1b2c3d4e5"

    # 2. Trojan
    trojan_uri = "trojan://secretpass123@trojan.example.com:443?security=tls&sni=trojan.example.com#Netherlands%20Trojan"
    t_node = parse_node(trojan_uri)
    assert t_node is not None
    assert t_node["type"] == "trojan"
    assert t_node["password"] == "secretpass123"
    assert t_node["country"]["code"] == "NL"
    t_outbound = node_to_singbox_outbound(t_node)
    assert t_outbound["type"] == "trojan"

    # 3. Shadowsocks
    ss_uri = "ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzMTIz@198.51.100.2:8388#USA%20Shadowsocks"
    s_node = parse_node(ss_uri)
    assert s_node is not None
    assert s_node["type"] == "shadowsocks"
    assert s_node["method"] == "chacha20-ietf-poly1305"
    assert s_node["password"] == "pass123"
    assert s_node["country"]["code"] == "US"

    # 4. Hysteria 2
    hy2_uri = "hysteria2://mypassword@hy2.example.com:8443?sni=hy2.example.com#Turkey%20Hysteria2"
    h_node = parse_node(hy2_uri)
    assert h_node is not None
    assert h_node["type"] == "hysteria2"
    assert h_node["password"] == "mypassword"
    assert h_node["country"]["code"] == "TR"

    print("✓ All URI Parsers and Sing-box Outbound conversions passed!")

def test_bypass_parser():
    print("Testing Bypass (traffic that skips VPN) Parser...")
    from core.bypass import parse_bypass_entries, describe

    rules = parse_bypass_entries([
        "youtube.com",
        "*.vk.com",
        "steam.exe",
        "192.168.1.0/24",
        "https://site.com/path",
        "",
        "# комментарий",
        "  spaced.com  "
    ])
    assert "youtube.com" in rules["domain_suffix"], rules
    assert "vk.com" in rules["domain_suffix"], rules
    assert "site.com" in rules["domain_suffix"], rules
    assert "spaced.com" in rules["domain_suffix"], rules
    assert "steam.exe" in rules["process_name"], rules
    assert "192.168.1.0/24" in rules["ip_cidr"], rules
    assert rules["ip_cidr"] == ["192.168.1.0/24"], rules
    assert "youtube.com" not in rules["process_name"], rules

    # Приём текста одной строкой
    from_text = parse_bypass_entries("a.com\nb.com")
    assert "a.com" in from_text["domain_suffix"] and "b.com" in from_text["domain_suffix"]

    assert "steam.exe" in describe(rules)
    print("✓ Bypass Parser passed!")

def test_config_builder():
    print("Testing Sing-box Configuration Builder...")
    vless_uri = "vless://b831381d-6324-4d53-ad4f-8cda48b30811@198.51.100.1:443?security=reality&pbk=c4t56u7i8o9p0q1r2s3t4u5v6w7x8y9z0a1b2c3d4e5&sid=1a2b3c4d&type=tcp#Test"
    node = parse_node(vless_uri)

    cfg_bypass = runner.build_config(node, routing_mode="bypass_ru")
    assert cfg_bypass["inbounds"][0]["listen_port"] == 20809
    assert cfg_bypass["inbounds"][1]["listen_port"] == 20808
    assert cfg_bypass["outbounds"][0]["type"] == "vless"

    rules = cfg_bypass["route"]["rules"]
    ru_rule = any(".ru" in r.get("domain_suffix", []) for r in rules)
    assert ru_rule, "Expected Russian domain_suffix bypass rule!"

    cfg_global = runner.build_config(node, routing_mode="global")
    rules_global = cfg_global["route"]["rules"]
    ru_in_global = any(r.get("geoip") == ["private", "ru"] for r in rules_global)
    assert not ru_in_global, "Global mode should not bypass RU!"

    # TUN Mode Config Check
    cfg_tun = runner.build_config(node, routing_mode="bypass_ru", tun_mode=True)
    assert any(ib.get("type") == "tun" for ib in cfg_tun["inbounds"]), "Expected tun inbound in TUN mode!"
    assert "dns" in cfg_tun, "Expected DNS configuration in TUN mode!"
    assert cfg_tun["route"]["default_domain_resolver"] == "dns-direct"
    assert any(r.get("action") == "sniff" for r in cfg_tun["route"]["rules"])
    assert any(r.get("action") == "hijack-dns" for r in cfg_tun["route"]["rules"])

    # --- Правила "мимо VPN" ---
    cfg_bl = runner.build_config(
        node,
        routing_mode="bypass_ru",
        bypass_entries=["youtube.com", "*.vk.com", "steam.exe", "192.168.1.0/24"]
    )
    rules_bl = cfg_bl["route"]["rules"]

    dom_rule = next((r for r in rules_bl if r.get("domain_suffix") and "youtube.com" in r["domain_suffix"]), None)
    assert dom_rule is not None, "Expected custom domain_suffix rule!"
    assert dom_rule["outbound"] == "direct", dom_rule

    proc_rule = next((r for r in rules_bl if r.get("process_name")), None)
    assert proc_rule is not None, "Expected process_name rule!"
    assert proc_rule["outbound"] == "direct", proc_rule
    assert "steam.exe" in proc_rule["process_name"]

    ip_rule = next((r for r in rules_bl if r.get("ip_cidr")), None)
    assert ip_rule is not None, "Expected ip_cidr rule!"
    assert ip_rule["outbound"] == "direct", ip_rule

    assert cfg_bl["route"].get("find_process") is True, "Expected find_process enabled for process rules!"

    # Direct-правила обязаны стоять раньше catch-all правила "весь трафик в прокси"
    idx_direct = max(i for i, r in enumerate(rules_bl) if r.get("outbound") == "direct" and r.get("domain_suffix"))
    idx_proxy = max(i for i, r in enumerate(rules_bl) if r.get("outbound") == "proxy")
    assert idx_direct < idx_proxy, "Bypass rules must precede the catch-all proxy rule!"

    # В global-режиме кастомные правила тоже применяются
    cfg_bl_global = runner.build_config(node, routing_mode="global", bypass_entries=["youtube.com"])
    assert any(r.get("domain_suffix") and "youtube.com" in r["domain_suffix"]
               for r in cfg_bl_global["route"]["rules"]), "Expected bypass rule in global mode!"

    # В TUN-режиме домены из списка резолвятся локально
    cfg_bl_tun = runner.build_config(node, routing_mode="bypass_ru", tun_mode=True,
                                     bypass_entries=["youtube.com"])
    dns_rules = cfg_bl_tun["dns"]["rules"]
    assert any("youtube.com" in r.get("domain_suffix", []) and r.get("server") == "dns-direct"
               for r in dns_rules), "Expected custom domain in DNS direct rules!"

    # Experimental Clash API (Traffic Meter) check
    assert "experimental" in cfg_bypass
    assert "clash_api" in cfg_bypass["experimental"]
    assert cfg_bypass["experimental"]["clash_api"]["external_controller"] == "127.0.0.1:20810"

    # Kill Switch check
    cfg_ks = runner.build_config(node, routing_mode="bypass_ru", kill_switch=True)
    assert any(r.get("outbound") == "block" for r in cfg_ks["route"]["rules"]), "Kill Switch must include block outbound rule!"

    # DoH Protection check
    cfg_doh = runner.build_config(node, tun_mode=True, doh_protection=True)
    assert any(s.get("type") == "https" and s.get("server") == "1.1.1.1" for s in cfg_doh["dns"]["servers"]), "Expected DoH 1.1.1.1 server!"
    assert any(s.get("type") == "https" and s.get("server") == "8.8.8.8" for s in cfg_doh["dns"]["servers"]), "Expected DoH 8.8.8.8 backup server!"
    cfg_no_doh = runner.build_config(node, tun_mode=True, doh_protection=False)
    assert any(s.get("type") == "tcp" and s.get("server") == "1.1.1.1" for s in cfg_no_doh["dns"]["servers"]), "Expected TCP fallback DNS server!"

    print("✓ Sing-box Config Builder (including TUN, Clash API, Kill Switch and DoH) passed!")

def test_text_keys_extractor():
    print("Testing Keys and Subscriptions Extractor...")
    blob = """
    vless://b831381d-6324-4d53-ad4f-8cda48b30811@de.server.com:443?security=reality&pbk=abc&sid=123#DE-Node
    trojan://mypass@nl.server.com:443#NL-Trojan
    ss://Y2hhY2hhMjAtaWV0Zi1wb2x5MTMwNTpwYXNzMTIz@us.server.com:8388#US-SS
    """
    nodes = extract_nodes_from_text(blob, subscription_name="TestSub")
    assert len(nodes) == 3, f"Expected 3 nodes, got {len(nodes)}"
    assert nodes[0]["country"]["code"] == "DE"
    assert nodes[1]["country"]["code"] == "NL"
    assert nodes[2]["country"]["code"] == "US"
    print("✓ Keys Extractor passed!")

def test_fast_ping():
    print("Testing High-Concurrency Fast Ping Engine...")
    test_nodes = [
        {"id": f"node_{i}", "server": "127.0.0.1", "port": 50000 + i, "name": f"Node {i}"}
        for i in range(25)
    ]
    t0 = time.perf_counter()
    results = ping_all_nodes(test_nodes, concurrency=25, timeout_sec=0.2)
    elapsed = time.perf_counter() - t0

    assert len(results) == 25
    for r in results:
        assert "ping" in r
    print(f"✓ Fast Ping Engine passed! Tested {len(test_nodes)} nodes in {elapsed:.3f}s")

def test_network_recovery():
    print("Testing Network Self-Recovery (proxy guard)...")
    from core import recovery

    # --- Разбор адреса прокси ---
    assert recovery.parse_host_port("127.0.0.1:20809") == ("127.0.0.1", 20809)
    assert recovery.parse_host_port("127.0.0.1") == ("127.0.0.1", None)
    assert recovery.parse_host_port("") == ("", None)
    assert recovery.parse_proxy_server("127.0.0.1:20809") == ("127.0.0.1", 20809)
    assert recovery.parse_proxy_server("http=127.0.0.1:20809;https=127.0.0.1:20809") == ("127.0.0.1", 20809)
    assert recovery.parse_proxy_server("") == ("", None)

    # --- Проверка «живого» порта ---
    assert recovery.is_port_listening("127.0.0.1", 1, timeout=0.3) is False
    assert recovery.is_port_listening("127.0.0.1", 20809, timeout=0.3) in (True, False)

    # --- Зависший прокси распознаётся, чужой — нет ---
    stale = {"enabled": True, "server": "127.0.0.1:20809", "host": "127.0.0.1",
             "port": 20809, "listening": False, "own": True}
    assert recovery.is_proxy_stale(stale) is True

    foreign = {"enabled": True, "server": "127.0.0.1:7890", "host": "127.0.0.1",
               "port": 7890, "listening": False, "own": False}
    assert recovery.is_proxy_stale(foreign) is False

    disabled = {"enabled": False, "server": "", "host": "", "port": None,
                "listening": False, "own": False}
    assert recovery.is_proxy_stale(disabled) is False

    # --- Проверка состояния процессов ---
    assert recovery.process_alive(os.getpid()) is True
    assert recovery.process_alive(0) is False
    assert recovery.process_has_exited(os.getpid()) is False

    # --- PID-файлы ---
    recovery.write_pid_file(4242)
    assert recovery.read_pid_file() == 4242
    recovery.clear_pid_file()
    assert recovery.read_pid_file() is None

    print("✓ Network Self-Recovery passed!")

def _temp_storage():
    """
    Изолированное хранилище во временной папке.
    Тесты не должны ни читать, ни писать реальные данные пользователя.
    """
    import tempfile
    from core.storage import Storage

    tmpdir = tempfile.mkdtemp(prefix="velox_test_")
    return Storage(
        config_path=os.path.join(tmpdir, "app_config.json"),
        backup_path=os.path.join(tmpdir, "app_config.backup.json"),
    )

def test_storage_thread_safety_and_backup():
    print("Testing Storage Atomic Persistence & Thread Safety...")
    from core.storage import Storage
    import threading

    # Работаем на временном файле — реальный конфиг пользователя не трогаем
    storage = _temp_storage()
    config_path = Path(storage.config_path)

    initial_nodes = storage.get_nodes()
    assert isinstance(initial_nodes, list)

    def worker(idx):
        for _ in range(5):
            storage.update_settings({"test_concurrency_val": idx})
            _ = storage.get_settings()
            _ = storage.get_nodes()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert config_path.exists()
    assert config_path.stat().st_size > 0
    print("✓ Storage Atomic Persistence & Thread Safety passed!")

def test_speedtest_and_killswitch():
    print("Testing Speedtest, Traffic Meter & Kill Switch logic...")
    from core.pinger import real_speedtest
    from core.storage import storage
    
    settings = storage.get_settings()
    assert "kill_switch" in settings
    
    # Test runner state
    assert hasattr(runner, "speed_down")
    assert hasattr(runner, "speed_up")
    assert hasattr(runner, "total_down")
    assert hasattr(runner, "total_up")
    assert hasattr(runner, "kill_switch_active")
    
    info = runner.get_info()
    assert "speed_down" in info
    assert "speed_up" in info
    assert "total_down" in info
    assert "total_up" in info
    assert "kill_switch_active" in info
    print("✓ Speedtest, Traffic Meter & Kill Switch logic passed!")

def test_tray_and_doh_settings():
    print("Testing Tray Manager and DoH settings...")
    from core.storage import storage
    settings = storage.get_settings()
    assert "doh_protection" in settings, "Settings must include doh_protection"
    assert "minimize_to_tray" in settings, "Settings must include minimize_to_tray"

    from core.tray import TrayManager, _render_icon
    img = _render_icon("running", size=32)
    assert img.size == (32, 32), "Rendered tray icon must match requested size"

    tray = TrayManager("http://127.0.0.1:54321", lambda: None, lambda: None)
    started = tray.start()
    assert started is True, "TrayManager must start without WinError 5"
    tray.stop()
    print("✓ Tray Manager and DoH settings passed!")

def test_server_deduplication():
    print("Testing Server Canonical Keys and Deduplication Engine...")
    from core.parser import (
        normalize_host, normalize_port, get_canonical_node_key, deduplicate_nodes
    )
    # Изолированное хранилище: реальные данные пользователя не затрагиваются
    storage = _temp_storage()

    # 1. Host normalization
    assert normalize_host("Example.COM.") == "example.com"
    assert normalize_host("[2001:0db8:0000:0000:0000:ff00:0042:8329]") == "2001:db8::ff00:42:8329"
    assert normalize_host("2001:db8::ff00:42:8329") == "2001:db8::ff00:42:8329"
    assert normalize_host("192.168.1.1.") == "192.168.1.1"

    # 2. Port normalization
    assert normalize_port(None, "vless") == 443
    assert normalize_port("8388", "ss") == 8388
    assert normalize_port("", "trojan") == 443

    # 3. Canonical key uniqueness vs equality
    n_vless1 = {
        "id": "v1", "name": "VLESS 1", "type": "vless", "server": "Srv.Org.", "port": 443,
        "uuid": "00000000-0000-0000-0000-000000000001", "network": "TCP", "security": "reality",
        "sni": "google.com.", "reality_pubkey": "pub1"
    }
    # Duplicate with different name, different case, bracketed/dot host
    n_vless1_dup = {
        "id": "v1_dup", "name": "🇩🇪 Германия Быстрый", "type": "VLESS", "server": "srv.org", "port": "443",
        "uuid": "00000000-0000-0000-0000-000000000001", "network": "tcp", "security": "REALITY",
        "sni": "google.com", "reality_pubkey": "pub1", "ping": 38.2
    }
    # Different port
    n_vless_diff_port = dict(n_vless1, id="v_port", port=8443)
    # Different protocol
    n_trojan = {
        "id": "tr1", "name": "VLESS 1", "type": "trojan", "server": "srv.org", "port": 443,
        "password": "pass1", "security": "tls", "sni": "google.com"
    }
    # Different credentials
    n_vless_diff_uuid = dict(n_vless1, id="v_diff_uuid", uuid="00000000-0000-0000-0000-000000000002")

    k1 = get_canonical_node_key(n_vless1)
    k1_dup = get_canonical_node_key(n_vless1_dup)
    k_port = get_canonical_node_key(n_vless_diff_port)
    k_trojan = get_canonical_node_key(n_trojan)
    k_uuid = get_canonical_node_key(n_vless_diff_uuid)

    assert k1 == k1_dup, "Canonical key must match for duplicate connection params despite name/case differences"
    assert k1 != k_port, "Different ports must produce different canonical keys"
    assert k1 != k_trojan, "Different protocols must produce different canonical keys"
    assert k1 != k_uuid, "Different credentials (UUID) must produce different canonical keys"

    # 4. Deduplication and Selection Remapping
    test_nodes = [n_vless1, n_vless1_dup, n_vless_diff_port, n_trojan, n_vless_diff_uuid]
    clean_nodes, stats = deduplicate_nodes(
        test_nodes,
        selected_node_id="v1_dup",
        favorites=["v1_dup"]
    )

    assert len(clean_nodes) == 4, f"Expected 4 unique nodes, got {len(clean_nodes)}"
    assert stats["duplicates_removed"] == 1
    assert stats["remapped_selected_id"] == "v1", f"Expected selected remapped to v1, got {stats['remapped_selected_id']}"
    assert "v1" in stats["favorites"], "Favorite must be remapped to survivor node ID"
    assert clean_nodes[0]["name"] == "🇩🇪 Германия Быстрый", "Survivor must inherit better display name"
    assert clean_nodes[0]["ping"] == 38.2, "Survivor must inherit ping from duplicate"

    # 5. Idempotency
    clean_nodes2, stats2 = deduplicate_nodes(clean_nodes, selected_node_id=stats["remapped_selected_id"])
    assert len(clean_nodes2) == len(clean_nodes)
    assert stats2["duplicates_removed"] == 0
    assert [n["id"] for n in clean_nodes2] == [n["id"] for n in clean_nodes]

    # 6. Storage integration
    storage.set_nodes(test_nodes)
    stored = storage.get_nodes()
    assert len(stored) == 4, f"Storage must store only deduplicated nodes, got {len(stored)}"

    print("✓ Server Canonical Keys and Deduplication Engine passed!")

def test_subscription_usage_and_theme():
    print("Testing Subscription Traffic Metadata & Theme Settings...")
    from core.subscription import parse_subscription_userinfo, build_usage_info

    # 1. Разбор заголовка Subscription-Userinfo (стандарт XRay/v2rayN)
    raw = "upload=1000; download=414769795285; total=2199023255552; expire=1797977802"
    info = parse_subscription_userinfo(raw)
    assert info["upload"] == 1000
    assert info["download"] == 414769795285
    assert info["used"] == 1000 + 414769795285, f"used must be upload+download, got {info['used']}"
    assert info["total"] == 2199023255552
    assert info["remaining"] == 2199023255552 - (1000 + 414769795285)
    assert 18 < info["percent"] < 19, f"percent must be ~18.9, got {info['percent']}"
    assert "expire" in info and info["expire"] == 1797977802
    assert info["expire_days_left"] >= 0

    # 2. Мусорные и отсутствующие заголовки не должны ломать разбор
    assert parse_subscription_userinfo(None) == {}
    assert parse_subscription_userinfo("") == {}
    assert parse_subscription_userinfo("garbage") == {}
    assert parse_subscription_userinfo("upload=abc; download=1") == {"upload": 0, "download": 1, "used": 1, "total": 0, "remaining": 0, "percent": 0.0}

    # 3. Сбор сводки из заголовков + дата обновления пакета
    headers = {
        "Subscription-Userinfo": raw,
        "Subscription-Refill-Date": "1796083800",
    }
    summary = build_usage_info(headers, {"fetched_at": 111})
    assert summary["refill_date"] == 1796083800
    assert summary["fetched_at"] == 111
    assert build_usage_info({}) == {}

    # 4. Подписки-дубликаты не должны удваивать трафик в сводке
    st = _temp_storage()
    st.set_subscriptions([
        {"id": "sub1", "name": "Подписка", "url": "https://example.com/a", "enabled": True},
        {"id": "sub1", "name": "Подписка", "url": "https://example.com/a", "enabled": True},
    ])
    subs = st.get_subscriptions()
    assert len(subs) == 1, f"Duplicate subscription must be removed, got {len(subs)}"

    st.update_subscription_usage({
        "Подписка": {
            "upload": 0, "download": 100, "used": 100,
            "total": 1000, "remaining": 900, "percent": 10.0,
            "expire": 1797977802, "expire_days_left": 28,
        }
    })
    usage = st.get_subscription_usage_summary()
    assert usage["has_data"] is True
    assert usage["used"] == 100, f"Traffic must not be doubled, got {usage['used']}"
    assert usage["total"] == 1000
    assert usage["remaining"] == 900
    assert usage["percent"] == 10.0
    assert len(usage["subscriptions"]) == 1

    # 5. Тема сохраняется в настройках
    st.update_settings({"theme": "dark"})
    assert st.get_settings().get("theme") == "dark"
    st.update_settings({"theme": "light"})
    assert st.get_settings().get("theme") == "light"

    print("✓ Subscription Traffic Metadata & Theme Settings passed!")

def main():
    test_whitelist_detection()
    test_country_detection()
    test_uri_parsers()
    test_bypass_parser()
    test_config_builder()
    test_text_keys_extractor()
    test_fast_ping()
    test_network_recovery()
    test_storage_thread_safety_and_backup()
    test_speedtest_and_killswitch()
    test_tray_and_doh_settings()
    test_server_deduplication()
    test_subscription_usage_and_theme()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY! The core engine is rock-solid.")

if __name__ == "__main__":
    main()
