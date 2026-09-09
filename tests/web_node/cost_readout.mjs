/* Drives cost_readout.js's pure core in a vm sandbox and prints a JSON
 * report for tests/test_cost_readout.py to assert on. No DOM: the fold,
 * pricing and formatting are plain functions over the chat stream's events.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf-8");
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: "cost_readout.js" });
const C = sandbox.window.ThomasCostReadout;
if (!C) { console.error("no ThomasCostReadout"); process.exit(1); }

// The pricing table exactly as /api/spend/pricing returns it.
const table = {
  "gpt-4o": { input_per_1k: 0.005, output_per_1k: 0.015 },
  "anthropic:claude-x": { input_per_1k: 0.01, output_per_1k: 0.02 },
  defaults: { input_per_1k: 0.002, output_per_1k: 0.002 },
};

let state = C.fold(null, { type: "text", text: "hi" });
state = C.fold(state, { type: "model_runtime", runtime: { active: { provider: "openai", model: "gpt-4o", profile: "fast" } } });
state = C.fold(state, {
  type: "done",
  run_usage: { prompt_tokens: 1200, completion_tokens: 340, total_tokens: 1540 },
  session_usage: { prompt_tokens: 18000, completion_tokens: 2300, total_tokens: 20300 },
});

const report = {
  model_after_receipt: state.model,
  provider_after_receipt: state.provider,
  turn_total: state.turn.total_tokens,
  session_total: state.session.total_tokens,
  // Same key order as CostTracker._get_price: provider:model, provider/model, lowercase, bare model, defaults.
  usd_known: C.price({ prompt_tokens: 1000, completion_tokens: 1000 }, table, "gpt-4o", "openai"),
  usd_provider_keyed: C.price({ prompt_tokens: 1000, completion_tokens: 0 }, table, "Claude-X", "Anthropic"),
  usd_unknown_uses_defaults: C.price({ prompt_tokens: 500, completion_tokens: 500 }, table, "mystery", ""),
  usd_without_table: C.price({ prompt_tokens: 500, completion_tokens: 500 }, null, "gpt-4o", "openai"),
  line_with_prices: C.format(state, table),
  line_without_prices: C.format(state, null),
  line_before_any_reply: C.format(C.fold(null, { type: "text" }), table),
  done_without_usage_keeps_last: C.fold(state, { type: "done" }).turn.total_tokens,
  compact: [C.compact(0), C.compact(999), C.compact(1540), C.compact(20300), C.compact(1250000)],
  // After a server restart the chat total is floored to the persisted count while the in/out split only
  // covers the turns since; the dollars are then a lower bound, priced at the input rate, and say so.
  floored_session_line: C.format(C.fold(C.fold(null, { type: "model_runtime", runtime: { active: { provider: "openai", model: "gpt-4o" } } }), {
    type: "done",
    run_usage: { prompt_tokens: 1000, completion_tokens: 0, total_tokens: 1000 },
    session_usage: { prompt_tokens: 1000, completion_tokens: 0, total_tokens: 3000 },
  }), table),
  // A reply whose prompt was mostly served from the provider's cache says so.
  cached_line: C.format(C.fold(null, {
    type: "done",
    run_usage: { prompt_tokens: 1200, completion_tokens: 30, total_tokens: 1230, cached_prompt_tokens: 1000 },
  }), null),
  // A local model server is not billed: the receipt counts the tokens and says no charge, never a cloud price.
  local_line: C.format(C.fold(C.fold(null, { type: "model_runtime", runtime: { active: { provider: "ollama", model: "qwen2.5-coder:7b" } } }), {
    type: "done",
    run_usage: { prompt_tokens: 4100, completion_tokens: 36, total_tokens: 4136 },
    session_usage: { prompt_tokens: 4100, completion_tokens: 36, total_tokens: 4136 },
  }), table),
  // The server flags a configured local model in its pricing row; the provider name alone cannot say so.
  local_row_line: C.format(C.fold(C.fold(null, { type: "model_runtime", runtime: { active: { provider: "openai_compat", model: "qwen2.5-coder:7b" } } }), {
    type: "done",
    run_usage: { prompt_tokens: 4100, completion_tokens: 2, total_tokens: 4102 },
    session_usage: { prompt_tokens: 4100, completion_tokens: 2, total_tokens: 4102 },
  }), Object.assign({ "openai_compat:qwen2.5-coder:7b": { input_per_1k: 0, output_per_1k: 0, local: true } }, table)),
  // A local model server that reported no usage: the receipt says so, and never prices zeros.
  unreported_line: C.format(C.fold(C.fold(null, { type: "model_runtime", runtime: { active: { provider: "ollama", model: "qwen2.5-coder:7b" } } }), {
    type: "done",
    usage_reported: false,
    run_usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    session_usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  }), table),
};
console.log(JSON.stringify(report));
