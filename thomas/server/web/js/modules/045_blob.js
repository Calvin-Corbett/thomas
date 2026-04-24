// Extracted from part-023b.js
// From blob

                device: wb.device,
                components: wb.components,
            }, 'App Builder Schema');
            return;
        }
        if (action === 'export_html') {
            renderPreview();
            moduleWorkbenchDownloadText('thomas-app-preview.html', wb.previewHtml, 'text/html;charset=utf-8');
            notifyUser('Exported runtime HTML.', { tone: 'success', durationMs: 1600, debugKind: 'app-builder' });
            return;
        }
        if (action === 'open_preview') {
            renderPreview();
            const blob = new Blob([wb.previewHtml], { type: 'text/html;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank', 'noopener');
            window.setTimeout(() => URL.revokeObjectURL(url), 5000);
            return;
        }
        if (action === 'export_page_dsl') {
            moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToPageDsl(wb), 'Page DSL JSON');
            return;
        }
        if (action === 'export_builder_dsl') {
            moduleWorkbenchCopyJson(moduleWorkbenchAppSchemaToBuilderDsl(wb), 'Builder DSL JSON');
            return;
        }
        if (action === 'reset') {
            grid.removeAll(false);
