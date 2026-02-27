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

function taskContinuityStatusLabel(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'complete') return 'complete';
    if (status === 'blocked') return 'blocked';
    return 'in_progress';
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