// Extracted from part-028.js
// Generic module content

        wb.viewMode = moduleGameStudioViewMode(payload.viewMode || wb.viewMode);
        wb.playTarget = moduleGameStudioPlayTarget(payload.playTarget || wb.playTarget);
        wb.unrealViewportUrl = safeString(payload.unrealViewportUrl) || wb.unrealViewportUrl;
        wb.unrealRcUrl = safeString(payload.unrealRcUrl) || wb.unrealRcUrl;
        wb.unrealRcEndpoint = safeString(payload.unrealRcEndpoint) || wb.unrealRcEndpoint;
        wb.unrealRcPayload = safeString(payload.unrealRcPayload) || wb.unrealRcPayload;
        wb.aiPrompt = safeString(payload.aiPrompt) || wb.aiPrompt;