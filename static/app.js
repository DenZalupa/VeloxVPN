// VeloxVPN Frontend Application Logic

let nodes = [];
let subscriptions = [];
let favorites = new Set();
let currentStatus = {
    status: "stopped",
    active_node: null,
    routing_mode: "bypass_ru",
    has_core: false,
    system_proxy_enabled: false
};
let activeCategory = "regular"; // "regular" | "whitelist" | "all"
let activeFilter = "all";
let searchQuery = "";
let currentSort = "ping";
let ws = null;
let uptimeInterval = null;
let realDelayInterval = null;

// Regex for whitelist detection in node names
const WHITELIST_REGEX = /(?:бел(?:ый|ые|ых|ого|ом|ому)?\s*список|белые\s*списки|whitelist|white\s*list|\bбс\b|\bwl\b)/i;

function isNodeWhitelist(node) {
    if (node && typeof node.is_whitelist === "boolean") {
        return node.is_whitelist;
    }
    const name = (node && node.name) || "";
    return WHITELIST_REGEX.test(name);
}

// DOM Elements
const serverGrid = document.getElementById("serverGrid");
const emptyState = document.getElementById("emptyState");
const btnToggleConnect = document.getElementById("btnToggleConnect");
const connStateText = document.getElementById("connStateText");
const connTargetText = document.getElementById("connTargetText");
const connUptime = document.getElementById("connUptime");
const connRealDelay = document.getElementById("connRealDelay");
const coreStatusPill = document.getElementById("coreStatusPill");
const coreStatusText = document.getElementById("coreStatusText");
const proxyStatusBadge = document.getElementById("proxyStatusBadge");
const proxyStatusText = document.getElementById("proxyStatusText");
const btnPingAll = document.getElementById("btnPingAll");
const btnUpdateAllSubs = document.getElementById("btnUpdateAllSubs");
const pingSummaryPill = document.getElementById("pingSummaryPill");
const pingSummaryText = document.getElementById("pingSummaryText");
const searchInput = document.getElementById("searchInput");
const sortDropdown = document.getElementById("sortDropdown");
const sortTriggerBtn = document.getElementById("sortTriggerBtn");
const sortSelectedLabel = document.getElementById("sortSelectedLabel");

// TUN Mode Elements
const chkTunMode = document.getElementById("chkTunMode");
const tunStatusPill = document.getElementById("tunStatusPill");
const tunStatusText = document.getElementById("tunStatusText");
const tunCardSub = document.getElementById("tunCardSub");
const adminWarnBar = document.getElementById("adminWarnBar");
const btnElevateAdmin = document.getElementById("btnElevateAdmin");
const cfgWintunStatus = document.getElementById("cfgWintunStatus");
const cfgAdminStatus = document.getElementById("cfgAdminStatus");
const rowInstallWintun = document.getElementById("rowInstallWintun");
const btnDownloadWintun = document.getElementById("btnDownloadWintun");
const btnRepairNetwork = document.getElementById("btnRepairNetwork");
const btnRepairNetworkSettings = document.getElementById("btnRepairNetworkSettings");
const cfgProxyState = document.getElementById("cfgProxyState");
const cfgGuardianState = document.getElementById("cfgGuardianState");

// Live Speed, Speedtest & Kill Switch Elements
const heroMetricsDeck = document.getElementById("heroMetricsDeck");
const speedDownVal = document.getElementById("speedDownVal");
const speedUpVal = document.getElementById("speedUpVal");
const totalVal = document.getElementById("totalVal");
const btnSpeedtest = document.getElementById("btnSpeedtest");
const speedtestResult = document.getElementById("speedtestResult");
const speedtestVal = document.getElementById("speedtestVal");
const cfgKillSwitch = document.getElementById("cfgKillSwitch");
const cfgDohProtection = document.getElementById("cfgDohProtection");
const cfgMinimizeToTray = document.getElementById("cfgMinimizeToTray");

// Главный экран: кнопка подключения и окно списка серверов
const btnToggleConnectHint = document.getElementById("btnToggleConnectHint");
const serversModal = document.getElementById("serversModal");
const btnOpenServers = document.getElementById("btnOpenServers");
const btnCloseServers = document.getElementById("btnCloseServers");
const cfgServerCount = document.getElementById("cfgServerCount");
const cfgDedupCount = document.getElementById("cfgDedupCount");
const pingSummaryPillServers = document.getElementById("pingSummaryPillServers");
const pingSummaryTextServers = document.getElementById("pingSummaryTextServers");

// Сводка по подписке на главном экране (трафик + срок действия)
const subUsageCard = document.getElementById("subUsageCard");
const subUsageName = document.getElementById("subUsageName");
const subUsageExpire = document.getElementById("subUsageExpire");
const subUsageBar = document.getElementById("subUsageBar");
const subUsageFill = document.getElementById("subUsageFill");
const subUsageUsed = document.getElementById("subUsageUsed");
const subUsageLeft = document.getElementById("subUsageLeft");
const subUsagePercent = document.getElementById("subUsagePercent");

// Переключатель темы
const btnToggleTheme = document.getElementById("btnToggleTheme");
const THEME_STORAGE_KEY = "velox.theme";

/**
 * Состояния главной кнопки. Один и тот же набор текстов для всех состояний —
 * чтобы при смене статуса не «прыгал» layout.
 */
const CONNECT_STATES = {
    disconnected: {
        label: "Отключено",
        hint: "Нажмите, чтобы подключиться",
        aria: "Подключиться к VPN"
    },
    connecting: {
        label: "Подключение…",
        hint: "Устанавливаем соединение с VPN",
        aria: "Подключение к VPN"
    },
    connected: {
        label: "Подключено",
        hint: "Нажмите, чтобы отключиться",
        aria: "Отключиться от VPN"
    },
    error: {
        label: "Ошибка",
        hint: "Нажмите, чтобы повторить подключение",
        aria: "Повторить подключение к VPN"
    }
};

/**
 * Человекочитаемый текст ошибки замера скорости.
 * Технический текст с сервера (таймаут к CDN) переводим в понятную форму,
 * но исходную причину не теряем — она помогает понять, что именно сломалось.
 */
function speedtestErrorText(rawError) {
    const text = (rawError || "").trim();
    if (!text) return "Ошибка замера скорости";
    if (/timeout|timed out/i.test(text)) {
        return "Замер не удался: сервер замера (Cloudflare) не ответил вовремя";
    }
    if (/connection|refused|reset/i.test(text)) {
        return "Замер не удался: нет связи с сервером замера";
    }
    return "Ошибка замера скорости: " + text;
}

function formatSpeed(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec <= 0) return "0.0 КБ/с";
    if (bytesPerSec >= 1024 * 1024) {
        return (bytesPerSec / (1024 * 1024)).toFixed(1) + " МБ/с";
    }
    return (bytesPerSec / 1024).toFixed(0) + " КБ/с";
}

function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return "0 МБ";
    if (bytes >= 1024 * 1024 * 1024) {
        return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " ГБ";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " МБ";
}

/**
 * Убирает ведущий эмодзи-флаг из названия сервера.
 *
 * Название вроде «🇫🇷 Франция» уже содержит флаг, поэтому если рядом
 * рисуется SVG-флаг, он дублировался бы. Региональные индикаторы —
 * это пары символов U+1F1E6–U+1F1FF.
 */
function stripFlagEmoji(name) {
    const text = String(name || "");
    return text.replace(/^[\u{1F1E6}-\u{1F1FF}]{2}\s*/u, "").trim();
}

/**
 * Форматирует объём трафика в привычные единицы (ГБ/МБ).
 * Значения приходят с сервера в байтах.
 */
