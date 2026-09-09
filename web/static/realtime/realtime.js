import { detectCompat, prettyCompat } from "./compat.js";
import { RealtimeWS } from "./ws_client.js";
import { AudioCapture } from "./audio_capture.js";
import { BrowserSTT } from "./stt_client.js";
import { DuplexState } from "./state_machine.js";
import { nowMs, fmtMs } from "./util.js";

const $ = (id) => document.getElementById(id);

const stream = $("stream");
const input = $("input");
const sendBtn = $("sendBtn");
const connectBtn = $("connectBtn");
const micBtn = $("micBtn");
const pttBtn = $("pttBtn");
const interruptBtn = $("interruptBtn");
const status = $("status");
const banner = $("banner");
const modeSelect = $("modeSelect");
const sttModeSelect = $("sttModeSelect");
const ttsToggle = $("ttsToggle");
const intentBox = $("intentBox");
const nudgeBox = $("nudgeBox");
const telemetryBox = $("telemetryBox");
const qualityBox = $("qualityBox");
const attachmentsBox = $("attachments");
const pinBtn = $("pinBtn");

const compat = detectCompat();
let ws = null;
let audio = null;
let stt = null;
let state = new DuplexState();

let sessionId = null;
let lastAssistantMsgEl = null;
let assistantTextBuffer = "";

// incremental TTS
let ttsQueue = [];
let ttsSpeaking = false;
let ttsSpokenUpTo = 0;
let ttsEnabled = true;

// STT mode: "browser" | "server" | "off"
let sttMode = "browser";

// attachments handles
let attachments = [];

let budgets = {
  fast: { stt_to_text_ms: 600, user_to_first_token_ms: 800, assistant_to_tts_start_ms: 350 },
  balanced: { stt_to_text_ms: 900, user_to_first_token_ms: 1200, assistant_to_tts_start_ms: 500 },
  deep: { stt_to_text_ms: 1400, user_to_first_token_ms: 2000, assistant_to_tts_start_ms: 650 },
};

let telemetry = {
  last_rtt_ms: 0,
  last_first_token_latency_ms: 0,
  tokens_in: 0,
  tokens_out: 0,
  stt_duplicates_suppressed: 0,
  interruptions: 0,
  errors: 0
};

let quality = {};

function setStatus(s) { status.textContent = s; }
function showBanner(msg, kind="warn") {
  banner.classList.remove("hidden");
  banner.textContent = msg;
  banner.style.borderColor = kind === "bad" ? "rgba(239,68,68,0.55)" : "rgba(245,158,11,0.45)";
  banner.style.background = kind === "bad" ? "rgba(239,68,68,0.12)" : "rgba(245,158,11,0.12)";
}
function hideBanner() { banner.classList.add("hidden"); banner.textContent = ""; }

function addMsg(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `
    <div class="meta">${role} · ${new Date().toLocaleTimeString()}</div>
    <div class="body"></div>
  `;
  el.querySelector(".body").textContent = text || "";
  stream.appendChild(el);
  stream.scrollTop = stream.scrollHeight;
  return el;
}

function ensureAssistantMsg() {
  if (!lastAssistantMsgEl) lastAssistantMsgEl = addMsg("assistant", "");
  return lastAssistantMsgEl;
}

function renderIntent(intent, suggestions) {
  const lines = [];
  if (intent) lines.push(`intent: ${intent.name} (${(intent.confidence*100).toFixed(0)}%)`);
  if (suggestions && suggestions.length) {
    lines.push("");
    lines.push("suggestions:");
    for (const s of suggestions) lines.push(`- ${s.title} [${s.kind}]`);
  }
  lines.push("");
  lines.push(`stt mode: ${sttMode}`);
  lines.push(`tts: ${ttsEnabled ? "on" : "off"} (speaks as it streams)`);
  intentBox.textContent = lines.join("\n");
}

function renderNudge(nudge) {
  if (!nudge) return;
  const ts = new Date().toLocaleTimeString();
  const prev = nudgeBox.textContent.trim();
  const line = `[${ts}] ${nudge.kind}: ${nudge.text}`;
  nudgeBox.textContent = prev ? `${line}\n\n${prev}` : line;
}

