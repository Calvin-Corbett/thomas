(function () {
  function formatUSD(x) {
    const n = Number(x || 0);
    if (n >= 10) return `$${n.toFixed(2)}`;
    if (n >= 1) return `$${n.toFixed(2)}`;
    if (n >= 0.1) return `$${n.toFixed(2)}`;
    return `$${n.toFixed(3)}`;
  }

  function formatK(n) {
    n = Number(n || 0);
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}m`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
    return String(Math.round(n));
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return await r.json();
  }

  function escapeHTML(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function el(tag, attrs, html) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") n.className = v;
        else if (k === "hidden") n.hidden = !!v;
        else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
        else n.setAttribute(k, String(v));
      }
    }
    if (html !== undefined) n.innerHTML = html;
    return n;
  }

  function findHeaderMount() {
    const selectors = [
      ".chat-header-primary .chat-header-right",
      ".chat-header-right",
      ".topbar-actions",
      "header .actions",
      "header",
      ".header",
      ".topbar",
      ".navbar",
      "#header",
      "#topbar",
      "[data-header]",
    ];
    for (const s of selectors) {
      const n = document.querySelector(s);
      if (n) return n;
    }
    return null;
  }

  function findModalHost() {
    return (
      document.querySelector("main.main") ||
      document.querySelector("#app .main") ||
      document.getElementById("app") ||
      document.body
    );
  }

  function ensureModal() {
    let backdrop = document.getElementById("spendModalBackdrop");
    let modal = document.getElementById("spendModal");
    const host = findModalHost();
    if (backdrop && modal) {
      if (backdrop.parentElement !== host) host.appendChild(backdrop);
      if (modal.parentElement !== host) host.appendChild(modal);
      return { backdrop, modal, host };
    }

    backdrop = el("div", { id: "spendModalBackdrop", class: "thomas-spend-backdrop", hidden: true });
    modal = el("div", {
      id: "spendModal",
      class: "thomas-spend-modal",
      hidden: true,
      role: "dialog",
      "aria-modal": "true",
      "aria-labelledby": "spendModalTitle",
    });

    const header = el("div", { class: "thomas-spend-modal-header" });

    const left = el("div");
    left.appendChild(el("div", { id: "spendModalTitle", class: "thomas-spend-title" }, "Spend"));
    left.appendChild(el("div", { id: "spendModalSubtitle", class: "thomas-spend-subtitle" }, "Today + Session"));
    header.appendChild(left);

    const tabs = el("div", { class: "thomas-spend-tabs", role: "tablist" });
    const tabToday = el("button", { id: "spendTabToday", class: "thomas-spend-tab", type: "button", role: "tab", "aria-selected": "true" }, "Today");
    const tabSession = el("button", { id: "spendTabSession", class: "thomas-spend-tab", type: "button", role: "tab", "aria-selected": "false" }, "Session");
    tabs.appendChild(tabToday);
    tabs.appendChild(tabSession);

    const right = el("div", { style: "display:flex; gap:10px; align-items:center;" });
    right.appendChild(tabs);
    const close = el("button", { id: "spendModalClose", class: "thomas-spend-close", type: "button", "aria-label": "Close" }, "x");
    right.appendChild(close);
    header.appendChild(right);

    const body = el("div", { class: "thomas-spend-modal-body" });

    body.appendChild(el("div", { class: "thomas-spend-row" }, `
      <div class="thomas-spend-metric">
        <div class="thomas-spend-metric-label">
          <span id="spendMetricLeftLabel">Today</span>
          <button id="spendExportCsv" class="thomas-spend-chip" type="button" title="Export last 30 days as CSV">Export CSV</button>
        </div>
        <div id="spendLeftTotal" class="thomas-spend-metric-value">$0.00</div>
        <div id="spendLeftFoot" class="thomas-spend-metric-footnote">0 calls  0 tok</div>
      </div>
      <div class="thomas-spend-metric">
        <div class="thomas-spend-metric-label">
          <span id="spendMetricRightLabel">Session</span>
          <button id="spendResetSession" class="thomas-spend-chip" type="button" title="Reset session counters">Reset</button>
        </div>
        <div id="spendRightTotal" class="thomas-spend-metric-value">$0.00</div>
        <div id="spendRightFoot" class="thomas-spend-metric-footnote">0 calls  0 tok</div>
      </div>
    `));

    body.appendChild(el("div", { class: "thomas-spend-section" }, `
      <div class="thomas-spend-section-title">
        <span>By model</span>
        <small id="spendProjection"></small>
      </div>
      <div class="thomas-spend-by-model-head">
        <div>Model</div><div style="text-align:right;">USD</div><div style="text-align:right;">Tokens</div><div style="text-align:right;">Calls</div>
      </div>
      <div id="spendByModel" class="thomas-spend-by-model"></div>
    `));

    body.appendChild(el("div", { class: "thomas-spend-section" }, `
      <div class="thomas-spend-section-title"><span>Last 7 days</span><small id="spendHistTotal"></small></div>
      <div class="thomas-spend-chart-wrap">
        <canvas id="spendChart" class="thomas-spend-chart" width="720" height="180"></canvas>
        <div id="spendTooltip" class="thomas-spend-tooltip"></div>
      </div>
      <div class="thomas-spend-footer">
        <div id="spendLiveState">Live: connecting</div>
        <div style="opacity:.7;">SSE + polling fallback</div>
      </div>
    `));

    modal.appendChild(header);
    modal.appendChild(body);

    host.appendChild(backdrop);
    host.appendChild(modal);

    return { backdrop, modal, host };
  }

  function openModal() {
    const { backdrop, modal, host } = ensureModal();
    backdrop.hidden = false;
    modal.hidden = false;
    if (host && host.dataset) host.dataset.spendModalOpen = "1";
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    const backdrop = document.getElementById("spendModalBackdrop");
    const modal = document.getElementById("spendModal");
    const host = findModalHost();
    if (backdrop) backdrop.hidden = true;
    if (modal) modal.hidden = true;
    if (host && host.dataset) delete host.dataset.spendModalOpen;
    document.body.style.overflow = "";
  }

  function renderByModel(container, detail) {
    if (!container) return;
    const entries = Object.entries(detail || {});
    if (entries.length === 0) {
      container.innerHTML = `<div class="model">No spend yet.</div><div class="usd"></div><div class="tok"></div><div class="calls"></div>`;
      return;
    }
    container.innerHTML = entries.map(([m, row]) => {
      const usd = formatUSD(row.usd || 0);
      const tok = formatK(row.total_tokens || 0);
      const calls = row.calls || 0;
      return `<div class="model" title="${escapeHTML(m)}">${escapeHTML(m)}</div>
              <div class="usd">${usd}</div>
              <div class="tok">${tok}</div>
              <div class="calls">${calls}</div>`;
    }).join("");
  }

  function drawBarChart(canvas, points) {
    if (!canvas) return { bars: [], total: 0, avg: 0 };
    const ctx = canvas.getContext("2d");
    if (!ctx) return { bars: [], total: 0, avg: 0 };

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const data = (points || []).map(p => ({ date: p.date, usd: Number(p.usd || 0) }));
    const max = Math.max(0.000001, ...data.map(d => d.usd));
    const total = data.reduce((s, d) => s + d.usd, 0);
    const avg = data.length ? total / data.length : 0;

    const padL = 36, padR = 14, padT = 16, padB = 36;
    const innerW = w - padL - padR;
    const innerH = h - padT - padB;
    const n = data.length || 7;
    const step = innerW / n;
    const barW = Math.max(8, step - 14);

    ctx.strokeStyle = "rgba(255,255,255,0.10)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = padT + (innerH * i) / 3;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
    }

    const bars = [];
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";

    for (let i = 0; i < n; i++) {
      const v = data[i] ? data[i].usd : 0;
      const bh = Math.max(0, (v / max) * innerH);
      const x = padL + i * step + (step - barW) / 2;
      const y = padT + (innerH - bh);

      ctx.fillStyle = "rgba(255,255,255,0.28)";
      ctx.fillRect(x, y, barW, bh);

      const label = data[i] ? String(data[i].date).slice(5) : "";
      ctx.fillStyle = "rgba(255,255,255,0.70)";
      ctx.fillText(label, x + barW / 2, h - 12);

      bars.push({ x, y, w: barW, h: bh, date: data[i] ? data[i].date : "", usd: v });
    }

    ctx.fillStyle = "rgba(255,255,255,0.65)";
    ctx.textAlign = "right";
    ctx.fillText(formatUSD(max), w - padR, padT + 11);

    return { bars, total, avg };
  }

  function wireChartTooltip(canvas, bars) {
    if (!canvas) return;
    const tip = document.getElementById("spendTooltip");
    if (!tip) return;

    function hide() { tip.classList.remove("on"); }

    function showAt(x, y, html) {
      tip.innerHTML = html;
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
      tip.classList.add("on");
    }

    canvas.onmousemove = (ev) => {
      const rect = canvas.getBoundingClientRect();
      const mx = (ev.clientX - rect.left) * (canvas.width / rect.width);
      const my = (ev.clientY - rect.top) * (canvas.height / rect.height);

      let hit = null;
      for (const b of (bars || [])) {
        if (mx >= b.x && mx <= (b.x + b.w) && my >= b.y && my <= (b.y + b.h)) { hit = b; break; }
      }
      if (!hit) return hide();

      const x = (hit.x + hit.w / 2) * (rect.width / canvas.width);
      const y = hit.y * (rect.height / canvas.height);
      showAt(x, y, `<div style="opacity:.85;">${escapeHTML(hit.date || "")}</div><div style="font-weight:700;">${formatUSD(hit.usd || 0)}</div>`);
    };

    canvas.onmouseleave = hide;
  }

  function mountBadge() {
    if (document.getElementById("spendBadge")) return document.getElementById("spendBadge");

    const badge = el("button", { id: "spendBadge", class: "thomas-spend-badge", type: "button", title: "Click to view spend details" },
      `<span id="spendBadgeUsd">$0.00 today</span><span id="spendBadgeTok" style="opacity:.75; font-size:12px;">0 tok</span>`
    );

    const header = findHeaderMount();
    if (header) header.appendChild(badge);
    else {
      badge.style.position = "fixed";
      badge.style.top = "12px";
      badge.style.right = "12px";
      badge.style.zIndex = "99997";
      document.body.appendChild(badge);
    }
    return badge;
  }

  function setBadge(today) {
    const usdEl = document.getElementById("spendBadgeUsd");
    const tokEl = document.getElementById("spendBadgeTok");
    if (!today) return;
    if (usdEl) usdEl.textContent = `${formatUSD(today.total_usd)} today`;
    const tok = today.tokens ? today.tokens.total : 0;
    if (tokEl) tokEl.textContent = `${formatK(tok)} tok`;
  }

  async function refreshBadge() {
    try {
      const today = await fetchJSON("/api/spend/today");
      setBadge(today);
    } catch (e) {
      const usdEl = document.getElementById("spendBadgeUsd");
      const tokEl = document.getElementById("spendBadgeTok");
      if (usdEl) usdEl.textContent = "$0.00 today";
      if (tokEl) tokEl.textContent = "offline";
    }
  }

  function setSelectedTab(which) {
    const t1 = document.getElementById("spendTabToday");
    const t2 = document.getElementById("spendTabSession");
    if (t1) t1.setAttribute("aria-selected", which === "today" ? "true" : "false");
    if (t2) t2.setAttribute("aria-selected", which === "session" ? "true" : "false");
  }

  function setLiveState(text) {
    const s = document.getElementById("spendLiveState");
    if (s) s.textContent = text;
  }

  function computeProjectionFromHist(hist) {
    const data = (hist || []).map(p => Number(p.usd || 0));
    const avg = data.length ? data.reduce((a, b) => a + b, 0) / data.length : 0;
    return avg * 30;
  }

  async function refreshModal(which) {
    const leftLabel = document.getElementById("spendMetricLeftLabel");
    const rightLabel = document.getElementById("spendMetricRightLabel");
    const leftTotal = document.getElementById("spendLeftTotal");
    const rightTotal = document.getElementById("spendRightTotal");
    const leftFoot = document.getElementById("spendLeftFoot");
    const rightFoot = document.getElementById("spendRightFoot");
    const byModel = document.getElementById("spendByModel");
    const chart = document.getElementById("spendChart");
    const histTotal = document.getElementById("spendHistTotal");
    const projection = document.getElementById("spendProjection");

    try {
      const [today, session, hist] = await Promise.all([
        fetchJSON("/api/spend/today"),
        fetchJSON("/api/spend/session"),
        fetchJSON("/api/spend/history?days=7"),
      ]);

      setBadge(today);

      if (which === "today") {
        if (leftLabel) leftLabel.textContent = "Today";
        if (rightLabel) rightLabel.textContent = "Session";
        if (leftTotal) leftTotal.textContent = formatUSD(today.total_usd);
        if (rightTotal) rightTotal.textContent = formatUSD(session.total_usd);

        const tTok = today.tokens ? today.tokens.total : 0;
        const sTok = session.tokens ? session.tokens.total : 0;
        if (leftFoot) leftFoot.textContent = `${today.call_count || 0} calls  ${formatK(tTok)} tok`;
        if (rightFoot) rightFoot.textContent = `${session.call_count || 0} calls  ${formatK(sTok)} tok`;

        renderByModel(byModel, today.by_model_detail || {});
      } else {
        if (leftLabel) leftLabel.textContent = "Session";
        if (rightLabel) rightLabel.textContent = "Today";
        if (leftTotal) leftTotal.textContent = formatUSD(session.total_usd);
        if (rightTotal) rightTotal.textContent = formatUSD(today.total_usd);

        const tTok = today.tokens ? today.tokens.total : 0;
        const sTok = session.tokens ? session.tokens.total : 0;
        if (leftFoot) leftFoot.textContent = `${session.call_count || 0} calls  ${formatK(sTok)} tok`;
        if (rightFoot) rightFoot.textContent = `${today.call_count || 0} calls  ${formatK(tTok)} tok`;

        renderByModel(byModel, session.by_model_detail || {});
      }

      const res = drawBarChart(chart, hist || []);
      wireChartTooltip(chart, res.bars);
      if (histTotal) histTotal.textContent = `${formatUSD(res.total)} total  ${formatUSD(res.avg)}/day avg`;
      const proj = computeProjectionFromHist(hist || []);
      if (projection) projection.textContent = `~${formatUSD(proj)} / 30d projection (from 7d avg)`;
    } catch (e) {
      if (leftTotal) leftTotal.textContent = "$0.00";
      if (rightTotal) rightTotal.textContent = "$0.00";
      if (byModel) byModel.innerHTML = `<div class="model">Could not load spend data.</div><div class="usd"></div><div class="tok"></div><div class="calls"></div>`;
      drawBarChart(chart, []);
    }
  }

  function connectLive(onUpdate) {
    try {
      const es = new EventSource("/api/spend/stream");
      es.addEventListener("hello", () => setLiveState("Live: connected"));
      es.addEventListener("spend", (ev) => {
        try {
          const payload = JSON.parse(ev.data || "{}");
          onUpdate(payload);
        } catch {}
      });
      es.onerror = () => {
        setLiveState("Live: unavailable (polling)");
        es.close();
      };
      return () => es.close();
    } catch (e) {
      setLiveState("Live: unavailable (polling)");
      return () => {};
    }
  }

  function wire() {
    mountBadge();
    ensureModal();

    const badge = document.getElementById("spendBadge");
    const backdrop = document.getElementById("spendModalBackdrop");
    const closeBtn = document.getElementById("spendModalClose");
    const tabToday = document.getElementById("spendTabToday");
    const tabSession = document.getElementById("spendTabSession");
    const resetBtn = document.getElementById("spendResetSession");
    const exportBtn = document.getElementById("spendExportCsv");

    let currentTab = "today";
    let modalOpen = false;

    function open() {
      modalOpen = true;
      openModal();
      setSelectedTab(currentTab);
      refreshModal(currentTab);
    }
    function close() {
      modalOpen = false;
      closeModal();
    }

    window.openThomasSpend = open;
    window.closeThomasSpend = close;

    if (badge) badge.addEventListener("click", open);
    if (backdrop) backdrop.addEventListener("click", close);
    if (closeBtn) closeBtn.addEventListener("click", close);

    if (tabToday) tabToday.addEventListener("click", () => {
      currentTab = "today";
      setSelectedTab("today");
      refreshModal("today");
    });

    if (tabSession) tabSession.addEventListener("click", () => {
      currentTab = "session";
      setSelectedTab("session");
      refreshModal("session");
    });

    if (resetBtn) resetBtn.addEventListener("click", async () => {
      try { await fetch("/api/spend/session/reset", { method: "POST" }); } catch {}
      refreshModal(currentTab);
    });

    if (exportBtn) exportBtn.addEventListener("click", () => {
      window.location.href = "/api/spend/export.csv?days=30";
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });

    const stopLive = connectLive(() => {
      if (modalOpen) refreshModal(currentTab);
      else refreshBadge();
    });

    refreshBadge();
    const poll = setInterval(() => {
      if (!modalOpen) refreshBadge();
    }, 15000);

    window.addEventListener("beforeunload", () => {
      try { stopLive(); } catch {}
      try { clearInterval(poll); } catch {}
      try { delete window.openThomasSpend; } catch {}
      try { delete window.closeThomasSpend; } catch {}
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
