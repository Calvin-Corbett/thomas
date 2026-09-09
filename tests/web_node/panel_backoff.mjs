/* Both composer panels poll the server; when it is away they must back off
 * instead of logging a refused connection every 1.5 s (3,179 console errors
 * on 2026-09-05 while the verify server restarted). Drives the pure
 * nextDelay(current, ok) each module exposes.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

function core(path, name) {
  const sandbox = { window: {}, console };
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(path, "utf-8"), sandbox, { filename: path });
  const c = sandbox.window[name];
  if (!c || typeof c.nextDelay !== "function") { console.error("no " + name + ".nextDelay"); process.exit(1); }
  return c;
}

const ask = core(process.argv[2], "ThomasAskUserPanel");
const todo = core(process.argv[3], "ThomasTodoPanel");

function series(c) {
  const out = [];
  let d = c.nextDelay(0, true);
  out.push(d);
  for (let i = 0; i < 6; i++) { d = c.nextDelay(d, false); out.push(d); }
  out.push(c.nextDelay(d, true));
  return out;
}

console.log(JSON.stringify({ ask: series(ask), todo: series(todo) }));
