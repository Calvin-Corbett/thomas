/* ============================================================
   Thomas Inspector
   ============================================================
   Right panel with tabs: Run, Jobs, Trace, Tools, Memory, Artifacts, Files.
   ============================================================ */

import { getState, subscribe, setState, setActiveChat } from './store.js';
import {
  fetchTools,
  fetchMemory,
  setMemoryPin,
  clearMemoryPin,
  fetchMemoryContradictions,
  resolveMemoryContradiction,
} from './api.js';
import { el, formatDuration, formatNumber } from './utils.js';
import { createTabs, createEmptyState } from './components.js';
import { setSwarmContainer } from './swarm.js';
import { cancelJob, scrollToMessage } from './chat.js';

let _tabsEl = null;
let _bodyEl = null;
let _tabSystem = null;
let _memoryLoadNonce = 0;

const TABS = [
  { id: 'run', label: 'Run' },
  { id: 'jobs', label: 'Jobs' },
  { id: 'trace', label: 'Trace' },
  { id: 'tools', label: 'Tools' },
  { id: 'memory', label: 'Memory' },
  { id: 'swarm', label: 'Swarm' },
  { id: 'artifacts', label: 'Artifacts' },
  { id: 'files', label: 'Files' },
];

export function initInspector() {
  _tabsEl = document.getElementById('inspectorTabs');
  _bodyEl = document.getElementById('inspectorBody');

  if (!_tabsEl || !_bodyEl) return;

  // Create tab system
  _tabSystem = createTabs({
    tabs: TABS,
    activeId: getState().ui.inspectorTab,
    onSwitch: (tabId) => {
      setState('ui', { inspectorTab: tabId });
      renderTabContent(tabId);
    },
  });
  _tabsEl.appendChild(_tabSystem.container);

  // Subscribe to state
  subscribe('activeRun', () => {
    const tab = getState().ui.inspectorTab;
    if (tab === 'run' || tab === 'trace') renderTabContent(tab);
  });
  subscribe('jobs', () => {
    if (getState().ui.inspectorTab === 'jobs') renderTabContent('jobs');
  });
  subscribe('tools', () => {
    if (getState().ui.inspectorTab === 'tools') renderTabContent('tools');
  });
  subscribe('ui', () => {
    _tabSystem?.setActive(getState().ui.inspectorTab);
  });
  subscribe('activeChatId', () => {
    if (getState().ui.inspectorTab === 'memory') renderTabContent('memory');
  });

  // Load tools
  loadTools();

  renderTabContent(getState().ui.inspectorTab);
}

async function loadTools() {
  try {
    const data = await fetchTools();
    setState('tools', data.tools || []);
  } catch {
    // Tools endpoint may not exist yet; that's fine
  }
}

function renderTabContent(tabId) {
  if (!_bodyEl) return;
  _bodyEl.innerHTML = '';

  switch (tabId) {
    case 'run': renderRunTab(); break;
    case 'jobs': renderJobsTab(); break;
    case 'trace': renderTraceTab(); break;
    case 'tools': renderToolsTab(); break;
    case 'memory': renderMemoryTab(); break;
    case 'swarm': renderSwarmTab(); break;
    case 'artifacts': renderPlaceholder('Artifacts', 'Generated files, documents, images, and tables.'); break;
    case 'files': renderPlaceholder('Files', 'Workspace file browser for uploads and generated outputs.'); break;
  }
}

