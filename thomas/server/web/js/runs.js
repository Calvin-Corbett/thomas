
import { apiGet, apiStreamNDJSON } from "./api.js";
import { inspectorConsumeEvent, inspectorReset, inspectorSetRunId } from "./inspector_bridge.js";

function el(tag, attrs = {}, ...children){
  const n = document.createElement(tag);
  for (const [k,v] of Object.entries(attrs)){
    if (k === "class") n.className = v;
    else if (k === "style") n.setAttribute("style", v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children){
    if (c == null) continue;
    if (typeof c === "string") n.appendChild(document.createTextNode(c));
    else n.appendChild(c);
  }
  return n;
}

function fmtTs(iso){
  if (!iso) return "";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function pill(text, cls){ return el("span", {class: `pill ${cls||""}`.trim()}, text); }

function button(text, onClick, cls="btn"){
  return el("button", {class: cls, onclick: onClick, type:"button"}, text);
}

function input(attrs){ return el("input", Object.assign({type:"text"}, attrs)); }

function select(options, attrs){
  const s = el("select", attrs||{});
  for (const opt of options){
    const o = el("option", {value: opt.value}, opt.label);
    s.appendChild(o);
  }
  return s;
}

function copyToClipboard(text){
  try { navigator.clipboard.writeText(text); } catch {}
}

async function fetchRuns(state){
  const qp = new URLSearchParams();
  qp.set("limit", String(state.limit));
  qp.set("offset", String(state.offset));
  if (state.profile) qp.set("profile", state.profile);
  if (state.mode) qp.set("mode", state.mode);
  if (state.ok !== "") qp.set("ok", state.ok);
  if (state.q) qp.set("q", state.q);
  const data = await apiGet(`/api/runs?${qp.toString()}`);
  return data.runs || [];
}

async function replayRun(runId, statusEl){
  inspectorReset();
  inspectorSetRunId(runId);
  statusEl.textContent = `Replaying run ${runId} ...`;

  const url = `/api/runs/${encodeURIComponent(runId)}/replay`;
  await apiStreamNDJSON(url, (obj) => {
    inspectorConsumeEvent(obj);
    if (obj && obj.type === "run_start" && obj.run_id) inspectorSetRunId(obj.run_id);
  });

  statusEl.textContent = `Replay complete for ${runId}`;
}

export function mountRunsView(container){
  container.innerHTML = "";

  const state = { limit: 50, offset: 0, profile: "", mode: "", ok: "", q: "" };

  const title = el("div", {class:"runs-title"},
    el("div", {class:"h1"}, "Runs"),
    el("div", {class:"muted"}, "Recorded /api/chat runs. Replay without calling a model.")
  );

  const statusEl = el("div", {class:"runs-status muted"}, "");

  const profileInp = input({placeholder:"profile", class:"input"});
  const modeInp = input({placeholder:"mode", class:"input"});
  const okSel = select([
    {value:"", label:"ok: any"},
    {value:"1", label:"ok: true"},
    {value:"0", label:"ok: false"},
  ], {class:"select"});

  const qInp = input({placeholder:"search text in events", class:"input", style:"min-width:260px"});
  const refreshBtn = button("Refresh", async () => { await load(); }, "btn");
  const nextBtn = button("Next", async () => { state.offset += state.limit; await load(); }, "btn");
  const prevBtn = button("Prev", async () => { state.offset = Math.max(0, state.offset - state.limit); await load(); }, "btn");

  const filtersRow = el("div", {class:"runs-filters"},
    profileInp, modeInp, okSel, qInp,
    refreshBtn, prevBtn, nextBtn
  );

  const table = el("div", {class:"runs-table"});

  container.appendChild(title);
  container.appendChild(filtersRow);
  container.appendChild(statusEl);
  container.appendChild(table);

  async function load(){
    state.profile = profileInp.value.trim();
    state.mode = modeInp.value.trim();
    state.ok = okSel.value;
    state.q = qInp.value.trim();

    statusEl.textContent = "Loading…";
    table.innerHTML = "";

    let runs = [];
    try { runs = await fetchRuns(state); }
    catch (e){
      statusEl.textContent = "Failed to load runs.";
      table.appendChild(el("div", {class:"muted"}, String(e)));
      return;
    }

    statusEl.textContent = `Showing ${runs.length} runs (offset ${state.offset})`;
    if (!runs.length){
      table.appendChild(el("div", {class:"muted"}, "No runs found."));
      return;
    }

    for (const r of runs){
      const ok = r.ok === true ? pill("ok", "pill-ok") : (r.ok === false ? pill("fail","pill-fail") : pill("?", "pill-unknown"));
      const runId = r.run_id;

      const row = el("div", {class:"run-row"},
        el("div", {class:"run-main"},
          el("div", {class:"run-top"},
            ok,
            el("span", {class:"run-id"}, runId),
            button("Copy", () => copyToClipboard(runId), "btn btn-small"),
            button("Replay", () => replayRun(runId, statusEl), "btn btn-small"),
            el("a", {class:"btn btn-small", href:`/api/runs/${encodeURIComponent(runId)}/export`, target:"_blank", rel:"noreferrer"}, "Export")
          ),
          el("div", {class:"run-meta muted"},
            `session=${r.session_id || ""}  profile=${r.profile || ""}  mode=${r.mode || ""}  model=${r.model_id || ""}  started=${fmtTs(r.started_at)}`
          )
        )
      );

      table.appendChild(row);
    }
  }

  load();
}
