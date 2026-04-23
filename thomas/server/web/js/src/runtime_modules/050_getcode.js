// Extracted from part-026.js
// From getcode

        wrap: true,
    });
    editor.session.setUseWorker(false);
    editor.setOption('tabSize', 4);
    editor.setOption('useSoftTabs', true);
    editor.setValue(wb.code, -1);
    wb.aceEditor = editor;

    const getCode = () => safeString(editor.getValue());
    const setCode = (text) => editor.setValue(safeString(text), -1);
    const log = (message, tone = 'ok') => moduleWorkbenchPushLog(wb.logs, message, tone, 120, 'dev-log');
    const renderLogs = () => {
        logsEl.innerHTML = wb.logs.length
            ? wb.logs.slice(0, 16).map((entry) => `<article class="module-wb-log-item ${moduleToneClass(entry.tone) || 'ok'}"><span>${escapeHtml(safeString(entry.time))}</span><p>${escapeHtml(safeString(entry.message))}</p></article>`).join('')
            : '<div class="module-wb-ghost">No execution logs yet.</div>';
    };
    const renderIssues = () => {
        issuesEl.innerHTML = wb.issues.length
            ? wb.issues.map((issue) => `<article class="module-wb-issue ${moduleToneClass(issue.tone) || 'ok'}">${escapeHtml(safeString(issue.text))}</article>`).join('')
            : '<div class="module-wb-ghost">No checks run yet.</div>';
        const errors = wb.issues.filter((issue) => moduleToneClass(issue.tone) === 'error').length;
        status.textContent = `${errors ? `${errors} error` : 'No critical errors'} | ${getCode().length} chars`;
    };
    const applyAnnotations = () => {
        const annotations = wb.issues
            .filter((issue) => moduleToneClass(issue.tone) !== 'ok')
            .map((issue) => ({
                row: Math.max(0, (Number(issue.line) || 1) - 1),
                column: 0,
                text: safeString(issue.text),
                type: moduleToneClass(issue.tone) === 'error' ? 'error' : 'warning',
            }));
        editor.session.setAnnotations(annotations);
    };
    const analyze = () => {
        wb.code = getCode();
        wb.issues = moduleDevStudioScanIssues(wb.code);
        applyAnnotations();
        renderIssues();
    };

    analyze();
    renderLogs();

    editor.session.on('change', () => {
        wb.code = getCode();
        renderIssues();
    });

    shell.addEventListener('click', (event) => {
        if (moduleWorkbenchHandleOssStackClick(event.target)) return;
        const target = event.target instanceof Element ? event.target.closest('[data-dev-action]') : null;
        if (!target) return;
        const action = safeString(target.dataset.devAction).toLowerCase();
        wb.code = getCode();
        if (action === 'analyze') {
            analyze();
            log('Static analysis completed.', wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error') ? 'warn' : 'ok');
        }
        if (action === 'tests') {
            const hasTests = /\b(test|describe|it)\s*\(/.test(wb.code);
            if (!hasTests) {
                setCode(`${wb.code.trimEnd()}\n\n// test('smoke', () => expect(true).toBe(true));\n`);
                wb.code = getCode();
            }
            analyze();
            log(hasTests ? 'Tests passed in simulation.' : 'No tests found. Added smoke test stub.', hasTests ? 'ok' : 'warn');
        }
        if (action === 'build') {
            analyze();
            const failed = wb.issues.some((issue) => moduleToneClass(issue.tone) === 'error');
            log(failed ? 'Build failed.' : 'Build succeeded.', failed ? 'error' : 'ok');
        }
        if (action === 'format') {
            try {
                editor.execCommand('beautify');
                log('Format command executed.', 'ok');
            } catch (_error) {
                log('Format command unavailable in this runtime.', 'warn');
            }
        }
        if (action === 'snippet') {
            const snippet = `\nexport async function rollout(ctx) {\n    const records = await ctx.fetch();\n    return { ok: true, count: Array.isArray(records) ? records.length : 0 };\n}\n`;
            setCode(`${getCode().trimEnd()}\n${snippet}`);
            wb.code = getCode();
            analyze();
            log('Inserted rollout snippet.', 'ok');
        }
        if (action === 'dockerfile') {
            moduleWorkbenchCopyText(moduleWorkbenchDevDockerfileSnippet(), 'Dockerfile Snippet');
            log('Copied Dockerfile starter.', 'ok');
        }
        if (action === 'export') {
            moduleWorkbenchCopyJson({ code: wb.code, issues: wb.issues, logs: wb.logs.slice(0, 24) }, 'Dev Studio Snapshot');
        }
        renderIssues();
        renderLogs();
    });

    return true;
}

function moduleRenderWorkbenchDevStudio(container, wb) {
    if (moduleRenderWorkbenchDevStudioOss(container, wb)) return;
    if (!container || !wb) return;
    wb.code = safeString(wb.code);