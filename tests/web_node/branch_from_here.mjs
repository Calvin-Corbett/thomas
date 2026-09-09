/* Drives message_feedback.js's pure core: which message count a "Branch from
 * here" on a given reply row asks the server to keep.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], "utf-8"), sandbox, { filename: "message_feedback.js" });
const F = sandbox.window.ThomasMessageFeedback;
if (!F || typeof F.uptoFor !== "function") { console.error("no ThomasMessageFeedback.uptoFor"); process.exit(1); }

// Six messages in document order: user, reply, user, reply, user, reply.
// Every message row carries a copy button; user rows also carry an edit button.
const copies = [1, 2, 3, 4, 5, 6].map((n) => ({ n }));
const report = {
  first_reply: F.uptoFor(copies, copies[1]),
  second_reply: F.uptoFor(copies, copies[3]),
  last_reply: F.uptoFor(copies, copies[5]),
  unknown_row: F.uptoFor(copies, { n: 99 }),
};
console.log(JSON.stringify(report));