function formatTraffic(bytes) {
    const value = Number(bytes) || 0;
    if (value <= 0) return "0 МБ";
    if (value >= 1024 * 1024 * 1024) {
        return (value / (1024 * 1024 * 1024)).toFixed(2) + " ГБ";
    }
    if (value >= 1024 * 1024) {
        return (value / (1024 * 1024)).toFixed(1) + " МБ";
    }
    return Math.round(value / 1024) + " КБ";
}

/**
 * Форматирует unix-время в дату «ДД.ММ.ГГГГ».
 */
function formatExpiry(unixSeconds) {
    if (!unixSeconds) return "";
    const d = new Date(Number(unixSeconds) * 1000);
    if (isNaN(d.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

// ============================================================
// ТЁМНАЯ / СВЕТЛАЯ ТЕМА
// Выбор хранится в localStorage (мгновенное применение при старте)
// и дублируется в настройках приложения — чтобы тема была
// общей для всех окон и сохранялась между запусками.
// ============================================================

/** Применяет тему к документу. */
function applyTheme(theme) {
    const isDark = theme === "dark";
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
    if (btnToggleTheme) {
        btnToggleTheme.setAttribute("aria-label", isDark ? "Включить светлую тему" : "Включить тёмную тему");
        btnToggleTheme.setAttribute("title", isDark ? "Светлая тема" : "Тёмная тема");
    }
}

/** Текущая выбранная тема. */
function getCurrentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/** Восстанавливает тему из localStorage при загрузке страницы. */
function restoreTheme() {
    let theme = "light";
    try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === "dark" || saved === "light") theme = saved;
    } catch (e) {
        // localStorage может быть недоступен — тогда остаётся светлая тема
    }
    applyTheme(theme);
}

/** Переключает тему и сохраняет выбор. */
function toggleTheme() {
    const next = getCurrentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
        localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch (e) {
        // не критично: тема всё равно применилась
    }
    saveSettings({ theme: next });
}

// ============================================================
// СВОДКА ПО ПОДПИСКЕ (главный экран)
// Данные приходят из /api/status → subscription.
// Показываем только то, что реально знает провайдер: никаких
// выдуманных цифр — если данных нет, карточка скрыта.
// ============================================================

/**
 * Обновляет карточку сводки по подписке.
 * usage — объект {has_data, used, total, remaining, percent, expire, ...}.
 */
function updateSubscriptionUsage(usage) {
    if (!subUsageCard) return;
    if (!usage || !usage.has_data || !usage.total) {
        subUsageCard.hidden = true;
        return;
    }

    const subs = Array.isArray(usage.subscriptions) ? usage.subscriptions : [];
    // Если подписок несколько — показываем сумму и имя первой,
    // чтобы строка оставалась компактной.
    const title = subs.length === 1
        ? subs[0].name
        : `Подписки (${subs.length})`;

    const percent = Math.max(0, Math.min(100, Number(usage.percent) || 0));

    if (subUsageName) subUsageName.textContent = title;

    if (subUsageExpire) {
        const expireText = formatExpiry(usage.expire);
        if (expireText) {
            const days = usage.expire_days_left;
            subUsageExpire.textContent = days !== undefined && days !== null
                ? `до ${expireText} · ${days} дн.`
                : `до ${expireText}`;
        } else {
            subUsageExpire.textContent = "";
        }
    }

    if (subUsageFill) {
        subUsageFill.style.width = percent + "%";
        subUsageFill.classList.remove("is-warn", "is-danger");
        if (percent >= 90) subUsageFill.classList.add("is-danger");
        else if (percent >= 70) subUsageFill.classList.add("is-warn");
    }

    if (subUsageBar) {
        subUsageBar.setAttribute("aria-valuenow", String(Math.round(percent)));
        subUsageBar.setAttribute("aria-valuetext",
            `Израсходовано ${formatTraffic(usage.used)} из ${formatTraffic(usage.total)}`);
    }

    if (subUsageUsed) subUsageUsed.textContent = `Израсходовано ${formatTraffic(usage.used)}`;
    if (subUsageLeft) subUsageLeft.textContent = `Осталось ${formatTraffic(usage.remaining)}`;
    if (subUsagePercent) subUsagePercent.textContent = `${percent.toFixed(1)}% пакета`;

    subUsageCard.hidden = false;
}

// Modals
const subsModal = document.getElementById("subsModal");
const settingsModal = document.getElementById("settingsModal");
const btnOpenSubs = document.getElementById("btnOpenSubs");
const btnCloseSubs = document.getElementById("btnCloseSubs");
const btnOpenSettings = document.getElementById("btnOpenSettings");
const btnCloseSettings = document.getElementById("btnCloseSettings");
const btnEmptyAdd = document.getElementById("btnEmptyAdd");

// --- Initialization ---
document.addEventListener("DOMContentLoaded", () => {
    restoreTheme();
    initWebSocket();
    loadStatus();
    loadFavorites();
    loadNodes();
    loadSubscriptions();
    loadSettings();
    setupEventListeners();
});

// --- WebSocket Setup ---
function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWsEvent(msg.type, msg.data);
        } catch (e) {
            console.error("WS Parse error", e);
        }
    };

    ws.onclose = () => {
        setTimeout(initWebSocket, 2000); // Auto reconnect
    };
}

function handleWsEvent(type, data) {
    if (type === "node_pinged") {
        const target = nodes.find(n => n.id === data.id);
        if (target) {
            target.ping = data.ping;
            target.last_ping_time = data.last_ping_time;
            updateNodeCardPing(data.id, data.ping);
            updateFilterCounts();
        }
    } else if (type === "network_repaired") {
        showToast("Сетевые настройки сброшены — интернет восстановлен!");
        loadStatus();
        renderServerGrid();
    } else if (type === "ping_all_finished") {
        setPingAllLoading(false);
        nodes = data.nodes;
        showToast(`Проверено ${data.count} серверов за ${data.duration} сек!`);
        // Итог теста пинга — и в плитке главного экрана, и в окне серверов
        const summary = `${data.count} узлов за ${data.duration}с`;
        if (pingSummaryText) pingSummaryText.textContent = summary;
        if (pingSummaryTextServers) pingSummaryTextServers.textContent = summary;
        if (pingSummaryPillServers) pingSummaryPillServers.style.display = "inline-flex";
        updateFilterCounts();
        renderServerGrid();
    } else if (type === "connection_changed") {
        currentStatus = data;
        updateConnectionUI();
        renderServerGrid();
    } else if (type === "subs_update_started") {
        setSubsLoading(true);
    } else if (type === "subs_update_finished") {
        setSubsLoading(false);
        showToast(`Обновлено узлов: ${data.nodes_count}` + dedupToastSuffix(data.duplicates_removed));
        loadNodes();
        loadSubscriptions();
    } else if (type === "nodes_imported") {
        showToast(`Добавлено новых узлов: ${data.added}` + dedupToastSuffix(data.duplicates_removed));
        loadNodes();
    } else if (type === "core_download_finished") {
        document.getElementById("coreDownloadProgress").style.display = "none";
        loadStatus();
        if (data.success) {
            showToast("Ядро sing-box успешно установлено!");
        } else {
            showToast("Не удалось скачать ядро sing-box");
        }
    } else if (type === "wintun_download_finished") {
        loadStatus();
        if (data.success) {
            showToast("Драйвер Wintun успешно установлен!");
        } else {
            showToast("Не удалось скачать драйвер Wintun");
        }
    } else if (type === "traffic_update") {
        if (speedDownVal && speedUpVal) {
            speedDownVal.textContent = formatSpeed(data.speed_down);
            speedUpVal.textContent = formatSpeed(data.speed_up);
        }
        if (totalVal) {
            const sumBytes = (data.total_down || 0) + (data.total_up || 0);
            totalVal.textContent = formatBytes(sumBytes);
        }
    } else if (type === "kill_switch_triggered") {
        showToast("🛡️ Kill Switch: интернет заблокирован во избежание утечки реального IP!", "warning");
    }
}

