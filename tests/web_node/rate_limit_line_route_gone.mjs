/* Drives rate_limit_banner.js's page wiring with the cooldown route gone, as it is while the switch for this
 * line is off on the Plugins page. tests/web_node/rate_limit_banner.mjs cannot show this: it has no document, so
 * the file returns before it asks the route or paints.
 *
 * Each page opens with the route still answering, so the line names a plan and a reset, then the route answers
 * 404. Prints what the line says at each step, for
 * tests/test_turning_cooldown_and_logs_off_touches_only_its_routes.py to hold the words on the Plugins page to.
 */
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(process.argv[2], "utf-8");

const OPENED = 1_800_000_000_000;
const RESETS_IN_S = 36 * 3600;
const PARK_S = 582;
const LIMIT = {
  profile: "local",
  remaining_s: 600,
  failure_type: "rate_limit",
  spent: true,
  account: "ChatGPT Pro",
  resets_at: OPENED / 1000 + RESETS_IN_S,
  resets_words: "Monday 2 November at 18:48",
};
const ROUTE_ON = { ok: true, json: async () => ({ cooldowns: [LIMIT] }) };
const ROUTE_GONE = { ok: false, status: 404 };

const answeredBy = (profile) => ({
  type: "model_runtime",
  runtime: { active: { profile }, attempts: [{ profile, status: "success" }] },
});
const SKIPPED_A_RESTING_MODEL = {
  type: "model_runtime",
  runtime: { attempts: [{ profile: "local", status: "skipped_rate_limited", cooldown_remaining_s: PARK_S }] },
};
const REFUSED_BY_A_RESTING_MODEL = {
  type: "error",
  error: `Rate-limit cooldown active for profile 'local' (${PARK_S}s remaining).`,
};

const settled = () => new Promise((done) => setImmediate(done));

async function open(route) {
  const line = { textContent: "", hidden: true };
  const clock = { now: OPENED, paint: null };
  const answer = { route };
  const consumer = { consume: (events, onEvent) => events.forEach(onEvent) };
  const sandbox = {
    window: { ThomasChatStreamConsumer: consumer },
    document: { readyState: "complete", getElementById: () => line },
    Date: { now: () => clock.now },
    fetch: async () => answer.route,
    setInterval: (paint) => {
      clock.paint = paint;
      return 1;
    },
    clearInterval: () => {
      clock.paint = null;
    },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "rate_limit_banner.js" });
  await settled();
  return {
    turnOff() {
      answer.route = ROUTE_GONE;
    },
    async receive(event) {
      consumer.consume([event], () => undefined);
      await settled();
    },
    wait(seconds) {
      clock.now += seconds * 1000;
      if (clock.paint) clock.paint();
    },
    says: () => (line.hidden ? "" : line.textContent),
  };
}

async function openThenTurnOff() {
  const page = await open(ROUTE_ON);
  page.turnOff();
  return page;
}

const report = {};

const page = await open(ROUTE_ON);
report.opened = page.says();
page.turnOff();
page.wait(60);
report.turned_off = page.says();
await page.receive(answeredBy("claude"));
report.another_model_answered = page.says();
await page.receive(SKIPPED_A_RESTING_MODEL);
report.a_message_ran_into_a_resting_model = page.says();
page.wait(PARK_S + 1);
report.that_countdown_ended = page.says();

const refused = await openThenTurnOff();
await refused.receive(REFUSED_BY_A_RESTING_MODEL);
report.a_resting_model_refused_the_message = refused.says();

const answered = await openThenTurnOff();
await answered.receive(answeredBy("local"));
report.that_model_answered = answered.says();

const expired = await openThenTurnOff();
expired.wait(RESETS_IN_S + 1);
report.its_time_was_up = expired.says();

const reloaded = await open(ROUTE_GONE);
report.reloaded = reloaded.says();

console.log(JSON.stringify(report));
