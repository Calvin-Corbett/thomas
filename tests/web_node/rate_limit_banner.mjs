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

// A spent allowance: the park is ten minutes, the limit runs 36 hours. The row
// carries what the refusal said, so the line names the limit and its reset
// instead of counting the park down -- and outlasts the park.
const resetsAt = now / 1000 + 36 * 3600; // the route sends Unix seconds
const spent = [
  { profile: "gpt-5.6-sol", remaining_s: 600, failure_type: "rate_limit", spent: true, account: "ChatGPT Pro", resets_at: resetsAt, resets_words: "Saturday 26 September at 08:02" },
];
state = B.applyCooldowns(null, spent, now);
report.spent_until_is_the_reset = state.until === resetsAt * 1000;
report.line_spent = B.format(state, now);
report.line_spent_after_the_park = B.format(state, now + 601_000);
report.line_spent_after_the_reset = B.format(state, resetsAt * 1000 + 1);
// with failover, the model that answered instead is named in place of the advice
state = B.applyCooldowns({ via: "claude-x" }, spent, now);
report.line_spent_via = B.format(state, now);
// a spent allowance whose body gave no reset must not have one invented for it
state = B.applyCooldowns(null, [{ profile: "gpt-5.6-sol", remaining_s: 600, failure_type: "rate_limit", spent: true, account: "ChatGPT" }], now);
report.line_spent_no_reset = B.format(state, now);
// the longest-lasting row wins, not the longest park
state = B.applyCooldowns(null, spent.concat([{ profile: "claude-x", remaining_s: 900, failure_type: "server" }]), now);
report.spent_outranks_a_longer_park = state.profile;
// eleven minutes in, or a page opened the next morning: the park is over and the
// allowance is not, so the route sends the row with no seconds left on it.
const lifted = { profile: "gpt-5.6-sol", remaining_s: 0, failure_type: "rate_limit", spent: true, account: "ChatGPT Pro", resets_at: resetsAt, resets_words: "Saturday 26 September at 08:02" };
report.line_after_the_park_lifted = B.format(B.applyCooldowns(null, [lifted], now), now);
// and a park with no allowance behind it, once lifted, is nothing to announce
report.a_lifted_burst_shows_nothing = B.applyCooldowns(null, [{ profile: "claude-x", remaining_s: 0, failure_type: "rate_limit" }], now);

// Saturday morning: the plan answers before the reset its refusal named (a reset
// read from the CLI's words is put an hour late on purpose). The receipt says it
// answered, so the line must go -- it would otherwise sit directly above the reply.
const spentClaude = B.applyCooldowns(null, [
  { profile: "anthropic", remaining_s: 0, failure_type: "rate_limit", spent: true, account: "Claude", resets_at: resetsAt, resets_words: "Saturday 26 September at 08:02" },
], now);
report.line_before_it_answered = B.format(spentClaude, now);
const success = { type: "model_runtime", runtime: { active: { profile: "anthropic", model: "sonnet" }, attempts: [{ profile: "anthropic", model: "sonnet", status: "success" }] } };
report.answered_names_the_profile = B.answered(success);
report.answering_retires_its_own_line = B.fold(spentClaude, success, now);
// another connection's turn says nothing about this one's allowance
const other = { type: "model_runtime", runtime: { active: { profile: "local" }, attempts: [{ profile: "local", status: "success" }] } };
report.someone_elses_turn_leaves_it_up = B.format(B.fold(spentClaude, other, now), now);
// and a receipt that reports a park still parks, even though one attempt succeeded
report.a_failover_still_parks = B.fold(null, {
  type: "model_runtime",
  runtime: { active: { profile: "claude-x" }, attempts: [
    { profile: "gpt-5.6-sol", status: "skipped_rate_limited", cooldown_remaining_s: 200 },
    { profile: "claude-x", status: "success" },
  ] },
}, now).profile;
report.answered_ignores_other_events = [B.answered({ type: "error", error: "x" }), B.answered(null)];
console.log(JSON.stringify(report));