function renderJobsTab() {
  const jobs = Array.isArray(getState().jobs) ? getState().jobs.slice() : [];
  if (jobs.length === 0) {
    _bodyEl.appendChild(createEmptyState({
      icon: '\u23F1\uFE0F',
      title: 'No jobs',
      subtitle: 'Background runs will appear here.',
    }));
    return;
  }

  const panel = el('div', { style: { padding: 'var(--space-3)' } });
  const runningCount = jobs.filter((j) => j.status === 'starting' || j.status === 'running').length;
  panel.appendChild(el('div', {
    style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-2)' },
  }, `${runningCount} running | ${jobs.length} total`));

  const chats = getState().chats;

  for (const j of jobs) {
    const status = String(j.status || 'unknown');
    const tone = status === 'done'
      ? 'var(--success-text)'
      : (status === 'error' ? 'var(--danger-text)' : (status === 'stopped' ? 'var(--text-muted)' : 'var(--warning-text)'));
    const chatTitle = chats.get(j.chatId)?.title || 'Chat';
    const startedAt = Number(j.startedAt || 0);
    const endedAt = Number(j.endedAt || 0);
    const baseTs = startedAt || Number(j.queuedAt || 0);
    const elapsedMs = baseTs > 0 ? Math.max(0, (endedAt || Date.now()) - baseTs) : 0;

    const card = el('div', {
      style: {
        border: '1px solid var(--border-subtle)',
        borderRadius: '10px',
        padding: 'var(--space-3)',
        marginBottom: 'var(--space-2)',
        background: 'var(--bg-secondary)',
      },
    });

    const top = el('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' } });
    top.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, chatTitle));
    top.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: tone, textTransform: 'uppercase' } }, status));
    card.appendChild(top);

    card.appendChild(el('div', {
      style: {
        marginTop: '6px',
        fontSize: 'var(--text-sm)',
        color: 'var(--text-primary)',
        lineHeight: '1.45',
        whiteSpace: 'pre-wrap',
      },
    }, String(j.preview || '').slice(0, 220)));

    card.appendChild(el('div', {
      style: { marginTop: '6px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' },
    }, `Mode: ${j.mode || ''} | Profile: ${j.profile || ''} | Elapsed: ${formatDuration(elapsedMs)}`));

    if (j.error) {
      card.appendChild(el('div', {
        style: { marginTop: '6px', fontSize: 'var(--text-xs)', color: 'var(--danger-text)', whiteSpace: 'pre-wrap' },
      }, String(j.error)));
    }

    const actions = el('div', { style: { display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' } });
    const openBtn = el('button', { className: 'btn btn-sm' }, 'Open chat');
    openBtn.onclick = () => {
      setActiveChat(j.chatId);
      setState('ui', { inspectorTab: 'run' });
      if (j.messageId) {
        setTimeout(() => scrollToMessage(j.messageId), 80);
      }
    };
    actions.appendChild(openBtn);

    if (status === 'queued' || status === 'starting' || status === 'running') {
      const stopBtn = el('button', { className: 'btn btn-sm btn-danger' }, status === 'queued' ? 'Cancel' : 'Stop');
      stopBtn.onclick = () => {
        cancelJob(j.id);
      };
      actions.appendChild(stopBtn);
    }

    card.appendChild(actions);
    panel.appendChild(card);
  }

  _bodyEl.appendChild(panel);
}

function renderRunTab() {
  const run = getState().activeRun;

  if (!run) {
    _bodyEl.appendChild(createEmptyState({
      icon: '\u25B6\uFE0F',
      title: 'No active run',
      subtitle: 'Send a message to start a run.',
    }));
    return;
  }

  const panel = el('div', { className: 'tab-panel active', style: { padding: 'var(--space-4)' } });

  // Status
  const statusBadge = el('div', { style: {
    display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)',
  }});
  const statusColor = run.status === 'done' ? 'var(--success)' : run.status === 'error' ? 'var(--danger)' : 'var(--warning)';
  statusBadge.innerHTML = `
    <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${statusColor};"></span>
    <strong style="font-size:var(--text-sm);text-transform:capitalize;">${run.status}</strong>
  `;
  panel.appendChild(statusBadge);

  // Model/mode summary
  if (run.profile || run.modelId || run.mode) {
    const row = el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)', lineHeight: '1.6' } });
    const modelLabel = run.modelId ? String(run.modelId) : '(profile default)';
    row.textContent = `Profile: ${run.profile || ''}  Model: ${modelLabel}  Mode: ${run.mode || ''}`;
    panel.appendChild(row);
  }

  // Token usage
  if (run.tokenEstimate > 0) {
    const tokens = el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)' } });
    tokens.textContent = `Tokens: ~${formatNumber(run.tokenEstimate)} / ${formatNumber(run.contextWindow || 0)} context`;
    panel.appendChild(tokens);
  }

  // Server-reported usage (if available)
  if (run.usage && run.usage.total_tokens > 0) {
    const u = run.usage;
    const usageEl = el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)' } });
    usageEl.textContent = `Usage: ${formatNumber(u.prompt_tokens || 0)} prompt + ${formatNumber(u.completion_tokens || 0)} completion = ${formatNumber(u.total_tokens || 0)} total`;
    panel.appendChild(usageEl);
  }

  if (run.tokenReport) {
    const tr = run.tokenReport;
    const box = el('div', { style: {
      border: '1px solid var(--border-subtle)',
      borderRadius: '10px',
      padding: 'var(--space-3)',
      marginBottom: 'var(--space-3)',
      background: 'var(--bg-secondary)',
    }});
    box.appendChild(el('div', {
      style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', marginBottom: 'var(--space-2)' },
    }, 'Token Efficiency'));
    box.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', lineHeight: '1.6' } },
      `Peak context: ${formatNumber(tr.peak_context_tokens || 0)} | Memory: ${formatNumber(tr.memory_context_tokens || 0)} | Prompt/Completion: ${Number(tr.prompt_to_completion_ratio || 0).toFixed(2)}`
    ));

    if (Array.isArray(tr.flags) && tr.flags.length > 0) {
      const flagsWrap = el('div', { style: { marginTop: 'var(--space-2)' } });
      for (const f of tr.flags) {
        const sev = String(f.severity || 'info').toLowerCase();
        const color = sev === 'high' ? 'var(--danger-text)' : (sev === 'medium' ? 'var(--warning-text)' : 'var(--text-muted)');
        flagsWrap.appendChild(el('div', {
          style: { fontSize: 'var(--text-xs)', color, marginTop: '2px' },
        }, `• ${f.kind || 'flag'}: ${f.detail || ''}`));
      }
      box.appendChild(flagsWrap);
    }

    if (Array.isArray(tr.suggestions) && tr.suggestions.length > 0) {
      const sugg = el('div', { style: { marginTop: 'var(--space-2)', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)' } });
      sugg.textContent = `Next optimization: ${tr.suggestions[0]}`;
      box.appendChild(sugg);
    }
    panel.appendChild(box);
  }

  if (run.elapsedMs && run.elapsedMs > 0) {
    const dur = el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)' } });
    dur.textContent = `Elapsed: ${formatDuration(run.elapsedMs)}`;
    panel.appendChild(dur);
  }

  // Steps
  if (run.steps.length > 0) {
    const stepsLabel = el('div', { style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', color: 'var(--text-secondary)', marginBottom: 'var(--space-2)' } }, 'Steps');
    panel.appendChild(stepsLabel);

    for (let i = 0; i < run.steps.length; i++) {
      const step = run.steps[i];
      const stepEl = el('div', { style: {
        display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
        padding: 'var(--space-1) 0', fontSize: 'var(--text-xs)', color: 'var(--text-secondary)',
        fontFamily: 'var(--font-mono)',
      }});

      const num = el('span', { style: { color: 'var(--text-muted)', minWidth: '20px' } }, `${i + 1}.`);
      stepEl.appendChild(num);

      if (step.type === 'tool_start') {
        stepEl.appendChild(el('span', {}, `\u26A1 ${step.name}`));
      } else if (step.type === 'tool_result') {
        const icon = step.ok ? '\u2713' : '\u2717';
        const color = step.ok ? 'var(--success-text)' : 'var(--danger-text)';
        stepEl.appendChild(el('span', { style: { color } }, `${icon} ${step.name} (${formatDuration(step.ms || 0)})`));
      } else if (step.type === 'iteration') {
        stepEl.appendChild(el('span', {}, `\uD83D\uDD04 Iteration ${(step.iteration || 0) + 1}`));
      } else if (step.type === 'guardrails') {
        stepEl.appendChild(el('span', {}, `\uD83D\uDEE1\uFE0F ${step.event || 'guardrails'} ${step.tool || ''}`));
      }

      panel.appendChild(stepEl);
    }
  }

  // Error
  if (run.error) {
    const errEl = el('div', { className: 'error-banner', style: { marginTop: 'var(--space-3)' } });
    errEl.textContent = run.error;
    panel.appendChild(errEl);
  }

  _bodyEl.appendChild(panel);
}

function renderTraceTab() {
  const run = getState().activeRun;

  if (!run || run.steps.length === 0) {
    _bodyEl.appendChild(createEmptyState({
      icon: '\uD83D\uDD0D',
      title: 'No trace data',
      subtitle: 'Tool calls and detailed events will appear here during a run.',
    }));
    return;
  }

  const panel = el('div', { style: { padding: 'var(--space-3)' } });

  for (const step of run.steps) {
    const entry = el('div', { style: {
      padding: 'var(--space-2) var(--space-3)',
      borderBottom: '1px solid var(--border-subtle)',
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--text-xs)',
      color: 'var(--text-secondary)',
    }});

    const time = new Date(step.timestamp).toLocaleTimeString();
    entry.innerHTML = `<span style="color:var(--text-muted)">${time}</span> `;

    if (step.type === 'tool_start') {
      entry.innerHTML += `<span style="color:var(--warning-text)">\u26A1 ${step.name}</span> starting`;
    } else if (step.type === 'tool_result') {
      const color = step.ok ? 'var(--success-text)' : 'var(--danger-text)';
      entry.innerHTML += `<span style="color:${color}">${step.ok ? '\u2713' : '\u2717'} ${step.name}</span> ${formatDuration(step.ms || 0)}`;
    } else if (step.type === 'iteration') {
      entry.innerHTML += `<span>\uD83D\uDD04</span> Iteration ${(step.iteration || 0) + 1}`;
    } else if (step.type === 'guardrails') {
      entry.innerHTML += `<span>\uD83D\uDEE1\uFE0F</span> ${step.event || 'guardrails'} ${step.tool || ''}`;
    }

    panel.appendChild(entry);
  }

  _bodyEl.appendChild(panel);
}

