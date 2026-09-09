const $ = (id) => document.getElementById(id);

function getToken() {
  const t = $("token").value || localStorage.getItem("autonomy_token") || "";
  if ($("token").value) localStorage.setItem("autonomy_token", $("token").value);
  return t.trim();
}

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(path, { ...opts, headers });
  const txt = await res.text();
  let data;
  try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
  if (!res.ok) throw new Error((data && data.error) ? data.error : (txt || res.status));
  return data;
}

function pill(text, cls="") {
  const s = document.createElement("span");
  s.className = "pill " + cls;
  s.textContent = text;
  return s;
}

function statusClass(status) {
  if (status === "succeeded") return "good";
  if (status === "queued" || status === "running") return "warn";
  if (status === "awaiting_approval") return "warn";
  if (status === "dead" || status === "failed") return "bad";
  return "";
}

function el(tag, cls="", text="") {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

function renderApprovals(list) {
  const wrap = $("approvals");
  wrap.innerHTML = "";
  if (!list.length) {
    wrap.appendChild(el("div", "hint", "No pending approvals."));
    return;
  }
  list.forEach(a => {
    const item = el("div", "item");
    const meta = el("div", "meta");
    meta.appendChild(pill("pending", "warn"));
    meta.appendChild(pill("risk: " + a.risk_class, a.risk_class === "low" ? "good" : "warn"));
    meta.appendChild(pill("job: " + a.job_id.slice(0, 10) + "…"));
    item.appendChild(meta);

    const pre = el("pre", "pre");
    pre.textContent = JSON.stringify(a.action, null, 2);
    item.appendChild(pre);

    const actions = el("div", "actions");
    const ok = el("button", "", "Approve");
    const no = el("button", "", "Deny");
    ok.onclick = async () => {
      await api(`/api/autonomy/approvals/${a.id}/decide`, { method: "POST", body: JSON.stringify({ approve: true, actor: "ui" })});
      await refreshAll();
    };
    no.onclick = async () => {
      const reason = prompt("Reason (optional):") || "";
      await api(`/api/autonomy/approvals/${a.id}/decide`, { method: "POST", body: JSON.stringify({ approve: false, actor: "ui", reason })});
      await refreshAll();
    };
    actions.appendChild(ok);
    actions.appendChild(no);
    item.appendChild(actions);

    wrap.appendChild(item);
  });
}

function renderJobs(list) {
  const wrap = $("jobs");
  wrap.innerHTML = "";
  if (!list.length) {
    wrap.appendChild(el("div", "hint", "No jobs."));
    return;
  }
  list.forEach(j => {
    const item = el("div", "item");
    const meta = el("div", "meta");
    meta.appendChild(pill(j.status, statusClass(j.status)));
    meta.appendChild(pill(j.kind));
    meta.appendChild(pill("risk: " + j.risk_class, j.risk_class === "low" ? "good" : "warn"));
    meta.appendChild(pill("attempts: " + (j.attempts || 0)));
    if (j.next_run_at) meta.appendChild(pill("next: " + j.next_run_at));
    item.appendChild(meta);

    item.appendChild(el("div", "", j.name || j.id));

    if (j.error) {
      const pre = el("pre", "pre");
      pre.textContent = JSON.stringify(j.error, null, 2);
      item.appendChild(pre);
    }

    const actions = el("div", "actions");
    const run = el("button", "", "Run now");
    run.onclick = async () => {
      await api(`/api/autonomy/jobs/${j.id}/run_now`, { method: "POST", body: "{}" });
      await refreshJobs();
    };
    const cancel = el("button", "", "Cancel");
    cancel.onclick = async () => {
      await api(`/api/autonomy/jobs/${j.id}/cancel`, { method: "POST", body: "{}" });
      await refreshJobs();
    };
    const audit = el("button", "", "Audit");
    audit.onclick = async () => {
      $("auditJobId").value = j.id;
      await refreshAudit();
    };
    actions.appendChild(run);
    actions.appendChild(cancel);
    actions.appendChild(audit);
    item.appendChild(actions);

    wrap.appendChild(item);
  });
}

function renderMessages(list) {
  const wrap = $("messages");
  wrap.innerHTML = "";
  if (!list.length) {
    wrap.appendChild(el("div", "hint", "No messages yet."));
    return;
  }
  list.forEach(m => {
    const item = el("div", "item");
    const meta = el("div", "meta");
    meta.appendChild(pill(m.level || "info", (m.level === "error") ? "bad" : "good"));
    meta.appendChild(pill(m.ts));
    if (m.session_id) meta.appendChild(pill("session: " + m.session_id));
    item.appendChild(meta);
    item.appendChild(el("div", "", m.text));
    wrap.appendChild(item);
  });
}

function renderBriefings(list) {
  const wrap = $("briefings");
  wrap.innerHTML = "";
  if (!list.length) {
    wrap.appendChild(el("div", "hint", "No briefings yet."));
    return;
  }
  list.forEach(b => {
    const item = el("div", "item");
    const meta = el("div", "meta");
    meta.appendChild(pill(b.ts));
    item.appendChild(meta);
    const pre = el("pre", "pre");
    pre.textContent = JSON.stringify(b.content, null, 2);
    item.appendChild(pre);
    wrap.appendChild(item);
  });
}

async function refreshApprovals() {
  const data = await api("/api/autonomy/approvals?status=pending&limit=200");
  renderApprovals(data.approvals || []);
}

async function refreshJobs() {
  const status = $("statusFilter").value;
  const qs = status ? ("?status=" + encodeURIComponent(status) + "&limit=200") : "?limit=200";
  const data = await api("/api/autonomy/jobs" + qs);
  renderJobs(data.jobs || []);
}

async function refreshAudit() {
  const jobId = $("auditJobId").value.trim();
  const qs = jobId ? ("?job_id=" + encodeURIComponent(jobId) + "&limit=400") : "?limit=400";
  const data = await api("/api/autonomy/audit" + qs);
  $("audit").textContent = JSON.stringify(data.events || [], null, 2);
}

async function refreshMessages() {
  const data = await api("/api/autonomy/messages?limit=200");
  renderMessages(data.messages || []);
}

async function refreshBriefings() {
  const data = await api("/api/autonomy/briefings?limit=30");
  renderBriefings(data.briefings || []);
}

async function refreshAll() {
  await Promise.all([refreshApprovals(), refreshJobs(), refreshMessages(), refreshBriefings()]);
}

function setupCreateForm() {
  function updateKindFields() {
    const kind = $("kind").value;
    $("reminderTextWrap").style.display = (kind === "reminder") ? "grid" : "none";
    $("briefPromptWrap").style.display = (kind === "daily_briefing") ? "grid" : "none";
    $("goalWrap").style.display = (kind === "autonomy_task") ? "grid" : "none";
    $("contextWrap").style.display = (kind === "autonomy_task") ? "grid" : "none";
    $("payloadWrap").style.display = (kind === "reminder") ? "none" : "grid";
  }
  $("kind").addEventListener("change", updateKindFields);
  updateKindFields();

  $("create").onclick = async () => {
    const kind = $("kind").value;
    const risk_class = $("riskClass").value;
    const run_at = $("runAt").value.trim();
    let schedule = $("schedule").value.trim();
    let scheduleObj = null;

    if (schedule) {
      try { scheduleObj = JSON.parse(schedule); } catch (e) { alert("Invalid schedule JSON"); return; }
    }

    const name = $("jobName").value.trim() || kind;
    const session_id = $("sessionId").value.trim() || null;
    const requires_approval = !!$("requiresApproval").checked;

    const payload = {};
    if (kind === "reminder") {
      payload.text = $("reminderText").value;
    } else if (kind === "daily_briefing") {
      const p = $("briefPrompt").value.trim();
      if (p) payload.prompt = p;
    } else if (kind === "autonomy_task") {
      payload.goal = $("goal").value.trim();
      const ctx = $("context").value.trim();
      if (ctx) payload.context = ctx;
    }

    // Advanced: merge additional payload JSON
    const extra = $("payloadJson").value.trim();
    if (extra) {
      let obj;
      try { obj = JSON.parse(extra); } catch { alert("Invalid payload JSON"); return; }
      if (obj && typeof obj === "object") Object.assign(payload, obj);
    }

    const body = { name, kind, payload, risk_class, requires_approval };
    if (run_at) body.run_at = run_at;
    if (scheduleObj) body.schedule = scheduleObj;
    if (session_id) body.session_id = session_id;

    await api("/api/autonomy/jobs", { method: "POST", body: JSON.stringify(body) });
    $("reminderText").value = "";
    $("briefPrompt").value = "";
    $("goal").value = "";
    $("context").value = "";
    $("payloadJson").value = "";
    $("runAt").value = "";
    await refreshAll();
  };
}

function setupButtons() {
  $("refresh").onclick = refreshAll;
  $("wakeup").onclick = async () => { await api("/api/autonomy/wakeup", { method: "POST", body: "{}" }); };
  $("auditLoad").onclick = refreshAudit;
  $("statusFilter").onchange = refreshJobs;
}

window.addEventListener("load", async () => {
  const stored = localStorage.getItem("autonomy_token");
  if (stored) $("token").value = stored;
  setupCreateForm();
  setupButtons();
  await refreshAll();
});