// --- API Calls ---
/**
 * Аккуратное дополнение к уведомлению о дубликатах.
 * Показываем только когда реально что-то исключили — без спама.
 */
function dedupToastSuffix(removed) {
    const n = Number(removed || 0);
    if (!n) return "";
    const word = (n % 10 === 1 && n % 100 !== 11) ? "дубликат"
        : ((n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20)) ? "дубликата" : "дубликатов");
    return ` · исключено ${n} ${word}`;
}

async function loadStatus() {
    try {
        const res = await fetch("/api/status");
        currentStatus = await res.json();
        updateConnectionUI();
        updateCoreUI();
        // Сводка по подписке (трафик + срок) на главном экране
        updateSubscriptionUsage(currentStatus.subscription);
    } catch (e) {
        console.error("Failed to load status", e);
    }
}

async function loadFavorites() {
    try {
        const res = await fetch("/api/favorites");
        const data = await res.json();
        favorites = new Set(data.favorites || []);
        updateFilterCounts();
        // Избранное влияет на выбор сервера главной кнопки
        updateConnectionUI();
    } catch (e) {
        console.error("Failed to load favorites", e);
    }
}

async function toggleFavorite(nodeId, event) {
    if (event) event.stopPropagation();
    try {
        const res = await fetch("/api/favorites/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: nodeId })
        });
        const data = await res.json();
        if (data.is_favorite) {
            favorites.add(nodeId);
            showToast("Добавлено в избранное");
        } else {
            favorites.delete(nodeId);
            showToast("Удалено из избранного");
        }
        updateFilterCounts();
        renderServerGrid();
    } catch (e) {
        showToast("Ошибка сохранения избранного");
    }
}

async function loadNodes() {
    try {
        const res = await fetch("/api/nodes");
        const data = await res.json();
        nodes = data.nodes || [];
        updateFilterCounts();
        renderServerGrid();
        // Подпись под кнопкой («Подключиться к: …») зависит от списка серверов
        updateConnectionUI();
    } catch (e) {
        console.error("Failed to load nodes", e);
    }
}

async function loadSubscriptions() {
    try {
        const res = await fetch("/api/subscriptions");
        const data = await res.json();
        subscriptions = data.subscriptions || [];
        renderSubsList();
    } catch (e) {
        console.error("Failed to load subs", e);
    }
}

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        document.getElementById("cfgTimeout").value = data.ping_timeout || 1.2;
        document.getElementById("cfgConcurrency").value = data.ping_concurrency || 80;
        document.getElementById("cfgSysProxy").checked = data.system_proxy !== false;
        if (cfgKillSwitch) cfgKillSwitch.checked = !!data.kill_switch;
        if (cfgDohProtection) cfgDohProtection.checked = data.doh_protection !== false;
        if (cfgMinimizeToTray) cfgMinimizeToTray.checked = data.minimize_to_tray !== false;

        const bypassList = Array.isArray(data.bypass_list) ? data.bypass_list : [];
        const bypassBox = document.getElementById("cfgBypassList");
        if (bypassBox) bypassBox.value = bypassList.join("\n");
        updateBypassIndicators(bypassList.length);

        // Тема из настроек сервера — на случай, если localStorage недоступен
        // или очищен. Приоритет у localStorage: он применяется мгновенно.
        let storedTheme = null;
        try {
            storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
        } catch (e) {
            storedTheme = null;
        }
        if (!storedTheme && (data.theme === "dark" || data.theme === "light")) {
            applyTheme(data.theme);
        }
    } catch (e) {
        console.error("Failed to load settings", e);
    }
}

// --- Bypass list (traffic that skips the VPN) ---
function updateBypassIndicators(count) {
    const badge = document.getElementById("bypassCountBadge");
    if (badge) badge.textContent = count;

    const pill = document.getElementById("bypassPill");
    const pillText = document.getElementById("bypassPillText");
    if (pill && pillText) {
        pill.style.display = count > 0 ? "inline-flex" : "none";
        pillText.textContent = `Мимо VPN: ${count}`;
    }
}

function readBypassBox() {
    const box = document.getElementById("cfgBypassList");
    if (!box) return [];
    return box.value
        .split("\n")
        .map(line => line.trim())
        .filter(line => line.length > 0 && !line.startsWith("#"));
}

async function saveBypassList(silent) {
    const entries = readBypassBox();

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ bypass_list: entries })
        });
        if (!res.ok) throw new Error("bad response");

        updateBypassIndicators(entries.length);
        if (!silent) {
            showToast(entries.length
                ? `Сохранено правил мимо VPN: ${entries.length}`
                : "Список очищен — весь трафик по правилам режима");
        }

        // Переподключаем, чтобы новые правила вступили в силу
        if (currentStatus.status === "running" && currentStatus.active_node) {
            if (!silent) showToast("Переподключение с новыми правилами...");
            await selectAndConnect(currentStatus.active_node.id);
        }
    } catch (e) {
        console.error("Failed to save bypass list", e);
        showToast("Ошибка сохранения списка");
    }
}

function addBypassPreset(value) {
    const box = document.getElementById("cfgBypassList");
    if (!box) return;
    const existing = readBypassBox();
    if (!existing.includes(value)) {
        existing.push(value);
        box.value = existing.join("\n");
    }
    saveBypassList(false);
}

