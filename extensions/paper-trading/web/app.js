"use strict";
// Paper Trading workspace client. Talks to /api/plugins/paper-trading/*.
// The human approval gate lives here: the Approve button is the only path that
// promotes a proposal and submits it.

const API = "/api/plugins/paper-trading";

const $ = (id) => document.getElementById(id);

function toast(msg, kind) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "pt-toast" + (kind ? " pt-toast-" + kind : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 3200);
}

async function api(path, opts) {
  const res = await fetch(API + path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  const text = await res.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = { error: text }; }
  if (!res.ok) throw new Error(body.error || body.message || text || ("HTTP " + res.status));
  return body;
}

function money(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function pct(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const v = Number(n);
  return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
}

const STATUS_LABEL = {
  pending_approval: "Pending approval",
  blocked_by_risk: "Blocked by risk",
  approved: "Approved",
  rejected: "Rejected",
  submitted: "Submitted",
  filled: "Filled",
  error: "Error",
};

function renderProposals(rows) {
  const wrap = $("proposals");
  if (!rows || !rows.length) { wrap.innerHTML = '<p class="pt-empty">No proposals yet.</p>'; return; }
  wrap.innerHTML = "";
  rows.slice().reverse().forEach((p) => {
    const card = document.createElement("div");
    card.className = "pt-proposal pt-status-" + p.status;
    const size = p.notional ? money(p.notional) : (p.qty ? p.qty + " sh" : "—");
    const violations = (p.risk && p.risk.violations) || [];
    card.innerHTML =
      '<div class="pt-prop-top">' +
        '<span class="pt-side pt-side-' + escapeHtml(p.side) + '">' + escapeHtml(String(p.side).toUpperCase()) + "</span>" +
        '<strong class="pt-sym">' + escapeHtml(p.symbol) + "</strong>" +
        '<span class="pt-prop-size">' + size + " · " + escapeHtml(p.order_type) + "</span>" +
        '<span class="pt-statusbadge">' + escapeHtml(STATUS_LABEL[p.status] || p.status) + "</span>" +
      "</div>" +
      '<div class="pt-thesis"><span>Thesis</span>' + escapeHtml(p.thesis) + "</div>" +
      '<div class="pt-thesis"><span>Invalidation</span>' + escapeHtml(p.invalidation) + "</div>" +
      (violations.length ? '<div class="pt-violations">⚠ ' + violations.map(escapeHtml).join("; ") + "</div>" : "");
    if (p.status === "pending_approval") {
      const actions = document.createElement("div");
      actions.className = "pt-actions";
      const approve = document.createElement("button");
      approve.className = "pt-btn pt-btn-primary";
      approve.textContent = "✓ Approve & submit";
      approve.onclick = () => decide(p.id, true);
      const reject = document.createElement("button");
      reject.className = "pt-btn pt-btn-danger";
      reject.textContent = "✗ Reject";
      reject.onclick = () => decide(p.id, false);
      actions.appendChild(approve);
      actions.appendChild(reject);
      card.appendChild(actions);
    }
    wrap.appendChild(card);
  });
}

async function decide(id, approve) {
  try {
    if (approve) {
      await api("/proposals/" + id + "/approve", { method: "POST", body: JSON.stringify({ submit: true }) });
      toast("Approved & submitted", "ok");
    } else {
      await api("/proposals/" + id + "/reject", { method: "POST", body: JSON.stringify({ note: "rejected by owner" }) });
      toast("Rejected", "muted");
    }
    await refreshAll();
  } catch (e) { toast(e.message, "error"); }
}

function renderTrack(review) {
  const tr = review.track_record || {};
  const wrap = $("trackRecord");
  $("simNote").textContent = review.simulated ? "(simulated)" : "";
  const recent = (review.recent || []).map((l) => '<li>' + escapeHtml(l) + "</li>").join("");
  wrap.innerHTML =
    '<div class="pt-track-stats">' +
      stat("Trades", tr.total || 0) +
      stat("Win rate", (tr.win_rate || 0) + "%") +
      stat("Realized P&L", money(tr.total_realized_pl)) +
      stat("Open P&L", money(tr.total_unrealized_pl)) +
      stat("Thesis ✓/✗", (tr.thesis_validated || 0) + " / " + (tr.thesis_invalidated || 0)) +
    "</div>" +
    (recent ? '<ul class="pt-lessons">' + recent + "</ul>" : "");
}

function stat(label, val) {
  return '<div class="pt-tstat"><span>' + label + "</span><strong>" + val + "</strong></div>";
}

function renderPositions(rows) {
  const wrap = $("positions");
  if (!rows || !rows.length) { wrap.innerHTML = '<p class="pt-empty">No open positions.</p>'; return; }
  wrap.innerHTML = '<table class="pt-table"><thead><tr><th>Symbol</th><th>Qty</th><th>Price</th><th>Value</th><th>P&L</th></tr></thead><tbody>' +
    rows.map((p) =>
      "<tr><td>" + escapeHtml(p.symbol) + "</td><td>" + Number(p.qty).toFixed(2) + "</td><td>" + money(p.current_price) +
      "</td><td>" + money(p.market_value) + '</td><td class="' + (p.unrealized_pl >= 0 ? "pt-pos" : "pt-neg") + '">' +
      money(p.unrealized_pl) + " (" + pct(p.unrealized_plpc) + ")</td></tr>"
    ).join("") + "</tbody></table>";
}

function renderAccount(b) {
  $("modeBadge").textContent = b.simulated ? "simulator" : "live paper";
  $("modeBadge").className = "pt-badge " + (b.simulated ? "pt-badge-sim" : "pt-badge-live");
  $("clockBadge").textContent = "market: " + (b.market_open ? "open" : "closed");
  const acct = b.account || {};
  $("acctEquity").textContent = money(acct.equity);
  $("acctCash").textContent = money(acct.cash);
  $("acctBp").textContent = money(acct.buying_power);
  $("credBanner").hidden = !!b.has_credentials;
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function refreshAll() {
  try {
    const b = await api("/bootstrap");
    renderAccount(b);
    renderProposals(b.proposals);
    renderTrack(b.review);
    renderPositions(b.positions);
  } catch (e) { toast(e.message, "error"); }
}

function wire() {
  $("proposeForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = {
      symbol: $("pSymbol").value.trim().toUpperCase(),
      side: $("pSide").value,
      thesis: $("pThesis").value.trim(),
      invalidation: $("pInvalidation").value.trim(),
    };
    const notional = parseFloat($("pNotional").value);
    const qty = parseFloat($("pQty").value);
    if (notional > 0) body.notional = notional;
    else if (qty > 0) body.qty = qty;
    else { toast("Enter a dollar amount or share count", "error"); return; }
    try {
      const p = await api("/proposals", { method: "POST", body: JSON.stringify(body) });
      toast(p.status === "blocked_by_risk" ? "Blocked by risk rules" : "Proposal created", p.status === "blocked_by_risk" ? "error" : "ok");
      $("proposeForm").reset();
      await refreshAll();
    } catch (e) { toast(e.message, "error"); }
  });

  $("quoteForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const sym = $("qSymbol").value.trim().toUpperCase();
    if (!sym) return;
    try {
      const q = await api("/quote?symbol=" + encodeURIComponent(sym));
      $("quoteOut").innerHTML = "<strong>" + q.symbol + "</strong> " + money(q.price) +
        ' <span class="pt-hint">bid ' + money(q.bid) + " / ask " + money(q.ask) + " · " + q.feed + "</span>";
    } catch (e) { toast(e.message, "error"); }
  });

  $("credForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/credentials", { method: "POST", body: JSON.stringify({ key_id: $("credKey").value.trim(), secret_key: $("credSecret").value.trim() }) });
      toast("Keys saved", "ok");
      await refreshAll();
    } catch (e) { toast(e.message, "error"); }
  });

  $("reconcileBtn").addEventListener("click", async () => {
    try { await api("/reconcile", { method: "POST", body: "{}" }); toast("Reconciled & scored", "ok"); await refreshAll(); }
    catch (e) { toast(e.message, "error"); }
  });
  $("refreshProposals").addEventListener("click", refreshAll);
}

wire();
refreshAll();
