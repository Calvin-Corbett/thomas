// Guardrails UI: approval modal + timeline markers.
// Expectation: your main event stream handler calls window.guardrailsHandleEvent(evtType, payload)

(function(){
  let backdrop, modal, pre, titleEl, reasonEl, pillTool, pillRun;
  let current = null;

  function ensureUI() {
    if (backdrop) return;
    backdrop = document.createElement('div');
    backdrop.className = 'gr-modal-backdrop';
    backdrop.innerHTML = `
      <div class="gr-modal" role="dialog" aria-modal="true">
        <h2 id="grTitle">Tool approval required</h2>
        <div class="gr-row" style="margin: 6px 0 10px 0;">
          <div class="gr-pill" id="grPillTool"></div>
          <div class="gr-pill" id="grPillRun"></div>
        </div>
        <div class="gr-pill" id="grReason" style="margin-bottom:10px;"></div>
        <div class="gr-pre" id="grArgs"></div>
        <div class="gr-actions">
          <button class="gr-btn gr-btn-approve" id="grApproveOnce">Approve once</button>
          <button class="gr-btn gr-btn-deny" id="grDeny">Deny</button>
          <button class="gr-btn gr-btn-session" id="grApproveSession">Always approve this tool for this session</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    modal = backdrop.querySelector('.gr-modal');
    pre = backdrop.querySelector('#grArgs');
    titleEl = backdrop.querySelector('#grTitle');
    reasonEl = backdrop.querySelector('#grReason');
    pillTool = backdrop.querySelector('#grPillTool');
    pillRun = backdrop.querySelector('#grPillRun');

    backdrop.querySelector('#grApproveOnce').addEventListener('click', () => resolve('approve', false));
    backdrop.querySelector('#grDeny').addEventListener('click', () => resolve('deny', false));
    backdrop.querySelector('#grApproveSession').addEventListener('click', () => resolve('approve', true));
  }

  function showModal(payload) {
    ensureUI();
    current = payload;
    pillTool.textContent = `Tool: ${payload.tool_name}`;
    pillRun.textContent = `Run: ${payload.run_id}`;
    reasonEl.textContent = payload.reason || 'Approval required by policy';
    pre.textContent = payload.args_pretty || JSON.stringify(payload.args || {}, null, 2);
    backdrop.style.display = 'flex';
  }

  function hideModal() {
    if (!backdrop) return;
    backdrop.style.display = 'none';
    current = null;
  }

  async function resolve(decision, allowSessionTool) {
    if (!current) return;
    const body = {
      run_id: current.run_id,
      tool_call_id: current.tool_call_id,
      decision,
      allow_session_tool: !!allowSessionTool,
      tool_name: current.tool_name,
      session_id: current.session_id,
    };
    try {
      const res = await fetch('/api/approvals/resolve', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      });
      await res.json();
    } catch (e) {
      console.error('Approval resolve failed', e);
    } finally {
      hideModal();
    }
  }

  function addTimelineMarker(text) {
    const el = document.querySelector('#runTimeline');
    if (!el) return;
    const li = document.createElement('li');
    li.textContent = text;
    el.appendChild(li);
  }

  window.guardrailsHandleEvent = function(type, payload) {
    if (type === 'TOOL_APPROVAL_REQUIRED') {
      showModal(payload);
      addTimelineMarker(`Approval required: ${payload.tool_name} (${payload.tool_call_id})`);
    } else if (type === 'TOOL_APPROVAL_RESOLVED') {
      addTimelineMarker(`Approval ${payload.approved ? 'approved' : 'denied'}: ${payload.tool_name} (${payload.tool_call_id})`);
    }
  };
})();
