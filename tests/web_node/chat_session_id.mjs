/* Drives chat_session_id.js's pure core: the one place the injected panels
 * learn which chat is open, so questions and checklists stay with their chat.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], "utf-8"), sandbox, { filename: "chat_session_id.js" });
const S = sandbox.window.ThomasChatSession;
if (!S) { console.error("no ThomasChatSession"); process.exit(1); }

const rowDoc = { querySelector: (sel) => (sel.includes("aria-current") ? { dataset: { historyId: "row-session" } } : null) };
const emptyDoc = { querySelector: () => null };

const report = {};
report.nothing_known = S.current(emptyDoc);
report.row_fallback = S.current(rowDoc);

const calls = [];
const inner = async (url, init) => { calls.push(String(url)); return { ok: true }; };
const wrapped = S.wrapFetch(inner);
await wrapped("/api/v2/chat", { method: "POST", body: JSON.stringify({ message: "hi", session_id: "sent-session" }) });
report.after_send = S.current(rowDoc);
await wrapped("/api/preferences", { method: "PATCH", body: JSON.stringify({ session_id: "not-a-chat" }) });
report.other_routes_ignored = S.current(rowDoc);
S.fold({ type: "done", session_id: "stream-session" });
report.after_done = S.current(rowDoc);
S.fold({ type: "text", session_id: "ignored" });
report.text_events_ignored = S.current(rowDoc);
await wrapped("/api/v2/chat", { method: "POST", body: JSON.stringify({ message: "new chat", session_id: null }) });
report.new_chat_clears = S.current(emptyDoc);
report.new_chat_uses_row = S.current(rowDoc);
report.passthrough_calls = calls.length;

// Switching chats in the sidebar: the remembered id must not outlive the switch.
S.remember("stream-session");
const switchedDoc = { querySelector: (sel) => (sel.includes("aria-current") ? { dataset: { historyId: "other-row" } } : null) };
report.before_switch = S.current(switchedDoc);
S.chatChanged("other-row");
report.after_switch = S.current(switchedDoc);
// A session created before the first send (the page's session provider) is learned from its response.
const creating = S.wrapFetch(async () => ({ ok: true, clone() { return { json: async () => ({ session_id: "fresh-session" }) }; } }));
await creating("/api/session/new", { method: "POST" });
await new Promise((r) => setTimeout(r, 10));
report.after_create = S.current(emptyDoc);
console.log(JSON.stringify(report));
