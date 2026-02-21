/*
Swarm Board (vanilla JS, no deps)

Goals:
- Rich progress UI for Swarm Mode NDJSON events.
- Left: task DAG list + dependency edges (simple SVG).
- Right: per-agent tabs with live logs + tool timeline.
- Click a task to focus logs/tools on that task.
- Cancel button calls POST /api/runs/{run_id}/cancel (localhost-only server endpoint).

This file is self-contained so it can be integrated into Thomas' existing UI stack
(store.js / components.js / inspector.js) with minimal friction.

Expected events:
- swarm_start: {graph:{tasks:[{id,title,agent,deps}...]}}
- task_update: {status,title,agent,deps,blocked_by?,duration_ms?}
- agent_text: {text}
- agent_tool_start / agent_tool_result: {tool_call_id, tool, args, mutates_fs, ok?, result?, error?, took_ms?}
- swarm_done: {ok, final, summary, error?}
*/
(function () {
  const SERVER_TOKEN_STORAGE_KEY = "thomas.serverApiToken";

  function esc(s) {
    return (s ?? "").toString()
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function byId(id) {
    const el = document.getElementById(id);
    if (!el) throw new Error("SwarmBoard missing element #" + id);
    return el;
  }

  function nowMs() {
    return Date.now();
  }

  function fmtMs(ms) {
    if (ms == null) return "";
    if (ms < 1000) return `${ms}ms`;
    const s = (ms / 1000).toFixed(2);
    return `${s}s`;
  }

  const STATUS_CLASS = {
    queued: "swarm-status-queued",
    running: "swarm-status-running",
    done: "swarm-status-done",
    failed: "swarm-status-failed",
    cancelled: "swarm-status-cancelled",
    blocked: "swarm-status-blocked",
  };

  function readServerToken() {
    try {
      return String(window.localStorage.getItem(SERVER_TOKEN_STORAGE_KEY) || "").trim();
    } catch {
      return "";
    }
  }

  function withAuth(opts = {}) {
    const headers = new Headers(opts.headers || {});
    const token = readServerToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return { ...opts, headers };
  }

  class SwarmBoard {
    constructor(rootEl, opts = {}) {
      this.root = rootEl;
      this.opts = {
        cancelUrl: (runId) => `/api/runs/${encodeURIComponent(runId)}/cancel`,
        ...opts,
      };

      this.runs = new Map(); // run_id -> state
      this.activeRunId = null;
      this.activeAgentId = null;
      this.activeTaskId = null;

      this._edgeRaf = null;

      this._renderShell();
      this._wire();
    }

    _renderShell() {
      this.root.innerHTML = `
        <div class="swarm-wrap">
          <div class="swarm-left">
            <div class="swarm-header">
              <div class="swarm-title">
                <div class="swarm-h1">Swarm Board</div>
                <div class="swarm-sub" id="swarmRunMeta">No active swarm</div>
              </div>
              <div class="swarm-actions">
                <button class="btn" id="swarmCancelBtn" disabled>Cancel</button>
              </div>
            </div>

            <div class="swarm-graph">
              <div class="swarm-graph-title">Task graph</div>
              <div class="swarm-graph-body">
                <div class="swarm-tasklist-wrap">
                  <svg class="swarm-edges" id="swarmEdges" aria-hidden="true"></svg>
                  <div class="swarm-tasklist" id="swarmTaskList"></div>
                </div>
              </div>
            </div>
          </div>

          <div class="swarm-right">
            <div class="swarm-right-top">
              <div class="swarm-tabs" id="swarmAgentTabs"></div>
              <div class="swarm-focus" id="swarmFocus"></div>
            </div>

            <div class="swarm-panels">
              <div class="swarm-panel">
                <div class="swarm-panel-title" id="swarmPanelTitle">Agent output</div>
                <pre class="swarm-log" id="swarmAgentLog"></pre>
              </div>
              <div class="swarm-panel">
                <div class="swarm-panel-title">Tools timeline</div>
                <div class="swarm-tools" id="swarmTools"></div>
              </div>
            </div>

            <div class="swarm-final" id="swarmFinal"></div>
          </div>
        </div>
      `;
    }

    _wire() {
      const cancelBtn = byId("swarmCancelBtn");
      cancelBtn.addEventListener("click", async () => {
        const runId = this.activeRunId;
        if (!runId) return;
        cancelBtn.disabled = true;
        try {
          const r = await fetch(this.opts.cancelUrl(runId), withAuth({ method: "POST" }));
          // even if it fails, the orchestrator might still stop; re-enable so user can retry.
          await r.text();
        } catch (e) {}
        setTimeout(() => { cancelBtn.disabled = false; }, 500);
      });
    }

    _ensureRun(runId) {
      if (!this.runs.has(runId)) {
        this.runs.set(runId, {
          run_id: runId,
          started_at_ms: nowMs(),
          graph: null,
          tasks: new Map(), // task_id -> {id,title,agent,deps,status,...}
          agents: new Map(), // agent_id -> {logByTask: Map(task_id->string), toolCalls: []}
          final: null,
          done: false,
        });
      }
      return this.runs.get(runId);
    }

    ingest(evt) {
      if (!evt || !evt.type || !evt.run_id) return;
      const runId = evt.run_id;
      const run = this._ensureRun(runId);
      this.activeRunId = runId;

      byId("swarmCancelBtn").disabled = false;
      byId("swarmRunMeta").textContent = `run ${runId}  seq ${evt.seq ?? "?"}`;

      const agentId = evt.agent_id || "orchestrator";
      const taskId = evt.task_id || "__swarm__";

      if (!run.agents.has(agentId)) {
        run.agents.set(agentId, { agent_id: agentId, logByTask: new Map(), toolCalls: [] });
        this._renderAgentTabs(run);
      }

      switch (evt.type) {
        case "swarm_start": {
          run.graph = evt.graph || null;
          this._renderGraph(run);
          this._scheduleEdgeRender();
          break;
        }
        case "task_update": {
          const t = run.tasks.get(taskId) || { id: taskId, title: evt.title || taskId, agent: evt.agent || agentId, deps: evt.deps || [] };
          t.title = evt.title || t.title;
          t.agent = evt.agent || t.agent;
          t.deps = evt.deps || t.deps;
          t.status = evt.status || t.status || "queued";
          t.ok = evt.ok;
          t.error = evt.error;
          t.blocked_by = evt.blocked_by;
          t.duration_ms = evt.duration_ms;
          run.tasks.set(taskId, t);
          this._renderTaskRow(run, t);
          this._scheduleEdgeRender();
          break;
        }
        case "agent_text": {
          const a = run.agents.get(agentId);
          const cur = a.logByTask.get(taskId) || "";
          a.logByTask.set(taskId, cur + (evt.text || ""));
          this._maybeRefreshRight(run);
          break;
        }
        case "agent_tool_start": {
          const a = run.agents.get(agentId);
          a.toolCalls.push({ phase: "start", at: nowMs(), ...evt });
          this._maybeRefreshRight(run);
          break;
        }
        case "agent_tool_result": {
          const a = run.agents.get(agentId);
          a.toolCalls.push({ phase: "result", at: nowMs(), ...evt });
          this._maybeRefreshRight(run);
          break;
        }
        case "swarm_done": {
          run.done = true;
          run.final = evt.final || "";
          run.summary = evt.summary || null;
          run.error = evt.error || null;
          this._renderFinal(run, evt);
          break;
        }
      }

      // default focus: first agent with output; default task: none
      if (!this.activeAgentId) this.activeAgentId = agentId;
      this._renderFocus(run);
      this._maybeRefreshRight(run);
    }

    _renderAgentTabs(run) {
      const tabs = byId("swarmAgentTabs");
      const agents = Array.from(run.agents.keys()).sort();
      tabs.innerHTML = agents.map(a => {
        const active = (a === this.activeAgentId) ? "swarm-tab-active" : "";
        return `<button class="swarm-tab ${active}" data-agent="${esc(a)}">${esc(a)}</button>`;
      }).join("");

      tabs.querySelectorAll(".swarm-tab").forEach(btn => {
        btn.addEventListener("click", () => {
          this.activeAgentId = btn.getAttribute("data-agent");
          this._renderAgentTabs(run);
          this._maybeRefreshRight(run, true);
        });
      });
    }

    _renderGraph(run) {
      const list = byId("swarmTaskList");
      list.innerHTML = "";

      // Prefer planner ordering if provided; else lexical order.
      const ordered = [];
      if (run.graph && Array.isArray(run.graph.tasks)) {
        for (const t of run.graph.tasks) ordered.push(t.id);
      } else {
        ordered.push(...Array.from(run.tasks.keys()).sort());
      }

      for (const tid of ordered) {
        const t = run.tasks.get(tid) || { id: tid, title: tid, agent: "?", deps: [] };
        run.tasks.set(tid, t);
        const row = document.createElement("div");
        row.className = "swarm-taskrow swarm-status-queued";
        row.id = `swarmTask_${tid}`;
        row.dataset.taskId = tid;
        row.innerHTML = `
          <div class="swarm-task-main">
            <div class="swarm-task-title">${esc(t.title)}</div>
            <div class="swarm-task-meta">
              <span class="swarm-pill">${esc(tid)}</span>
              <span class="swarm-pill">${esc(t.agent || "?")}</span>
              <span class="swarm-pill swarm-deps">${esc((t.deps || []).join(", "))}</span>
            </div>
          </div>
          <div class="swarm-task-status" title="status">${esc(t.status || "queued")}</div>
        `;
        row.addEventListener("click", () => {
          this.activeTaskId = tid;
          this._renderFocus(run);
          this._maybeRefreshRight(run, true);
        });
        list.appendChild(row);
      }
    }

    _renderTaskRow(run, t) {
      // If task list not yet created, build graph view now.
      if (!document.getElementById(`swarmTask_${t.id}`)) {
        this._renderGraph(run);
      }
      const row = document.getElementById(`swarmTask_${t.id}`);
      if (!row) return;

      const status = t.status || "queued";
      row.className = `swarm-taskrow ${STATUS_CLASS[status] || "swarm-status-queued"}`;
      row.querySelector(".swarm-task-title").textContent = t.title || t.id;
      row.querySelector(".swarm-task-status").textContent = status;

      const pills = row.querySelectorAll(".swarm-pill");
      if (pills[1]) pills[1].textContent = t.agent || "?";
      if (pills[2]) pills[2].textContent = (t.deps || []).join(", ") || "no deps";

      if (t.error) row.setAttribute("title", t.error);
      if (t.blocked_by) row.setAttribute("title", `blocked by ${t.blocked_by}`);
    }

    _renderFocus(run) {
      const focus = byId("swarmFocus");
      const task = this.activeTaskId ? run.tasks.get(this.activeTaskId) : null;

      if (task) {
        focus.innerHTML = `
          <div class="swarm-focus-inner">
            <div class="swarm-focus-title">Focus: ${esc(task.id)}  ${esc(task.title || "")}</div>
            <div class="swarm-focus-meta">
              <span class="swarm-pill">${esc(task.agent || "?")}</span>
              <span class="swarm-pill">${esc(task.status || "")}</span>
              ${task.duration_ms != null ? `<span class="swarm-pill">${esc(fmtMs(task.duration_ms))}</span>` : ""}
              <button class="swarm-clear" id="swarmClearFocus">clear</button>
            </div>
          </div>
        `;
        byId("swarmClearFocus").addEventListener("click", () => {
          this.activeTaskId = null;
          this._renderFocus(run);
          this._maybeRefreshRight(run, true);
        });
      } else {
        focus.innerHTML = `<div class="swarm-focus-inner"><div class="swarm-focus-title">Focus: none</div></div>`;
      }
    }

    _maybeRefreshRight(run, force = false) {
      if (!run) return;
      if (!this.activeAgentId) this.activeAgentId = Array.from(run.agents.keys())[0] || "orchestrator";
      const agent = run.agents.get(this.activeAgentId);
      if (!agent) return;

      // Render agent log
      const logEl = byId("swarmAgentLog");
      const titleEl = byId("swarmPanelTitle");

      if (this.activeTaskId) {
        titleEl.textContent = `Output  ${this.activeAgentId}  task ${this.activeTaskId}`;
        logEl.textContent = agent.logByTask.get(this.activeTaskId) || "";
      } else {
        titleEl.textContent = `Output  ${this.activeAgentId}  all tasks`;
        // concatenate per-task logs in a stable order
        const parts = [];
        const keys = Array.from(agent.logByTask.keys()).sort();
        for (const tid of keys) {
          const t = run.tasks.get(tid);
          parts.push(`\n=== ${tid}${t && t.title ? "  " + t.title : ""} ===\n`);
          parts.push(agent.logByTask.get(tid) || "");
        }
        logEl.textContent = parts.join("");
      }

      // Render tool timeline
      const toolsEl = byId("swarmTools");
      const calls = agent.toolCalls || [];
      const filtered = this.activeTaskId ? calls.filter(c => c.task_id === this.activeTaskId) : calls;

      toolsEl.innerHTML = filtered.slice(-200).map(c => {
        const ok = c.ok === true ? "ok" : (c.ok === false ? "err" : "start");
        const head = `${esc(c.tool || "")}  ${esc(ok)}  ${esc(c.tool_call_id || "")}`;
        const detailObj = (c.phase === "result")
          ? (c.ok ? c.result : { error: c.error })
          : { args: c.args, mutates_fs: c.mutates_fs };
        const detail = esc(JSON.stringify(detailObj, null, 2));
        const took = c.took_ms != null ? `<span class="swarm-pill">${esc(fmtMs(c.took_ms))}</span>` : "";
        return `
          <details class="swarm-tool ${ok}">
            <summary>
              <span class="swarm-tool-head">${head}</span>
              ${took}
            </summary>
            <pre class="swarm-tool-pre">${detail}</pre>
          </details>
        `;
      }).join("");
    }

    _renderFinal(run, evt) {
      const finalEl = byId("swarmFinal");
      const ok = !!evt.ok;
      const header = ok ? "Swarm complete" : "Swarm failed";
      const err = evt.error ? `<div class="swarm-final-err">${esc(evt.error)}</div>` : "";
      const finalText = run.final || "";
      const summary = run.summary ? esc(JSON.stringify(run.summary, null, 2)) : "";
      finalEl.innerHTML = `
        <div class="swarm-final-card">
          <div class="swarm-final-head">${esc(header)}</div>
          ${err}
          <pre class="swarm-final-pre">${esc(finalText)}</pre>
          ${summary ? `<details class="swarm-final-details"><summary>Run summary</summary><pre>${summary}</pre></details>` : ""}
        </div>
      `;
    }

    _scheduleEdgeRender() {
      if (this._edgeRaf) return;
      this._edgeRaf = requestAnimationFrame(() => {
        this._edgeRaf = null;
        try {
          this._renderEdges();
        } catch (e) {}
      });
    }

    _renderEdges() {
      const run = this.activeRunId ? this.runs.get(this.activeRunId) : null;
      if (!run) return;

      const svg = byId("swarmEdges");
      const list = byId("swarmTaskList");
      const rows = list.querySelectorAll(".swarm-taskrow");
      if (!rows.length) return;

      // compute row midpoints in list-local coordinates
      const listRect = list.getBoundingClientRect();
      const pos = new Map(); // task_id -> {x,y}
      rows.forEach(r => {
        const tid = r.dataset.taskId;
        const rect = r.getBoundingClientRect();
        const x = 12; // left gutter
        const y = (rect.top - listRect.top) + rect.height / 2;
        pos.set(tid, { x, y });
      });

      const lines = [];
      for (const [tid, t] of run.tasks.entries()) {
        if (!t.deps || !t.deps.length) continue;
        const p2 = pos.get(tid);
        if (!p2) continue;
        for (const dep of t.deps) {
          const p1 = pos.get(dep);
          if (!p1) continue;
          // simple elbow: from dep -> left gutter -> down/up -> to task
          const x1 = p1.x, y1 = p1.y;
          const x2 = p2.x, y2 = p2.y;
          const mx = 2; // very left edge
          lines.push(`<path d="M ${x1} ${y1} L ${mx} ${y1} L ${mx} ${y2} L ${x2} ${y2}" />`);
        }
      }

      const height = Math.max(0, list.scrollHeight);
      svg.setAttribute("viewBox", `0 0 24 ${height}`);
      svg.setAttribute("width", "24");
      svg.setAttribute("height", height.toString());
      svg.innerHTML = lines.join("");
    }
  }

  window.SwarmBoard = SwarmBoard;
})();