function renderTelemetry() {
  const m = state.mode || "balanced";
  const b = budgets[m] || budgets.balanced;
  const lines = [];
  lines.push(prettyCompat(compat));
  lines.push("");
  lines.push(`mode: ${m}`);
  lines.push(`rtt: ${fmtMs(telemetry.last_rtt_ms)} (target ~${fmtMs(80)})`);
  lines.push(`first token: ${fmtMs(telemetry.last_first_token_latency_ms)} (budget ${fmtMs(b.user_to_first_token_ms)})`);
  lines.push(`tokens: in ${telemetry.tokens_in} / out ${telemetry.tokens_out}`);
  lines.push(`stt dupes suppressed: ${telemetry.stt_duplicates_suppressed}`);
  lines.push(`interruptions: ${telemetry.interruptions}`);
  lines.push(`errors: ${telemetry.errors}`);
  telemetryBox.textContent = lines.join("\n");
}

function renderQuality(q) {
  if (!q) return;
  const lines = [];
  for (const [k, v] of Object.entries(q)) lines.push(`${k}: ${v}`);
  qualityBox.textContent = lines.join("\n");
}

function setConnected(is) {
  state.connected = is;
  connectBtn.textContent = is ? "Disconnect" : "Connect";
  setStatus(is ? "connected" : "disconnected");
}

