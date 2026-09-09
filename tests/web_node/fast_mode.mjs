/* Drives fast_mode.js's pure core in a vm sandbox and prints a JSON report
 * for tests/test_fast_mode.py. The core rewrites the chat request body the
 * page already sends; no DOM is needed to prove that.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf-8");
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "fast_mode.js" });
const F = sandbox.window.ThomasFastMode;
if (!F) { console.error("no ThomasFastMode"); process.exit(1); }

const calls = [];
const inner = async (url, init) => { calls.push({ url: String(url), body: init && init.body, method: init && init.method }); return { ok: true, url: String(url) }; };
let on = true;
const wrapped = F.wrapFetch(inner, () => on);

const chatReply = await wrapped("/api/v2/chat", { method: "POST", body: JSON.stringify({ message: "hi", session_id: "s1" }) });
await wrapped("/api/preferences", { method: "PATCH", body: JSON.stringify({ message: "hi" }) });
await wrapped("/api/v2/chat/session/s1/delegations");
on = false;
await wrapped("/api/v2/chat", { method: "POST", body: JSON.stringify({ message: "later" }) });

const report = {
  on_adds_mode: JSON.parse(F.applyFast(JSON.stringify({ message: "hi" }), true)).mode,
  off_leaves_body: F.applyFast('{"message":"hi"}', false),
  explicit_mode_kept: JSON.parse(F.applyFast(JSON.stringify({ message: "hi", mode: "thinking" }), true)).mode,
  non_json_untouched: F.applyFast("not json", true),
  chat_body_mode: JSON.parse(calls[0].body).mode,
  chat_body_keeps_fields: JSON.parse(calls[0].body).session_id,
  chat_reply_passthrough: chatReply.url,
  other_route_untouched: calls[1].body,
  get_untouched: calls[2].body === undefined,
  off_later_untouched: JSON.parse(calls[3].body).mode === undefined,
  call_count: calls.length,
};
console.log(JSON.stringify(report));