function renderToolsTab() {
  const tools = getState().tools;

  if (!tools || tools.length === 0) {
    _bodyEl.appendChild(createEmptyState({
      icon: '\uD83D\uDD27',
      title: 'Tools',
      subtitle: 'Registered tools will appear here. Make sure the server is running.',
    }));
    return;
  }

  const panel = el('div', { style: { padding: 'var(--space-3)' } });

  // Group by category
  const byCategory = {};
  for (const tool of tools) {
    const cat = tool.category || 'general';
    if (!byCategory[cat]) byCategory[cat] = [];
    byCategory[cat].push(tool);
  }

  for (const [category, catTools] of Object.entries(byCategory)) {
    const catLabel = el('div', { style: {
      fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)',
      color: 'var(--text-muted)', textTransform: 'uppercase',
      letterSpacing: '0.05em', padding: 'var(--space-3) var(--space-3) var(--space-1)',
    }}, category);
    panel.appendChild(catLabel);

    for (const tool of catTools) {
      const toolEl = el('div', { style: {
        padding: 'var(--space-2) var(--space-3)',
        fontSize: 'var(--text-sm)',
      }});
      toolEl.innerHTML = `<span style="font-family:var(--font-mono);color:var(--accent-text);font-size:var(--text-xs);">${tool.name}</span>
        <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:2px;">${tool.description || ''}</div>`;
      panel.appendChild(toolEl);
    }
  }

  _bodyEl.appendChild(panel);
}