async function connect() {
  if (ws) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/api/realtime/ws`;

  ws = new RealtimeWS({
    url,
    autoReconnect: true,
    onOpen: () => {
      setConnected(true);
      ws.send({ t: "hello", client: { ua: compat.userAgent, tz: compat.tz }, mode: modeSelect.value });
      ws.send({ t: "telemetry", kind: "ws_reconnect", value: 0 });
    },
    onClose: () => {
      setConnected(false);
      stopAudio();
    },
    onError: () => {
      telemetry.errors++;
      renderTelemetry();
      showBanner("WebSocket error. Will retry automatically. Text mode still works.", "bad");
    },
    onMessage: onWSMessage,
  });

  ws.connect();
}

function disconnect() {
  if (!ws) return;
  ws.close();
  ws = null;
  setConnected(false);
  stopAudio();
}

function onWSMessage(msg) {
  const t = msg.t;
  if (t === "ready") {
    sessionId = msg.session?.id || null;
    budgets = msg.cfg?.budgets || budgets;
    hideBanner();
    renderTelemetry();
    renderIntent(null, []);
    return;
  }

  if (t === "error") {
    const code = msg.code || "error";
    const m = msg.message || "unknown error";
    telemetry.errors++;
    renderTelemetry();
    showBanner(`${code}: ${m}`, code === "disabled" ? "warn" : "bad");
    return;
  }

  if (t === "assistant_delta") {
    const el = ensureAssistantMsg();
    state.onAssistantDelta(msg.text || "");
    assistantTextBuffer += msg.text || "";
    el.querySelector(".body").textContent = assistantTextBuffer;

    if (ttsEnabled) maybeQueueTTS(assistantTextBuffer);
    return;
  }

  if (t === "assistant_done") {
    const fullText = state.onAssistantDone();
    assistantTextBuffer = "";
    lastAssistantMsgEl = null;

    // flush any remaining text to TTS
    if (ttsEnabled && fullText) maybeQueueTTS(fullText, { forceFlush: true });

    // if canceled, stop speaking immediately
    const canceled = msg.quality?.canceled;
    if (canceled) stopSpeaking();
    return;
  }

  if (t === "intent") {
    renderIntent(msg.intent, msg.suggestions || []);
    return;
  }

  if (t === "nudge") {
    renderNudge(msg.nudge);
    return;
  }

  if (t === "metrics") {
    telemetry = { ...telemetry, ...(msg.telemetry || {}) };
    quality = msg.quality || quality;
    renderTelemetry();
    renderQuality(quality);
    return;
  }

  if (t === "stt_accepted") {
    const txt = (msg.text || "").trim();
    if (!txt) return;

    // Avoid stomping user typing; only replace if the box is empty or already close to transcript.
    const cur = (input.value || "").trim();
    if (!cur || Math.abs(cur.length - txt.length) < 12) {
      input.value = txt;
    }

    // Auto submit only during PTT hold
    if (msg.is_final && pttBtn.dataset.pttActive === "1") {
      submitText(txt);
    }
    return;
  }
}

function submitText(text) {
  const t = (text ?? input.value).trim();
  if (!t) return;

  addMsg("user", t);
  input.value = "";

  const atts = attachments.map(a => ({ handle: a.handle, name: a.name, mime: a.mime, size: a.size }));

  if (ws) {
    ws.send({ t: "text", text: t, attachments: atts, mode: modeSelect.value });
  } else {
    showBanner("Not connected. Click Connect.", "warn");
  }
}

sendBtn.onclick = () => submitText();

connectBtn.onclick = () => {
  if (ws) disconnect(); else connect();
};

modeSelect.onchange = () => {
  state.setMode(modeSelect.value);
  renderTelemetry();
  if (ws) ws.send({ t: "hello", client: { ua: compat.userAgent, tz: compat.tz }, mode: modeSelect.value });
};



sttModeSelect.onchange = () => {
  sttMode = sttModeSelect.value;
  renderIntent(null, []);
};

ttsToggle.onchange = () => {
  ttsEnabled = !!ttsToggle.checked;
  if (!ttsEnabled) stopSpeaking();
  renderIntent(null, []);
};

interruptBtn.onclick = () => {
  telemetry.interruptions++;
  renderTelemetry();
  stopSpeaking();
  if (ws) ws.sendInterrupt("user_interrupt");
};

function stopSpeaking() {
  try {
    if (compat.hasSpeechSynth) window.speechSynthesis.cancel();
  } catch {}
  ttsQueue = [];
  ttsSpeaking = false;
  ttsSpokenUpTo = 0;
  state.assistantStop();
}

function maybeQueueTTS(fullText, { forceFlush=false } = {}) {
  if (!compat.hasSpeechSynth) return;
  if (!fullText) return;

  // Speak in chunks: grab new text since last spoken, and split on sentence boundaries when possible.
  const newPart = fullText.slice(ttsSpokenUpTo);
  if (!newPart) return;

  // If we don't have a boundary and we aren't forcing, wait for more text.
  const boundary = findBoundary(fullText, ttsSpokenUpTo);
  if (boundary < 0 && !forceFlush) return;

  const end = boundary >= 0 ? boundary : fullText.length;
  const chunk = fullText.slice(ttsSpokenUpTo, end).trim();
  if (!chunk) {
    ttsSpokenUpTo = end;
    return;
  }

  ttsSpokenUpTo = end;
  ttsQueue.push(chunk);
  pumpTTS();
}

function findBoundary(text, startIdx) {
  // Find a good cut point after startIdx: punctuation + space/newline.
  const slice = text.slice(startIdx);
  const m = slice.match(/([\.\!\?]\s|\n)/);
  if (!m) {
    // Fallback: if chunk is very long, cut at ~160 chars on nearest space.
    if (slice.length > 220) {
      const cut = slice.slice(0, 220);
      const sp = cut.lastIndexOf(" ");
      return startIdx + (sp > 60 ? sp : 220);
    }
    return -1;
  }
  return startIdx + m.index + m[0].length;
}

function pumpTTS() {
  if (!compat.hasSpeechSynth) return;
  if (ttsSpeaking) return;
  const chunk = ttsQueue.shift();
  if (!chunk) return;

  try { window.speechSynthesis.cancel(); } catch {}

  const utter = new SpeechSynthesisUtterance(chunk);
  utter.rate = 1.05;
  utter.onstart = () => { ttsSpeaking = true; state.assistantStart(); };
  utter.onend = () => { ttsSpeaking = false; state.assistantStop(); pumpTTS(); };
  utter.onerror = () => { ttsSpeaking = false; state.assistantStop(); pumpTTS(); };
  window.speechSynthesis.speak(utter);
}

async function startAudio({ ptt=false } = {}) {
  if (!compat.hasMediaDevices) {
    showBanner("No microphone support (getUserMedia). Text mode still works.", "warn");
    return;
  }
  if (!ws) {
    showBanner("Connect first before using mic.", "warn");
    return;
  }

  stopAudio();
  // announce audio stream for server-stt fallback
  ws.send({ t: "audio_begin", mime: compat.bestMime || "audio/webm;codecs=opus" });

  // Browser STT (optional)
  stt = new BrowserSTT({
    onResult: (r) => {
      if (!ws) return;
      ws.send({ t: "stt", text: r.text, is_final: r.is_final, confidence: r.confidence, seq: r.seq, src: r.src, ts: nowMs() });
    },
    onError: () => {
      telemetry.errors++;
      renderTelemetry();
    }
  });

  const canBrowserSTT = stt.supported();

  // Choose STT mode automatically unless user forced it.
  if (sttMode === "browser" && canBrowserSTT) stt.start();
  if (sttMode === "browser" && !canBrowserSTT) sttMode = "server";
  if (sttMode === "off") { /* nothing */ }

  audio = new AudioCapture({
    mime: compat.bestMime || "audio/webm;codecs=opus",
    onChunk: (chunk) => {
      // Server STT fallback path: stream binary chunks
      if (!ws) return;
      if (sttMode === "server") ws.sendBinary(chunk.data);
    },
    onVadStart: () => {
      // barge-in: cancel assistant generation or speech
      if (state.assistantGenerating || state.assistantSpeaking) {
        stopSpeaking();
        ws?.sendInterrupt("barge_in");
      }
    },
    onVadEnd: () => {},
    onError: () => {
      telemetry.errors++;
      renderTelemetry();
    }
  });

  try {
    await audio.start();
    state.startMic();
    micBtn.textContent = "Mic (on)";
    if (ptt) pttBtn.dataset.pttActive = "1";
  } catch (e) {
    showBanner("Mic capture failed. Text mode still works.", "bad");
  }

  renderIntent(null, []);
}

function stopAudio() {
  try { if (audio) audio.stop(); } catch {}
  audio = null;
  try { if (stt) stt.stop(); } catch {}
  stt = null;
  state.stopMic();
  micBtn.textContent = "Mic";
  pttBtn.dataset.pttActive = "0";
}

micBtn.onclick = async () => {
  // normal mic toggle (no auto submit)
  pttBtn.dataset.pttActive = "0";
  if (audio) stopAudio();
  else await startAudio({ ptt:false });
};

// Push-to-talk (PTT): hold button to speak; on release stop mic; submit on final STT.
pttBtn.onmousedown = async () => {
  pttBtn.dataset.pttActive = "1";
  await startAudio({ ptt:true });
};
pttBtn.onmouseup = () => {
  stopAudio();
};

// Drag & drop attachments
input.addEventListener("dragover", (e) => { e.preventDefault(); input.style.borderColor = "rgba(74,163,255,0.65)"; });
input.addEventListener("dragleave", () => { input.style.borderColor = "rgba(255,255,255,0.10)"; });
input.addEventListener("drop", async (e) => {
  e.preventDefault();
  input.style.borderColor = "rgba(255,255,255,0.10)";
  if (!ws) {
    showBanner("Connect before uploading attachments.", "warn");
    return;
  }
  const files = [...(e.dataTransfer.files || [])];
  for (const f of files) await uploadFile(f);
});

async function uploadFile(file) {
  try {
    const form = new FormData();
    form.append("file", file, file.name);
    const resp = await fetch("/api/realtime/upload", { method: "POST", body: form });
    if (!resp.ok) {
      showBanner(`Upload failed: ${resp.status}`, "bad");
      return;
    }
    const obj = await resp.json();
    if (!obj.ok) return;
    attachments.unshift({ handle: obj.handle, name: obj.name, mime: obj.mime, size: obj.size });
    renderAttachments();
  } catch (e) {
    showBanner(`Upload error: ${String(e)}`, "bad");
  }
}

function renderAttachments() {
  attachmentsBox.innerHTML = "";
  for (const a of attachments) {
    const el = document.createElement("div");
    el.className = "att";
    el.textContent = `${a.name} (${Math.round(a.size/1024)}kb)`;
    attachmentsBox.appendChild(el);
  }
}

pinBtn.onclick = () => {
  const title = (input.value || "").trim();
  if (!title) {
    showBanner("Type a goal in the box first, then click Pin goal.", "warn");
    return;
  }
  if (!ws) return;
  ws.send({ t: "pin_goal", goal: { title } });
  input.value = "";
};

// Boot
(function boot() {
  state.setMode(modeSelect.value);
  pttBtn.dataset.pttActive = "0";
  if (sttModeSelect) sttMode = sttModeSelect.value;
  if (ttsToggle) ttsEnabled = !!ttsToggle.checked;
  renderTelemetry();
  renderIntent(null, []);
  if (!compat.hasWS) showBanner("WebSocket missing in this browser. Text mode only.", "bad");
})();