// --- UI Rendering ---
function renderServerGrid() {
    const filtered = getFilteredAndSortedNodes();
    serverGrid.innerHTML = "";

    if (filtered.length === 0) {
        serverGrid.style.display = "none";
        emptyState.style.display = "flex";
        if (activeFilter === "favorites") {
            emptyState.querySelector(".empty-title").textContent = "В избранном пока пусто";
            emptyState.querySelector(".empty-desc").textContent = "Нажмите на звезду на любой карточке сервера, чтобы добавить его сюда";
            btnEmptyAdd.style.display = "none";
        } else if (activeCategory === "whitelist" && nodes.filter(n => isNodeWhitelist(n)).length === 0) {
            emptyState.querySelector(".empty-title").textContent = "Серверы для белых списков не найдены";
            emptyState.querySelector(".empty-desc").textContent = "В подписке нет серверов с пометкой 'Белый список' или 'Whitelist'";
            btnEmptyAdd.style.display = "inline-flex";
        } else if (activeCategory === "regular" && nodes.filter(n => !isNodeWhitelist(n)).length === 0) {
            emptyState.querySelector(".empty-title").textContent = "Обычные серверы не найдены";
            emptyState.querySelector(".empty-desc").textContent = "Все доступные серверы относятся к обходу белых списков";
            btnEmptyAdd.style.display = "inline-flex";
        } else {
            emptyState.querySelector(".empty-title").textContent = "Узлы не найдены";
            emptyState.querySelector(".empty-desc").textContent = "Добавьте подписку или вставьте ключи vless / vmess / trojan / ss";
            btnEmptyAdd.style.display = "inline-flex";
        }
        return;
    }

    serverGrid.style.display = "grid";
    emptyState.style.display = "none";

    const isConnected = currentStatus.status === "running";
    const activeId = currentStatus.active_node ? currentStatus.active_node.id : null;

    filtered.forEach(node => {
        const isWhitelist = isNodeWhitelist(node);
        const card = document.createElement("div");
        const isCurrentActive = isConnected && (node.id === activeId);
        card.className = `server-card ${isCurrentActive ? 'active-connected' : ''} ${isWhitelist ? 'whitelist-card' : ''}`;
        card.dataset.id = node.id;

        // Ping badge config
        const pingVal = node.ping;
        let pingClass = "none";
        let pingText = "---";
        if (pingVal !== null && pingVal !== undefined) {
            if (pingVal > 0) {
                pingText = `${pingVal} ms`;
                if (pingVal < 120) pingClass = "fast";
                else if (pingVal < 250) pingClass = "medium";
                else pingClass = "slow";
            } else {
                pingText = "Таймаут";
                pingClass = "slow";
            }
        }

        const countryCode = node.country ? node.country.code : "UN";
        const countryName = node.country ? node.country.name : "Сервер";
        const flagHtml = typeof getCountryFlagHtml === "function" ? 
            getCountryFlagHtml(countryCode, node.country ? node.country.flag : "🌐") : 
            `<span class="country-flag">${node.country ? node.country.flag : "🌐"}</span>`;

        const protocolUpper = (node.type || "vpn").toUpperCase();
        const secTag = node.security === "reality" ? " Reality" : "";
        const isFav = favorites.has(node.id);

        card.innerHTML = `
            <div class="card-header-row">
                <div class="card-country-info">
                    ${flagHtml}
                    <div class="country-title-box">
                        <span class="server-name" title="${escapeHtml(node.name)}">${escapeHtml(stripFlagEmoji(node.name))}</span>
                        <span class="country-name">${escapeHtml(countryName)}</span>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <button class="btn-star ${isFav ? 'starred' : ''}" title="${isFav ? 'Удалить из избранного' : 'Добавить в избранное'}" onclick="toggleFavorite('${node.id}', event)">
                        <svg width="17" height="17" viewBox="0 0 24 24" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                    </button>
                    <div class="ping-badge ${pingClass}" id="ping-badge-${node.id}">
                        <span class="ping-text">${pingText}</span>
                    </div>
                </div>
            </div>

            <div class="card-footer-row">
                <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                    <span class="protocol-tag">${protocolUpper}${secTag}</span>
                    ${isWhitelist ? `
                        <span class="tag-whitelist" title="Сервер оптимизирован для обхода белых списков">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
                            Белый список
                        </span>
                    ` : ''}
                </div>
                <div class="card-actions">
                    <button class="action-icon-btn" title="Проверить пинг узла" onclick="pingSingleNode('${node.id}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    </button>
                    <button class="action-icon-btn" title="Копировать ссылку" onclick="copyNodeUri('${node.id}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    </button>
                    <button class="action-icon-btn" title="Удалить узел" onclick="deleteNode('${node.id}', event)">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                    <button class="btn btn-sm ${isCurrentActive ? 'btn-secondary' : 'btn-primary'}" onclick="selectAndConnect('${node.id}', event)">
                        ${isCurrentActive ? 'Активен' : 'Подключить'}
                    </button>
                </div>
            </div>
        `;

        card.addEventListener("click", () => {
            selectAndConnect(node.id);
        });

        serverGrid.appendChild(card);
    });
}

function updateNodeCardPing(nodeId, ping) {
    const badge = document.getElementById(`ping-badge-${nodeId}`);
    if (!badge) return;

    badge.className = "ping-badge";
    if (ping > 0) {
        badge.innerHTML = `<span class="ping-text">${ping} ms</span>`;
        if (ping < 120) badge.classList.add("fast");
        else if (ping < 250) badge.classList.add("medium");
        else badge.classList.add("slow");
    } else {
        badge.innerHTML = `<span class="ping-text">Таймаут</span>`;
        badge.classList.add("slow");
    }
}

function getFilteredAndSortedNodes() {
    let result = [...nodes];

    // Filter by category: regular / whitelist / all
    if (activeCategory === "regular") {
        result = result.filter(n => !isNodeWhitelist(n));
    } else if (activeCategory === "whitelist") {
        result = result.filter(n => isNodeWhitelist(n));
    }

    // Filter by search
    if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        result = result.filter(n => 
            (n.name && n.name.toLowerCase().includes(q)) ||
            (n.country && n.country.name && n.country.name.toLowerCase().includes(q)) ||
            (n.server && n.server.toLowerCase().includes(q))
        );
    }

    // Filter by favorites / protocol / alive
    if (activeFilter === "favorites") {
        result = result.filter(n => favorites.has(n.id));
    } else if (activeFilter === "alive") {
        result = result.filter(n => n.ping && n.ping > 0);
    } else if (activeFilter !== "all") {
        result = result.filter(n => n.type === activeFilter);
    }

    // Sorting
    result.sort((a, b) => {
        if (currentSort === "ping") {
            const pA = (a.ping && a.ping > 0) ? a.ping : 999999;
            const pB = (b.ping && b.ping > 0) ? b.ping : 999999;
            return pA - pB;
        } else if (currentSort === "country") {
            const cA = (a.country ? a.country.name : "") || "";
            const cB = (b.country ? b.country.name : "") || "";
            return cA.localeCompare(cB);
        } else if (currentSort === "name") {
            return (a.name || "").localeCompare(b.name || "");
        } else if (currentSort === "protocol") {
            return (a.type || "").localeCompare(b.type || "");
        }
        return 0;
    });

    return result;
}

function updateFilterCounts() {
    // 1. Update Category tab counters (global for all loaded nodes)
    const countRegular = nodes.filter(n => !isNodeWhitelist(n)).length;
    const countWhitelist = nodes.filter(n => isNodeWhitelist(n)).length;
    const countTotal = nodes.length;

    const elRegular = document.getElementById("countCatRegular");
    const elWhitelist = document.getElementById("countCatWhitelist");
    const elAll = document.getElementById("countCatAll");

    if (elRegular) elRegular.textContent = countRegular;
    if (elWhitelist) elWhitelist.textContent = countWhitelist;
    if (elAll) elAll.textContent = countTotal;

    // 2. Sub-filter counters (within the current active category)
    let categoryPool = nodes;
    if (activeCategory === "regular") {
        categoryPool = nodes.filter(n => !isNodeWhitelist(n));
    } else if (activeCategory === "whitelist") {
        categoryPool = nodes.filter(n => isNodeWhitelist(n));
    }

    const countAllEl = document.getElementById("countAll");
    if (countAllEl) countAllEl.textContent = categoryPool.length;

    const favCountEl = document.getElementById("countFavorites");
    if (favCountEl) {
        const favInCategory = categoryPool.filter(n => favorites.has(n.id)).length;
        favCountEl.textContent = favInCategory;
    }

    const aliveCountEl = document.getElementById("countAlive");
    if (aliveCountEl) {
        const aliveInCategory = categoryPool.filter(n => n.ping && n.ping > 0).length;
        aliveCountEl.textContent = aliveInCategory;
    }
}

