async function loadStatus() {
  const card = document.getElementById('statusCard');
  card.textContent = 'Loading…';
  try {
    const res = await fetch('/api/mission/control');
    const data = await res.json();
    const desktop = data.desktop_operator || {};
    const active = desktop.active_session || {};
    const session = active.session || {};
    const windowInfo = active.window || {};
    const running = desktop.running ? 'online' : 'offline';
    const summary = active.window ? 'Bound session active.' : 'No bound window yet.';
    card.innerHTML = [
      '<span class="status-pill">' + running + '</span>',
      '<p>' + summary + '</p>',
      '<div class="meta">',
      '<div><strong>Service</strong><span>' + (desktop.service_id || 'desktop.operator') + '</span></div>',
      '<div><strong>Session</strong><span>' + (session.session_id || 'none') + '</span></div>',
      '<div><strong>Window</strong><span>' + (windowInfo.title || 'none') + '</span></div>',
      '<div><strong>Monitor</strong><span>' + (windowInfo.monitor_id || 'n/a') + '</span></div>',
      '</div>'
    ].join('');
  } catch (err) {
    card.textContent = 'Status unavailable.';
  }
}
document.getElementById('refreshBtn').addEventListener('click', loadStatus);
loadStatus();
