
    // State Management
    const state = {
      missions: [],
      agents: [],
      approvals: [],
      activities: [],
      connected: false,
      selectedTab: 'missions'
    };

    // WebSocket Connection
    let ws = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;

    function connectWebSocket() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/events`;

      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('WebSocket connected');
        state.connected = true;
        reconnectAttempts = 0;
        showToast('Connected to Mission Control', 'success');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleWebSocketMessage(data);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        state.connected = false;
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        state.connected = false;
        attemptReconnect();
      };
    }

    function attemptReconnect() {
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        console.log(`Reconnecting in ${delay}ms...`);
        setTimeout(connectWebSocket, delay);
      }
    }

    function handleWebSocketMessage(data) {
      const { type, payload } = data;

      switch (type) {
        case 'mission_created':
          state.missions.push(payload);
          renderMissions();
          showToast(`Mission "${payload.name}" created`, 'success');
          break;
        case 'mission_updated':
          const idx = state.missions.findIndex(m => m.id === payload.id);
          if (idx >= 0) {
            state.missions[idx] = payload;
            renderMissions();
          }
          break;
        case 'mission_status_changed':
          const missionIdx = state.missions.findIndex(m => m.id === payload.id);
          if (missionIdx >= 0) {
            state.missions[missionIdx].status = payload.status;
            renderMissions();
          }
          showToast(`Mission status: ${payload.status}`, payload.status);
          break;
        case 'agent_connected':
          state.agents.push(payload);
          renderAgents();
          break;
        case 'agent_updated':
          const agentIdx = state.agents.findIndex(a => a.id === payload.id);
          if (agentIdx >= 0) {
            state.agents[agentIdx] = payload;
            renderAgents();
          }
          break;
        case 'activity':
          state.activities.unshift(payload);
          if (state.activities.length > 50) state.activities.pop();
          renderActivity();
          break;
        case 'approval_requested':
          state.approvals.push(payload);
          renderApprovals();
          break;
        case 'metrics_update':
          updateKPIs(payload);
          break;
      }
    }

    // API Functions
    async function fetchMissions() {
      try {
        const response = await fetch('/api/missions');
        if (!response.ok) throw new Error('Failed to fetch missions');
        state.missions = await response.json();
        renderMissions();
      } catch (e) {
        console.error('Error fetching missions:', e);
      }
    }

    async function fetchAgents() {
      try {
        const response = await fetch('/api/agents');
        if (!response.ok) throw new Error('Failed to fetch agents');
        state.agents = await response.json();
        renderAgents();
        populateAgentSelect();
      } catch (e) {
        console.error('Error fetching agents:', e);
      }
    }

    async function fetchApprovals() {
      try {
        const response = await fetch('/api/approvals');
        if (!response.ok) throw new Error('Failed to fetch approvals');
        state.approvals = await response.json();
        renderApprovals();
      } catch (e) {
        console.error('Error fetching approvals:', e);
      }
    }

    async function createMission(data) {
      try {
        const response = await fetch('/api/missions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error('Failed to create mission');
        const mission = await response.json();
        state.missions.push(mission);
        renderMissions();
        closeModal();
        showToast(`Mission "${mission.name}" created successfully`, 'success');
      } catch (e) {
        console.error('Error creating mission:', e);
        showToast('Failed to create mission', 'error');
      }
    }

    async function approveMission(approvalId) {
      try {
        const response = await fetch(`/api/approvals/${approvalId}/approve`, {
          method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to approve');
        state.approvals = state.approvals.filter(a => a.id !== approvalId);
        renderApprovals();
        showToast('Approval granted', 'success');
      } catch (e) {
        console.error('Error approving:', e);
        showToast('Failed to approve', 'error');
      }
    }

    async function rejectMission(approvalId) {
      try {
        const response = await fetch(`/api/approvals/${approvalId}/reject`, {
          method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to reject');
        state.approvals = state.approvals.filter(a => a.id !== approvalId);
        renderApprovals();
        showToast('Approval rejected', 'warning');
      } catch (e) {
        console.error('Error rejecting:', e);
        showToast('Failed to reject', 'error');
      }
    }

    // Rendering Functions
    function renderMissions() {
      const tbody = document.getElementById('missions-list');
      if (!state.missions.length) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" class="empty-state">
              <div class="empty-state-icon"><i class="ph-inbox"></i></div>
              <div class="empty-state-title">No missions yet</div>
              <div>Create a new mission to get started</div>
            </td>
          </tr>
        `;
        updateKPIs();
        return;
      }

      tbody.innerHTML = state.missions.map(mission => `
        <tr>
          <td class="mission-name">${escapeHtml(mission.name)}</td>
          <td>
            <span class="status-badge status-${mission.status}">
              <span class="spinner" style="display: ${mission.status === 'running' ? 'inline-block' : 'none'};"></span>
              ${mission.status.charAt(0).toUpperCase() + mission.status.slice(1)}
            </span>
          </td>
          <td>
            <div class="progress-bar">
              <div class="progress-fill" style="width: ${mission.progress || 0}%"></div>
            </div>
            <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">${mission.progress || 0}%</div>
          </td>
          <td>${escapeHtml(mission.agent || 'Unassigned')}</td>
          <td>${mission.priority || 'P3'}</td>
          <td style="font-size: 11px; color: var(--text-secondary);">${formatTime(mission.created_at)}</td>
        </tr>
      `).join('');

      updateKPIs();
    }

    function renderAgents() {
      const grid = document.getElementById('agents-grid');
      if (!state.agents.length) {
        grid.innerHTML = `
          <div class="empty-state" style="padding: 20px;">
            <div class="empty-state-icon"><i class="ph-robot"></i></div>
            <div class="empty-state-title">No agents connected</div>
          </div>
        `;
        return;
      }

      grid.innerHTML = state.agents.map(agent => `
        <div class="agent-card">
          <div class="agent-header">
            <div class="agent-name">${escapeHtml(agent.name)}</div>
            <span class="agent-state ${agent.state}">
              <i class="ph-circle-fill" style="font-size: 6px;"></i>
              ${agent.state}
            </span>
          </div>
          <div class="agent-stat">
            <span>Current Task:</span>
            <span class="agent-stat-value">${escapeHtml(agent.current_task || 'None')}</span>
          </div>
          <div class="agent-stat">
            <span>Uptime:</span>
            <span class="agent-stat-value">${agent.uptime_hours || 0}h</span>
          </div>
          <div class="agent-stat">
            <span>Success Rate:</span>
            <span class="agent-stat-value">${agent.success_rate || 0}%</span>
          </div>
        </div>
      `).join('');

      updateKPIs();
    }

    function renderActivity() {
      const feed = document.getElementById('activity-feed');
      if (!state.activities.length) {
        feed.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon"><i class="ph-radio-button-off"></i></div>
            <div class="empty-state-title">No activity yet</div>
            <div>Live events will appear here</div>
          </div>
        `;
        return;
      }

      feed.innerHTML = state.activities.map(activity => `
        <div class="activity-item ${activity.type}">
          <div class="activity-icon">
            ${getActivityIcon(activity.type)}
          </div>
          <div class="activity-content">
            <div class="activity-message">${escapeHtml(activity.message)}</div>
            <div class="activity-time">${formatTime(activity.timestamp)}</div>
          </div>
        </div>
      `).join('');
    }

    function renderApprovals() {
      const list = document.getElementById('approvals-list');
      const panel = document.getElementById('approvals-panel');

      if (!state.approvals.length) {
        list.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon"><i class="ph-check-circle"></i></div>
            <div class="empty-state-title">All clear!</div>
            <div>No pending approvals</div>
          </div>
        `;
        panel.innerHTML = `
          <div class="empty-state" style="padding: 20px;">
            <div class="empty-state-icon"><i class="ph-seal-check"></i></div>
            <div class="empty-state-title">No pending items</div>
          </div>
        `;
        return;
      }

      const html = state.approvals.map(approval => `
        <div class="approval-item">
          <div class="approval-title">${escapeHtml(approval.title)}</div>
          <div class="approval-desc">${escapeHtml(approval.description)}</div>
          <div class="approval-actions">
            <button class="btn btn-approve" onclick="approveMission('${approval.id}')">Approve</button>
            <button class="btn btn-reject" onclick="rejectMission('${approval.id}')">Reject</button>
          </div>
        </div>
      `).join('');

      list.innerHTML = html || list.innerHTML;
      panel.innerHTML = html || panel.innerHTML;
    }

    function updateKPIs(metrics = {}) {
      const completed = metrics.completed_today || state.missions.filter(m => m.status === 'succeeded').length;
      const avgTime = metrics.avg_completion_time || 45;
      const successRate = metrics.success_rate || (state.missions.length ? Math.round((state.missions.filter(m => m.status === 'succeeded').length / state.missions.length) * 100) : 0);
      const activeAgents = metrics.active_agents || state.agents.filter(a => a.state === 'working').length;
      const queueDepth = metrics.queue_depth || state.missions.filter(m => m.status === 'queued').length;

      document.getElementById('kpi-completed').textContent = completed;
      document.getElementById('kpi-completion-time').textContent = avgTime;
      document.getElementById('kpi-success-rate').textContent = `${successRate}%`;
      document.getElementById('kpi-active-agents').textContent = activeAgents;
      document.getElementById('kpi-queue-depth').textContent = queueDepth;
    }

    function populateAgentSelect() {
      const select = document.getElementById('mission-agent');
      select.innerHTML = '<option value="">Select an agent...</option>' +
        state.agents.map(agent => `<option value="${agent.id}">${escapeHtml(agent.name)}</option>`).join('');
    }

    // Utility Functions
    function showToast(message, type = 'info') {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      toast.className = `toast ${type}`;
      toast.innerHTML = `
        <i class="ph-${getToastIcon(type)}" style="font-size: 16px;"></i>
        <span>${escapeHtml(message)}</span>
      `;
      container.appendChild(toast);
      setTimeout(() => toast.remove(), 4000);
    }

    function getToastIcon(type) {
      const icons = {
        success: 'check-circle',
        error: 'warning-circle',
        warning: 'warning',
        info: 'info'
      };
      return icons[type] || icons.info;
    }

    function getActivityIcon(type) {
      const icons = {
        action: 'arrow-right',
        success: 'check-circle',
        error: 'warning-circle',
        warning: 'warning'
      };
      const icon = icons[type] || icons.action;
      return `<i class="ph-${icon}"></i>`;
    }

    function formatTime(timestamp) {
      if (!timestamp) return 'now';
      const date = new Date(timestamp);
      const now = new Date();
      const diff = Math.floor((now - date) / 1000);

      if (diff < 60) return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return date.toLocaleDateString();
    }

    function escapeHtml(text) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
      return text.replace(/[&<>"']/g, c => map[c]);
    }

    function sortTable(th) {
      const table = document.getElementById('missions-table');
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => r.cells[0] !== r.querySelector('[colspan]'));
      const index = Array.from(th.parentNode.children).indexOf(th);

      rows.sort((a, b) => {
        const aVal = a.cells[index].textContent.trim();
        const bVal = b.cells[index].textContent.trim();
        return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      });

      tbody.innerHTML = '';
      rows.forEach(row => tbody.appendChild(row));
    }

    function openModal() {
      document.getElementById('mission-modal').classList.add('active');
    }

    function closeModal() {
      document.getElementById('mission-modal').classList.remove('active');
      document.getElementById('mission-form').reset();
    }

    // Event Listeners
    document.getElementById('btn-new-mission').addEventListener('click', openModal);

    document.getElementById('mission-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const formData = new FormData(e.target);
      const data = {
        name: formData.get('mission-name'),
        goal: formData.get('mission-goal'),
        priority: formData.get('priority'),
        agent_id: formData.get('mission-agent'),
        autonomy: formData.get('mission-autonomy'),
        schedule_type: formData.get('schedule-type'),
        cron: formData.get('schedule-type') === 'cron' ? formData.get('mission-cron') : null,
        risk_class: formData.get('mission-risk')
      };
      createMission(data);
    });

    document.querySelectorAll('input[name="schedule-type"]').forEach(radio => {
      radio.addEventListener('change', (e) => {
        document.getElementById('cron-group').style.display = e.target.value === 'cron' ? 'block' : 'none';
      });
    });

    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', (e) => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        e.target.classList.add('active');
        const tabName = e.target.dataset.tab;
        document.getElementById(`tab-${tabName}`).classList.add('active');
      });
    });

    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
        e.currentTarget.classList.add('active');
      });
    });

    document.getElementById('toggle-filter').addEventListener('click', () => {
      alert('Filter functionality ready for implementation');
    });

    document.getElementById('mission-modal').addEventListener('click', (e) => {
      if (e.target === document.getElementById('mission-modal')) closeModal();
    });

    // Initialize
    function init() {
      connectWebSocket();
      fetchMissions();
      fetchAgents();
      fetchApprovals();

      // Auto-refresh every 30 seconds as fallback
      setInterval(() => {
        if (!state.connected) {
          fetchMissions();
          fetchAgents();
          fetchApprovals();
        }
      }, 30000);
    }

    // Keyboard accessibility
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeModal();
      if (e.ctrlKey && e.key === 'n') {
        e.preventDefault();
        openModal();
      }
    });

    // Start the application
    window.addEventListener('load', init);
  