// --- Connection UI Updates ---
function updateConnectionUI() {
    const isRunning = currentStatus.status === "running";
    const isStarting = currentStatus.status === "starting";
    const isError = currentStatus.status === "error";
    const killSwitchActive = currentStatus.kill_switch_active;

    // --- Главная кнопка: одно состояние, один цвет, без скачков layout ---
    let state = "disconnected";
    if (isRunning) state = "connected";
    else if (isStarting) state = "connecting";
    else if (isError || killSwitchActive) state = "error";

    const copy = CONNECT_STATES[state];
    btnToggleConnect.className = `power-btn power-btn--${state}`;
    btnToggleConnect.setAttribute("aria-label", copy.aria);
    // title держим в паре с aria-label, иначе подсказка в тултипе устаревает
    btnToggleConnect.setAttribute("title", copy.aria);
    btnToggleConnect.setAttribute("aria-busy", isStarting ? "true" : "false");
    btnToggleConnect.setAttribute("aria-pressed", isRunning ? "true" : "false");
    connStateText.className = "power-btn__label";
    connStateText.textContent = copy.label;
    if (btnToggleConnectHint) btnToggleConnectHint.textContent = copy.hint;

    // --- Подпись под кнопкой: активный сервер или тот, к которому подключимся ---
    if (isRunning && currentStatus.active_node) {
        const countryCode = currentStatus.active_node.country ? currentStatus.active_node.country.code : "UN";
        const flagHtml = typeof getCountryFlagHtml === "function" ?
            getCountryFlagHtml(countryCode) : "";
        // Флаг рисуем один раз: SVG-флаг + название без эмодзи-флага.
        const nodeName = stripFlagEmoji(currentStatus.active_node.name);
        connTargetText.innerHTML = `<span class="conn-target__server">${flagHtml} ${escapeHtml(nodeName)}</span>`;
    } else if (killSwitchActive) {
        connTargetText.textContent = "Связь потеряна. Интернет заблокирован во избежание утечки IP.";
    } else if (isError) {
        connTargetText.textContent = "Не удалось подключиться. Проверьте сервер или попробуйте другой.";
    } else {
        const preferred = pickPreferredNode();
        connTargetText.textContent = preferred
            ? `Подключиться к: ${stripFlagEmoji(preferred.name)}`
            : "Добавьте сервер в разделе «Серверы»";
    }

    // --- Таймер работы и реальная задержка ---
    if (isRunning) {
        startUptimeCounter();
        connRealDelay.textContent = "● Трафик через прокси";
        connRealDelay.className = "real-delay-badge good";
        startRealDelayTester();
    } else {
        stopUptimeCounter();
        stopRealDelayTester();
        connRealDelay.textContent = "Тест сети: —";
        connRealDelay.className = "real-delay-badge";
    }

    // --- Текущая скорость: плитки всегда на месте, меняются только значения ---
    if (speedDownVal && speedUpVal) {
        speedDownVal.textContent = formatSpeed(currentStatus.speed_down || 0);
        speedUpVal.textContent = formatSpeed(currentStatus.speed_up || 0);
    }
    if (totalVal) {
        const sumBytes = (currentStatus.total_down || 0) + (currentStatus.total_up || 0);
        totalVal.textContent = formatBytes(sumBytes);
    }

    // Windows Proxy Status
    const pState = currentStatus.proxy_state || {};
    if (currentStatus.system_proxy_enabled) {
        proxyStatusBadge.classList.add("active");
        proxyStatusBadge.classList.remove("stale");
        if (pState.enabled && pState.port && pState.listening === false) {
            proxyStatusBadge.classList.add("stale");
            proxyStatusText.textContent = "Прокси ВКЛ (нет ответа)";
        } else {
            proxyStatusText.textContent = "Системный прокси ВКЛ";
        }
    } else {
        proxyStatusBadge.classList.remove("active");
        proxyStatusBadge.classList.remove("stale");
        proxyStatusText.textContent = "Прокси выкл";
    }

    updateRecoveryUI(pState);
    updateDedupIndicators(currentStatus.dedup);

    // Routing Mode Button State
    document.querySelectorAll(".route-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.mode === currentStatus.routing_mode);
    });

    // TUN Mode state
    const isTunOn = currentStatus.tun_mode !== false;
    if (chkTunMode) chkTunMode.checked = isTunOn;
    if (tunStatusPill) {
        if (isTunOn) {
            tunStatusPill.classList.remove("off");
            tunStatusText.textContent = "TUN: ВКЛ";
            tunStatusPill.title = "TUN режим активен: весь сетевой трафик ПК (Telegram, Discord, игры) направлен в VPN";
        } else {
            tunStatusPill.classList.add("off");
            tunStatusText.textContent = "TUN: ВЫКЛ";
            tunStatusPill.title = "TUN режим выключен: работает только системный прокси";
        }
    }
    if (tunCardSub) {
        tunCardSub.textContent = isTunOn ? "Telegram, игры, весь ПК" : "Только прокси браузера";
    }

    // Administrator status warning
    if (adminWarnBar) {
        if (currentStatus.is_admin === false) {
            adminWarnBar.style.display = "flex";
        } else {
            adminWarnBar.style.display = "none";
        }
    }

    // Update Logs in settings modal
    if (currentStatus.logs) {
        const consoleEl = document.getElementById("logsConsole");
        if (consoleEl) {
            consoleEl.textContent = currentStatus.logs.join("\n");
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    }
}

/**
 * Сервер, к которому подключится главная кнопка:
 * избранный с лучшим пингом, иначе самый быстрый из всех.
 * Список фильтров пользователя здесь не учитывается — подключение не должно
 * зависеть от того, какой фильтр сейчас включён в окне серверов.
 */
function pickPreferredNode() {
    if (!nodes.length) return null;
    const sorted = [...nodes].sort((a, b) => {
        const pA = (a.ping && a.ping > 0) ? a.ping : 999999;
        const pB = (b.ping && b.ping > 0) ? b.ping : 999999;
        if (pA !== pB) return pA - pB;
        return (a.name || "").localeCompare(b.name || "");
    });
    return sorted.find(n => favorites.has(n.id)) || sorted[0];
}

function updateCoreUI() {
    if (currentStatus.has_core) {
        coreStatusPill.querySelector(".status-dot").className = "status-dot active";
        coreStatusText.textContent = "sing-box готов";
        document.getElementById("cfgCorePath").textContent = currentStatus.core_path || "sing-box.exe";
        document.getElementById("cfgCoreStatusLabel").textContent = "Ядро установлено и готово к работе";
        document.getElementById("btnDownloadCore").textContent = "Переустановить sing-box";
    } else {
        coreStatusPill.querySelector(".status-dot").className = "status-dot error";
        coreStatusText.textContent = "Ядро не найдено";
        document.getElementById("cfgCorePath").textContent = "Не найдено";
        document.getElementById("btnDownloadCore").textContent = "Скачать официальное sing-box";
    }

    // Wintun driver status
    if (cfgWintunStatus) {
        if (currentStatus.has_wintun) {
            cfgWintunStatus.textContent = "Установлен (wintun.dll)";
            cfgWintunStatus.style.color = "var(--accent-green)";
            if (rowInstallWintun) rowInstallWintun.style.display = "none";
        } else {
            cfgWintunStatus.textContent = "Не найден";
            cfgWintunStatus.style.color = "var(--accent-red)";
            if (rowInstallWintun) rowInstallWintun.style.display = "flex";
        }
    }

    // Windows Admin status
    if (cfgAdminStatus) {
        if (currentStatus.is_admin) {
            cfgAdminStatus.textContent = "Да (Администратор)";
            cfgAdminStatus.style.color = "var(--accent-green)";
        } else {
            cfgAdminStatus.textContent = "Нет (Обычный пользователь)";
            cfgAdminStatus.style.color = "var(--accent-amber)";
        }
    }
}

// --- Счётчики списка серверов (настройки) ---
/**
 * Показывает, сколько серверов в списке и сколько дубликатов исключено
 * (счётчик приходит с бэкенда — /api/status → dedup).
 */
