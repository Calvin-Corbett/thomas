/* Drives slash_palette.js's pure core in a vm sandbox with a stub document
 * and prints a JSON report for tests/test_slash_palette.py to assert on.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf-8");

function button(label, extra = {}) {
  const attrs = { "aria-label": label, ...extra };
  return {
    textContent: label,
    dataset: Object.fromEntries(Object.entries(extra).filter(([k]) => k.startsWith("data-")).map(([k, v]) => [k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v])),
    getAttribute: (name) => (name in attrs ? attrs[name] : null),
    clicked: 0,
    click() { this.clicked += 1; },
  };
}

const newChat = button("New chat");
const model = button("Switch model");
const openRow = button("R4 chart", { "aria-current": "true", "data-history-id": "chat_abc123", "data-history-title": "R4 chart" });
const edit = button("Edit and resend from here");
const fast = button("Fast replies");
const doc = {
  querySelectorAll: (sel) => (sel.includes("data-msg-edit") ? [edit] : [newChat, model, openRow, fast]),
  querySelector: (sel) => (sel.includes("aria-current") ? openRow : null),
};
const noRowDoc = { querySelectorAll: (sel) => (sel.includes("data-msg-edit") ? [] : [newChat]), querySelector: () => null };

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "slash_palette.js" });
const P = sandbox.window.ThomasSlashPalette;
if (!P) { console.error("no ThomasSlashPalette"); process.exit(1); }

const report = {
  all_present: P.match("/", doc).map((c) => c.name),
  narrowed: P.match("/mo", doc).map((c) => c.name),
  none: P.match("/zzz", doc).map((c) => c.name),
  hidden_without_control: P.match("/", noRowDoc).map((c) => c.name),
  export_url: (P.resolve("export", doc) || {}).url || null,
  click_kind: (P.resolve("new", doc) || {}).kind || null,
  missing_resolves_null: P.resolve("export", noRowDoc) === null,
  retry_kind: (P.resolve("retry", doc) || {}).kind || null,
  retry_hidden_without_edit: P.match("/re", noRowDoc).map((c) => c.name),
  help_always_present: P.match("/he", noRowDoc).map((c) => c.name),
  prefix_first: P.match("/he", doc).map((c) => c.name),
  help_kind: (P.resolve("help", noRowDoc) || {}).kind || null,
  help_lists_every_command: ((P.resolve("help", doc) || {}).commands || []).map((c) => c.name + ": " + c.hint),
};
console.log(JSON.stringify(report));
