/* Thomas Smart Notification Center  Web UI widget (no framework required)
 *
 * Mounts:
 * - bell icon with unread badge
 * - slide-out panel with filters
 * - SSE updates (/api/notifications/stream) with polling fallback
 * - optional Web Push subscribe button (if VAPID configured)
 */

export function mountThomasNotifications(opts = {}) {
  const apiBase = (opts.apiBase || "/api/notifications").replace(/\/+$/, "");
  const position = opts.position || "top-right";
  const pollMs = opts.pollMs || 15000;

  injectStyles();

  const root = document.createElement("div");
  root.className = "thomas-notif-root " + position;

  root.innerHTML = `
    <button class="thomas-notif-bell" aria-label="Notifications" title="Notifications">
      <span class="thomas-notif-bell-icon"></span>
      <span class="thomas-notif-badge" style="display:none">0</span>
    </button>
    <div class="thomas-notif-panel" aria-hidden="true">
      <div class="thomas-notif-panel-header">
        <div class="thomas-notif-title">Notifications</div>
        <div class="thomas-notif-actions">
          <button class="thomas-notif-btn thomas-notif-btn-secondary" data-action="enable-push" style="display:none">Enable Push</button>
          <button class="thomas-notif-btn thomas-notif-btn-secondary" data-action="refresh">Refresh</button>
          <button class="thomas-notif-btn thomas-notif-btn-danger" data-action="clear">Clear</button>
          <button class="thomas-notif-btn" data-action="close"></button>
        </div>
      </div>

      <div class="thomas-notif-filters">
        <label>
          <span>Type</span>
          <input class="thomas-notif-input" data-filter="type" placeholder="ex: task.complete" />
        </label>
        <label>
          <span>Severity</span>
          <select class="thomas-notif-input" data-filter="severity">
            <option value="">all</option>
            <option value="info">info</option>
            <option value="warn">warn</option>
            <option value="error">error</option>
          </select>
        </label>
        <label class="thomas-notif-unread-only">
          <input type="checkbox" data-filter="unread_only" />
          <span>Unread only</span>
        </label>
      </div>

      <div class="thomas-notif-list" role="list"></div>
      <div class="thomas-notif-footer">
        <span class="thomas-notif-muted" data-footer="status"></span>
      </div>
    </div>
  `;

  document.body.appendChild(root);

  const bell = root.querySelector(".thomas-notif-bell");
  const badge = root.querySelector(".thomas-notif-badge");
  const panel = root.querySelector(".thomas-notif-panel");
  const list = root.querySelector(".thomas-notif-list");
  const status = root.querySelector('[data-footer="status"]');

  const filterType = root.querySelector('[data-filter="type"]');
  const filterSeverity = root.querySelector('[data-filter="severity"]');
  const filterUnread = root.querySelector('[data-filter="unread_only"]');

  let open = false;
  let currentItems = [];
  let es = null;
  let pollTimer = null;

  function setStatus(msg) {
    status.textContent = msg || "";
  }

  function togglePanel(force) {
    open = (typeof force === "boolean") ? force : !open;
    panel.classList.toggle("open", open);
    panel.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) {
      refresh();
      startLive();
    } else {
      stopLive();
    }
  }

  bell.addEventListener("click", () => togglePanel());

  root.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;

    const action = btn.getAttribute("data-action");
    if (action === "close") togglePanel(false);
    if (action === "refresh") refresh();
    if (action === "clear") {
      await apiClear();
      await refresh();
    }
    if (action === "enable-push") {
      await enablePush();
    }
  });

  [filterType, filterSeverity, filterUnread].forEach((el) => {
    el.addEventListener("change", () => refresh());
    el.addEventListener("keyup", () => refreshDebounced());
  });

  let refreshDebounce = null;
  function refreshDebounced() {
    if (refreshDebounce) clearTimeout(refreshDebounce);
    refreshDebounce = setTimeout(refresh, 300);
  }

  function qs() {
    const params = new URLSearchParams();
    params.set("limit", "50");
    params.set("offset", "0");
    const t = (filterType.value || "").trim();
    const s = (filterSeverity.value || "").trim();
    const u = !!filterUnread.checked;

    if (t) params.set("type", t);
    if (s) params.set("severity", s);
    if (u) params.set("unread_only", "true");
    return params.toString();
  }

  async function apiGetNotifications() {
    const r = await fetch(`${apiBase}?${qs()}`, { credentials: "same-origin" });
    if (!r.ok) throw new Error(`GET notifications failed: ${r.status}`);
    return r.json();
  }

  async function apiMarkRead(id) {
    const r = await fetch(`${apiBase}/${encodeURIComponent(id)}/read`, {
      method: "POST",
      credentials: "same-origin"
    });
    if (!r.ok) throw new Error(`POST read failed: ${r.status}`);
    return r.json();
  }

  async function apiClear() {
    const r = await fetch(`${apiBase}/clear?mode=all`, {
      method: "DELETE",
      credentials: "same-origin"
    });
    if (!r.ok) throw new Error(`DELETE clear failed: ${r.status}`);
    return r.json();
  }

  function renderBadge(unreadCount) {
    if (unreadCount > 0) {
      badge.style.display = "inline-flex";
      badge.textContent = String(unreadCount);
    } else {
      badge.style.display = "none";
    }
  }

  function fmtTime(ms) {
    try {
      const d = new Date(ms);
      return d.toLocaleString();
    } catch (_) {
      return "";
    }
  }

  function severityDot(sev) {
    if (sev === "error") return "";
    if (sev === "warn") return "";
    return "";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function sanitizeActionUrl(raw) {
    const value = String(raw || "").trim();
    if (!value) return "";
    try {
      const url = new URL(value, window.location.origin);
      if (url.protocol !== "http:" && url.protocol !== "https:") {
        return "";
      }
      return url.toString();
    } catch (_) {
      return "";
    }
  }

  function renderList(items) {
    currentItems = items || [];
    if (!currentItems.length) {
      list.innerHTML = `<div class="thomas-notif-empty">No notifications</div>`;
      return;
    }

    list.innerHTML = currentItems.map(n => {
      const cls = `thomas-notif-item ${n.read ? "read" : "unread"} sev-${n.severity}`;
      const safeActionUrl = sanitizeActionUrl(n.action_url);
      const action = safeActionUrl ? `<a class="thomas-notif-link" href="${escapeHtml(safeActionUrl)}">open</a>` : "";
      return `
        <div class="${cls}" role="listitem" data-id="${escapeHtml(n.id)}">
          <div class="thomas-notif-item-top">
            <div class="thomas-notif-item-title">
              <span class="thomas-notif-sev">${severityDot(n.severity)}</span>
              <span>${escapeHtml(n.title)}</span>
            </div>
            <div class="thomas-notif-item-meta">
              <span class="thomas-notif-pill">${escapeHtml(n.type)}</span>
              <span class="thomas-notif-time">${escapeHtml(fmtTime(n.timestamp))}</span>
              ${action}
            </div>
          </div>
          <div class="thomas-notif-item-body">${escapeHtml(n.body)}</div>
        </div>
      `;
    }).join("");

    // click to mark read + follow action_url if present
    list.querySelectorAll(".thomas-notif-item").forEach(el => {
      el.addEventListener("click", async (e) => {
        const id = el.getAttribute("data-id");
        const link = e.target.closest("a.thomas-notif-link");
        try {
          await apiMarkRead(id);
          el.classList.add("read");
          el.classList.remove("unread");
          refreshUnreadCountOnly();
        } catch (_) {}
        if (link && link.href) {
          window.location.href = link.href;
        }
      });
    });
  }

  async function refresh() {
    setStatus("Loading");
    try {
      const data = await apiGetNotifications();
      renderList(data.items || []);
      renderBadge(data.unread_count || 0);
      setStatus("");
    } catch (e) {
      setStatus(String(e.message || e));
    }
    await maybeShowPushButton();
  }

  async function refreshUnreadCountOnly() {
    try {
      const r = await fetch(`${apiBase}/unread_count`, { credentials: "same-origin" });
      if (!r.ok) return;
      const data = await r.json();
      renderBadge(data.unread_count || 0);
    } catch (_) {}
  }

  function startLive() {
    stopLive();

    // Try SSE
    try {
      es = new EventSource(`${apiBase}/stream`, { withCredentials: true });
      es.addEventListener("notification", (ev) => {
        try {
          const n = JSON.parse(ev.data);
          // If filters are active, just refresh (simple + correct)
          refresh();
        } catch (_) {}
      });
      es.addEventListener("ping", () => {});
      es.onerror = () => {
        // fall back to polling
        stopSSEOnly();
        startPolling();
      };
      setStatus("Live updates on");
      return;
    } catch (_) {
      // fall back to polling
    }

    startPolling();
  }

  function stopSSEOnly() {
    try { if (es) es.close(); } catch (_) {}
    es = null;
  }

  function startPolling() {
    setStatus("Polling updates");
    pollTimer = setInterval(() => {
      if (open) refreshUnreadCountOnly();
    }, pollMs);
  }

  function stopLive() {
    stopSSEOnly();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    setStatus("");
  }

  async function maybeShowPushButton() {
    const btn = root.querySelector('button[data-action="enable-push"]');
    try {
      const r = await fetch(`${apiBase}/push/public-key`, { credentials: "same-origin" });
      if (!r.ok) { btn.style.display = "none"; return; }
      btn.style.display = "inline-flex";
    } catch (_) {
      btn.style.display = "none";
    }
  }

  async function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  async function enablePush() {
    setStatus("");
    if (!("serviceWorker" in navigator)) {
      setStatus("ServiceWorker not supported in this browser");
      return;
    }
    if (!("PushManager" in window)) {
      setStatus("Push not supported in this browser");
      return;
    }

    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") {
        setStatus("Push permission denied");
        return;
      }

      // Ensure service worker registered at root for proper scope
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });

      const keyResp = await fetch(`${apiBase}/push/public-key`, { credentials: "same-origin" });
      if (!keyResp.ok) throw new Error("VAPID not configured on server");
      const { publicKey } = await keyResp.json();

      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: await urlBase64ToUint8Array(publicKey)
      });

      const payload = sub.toJSON();
      const resp = await fetch(`${apiBase}/push/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload)
      });
      if (!resp.ok) throw new Error("Subscribe failed");

      setStatus("Push enabled");
    } catch (e) {
      setStatus(String(e.message || e));
    }
  }

  // initial load: unread badge only
  refreshUnreadCountOnly();
  maybeShowPushButton();

  return {
    refresh,
    open: () => togglePanel(true),
    close: () => togglePanel(false),
  };
}

function injectStyles() {
  if (document.getElementById("thomas-notif-styles")) return;
  const style = document.createElement("style");
  style.id = "thomas-notif-styles";
  style.textContent = `
  .thomas-notif-root { position: fixed; z-index: 9999; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; }
  .thomas-notif-root.top-right { top: 14px; right: 14px; }
  .thomas-notif-root.top-left { top: 14px; left: 14px; }

  .thomas-notif-bell { width: 44px; height: 44px; border-radius: 12px; border: 1px solid rgba(0,0,0,.15); background: rgba(255,255,255,.9); cursor: pointer; position: relative; box-shadow: 0 8px 24px rgba(0,0,0,.12); }
  .thomas-notif-bell:hover { transform: translateY(-1px); }
  .thomas-notif-bell-icon { font-size: 18px; }

  .thomas-notif-badge { position: absolute; top: -6px; right: -6px; min-width: 18px; height: 18px; padding: 0 6px; border-radius: 999px; border: 1px solid rgba(0,0,0,.25); background: #111; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; }

  .thomas-notif-panel { position: fixed; top: 70px; right: 14px; width: 420px; max-width: calc(100vw - 28px); max-height: calc(100vh - 92px); background: rgba(255,255,255,.98); border: 1px solid rgba(0,0,0,.15); border-radius: 16px; box-shadow: 0 18px 60px rgba(0,0,0,.18); overflow: hidden; transform: translateY(-6px); opacity: 0; pointer-events: none; transition: all .18s ease; }
  .thomas-notif-root.top-left .thomas-notif-panel { left: 14px; right: auto; }
  .thomas-notif-panel.open { opacity: 1; pointer-events: auto; transform: translateY(0); }

  .thomas-notif-panel-header { display:flex; align-items:center; justify-content: space-between; padding: 12px 12px 8px 12px; border-bottom: 1px solid rgba(0,0,0,.08); }
  .thomas-notif-title { font-weight: 700; font-size: 16px; }
  .thomas-notif-actions { display:flex; gap: 8px; align-items:center; }

  .thomas-notif-btn { border: 1px solid rgba(0,0,0,.15); background: #fff; border-radius: 10px; padding: 6px 10px; cursor: pointer; font-size: 12px; }
  .thomas-notif-btn:hover { background: rgba(0,0,0,.04); }
  .thomas-notif-btn-secondary { color: #111; }
  .thomas-notif-btn-danger { border-color: rgba(0,0,0,.22); color: #b00020; }

  .thomas-notif-filters { display:flex; gap: 10px; padding: 10px 12px; border-bottom: 1px solid rgba(0,0,0,.08); }
  .thomas-notif-filters label { display:flex; flex-direction: column; gap: 4px; font-size: 11px; color: rgba(0,0,0,.7); }
  .thomas-notif-input { border: 1px solid rgba(0,0,0,.15); border-radius: 10px; padding: 6px 8px; font-size: 12px; min-width: 120px; }
  .thomas-notif-unread-only { flex-direction: row !important; align-items: center; gap: 6px !important; padding-top: 18px; }

  .thomas-notif-list { padding: 10px 12px; overflow: auto; max-height: calc(100vh - 240px); }
  .thomas-notif-empty { padding: 16px; color: rgba(0,0,0,.6); font-size: 13px; }

  .thomas-notif-item { border: 1px solid rgba(0,0,0,.10); border-radius: 14px; padding: 10px 10px; margin-bottom: 10px; cursor: pointer; transition: background .12s ease; }
  .thomas-notif-item:hover { background: rgba(0,0,0,.03); }
  .thomas-notif-item.unread { border-color: rgba(0,0,0,.18); }
  .thomas-notif-item.sev-error { border-left: 5px solid #b00020; }
  .thomas-notif-item.sev-warn { border-left: 5px solid #a05a00; }
  .thomas-notif-item.sev-info { border-left: 5px solid #0057a0; }

  .thomas-notif-item-top { display:flex; flex-direction: column; gap: 6px; }
  .thomas-notif-item-title { display:flex; gap: 8px; align-items:center; font-weight: 650; font-size: 13px; }
  .thomas-notif-sev { font-size: 10px; opacity: .75; }
  .thomas-notif-item-body { font-size: 12px; color: rgba(0,0,0,.78); line-height: 1.3; }

  .thomas-notif-item-meta { display:flex; gap: 8px; align-items:center; flex-wrap: wrap; font-size: 11px; color: rgba(0,0,0,.6); }
  .thomas-notif-pill { border: 1px solid rgba(0,0,0,.12); border-radius: 999px; padding: 2px 8px; background: rgba(0,0,0,.03); }
  .thomas-notif-time { opacity: .8; }
  .thomas-notif-link { text-decoration: none; border: 1px solid rgba(0,0,0,.12); border-radius: 999px; padding: 2px 8px; color: #111; background: #fff; }
  .thomas-notif-link:hover { background: rgba(0,0,0,.04); }

  .thomas-notif-footer { padding: 10px 12px; border-top: 1px solid rgba(0,0,0,.08); display:flex; justify-content: space-between; align-items:center; }
  .thomas-notif-muted { color: rgba(0,0,0,.55); font-size: 12px; }
  `;
  document.head.appendChild(style);
}