function updateDedupIndicators(dedup) {
    const info = dedup || {};
    if (cfgServerCount) {
        const servers = Number(info.servers || 0);
        cfgServerCount.textContent = servers ? String(servers) : "0";
    }
    if (cfgDedupCount) {
        const removed = Number(info.removed_total || 0);
        cfgDedupCount.textContent = removed ? String(removed) : "0";
        cfgDedupCount.title = removed
            ? "Одинаковые подключения (протокол, адрес, порт, транспорт, учётные данные) объединены в один сервер"
            : "Дубликатов не найдено";
    }
}

// --- Автовосстановление сети ---
function updateRecoveryUI(proxyInfo) {    const info = proxyInfo || {};

    if (cfgProxyState) {
        if (!info.enabled) {
            cfgProxyState.textContent = "Выключен — интернет в порядке";
            cfgProxyState.style.color = "var(--accent-green)";
        } else if (info.listening === false) {
            cfgProxyState.textContent = `Включён (${info.server || "?"}), но порт не отвечает`;
            cfgProxyState.style.color = "var(--accent-amber)";
        } else {
            cfgProxyState.textContent = `Включён (${info.server || "?"}) — работает`;
            cfgProxyState.style.color = "var(--accent-green)";
        }
    }

    if (cfgGuardianState) {
        if (currentStatus.guardian_alive) {
            cfgGuardianState.textContent = "Работает — интернет будет восстановлен автоматически";
            cfgGuardianState.style.color = "var(--accent-green)";
        } else {
            cfgGuardianState.textContent = "Не запущен — восстановление при сбое не гарантируется";
            cfgGuardianState.style.color = "var(--accent-amber)";
        }
    }
}

async function repairNetwork() {
    const buttons = [btnRepairNetwork, btnRepairNetworkSettings].filter(Boolean);
    buttons.forEach(b => { b.disabled = true; b.style.opacity = "0.55"; });

    showToast("Восстанавливаю системные настройки сети...");

    try {
        const resp = await fetch("/api/repair-network", { method: "POST" });
        const data = await resp.json();

        if (data && data.success) {
            const report = data.report || {};
            const details = [];
            if (report.proxy_disabled) details.push("прокси выключен");
            if (report.core_killed) details.push("ядро остановлено");
            if (report.tun_removed) details.push("TUN-адаптер удалён");
            showToast(details.length
                ? "Интернет восстановлен: " + details.join(", ") + "."
                : "Проверено — всё в порядке, интернет работает.");
        } else {
            showToast("Не удалось выполнить восстановление");
        }
    } catch (e) {
        showToast("Нет связи с конфигуратором");
    } finally {
        buttons.forEach(b => { b.disabled = false; b.style.opacity = ""; });
        loadStatus();
    }
}

// --- Timers ---
function startUptimeCounter() {
    if (uptimeInterval) clearInterval(uptimeInterval);
    uptimeInterval = setInterval(() => {
        if (currentStatus.uptime_seconds !== undefined) {
            currentStatus.uptime_seconds++;
            const sec = currentStatus.uptime_seconds;
            const h = String(Math.floor(sec / 3600)).padStart(2, '0');
            const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
            const s = String(sec % 60).padStart(2, '0');
            connUptime.textContent = `Время: ${h}:${m}:${s}`;
        }
    }, 1000);
}

function stopUptimeCounter() {
    if (uptimeInterval) clearInterval(uptimeInterval);
    connUptime.textContent = "Время: 00:00:00";
}

function startRealDelayTester() {
    if (realDelayInterval) clearInterval(realDelayInterval);
    testRealDelay();
    realDelayInterval = setInterval(testRealDelay, 6000);
}

function stopRealDelayTester() {
    if (realDelayInterval) clearInterval(realDelayInterval);
}

async function testRealDelay() {
    if (currentStatus.status !== "running") return;
    try {
        const res = await fetch("/api/test-real-delay", { method: "POST" });
        const data = await res.json();
        if (data.delay > 0) {
            connRealDelay.textContent = `● ${data.delay} ms (Cloudflare)`;
            connRealDelay.className = "real-delay-badge good";
        } else {
            connRealDelay.textContent = `● Трафик через прокси`;
            connRealDelay.className = "real-delay-badge good";
        }
    } catch (e) {
        connRealDelay.textContent = `● Подключено`;
        connRealDelay.className = "real-delay-badge good";
    }
}

// --- User Actions ---
async function selectAndConnect(nodeId, event) {
    if (event) event.stopPropagation();

    if (currentStatus.status === "running" && currentStatus.active_node && currentStatus.active_node.id === nodeId) {
        // Disconnect
        await disconnectVPN();
        return;
    }

    if (!currentStatus.has_core) {
        showToast("Сначала скачайте ядро sing-box в настройках!");
        settingsModal.classList.add("open");
        return;
    }

    try {
        currentStatus.status = "starting";
        updateConnectionUI();

        const res = await fetch("/api/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                id: nodeId,
                routing_mode: currentStatus.routing_mode || "bypass_ru",
                tun_mode: true
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Подключено к VPN!");
        } else {
            const lastLog = (data.info && data.info.logs && data.info.logs.length) ? 
                data.info.logs[data.info.logs.length - 1] : "проверьте логи";
            showToast("Ошибка: " + lastLog);
        }
        loadStatus();
        renderServerGrid();
    } catch (e) {
        showToast("Ошибка запроса подключения");
        loadStatus();
    }
}

async function disconnectVPN() {
    try {
        await fetch("/api/disconnect", { method: "POST" });
        showToast("VPN отключен");
        loadStatus();
        renderServerGrid();
    } catch (e) {
        showToast("Ошибка отключения");
    }
}

async function pingAllServers() {
    if (nodes.length === 0) {
        showToast("Нет узлов для проверки");
        return;
    }
    setPingAllLoading(true);
    try {
        const res = await fetch("/api/ping-all", { method: "POST" });
        if (!res.ok) {
            const err = await res.json();
            showToast(err.error || "Ошибка запуска теста");
            setPingAllLoading(false);
        }
    } catch (e) {
        showToast("Ошибка соединения с сервером");
        setPingAllLoading(false);
    }
}

function setPingAllLoading(isLoading) {
    const icon = btnPingAll.querySelector(".spin-on-active");
    if (isLoading) {
        btnPingAll.classList.add("disabled");
        icon.classList.add("spin");
        btnPingAll.querySelector("span").textContent = "Проверка...";
    } else {
        btnPingAll.classList.remove("disabled");
        icon.classList.remove("spin");
        btnPingAll.querySelector("span").textContent = "Проверить";
    }
}

async function pingSingleNode(nodeId, event) {
    if (event) event.stopPropagation();
    const badge = document.getElementById(`ping-badge-${nodeId}`);
    if (badge) {
        badge.innerHTML = `<span class="ping-text">...</span>`;
        badge.className = "ping-badge none pinging";
    }
    try {
        await fetch("/api/ping-single", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: nodeId })
        });
    } catch (e) {
        showToast("Ошибка пинга узла");
    }
}

function copyNodeUri(nodeId, event) {
    if (event) event.stopPropagation();
    const node = nodes.find(n => n.id === nodeId);
    if (!node || !node.raw_uri) return;
    
    const uri = node.raw_uri;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(uri).then(() => {
            showToast("Ссылка на узел скопирована в буфер обмена!");
        }).catch(() => {
            fallbackCopyText(uri);
        });
    } else {
        fallbackCopyText(uri);
    }
}

function fallbackCopyText(text) {
    try {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        showToast("Ссылка на узел скопирована в буфер обмена!");
    } catch (e) {
        showToast("Не удалось скопировать ссылку");
    }
}

