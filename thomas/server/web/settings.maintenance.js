/* settings.maintenance.js - the integration and maintenance buttons of the
 * settings page (connect placeholders, Clear Cache, Export Logs, Reset All).
 *
 * Moved verbatim out of settings.script01.js, which sat at 850 lines against
 * the 800-line soft limit. Both are classic scripts on the same page, so the
 * top-level declarations of settings.script01.js (settings, pendingConfirmAction,
 * PREFERENCES_API, showToast, showConfirmModal, ...) are shared with this file.
 * settings.html is past the HTML limit and cannot gain a script tag, so
 * settings.script01.js loads this file itself.
 */

    // These buttons are intentionally honest until real authorization routes exist.
    function showUnavailableIntegration(name) {
      showToast(`${name} setup is not available in this build. No account changes were made.`, 'info');
    }

    function connectGoogleWorkspace() { showUnavailableIntegration('Google Workspace'); }
    function connectSlack() { showUnavailableIntegration('Slack'); }
    function connectNotion() { showUnavailableIntegration('Notion'); }

    // Maintenance functions
    function clearCache() {
      pendingConfirmAction = async () => {
        try {
          const response = await fetch('/api/cache/clear', { method: 'POST' });
          if (!response.ok) throw new Error('Failed to clear cache');
          showToast('Cache cleared successfully', 'success');
        } catch (error) {
          showToast('Failed to clear cache', 'error');
        }
      };
      showConfirmModal('Clear Cache?', 'This will remove all cached data. This operation cannot be undone.', 'Clear');
    }

    // Export Logs used to turn a 404 body into a zip and call it a success
    // (owner directive, 2026-09-01: fix every verified lie in the UI). The
    // button now says so while the route is missing, and the handler only
    // reports success after a real archive reached the browser.
    const LOGS_EXPORT_API = '/api/logs/export';
    function exportButtons() {
      return Array.from(document.querySelectorAll('button[onclick="exportLogs()"]'));
    }
    async function probeLogsExport() {
      let available = false;
      try {
        const response = await fetch(LOGS_EXPORT_API, { method: 'HEAD' });
        available = response.ok;
      } catch (error) {
        available = false;
      }
      exportButtons().forEach(button => {
        button.disabled = !available;
        button.title = available ? '' : 'Log export is not available on this server yet: nothing serves ' + LOGS_EXPORT_API + '.';
      });
      return available;
    }
    async function exportLogs() {
      try {
        const response = await fetch(LOGS_EXPORT_API);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const type = String(response.headers.get('content-type') || '');
        if (!/zip|octet-stream/i.test(type)) throw new Error('not an archive (' + (type || 'no content type') + ')');
        const blob = await response.blob();
        if (!blob.size) throw new Error('empty archive');
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `thomas-logs-${new Date().toISOString()}.zip`;
        a.click();
        showToast('Logs exported successfully', 'success');
      } catch (error) {
        showToast('Failed to export logs: ' + ((error && error.message) || 'request failed'), 'error');
      }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { void probeLogsExport(); }, { once: true });
    else void probeLogsExport();

    function confirmReset() {
      pendingConfirmAction = async () => {
        try {
          settings.__themeDirty = true;
          const response = await fetch(PREFERENCES_API, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildPreferencesPatch(defaultLegacySettings())),
          });
          if (!response.ok) throw new Error('Failed to reset settings');
          const data = await response.json();
          applyChatTheme(defaultLegacySettings().theme, { persist: true });
          Object.assign(settings, buildLegacySettings(data));
          populateForm();
          showToast('All settings reset to factory defaults', 'success');
        } catch (error) {
          showToast('Failed to reset settings', 'error');
        }
      };
      showConfirmModal('Reset All Settings?', 'This will restore all settings to factory defaults. This action cannot be undone.', 'Reset All');
    }
