/**
 * Client state machine for duplex voice chat.
 * Keeps the logic testable (used by web/tests/realtime_state.test.mjs).
 */
export class DuplexState {
  constructor() {
    this.connected = false;
    this.mode = "balanced";
    this.micActive = false;

    // Assistant activity (streaming or speaking)
    this.assistantGenerating = false;
    this.assistantSpeaking = false;

    this.pendingAssistantText = "";
    this.lastInterruptReason = null;
  }

  setMode(m) { this.mode = m || "balanced"; }

  onConnect() { this.connected = true; }
  onDisconnect() {
    this.connected = false;
    this.micActive = false;
    this.assistantGenerating = false;
    this.assistantSpeaking = false;
    this.pendingAssistantText = "";
  }

  startMic() {
    if (!this.connected) return { ok: false, reason: "not_connected" };
    this.micActive = true;
    return { ok: true };
  }
  stopMic() { this.micActive = false; }

  assistantGenStart() { this.assistantGenerating = true; }
  assistantGenStop() { this.assistantGenerating = false; }

  assistantStart() { this.assistantSpeaking = true; }
  assistantStop() { this.assistantSpeaking = false; }

  // barge-in: user starts speaking while assistant active
  bargeIn(reason="barge_in") {
    this.lastInterruptReason = reason;
    this.assistantGenerating = false;
    this.assistantSpeaking = false;
    this.pendingAssistantText = "";
    return { ok: true, reason };
  }

  onAssistantDelta(text) {
    if (!this.assistantGenerating) this.assistantGenStart();
    this.pendingAssistantText += (text || "");
  }
  onAssistantDone() {
    this.assistantGenStop();
    const out = this.pendingAssistantText;
    this.pendingAssistantText = "";
    return out;
  }
}