async function deleteNode(nodeId, event) {
    if (event) event.stopPropagation();
    try {
        await fetch("/api/nodes/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: nodeId })
        });
        nodes = nodes.filter(n => n.id !== nodeId);
        favorites.delete(nodeId);
        updateFilterCounts();
        renderServerGrid();
        showToast("Узел удален");
    } catch (e) {
        showToast("Ошибка удаления узла");
    }
}

// --- Subscriptions ---
function renderSubsList() {
    const container = document.getElementById("subsList");
    container.innerHTML = "";

    if (subscriptions.length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); font-size: 13px;">Подписок пока нет. Добавьте ссылку выше.</div>`;
        return;
    }

    subscriptions.forEach(sub => {
        const item = document.createElement("div");
        item.className = "sub-item";

        // Сводка по трафику и сроку — если провайдер отдал эти данные.
        const usage = sub.usage;
        let usageHtml = "";
        if (usage && usage.total) {
            const percent = Math.max(0, Math.min(100, Number(usage.percent) || 0));
            const expireText = formatExpiry(usage.expire);
            const days = usage.expire_days_left;
            const fillClass = percent >= 90 ? "is-danger" : (percent >= 70 ? "is-warn" : "");
            usageHtml = `
                <div class="sub-usage-bar" role="progressbar" aria-label="Расход трафика"
                     aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(percent)}">
                    <span class="sub-usage-fill ${fillClass}" style="width:${percent}%"></span>
                </div>
                <span class="sub-item-meta">
                    Израсходовано ${formatTraffic(usage.used)} из ${formatTraffic(usage.total)} ·
                    осталось ${formatTraffic(usage.remaining)} (${percent.toFixed(1)}%)
                    ${expireText ? ` · до ${expireText}${days !== undefined && days !== null ? ` (${days} дн.)` : ""}` : ""}
                </span>`;
        }

        item.innerHTML = `
            <div class="sub-item-info">
                <span class="sub-item-title">${escapeHtml(sub.name)}</span>
                <span class="sub-item-url" title="${escapeHtml(sub.url)}">${escapeHtml(sub.url)}</span>
                <span class="sub-item-meta">Узлов: ${sub.node_count || 0} ${sub.last_updated ? '• Обновлено: ' + sub.last_updated : ''}</span>
                ${usageHtml}
            </div>
            <button class="action-icon-btn" title="Удалить подписку" onclick="deleteSubscription('${sub.id}')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
        `;
        container.appendChild(item);
    });
}

async function addSubscription() {
    const nameInput = document.getElementById("newSubName");
    const urlInput = document.getElementById("newSubUrl");
    const url = urlInput.value.trim();
    const name = nameInput.value.trim() || "Подписка";

    if (!url) {
        showToast("Введите URL подписки");
        return;
    }

    try {
        const res = await fetch("/api/subscriptions/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url, name })
        });
        const data = await res.json();
        if (data.success) {
            urlInput.value = "";
            nameInput.value = "";
            showToast("Подписка добавлена, идет загрузка узлов...");
            loadSubscriptions();
        } else {
            showToast("Ошибка: " + data.error);
        }
    } catch (e) {
        showToast("Ошибка при добавлении подписки");
    }
}

async function deleteSubscription(subId) {
    try {
        await fetch("/api/subscriptions/delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: subId })
        });
        showToast("Подписка удалена");
        loadSubscriptions();
    } catch (e) {
        showToast("Ошибка удаления подписки");
    }
}

async function updateAllSubscriptions() {
    setSubsLoading(true);
    try {
        await fetch("/api/subscriptions/update-all", { method: "POST" });
    } catch (e) {
        showToast("Ошибка запуска обновления");
        setSubsLoading(false);
    }
}

function setSubsLoading(isLoading) {
    const icon = btnUpdateAllSubs.querySelector(".spin-on-active");
    if (isLoading) {
        icon.classList.add("spin");
        btnUpdateAllSubs.querySelector("span").textContent = "Обновление...";
    } else {
        icon.classList.remove("spin");
        btnUpdateAllSubs.querySelector("span").textContent = "Обновить";
    }
}

async function importKeys() {
    const textarea = document.getElementById("importKeysText");
    const text = textarea.value.trim();
    if (!text) {
        showToast("Вставьте ключи VPN в поле");
        return;
    }

    try {
        const res = await fetch("/api/subscriptions/import-keys", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text })
        });
        const data = await res.json();
        if (data.success) {
            textarea.value = "";
            showToast(`Успешно импортировано ${data.added} узлов!`);
            subsModal.classList.remove("open");
            loadNodes();
        } else {
            showToast(data.error || "Не удалось импортировать");
        }
    } catch (e) {
        showToast("Ошибка импорта");
    }
}

// --- Core Download ---
async function downloadOfficialCore() {
    const progressBox = document.getElementById("coreDownloadProgress");
    const bar = document.getElementById("coreBarFill");
    const text = document.getElementById("coreProgressText");
    
    progressBox.style.display = "block";
    bar.style.width = "30%";
    text.textContent = "Скачивание с GitHub...";

    try {
        await fetch("/api/core/download", { method: "POST" });
        showToast("Началась установка официального sing-box...");
    } catch (e) {
        showToast("Ошибка запуска скачивания ядра");
        progressBox.style.display = "none";
    }
}