function renderPlaceholder(title, description) {
  _bodyEl.appendChild(createEmptyState({
    icon: '\uD83D\uDEA7',
    title,
    subtitle: description + '\n\nComing in a future update.',
  }));
}

function renderSwarmTab() {
  const wrap = el('div', { style: { padding: 'var(--space-3)' } });
  const host = el('div', { style: { minHeight: '520px' } });
  wrap.appendChild(host);
  _bodyEl.appendChild(wrap);
  setSwarmContainer(host);
}

async function renderMemoryTab() {
  const panel = el('div', { style: { padding: 'var(--space-3)' } });
  panel.appendChild(el('div', { style: { fontSize: 'var(--text-sm)', color: 'var(--text-muted)' } }, 'Loading memory...'));
  _bodyEl.appendChild(panel);

  const chat = getState().activeChatId ? getState().chats.get(getState().activeChatId) : null;
  const sessionId = chat?.sessionId || null;
  const nonce = ++_memoryLoadNonce;

  try {
    const data = await fetchMemory({ session_id: sessionId, trace_limit: 8 });
    if (nonce !== _memoryLoadNonce) return;

    panel.innerHTML = '';
    if (!data?.enabled) {
      panel.appendChild(createEmptyState({
        icon: '\uD83E\uDDE0',
        title: 'Memory unavailable',
        subtitle: data?.error || 'Memory engine is not active in this runtime.',
      }));
      return;
    }

    const stats = data.stats || {};
    panel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)', lineHeight: '1.6' } },
      `Events: ${formatNumber(stats.event_count || 0)} | Dense: ${stats.has_dense ? `yes (${stats.dense_dim || 0})` : 'no'}`
    ));

    const controls = el('div', { style: { display: 'flex', gap: '6px', marginBottom: 'var(--space-3)' } });
    const addPinBtn = el('button', { className: 'btn btn-small' }, '+ Pin');
    addPinBtn.onclick = async () => {
      const key = window.prompt('Pin key (example: user.goal)');
      if (!key) return;
      const text = window.prompt('Pin text');
      if (!text) return;
      try {
        await setMemoryPin(String(key).trim(), String(text).trim());
        renderMemoryTab();
      } catch (e) {
        alert(`Failed to set pin: ${e?.message || e}`);
      }
    };
    const refreshBtn = el('button', { className: 'btn btn-small' }, 'Refresh');
    refreshBtn.onclick = () => renderMemoryTab();
    controls.appendChild(addPinBtn);
    controls.appendChild(refreshBtn);
    panel.appendChild(controls);

    const pins = Array.isArray(data.pins) ? data.pins : [];
    const pinsTitle = el('div', { style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', marginBottom: '6px' } }, `Pins (${pins.length})`);
    panel.appendChild(pinsTitle);
    if (pins.length === 0) {
      panel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--space-3)' } }, 'No pins yet.'));
    } else {
      for (const p of pins.slice(0, 20)) {
        const row = el('div', { style: {
          border: '1px solid var(--border-subtle)',
          borderRadius: '8px',
          padding: '8px',
          marginBottom: '6px',
          background: 'var(--bg-secondary)',
        }});
        const top = el('div', { style: { display: 'flex', justifyContent: 'space-between', gap: '8px' } });
        top.appendChild(el('code', { style: { fontSize: '11px' } }, String(p.key || '')));
        const del = el('button', { className: 'btn btn-small', style: { padding: '2px 6px' } }, 'Remove');
        del.onclick = async () => {
          try {
            await clearMemoryPin(String(p.key || ''));
            renderMemoryTab();
          } catch (e) {
            alert(`Failed to remove pin: ${e?.message || e}`);
          }
        };
        top.appendChild(del);
        row.appendChild(top);
        row.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: '4px', whiteSpace: 'pre-wrap' } }, String(p.text || '')));
        panel.appendChild(row);
      }
    }

    const traces = Array.isArray(data.traces) ? data.traces : [];
    panel.appendChild(el('div', {
      style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', margin: '10px 0 6px' },
    }, `Retrieval Traces (${traces.length})`));
    if (traces.length === 0) {
      panel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, 'No retrieval traces yet.'));
    } else {
      for (const t of traces.slice(0, 10)) {
        const tr = t.trace || {};
        const row = el('div', { style: {
          fontSize: '11px',
          color: 'var(--text-secondary)',
          borderBottom: '1px solid var(--border-subtle)',
          padding: '6px 0',
          lineHeight: '1.45',
        }});
        row.textContent = `[${t.mode || 'auto'}] ${String(t.query || '').slice(0, 80)} | hits fts=${tr.fts_hits || 0} sparse=${tr.sparse_hits || 0} loaded=${tr.events_loaded || 0} packed=${tr.events_packed || 0}`;
        panel.appendChild(row);
      }
    }

    const contraData = await fetchMemoryContradictions({ only_open: true, limit: 30 }).catch(() => null);
    const contradictions = Array.isArray(contraData?.contradictions) ? contraData.contradictions : [];
    panel.appendChild(el('div', {
      style: { fontSize: 'var(--text-xs)', fontWeight: 'var(--font-semibold)', margin: '12px 0 6px' },
    }, `Contradictions (${contradictions.length})`));
    if (contradictions.length === 0) {
      panel.appendChild(el('div', { style: { fontSize: 'var(--text-xs)', color: 'var(--text-muted)' } }, 'No open contradictions.'));
    } else {
      for (const c of contradictions.slice(0, 30)) {
        const cid = Number(c?.id || 0);
        const score = Number(c?.score || 0);
        const reason = String(c?.reason || '').trim() || 'unspecified';
        const row = el('div', { style: {
          border: '1px solid var(--border-subtle)',
          borderRadius: '8px',
          padding: '8px',
          marginTop: '6px',
          background: 'var(--bg-secondary)',
        }});
        row.appendChild(el('div', {
          style: { fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' },
        }, `#${cid} score=${score.toFixed(2)}`));
        row.appendChild(el('div', {
          style: { fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', marginTop: '4px', whiteSpace: 'pre-wrap' },
        }, reason));

        const controls = el('div', { style: { marginTop: '6px', display: 'flex', gap: '6px' } });
        const resolveBtn = el('button', { className: 'btn btn-small', style: { padding: '2px 6px' } }, 'Resolve');
        resolveBtn.onclick = async () => {
          try {
            await resolveMemoryContradiction(cid, true);
            renderMemoryTab();
          } catch (e) {
            alert(`Failed to resolve contradiction: ${e?.message || e}`);
          }
        };
        controls.appendChild(resolveBtn);
        row.appendChild(controls);
        panel.appendChild(row);
      }
    }
  } catch (e) {
    if (nonce !== _memoryLoadNonce) return;
    panel.innerHTML = '';
    panel.appendChild(createEmptyState({
      icon: '\u26A0\uFE0F',
      title: 'Memory load failed',
      subtitle: e?.message || String(e),
    }));
  }
}
