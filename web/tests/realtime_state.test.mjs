import test from "node:test";
import assert from "node:assert/strict";
import { DuplexState } from "../static/realtime/state_machine.js";

test("duplex state transitions", () => {
  const s = new DuplexState();
  assert.equal(s.connected, false);
  s.onConnect();
  assert.equal(s.connected, true);

  const r = s.startMic();
  assert.equal(r.ok, true);

  s.onAssistantDelta("hi");
  assert.equal(s.assistantGenerating, true);

  s.assistantStart();
  assert.equal(s.assistantSpeaking, true);

  s.bargeIn("barge_in");
  assert.equal(s.assistantSpeaking, false);
  assert.equal(s.assistantGenerating, false);

  s.onAssistantDelta("hi");
  s.onAssistantDelta(" there");
  const out = s.onAssistantDone();
  assert.equal(out, "hi there");
  assert.equal(s.assistantGenerating, false);
});
