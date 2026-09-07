/* Drives settings_parity.js's pure core: the "last run" line a scheduled task
 * shows, from the run history the schedules route already returns.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], "utf-8"), sandbox, { filename: "settings_parity.js" });
const P = sandbox.window.ThomasSettingsParity;
if (!P || typeof P.lastRunLine !== "function") { console.error("no ThomasSettingsParity.lastRunLine"); process.exit(1); }

const report = {
  never: P.lastRunLine({ run_history: [] }),
  ok: P.lastRunLine({ run_history: [{ finished_at: "2026-09-05T05:34:10+00:00", duration_ms: 26031, ok: true, error: null }] }),
  failed: P.lastRunLine({
    run_history: [
      { finished_at: "2026-09-05T05:00:00+00:00", duration_ms: 1000, ok: true, error: null },
      { finished_at: "2026-09-05T05:34:10+00:00", duration_ms: 3200, ok: false, error: "scheduled task timed out after 900s: see run.log" },
    ],
  }),
  paused_with_error: P.lastRunLine({ run_history: [], last_error: "Invalid cron (paused): bad field" }),
};
console.log(JSON.stringify(report));
