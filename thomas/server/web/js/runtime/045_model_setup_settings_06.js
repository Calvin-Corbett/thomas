function humanizeConnectionPath(pathRaw) {
    const path = safeString(pathRaw).toLowerCase();
    if (path === 'codex') return 'ChatGPT (OpenAI)';
    if (path === 'manual') return 'Provider API key';
    if (path === 'local') return 'Local Ollama';
    if (path) return path;
    return 'Not connected';
}

