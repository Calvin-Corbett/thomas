// Extracted from part-002b.js
// From message

            }
        }
        return {
            ok: response.ok,
            status: response.status,
            data,
            text,
        };
    } catch (error) {
        const message = error && error.name === 'AbortError' ? 'Request timeout' : safeString(error?.message);
        return {
            ok: false,
            status: 0,
            data: null,
            text: message || 'Network error',
        };
    } finally {
        if (timeoutId) {
            window.clearTimeout(timeoutId);
        }
    }
}

function taskContinuityStatusTone(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'complete' || status === 'done') return 'complete';
    if (status === 'blocked' || status === 'error') return 'blocked';
    if (!status || status === 'idle') return 'idle';
    return 'working';
}

function taskContinuityStatusLabel(statusRaw) {
    const tone = taskContinuityStatusTone(statusRaw);
    if (tone === 'complete') return 'Done';
    if (tone === 'blocked') return 'Needs help';
    if (tone === 'idle') return 'Idle';
    return 'Working';
}

function taskContinuityShouldBeVisible() {
    if (!taskContinuityPanel) return false;
    if (isSettingsScreenOpen()) return false;
    return sidebarNavMode === 'chat' || sidebarNavMode === 'search';
}

function stopTaskContinuityAutoRefresh() {
    if (taskContinuityAutoRefreshTimer) {
        window.clearInterval(taskContinuityAutoRefreshTimer);
        taskContinuityAutoRefreshTimer = 0;
    }
}

function startTaskContinuityAutoRefresh() {
    if (taskContinuityAutoRefreshTimer) return;
    taskContinuityAutoRefreshTimer = window.setInterval(() => {
        if (!taskContinuityShouldBeVisible()) return;
        void refreshTaskContinuity();
    }, TASK_CONTINUITY_REFRESH_INTERVAL_MS);
}

function renderTaskContinuity(state, events, sessionToken, { error = '' } = {}) {
    if (!taskContinuityPanel) return;

    const hasState = Boolean(state && typeof state === 'object');