// --- Event Listeners ---
function setupEventListeners() {
    btnToggleConnect.addEventListener("click", () => {
        if (currentStatus.status === "running") {
            disconnectVPN();
            return;
        }
        // Подключаемся к лучшему серверу: избранный, иначе самый быстрый.
        // Текущий фильтр в окне серверов на выбор не влияет.
        const targetNode = pickPreferredNode();
        if (targetNode) {
            selectAndConnect(targetNode.id);
        } else {
            showToast("Добавьте узлы перед подключением");
            subsModal.classList.add("open");
        }
    });

    btnPingAll.addEventListener("click", pingAllServers);
    btnUpdateAllSubs.addEventListener("click", updateAllSubscriptions);

    // Routing Mode Buttons
    document.querySelectorAll(".route-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const mode = btn.dataset.mode;
            currentStatus.routing_mode = mode;
            document.querySelectorAll(".route-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            if (currentStatus.status === "running" && currentStatus.active_node) {
                // Reconnect with new routing mode
                selectAndConnect(currentStatus.active_node.id);
            }
        });
    });

    // Search
    searchInput.addEventListener("input", (e) => {
        searchQuery = e.target.value;
        renderServerGrid();
    });

    // Custom Glassmorphic Sort Dropdown
    if (sortTriggerBtn) {
        sortTriggerBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            sortDropdown.classList.toggle("open");
        });
    }

    document.querySelectorAll(".dropdown-opt").forEach(opt => {
        opt.addEventListener("click", (e) => {
            e.stopPropagation();
            currentSort = opt.dataset.value;
            const text = opt.querySelector(".opt-text").textContent;
            const icon = opt.querySelector(".opt-icon").textContent;
            sortSelectedLabel.textContent = text;
            
            document.querySelectorAll(".dropdown-opt").forEach(o => o.classList.remove("active"));
            opt.classList.add("active");
            sortDropdown.classList.remove("open");
            renderServerGrid();
        });
    });

    document.addEventListener("click", (e) => {
        if (sortDropdown && !sortDropdown.contains(e.target)) {
            sortDropdown.classList.remove("open");
        }
    });

    // Category Switch Tabs (Regular vs Whitelist vs All)
    document.querySelectorAll(".category-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".category-tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            activeCategory = tab.dataset.category || "regular";
            updateFilterCounts();
            renderServerGrid();
        });
    });

    // Filter Chips
    document.querySelectorAll(".chip").forEach(chip => {
        chip.addEventListener("click", () => {
            document.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            activeFilter = chip.dataset.filter;
            renderServerGrid();
        });
    });

    // Modal Toggles
    btnOpenSubs.addEventListener("click", () => subsModal.classList.add("open"));
    btnCloseSubs.addEventListener("click", () => subsModal.classList.remove("open"));
    btnEmptyAdd.addEventListener("click", () => subsModal.classList.add("open"));

    // Переключатель темы (светлая / тёмная)
    if (btnToggleTheme) {
        btnToggleTheme.addEventListener("click", toggleTheme);
    }

    // Окно серверов (список вынесен с главного экрана)
    if (btnOpenServers) {
        btnOpenServers.addEventListener("click", () => {
            renderServerGrid();
            updateFilterCounts();
            serversModal.classList.add("open");
        });
    }    if (btnCloseServers) {
        btnCloseServers.addEventListener("click", () => serversModal.classList.remove("open"));
    }
    if (serversModal) {
        serversModal.addEventListener("click", (e) => {
            if (e.target === serversModal) serversModal.classList.remove("open");
        });
    }

    btnOpenSettings.addEventListener("click", () => {
        loadStatus();
        settingsModal.classList.add("open");
    });
    btnCloseSettings.addEventListener("click", () => settingsModal.classList.remove("open"));

    // Восстановление интернета
    if (btnRepairNetwork) btnRepairNetwork.addEventListener("click", repairNetwork);
    if (btnRepairNetworkSettings) btnRepairNetworkSettings.addEventListener("click", repairNetwork);

    // Subscriptions
    document.getElementById("btnAddSub").addEventListener("click", addSubscription);
    document.getElementById("btnImportKeys").addEventListener("click", importKeys);

    // Settings save
    document.getElementById("btnDownloadCore").addEventListener("click", downloadOfficialCore);

    // TUN Mode Switch
    if (chkTunMode) {
        chkTunMode.addEventListener("change", async () => {
            const tunOn = chkTunMode.checked;
            if (tunOn && currentStatus.is_admin === false) {
                showToast("Для TUN-режима требуются права Администратора (нажмите кнопку)");
            }
            try {
                const res = await fetch("/api/tun/toggle", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ tun_mode: tunOn })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(tunOn ? "TUN-режим включен (весь ПК в VPN)" : "TUN выключен (только системный прокси)");
                    loadStatus();
                }
            } catch (e) {
                showToast("Ошибка переключения TUN-режима");
            }
        });
    }

    if (btnElevateAdmin) {
        btnElevateAdmin.addEventListener("click", async () => {
            showToast("Запрос прав Администратора... Подтвердите UAC в Windows");
            try {
                await fetch("/api/restart-elevated", { method: "POST" });
            } catch (e) {
                showToast("Ошибка перезапуска: запустите run.bat от Администратора");
            }
        });
    }

    if (btnDownloadWintun) {
        btnDownloadWintun.addEventListener("click", async () => {
            showToast("Скачивание драйвера Wintun...");
            try {
                await fetch("/api/tun/install-wintun", { method: "POST" });
            } catch (e) {
                showToast("Ошибка скачивания Wintun");
            }
        });
    }

    document.getElementById("cfgTimeout").addEventListener("change", saveSettings);
    document.getElementById("cfgConcurrency").addEventListener("change", saveSettings);
    document.getElementById("cfgSysProxy").addEventListener("change", saveSettings);
    if (cfgKillSwitch) {
        cfgKillSwitch.addEventListener("change", () => {
            saveSettings();
            showToast(cfgKillSwitch.checked ? "🛡️ Kill Switch включен: интернет защищен от утечки IP" : "Kill Switch выключен");
        });
    }
    if (cfgDohProtection) {
        cfgDohProtection.addEventListener("change", () => {
            saveSettings();
            showToast(cfgDohProtection.checked ? "🔒 Защита DNS (DoH) включена" : "Защита DNS (DoH) выключена");
        });
    }
    if (cfgMinimizeToTray) {
        cfgMinimizeToTray.addEventListener("change", () => {
            saveSettings();
            showToast(cfgMinimizeToTray.checked ? "🔕 Сворачивание в трей включено" : "Сворачивание в трей отключено");
        });
    }

    // Express Speedtest Button
    if (btnSpeedtest) {
        btnSpeedtest.addEventListener("click", async () => {
            if (btnSpeedtest.disabled) return;
            if (currentStatus.status !== "running") {
                showToast("Для замера скорости сначала подключитесь к VPN", "warning");
                return;
            }
            btnSpeedtest.disabled = true;
            btnSpeedtest.innerHTML = '<svg class="speedtest-icon spin-on-active" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> <span>Замер (3 сек)...</span>';
            if (speedtestVal) speedtestVal.textContent = "…";
            try {
                const res = await fetch("/api/speedtest", { method: "POST" });
                const data = await res.json();
                if (data.success) {
                    const valEl = document.getElementById("speedtestVal");
                    if (valEl) valEl.textContent = data.speed_mbps;
                    showToast(`Замер скорости: ${data.speed_mbps} Мбит/с (через Cloudflare CDN)`);
                } else {
                    if (speedtestVal) speedtestVal.textContent = "—";
                    showToast(speedtestErrorText(data.error));
                }
            } catch (err) {
                if (speedtestVal) speedtestVal.textContent = "—";
                showToast("Не удалось измерить скорость");
            } finally {
                btnSpeedtest.disabled = false;
                btnSpeedtest.innerHTML = '<svg class="speedtest-icon spin-on-active" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> <span>Замерить</span>';
            }
        });
    }

    // Bypass list (traffic that skips the VPN)
    const btnSaveBypass = document.getElementById("btnSaveBypass");
    if (btnSaveBypass) {
        btnSaveBypass.addEventListener("click", () => saveBypassList(false));
    }

    const btnClearBypass = document.getElementById("btnClearBypass");
    if (btnClearBypass) {
        btnClearBypass.addEventListener("click", () => {
            const box = document.getElementById("cfgBypassList");
            if (box) box.value = "";
            saveBypassList(false);
        });
    }

    document.querySelectorAll(".preset-chip").forEach(chip => {
        chip.addEventListener("click", () => addBypassPreset(chip.dataset.preset));
    });
}

/**
 * Сохраняет настройки на сервере.
 * extra — дополнительные поля (например, выбранная тема), которые нужно
 * записать вместе с остальными, не трогая элементы формы.
 */
async function saveSettings(extra) {
    const timeout = parseFloat(document.getElementById("cfgTimeout").value) || 1.2;
    const concurrency = parseInt(document.getElementById("cfgConcurrency").value) || 80;
    const sysProxy = document.getElementById("cfgSysProxy").checked;
    const killSwitch = cfgKillSwitch ? cfgKillSwitch.checked : false;
    const dohProtection = cfgDohProtection ? cfgDohProtection.checked : true;
    const minimizeToTray = cfgMinimizeToTray ? cfgMinimizeToTray.checked : true;

    const payload = {
        ping_timeout: timeout,
        ping_concurrency: concurrency,
        system_proxy: sysProxy,
        kill_switch: killSwitch,
        doh_protection: dohProtection,
        minimize_to_tray: minimizeToTray
    };
    if (extra && typeof extra === "object") {
        Object.assign(payload, extra);
    }

    await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
}

// Toast Utility
function showToast(message) {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => {
        toast.classList.remove("show");
    }, 3200);
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
