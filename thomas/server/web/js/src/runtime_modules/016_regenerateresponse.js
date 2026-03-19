// Extracted from part-008b.js
// From regenerateresponse

    await streamChatResponse(payload, { userContext: newText });
}

/**
 * Regenerate an assistant response: remove it and re-stream from the
 * preceding user message.
 */
async function regenerateResponse(row) {
    if (isGenerating) return;

    const msgId = row.id;
    const histIdx = chatHistory.findIndex(m => m.id === msgId);
    if (histIdx < 0) return;

    // Find the preceding user message
    let userIdx = -1;
    for (let i = histIdx - 1; i >= 0; i--) {
        if (chatHistory[i].role === 'user') {
            userIdx = i;
            break;
        }
    }
    if (userIdx < 0) return; // No user message to regenerate from
