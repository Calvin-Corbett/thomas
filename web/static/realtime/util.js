export function nowMs() { return Date.now(); }

export function fmtMs(ms) {
  if (!ms && ms !== 0) return "n/a";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms/1000).toFixed(2)}s`;
}

export function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
