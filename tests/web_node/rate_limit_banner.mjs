/* Drives rate_limit_banner.js's pure core: what the page shows when a model
 * is resting after a rate limit, from the receipt, the error text, or the
 * cooldown route.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], "utf-8"), sandbox, { filename: "rate_limit_banner.js" });
const B = sandbox.window.ThomasRateLimitBanner;
if (!B) { console.error("no ThomasRateLimitBanner"); process.exit(1); }

const now = 1_000_000;
const report = {};

report.text_ignored = B.fold(null, { type: "text", text: "hi" }, now);

let state = B.fold(null, {
  type: "model_runtime",
  runtime: {
    active: { profile: "claude-x", provider: "anthropic", model: "claude-x" },
    failover_used: true,
    attempts: [
      { profile: "gpt-5.6-sol", provider: "openai", model: "gpt-5.6-sol", status: "skipped_rate_limited", cooldown_remaining_s: 200 },
      { profile: "claude-x", provider: "anthropic", model: "claude-x", status: "success" },
    ],
  },
}, now);
report.from_receipt = { profile: state.profile, until: state.until, via: state.via, kind: state.kind };
report.line_receipt = B.format(state, now + 5_000);

state = B.fold(null, { type: "error", error: "Rate-limit cooldown active for profile 'gpt-5.6-sol' (45s remaining)." }, now);
report.from_error = { profile: state.profile, until: state.until, via: state.via };
report.line_error = B.format(state, now);

state = B.applyCooldowns(null, [
  { profile: "claude-x", remaining_s: 12, failure_type: "server" },
  { profile: "gpt-5.6-sol", remaining_s: 90, failure_type: "rate_limit" },
], now);
report.from_route = { profile: state.profile, until: state.until, kind: state.kind };
report.line_route = B.format(state, now);
report.line_expired = B.format(state, now + 91_000);
report.empty_route_clears = B.applyCooldowns(state, [], now);
report.format_null = B.format(null, now);
report.clock = [B.clock(0), B.clock(59), B.clock(200), B.clock(3725)];
console.log(JSON.stringify(report));
