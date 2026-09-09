(function () {
  const DESKTOP_STATUS_API = '/api/onboarding/desktop/status';
  const DESKTOP_INSTALL_API = '/api/onboarding/desktop/install';
  const DESKTOP_TRUST_API = '/api/onboarding/desktop/trust';
  const DESKTOP_VM_SOURCE_API = '/api/onboarding/desktop/vm-source';
  const DESKTOP_VIEWER_API = '/api/onboarding/desktop/open-viewer';
  let isolatedDesktopState = null;

  function ensureProtectedOverrideApprovalSetting() {
    if (document.getElementById('protectedOverrideApproval')) return;
    const sessionToggle = document.getElementById('sessionEncryption');
    const sessionItem = sessionToggle && sessionToggle.closest('.setting-item');
    if (!sessionItem || !sessionItem.parentNode) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'setting-item';
    wrapper.innerHTML = `
      <div class="setting-label">
        <div class="setting-name">Protected Override Approval</div>
        <div class="setting-description">Require a fresh local Windows sign-in before protected overrides and breakglass actions. Disabled by default for new installs.</div>
      </div>
      <div class="setting-control">
        <button class="toggle-switch" id="protectedOverrideApproval" data-setting="protectedOverrideApproval" aria-label="Toggle protected override approval" role="switch" aria-checked="false"></button>
      </div>
    `;
    sessionItem.insertAdjacentElement('afterend', wrapper);
  }

  function renderIsolatedDesktopState() {
    const state = isolatedDesktopState || {};
    window.setToggle('isolatedDesktopEnabled', !!state.enabled);
    window.setSelectValue('isolatedDesktopTrustMode', state.trust_mode || 'ask_every_time');
    const localVm = state.local_vm || {};
    window.setSelectValue('isolatedDesktopVmSource', localVm.source_type || 'unconfigured');
    window.setInputValue('isolatedDesktopVmName', localVm.vm_name || '');
    window.setInputValue('isolatedDesktopTemplateVhdx', localVm.template_vhdx || '');
    const badge = document.getElementById('isolatedDesktopStatusBadge');
    const statusText = document.getElementById('isolatedDesktopStatusText');
    const nextAction = document.getElementById('isolatedDesktopNextAction');
    const note = document.getElementById('isolatedDesktopNote');
    const templateItem = document.getElementById('isolatedDesktopTemplateItem');
    const installBtn = document.getElementById('installHostServiceButton');
    const viewerBtn = document.getElementById('openViewerButton');
    if (badge) {
      badge.classList.remove('status-connected', 'status-disconnected', 'status-pending');
      const installationState = String(state.installation_state || 'not_enabled');
      if (installationState === 'local_vm_ready') badge.classList.add('status-connected');
      else if (installationState === 'host_service_installing') badge.classList.add('status-pending');
      else badge.classList.add('status-disconnected');
    }
    if (statusText) statusText.textContent = String(state.installation_state || 'not_enabled').replaceAll('_', ' ');
    if (nextAction) nextAction.textContent = state.next_action || 'Select an existing worker VM or a template disk.';
    if (note) note.textContent = state.note || 'Configure a worker VM source so Thomas can provision or attach the isolated desktop worker.';
    if (templateItem) templateItem.style.display = (localVm.source_type || 'unconfigured') === 'template_disk' ? 'flex' : 'none';
    if (installBtn) installBtn.disabled = !state.enabled;
    if (viewerBtn) viewerBtn.disabled = !(state.viewer && state.viewer.available);
  }

  window.refreshIsolatedDesktopStatus = async function refreshIsolatedDesktopStatus() {
    try {
      const response = await fetch(DESKTOP_STATUS_API);
      if (!response.ok) throw new Error('Failed to load isolated desktop status');
      const payload = await response.json();
      isolatedDesktopState = payload.isolated_desktop || null;
      renderIsolatedDesktopState();
    } catch (error) {
      console.error('Error loading isolated desktop status:', error);
      window.showToast('Failed to load isolated desktop status', 'error');
    }
  };

  window.saveIsolatedDesktopSettings = async function saveIsolatedDesktopSettings() {
    const enabled = document.getElementById('isolatedDesktopEnabled').classList.contains('on');
    const trustMode = document.getElementById('isolatedDesktopTrustMode').value;
    const sourceType = document.getElementById('isolatedDesktopVmSource').value;
    const vmName = document.getElementById('isolatedDesktopVmName').value.trim();
    const templateVhdx = document.getElementById('isolatedDesktopTemplateVhdx').value.trim();
    try {
      await fetch('/api/onboarding/desktop/opt-in', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, hidden_by_default: true }),
      });
      await fetch(DESKTOP_TRUST_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trust_mode: trustMode }),
      });
      await fetch(DESKTOP_VM_SOURCE_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_type: sourceType, vm_name: vmName, template_vhdx: templateVhdx }),
      });
      await window.refreshIsolatedDesktopStatus();
      window.showToast('Isolated desktop settings saved', 'success');
    } catch (error) {
      console.error('Error saving isolated desktop settings:', error);
      window.showToast('Failed to save isolated desktop settings', 'error');
    }
  };

  window.installIsolatedDesktopMode = async function installIsolatedDesktopMode() {
    try {
      const response = await fetch(DESKTOP_INSTALL_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: true, hidden_by_default: true }),
      });
      if (!response.ok) throw new Error('Failed to launch isolated desktop install');
      await window.refreshIsolatedDesktopStatus();
      window.showToast('Host service install launched', 'success');
    } catch (error) {
      console.error('Error launching isolated desktop install:', error);
      window.showToast('Failed to launch isolated desktop install', 'error');
    }
  };

  window.openIsolatedDesktopViewer = async function openIsolatedDesktopViewer() {
    try {
      const response = await fetch(DESKTOP_VIEWER_API, { method: 'POST' });
      if (!response.ok) throw new Error('Failed to open isolated desktop viewer');
      window.showToast('Viewer launch requested', 'success');
    } catch (error) {
      console.error('Error opening isolated desktop viewer:', error);
      window.showToast('Failed to open isolated desktop viewer', 'error');
    }
  };

  ensureProtectedOverrideApprovalSetting();
})();
