const $ = (sel) => document.querySelector(sel);

const els = {
  chatScroll: $("#chatScroll"),
  statusText: $("#statusText"),
  statusDot: $("#statusDot"),
  profileSelect: $("#profileSelect"),
  modelIdSelect: $("#modelIdSelect"),
  prompt: $("#prompt"),
  sendBtn: $("#sendBtn"),
  clearBtn: $("#clearBtn"),
  docInput: $("#docInput"),
  imgInput: $("#imgInput"),
  attachments: $("#attachments"),
  micBtn: $("#micBtn"),
  micHint: $("#micHint"),
};

const state = {
  sessionId: null,
  profiles: [],
  profile: null,
  modelId: "",
  mode: "auto",
  docs: [],
  images: [],
  streaming: false,
  recognition: null,
  listening: false,
};

function setStatus(text, ok = true) {
  els.statusText.textContent = text;
  els.statusDot.style.background = ok ? "rgba(15, 118, 110, 0.85)" : "rgba(185, 28, 28, 0.85)";
  els.statusDot.style.boxShadow = ok
    ? "0 0 0 4px rgba(15, 118, 110, 0.12)"
    : "0 0 0 4px rgba(185, 28, 28, 0.10)";
}

function escapeHtml(s) {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function addMessage(role, text = "") {
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = escapeHtml(text);

  msg.appendChild(bubble);
  els.chatScroll.appendChild(msg);
  els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
  return { msg, bubble };
}

function addToolLine(containerBubble, text) {
  const div = document.createElement("div");
  div.className = "tool-line";
  div.textContent = text;
  containerBubble.appendChild(div);
}

function renderAttachments() {
  els.attachments.innerHTML = "";
  for (const d of state.docs) {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = `<strong>doc</strong> ${escapeHtml(d.name)}`;
    els.attachments.appendChild(chip);
  }
  for (const img of state.images) {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = `<strong>img</strong> ${escapeHtml(img.name)}`;
    els.attachments.appendChild(chip);
  }
}

async function apiJson(url, opts = {}) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${t ? `: ${t}` : ""}`);
  }
  return res.json();
}

async function newSession() {
  const j = await apiJson("/api/session/new", { method: "POST" });
  state.sessionId = j.session_id;
}

async function loadProfiles() {
  const j = await apiJson("/api/models", { method: "GET" });
  state.profiles = j.profiles || [];
  state.profile = j.default || (state.profiles[0] && state.profiles[0].name) || null;

  els.profileSelect.innerHTML = "";
  for (const p of state.profiles) {
    const opt = document.createElement("option");
    opt.value = p.name;
    opt.textContent = `${p.name} (${p.provider})`;
    els.profileSelect.appendChild(opt);
  }
  if (state.profile) els.profileSelect.value = state.profile;

  await loadProfileModelIds(state.profile);
}

async function loadProfileModelIds(profile) {
  els.modelIdSelect.innerHTML = "";
  const baseOpt = document.createElement("option");
  baseOpt.value = "";
  baseOpt.textContent = "(profile default)";
  els.modelIdSelect.appendChild(baseOpt);

  if (!profile) return;
  try {
    const j = await apiJson(`/api/models/${encodeURIComponent(profile)}/ids`, { method: "GET" });
    for (const mid of j.models || []) {
      const opt = document.createElement("option");
      opt.value = mid;
      opt.textContent = mid;
      els.modelIdSelect.appendChild(opt);
    }
    els.modelIdSelect.value = state.modelId || "";
  } catch (e) {
    // Not fatal.
  }
}

function getMode() {
  const el = document.querySelector("input[name=mode]:checked");
  return el ? el.value : "auto";
}

async function sendPrompt() {
  if (state.streaming) return;

  const text = els.prompt.value.trim();
  const hasAttachments = state.docs.length > 0 || state.images.length > 0;
  if (!text && !hasAttachments) return;

  state.mode = getMode();
  state.profile = els.profileSelect.value;
  state.modelId = els.modelIdSelect.value;

  addMessage("user", text || "(attachments)");
  const asst = addMessage("assistant", "");

  const payload = {
    session_id: state.sessionId,
    profile: state.profile,
    model_id: state.modelId || null,
    mode: state.mode,
    text,
    docs: state.docs,
    images: state.images,
  };

  // Reset composer.
  els.prompt.value = "";
  state.docs = [];
  state.images = [];
  renderAttachments();

  state.streaming = true;
  setStatus(`thinking (${state.mode})...`, true);

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    let toolCount = 0;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      while (true) {
        const idx = buf.indexOf("\n");
        if (idx === -1) break;
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        if (!line) continue;

        let ev;
        try {
          ev = JSON.parse(line);
        } catch {
          continue;
        }

        if (ev.type === "text") {
          asst.bubble.textContent += ev.text || "";
          els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
        } else if (ev.type === "tool_start") {
          toolCount++;
          addToolLine(asst.bubble, `[tool] ${ev.name || "unknown"}...`);
        } else if (ev.type === "tool_result") {
          const ok = ev.ok ? "ok" : "fail";
          addToolLine(asst.bubble, `[tool] ${ev.name || "unknown"}: ${ok} (${Math.round(ev.ms || 0)}ms)`);
        } else if (ev.type === "error") {
          addToolLine(asst.bubble, `[error] ${ev.error || "unknown error"}`);
          setStatus("error", false);
        } else if (ev.type === "done") {
          setStatus(toolCount ? `done (${toolCount} tool calls)` : "done", true);
        }
      }
    }
  } catch (e) {
    addToolLine(asst.bubble, `[error] ${e.message || String(e)}`);
    setStatus("error", false);
  } finally {
    state.streaming = false;
  }
}

function setupSpeechToText() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    els.micBtn.disabled = true;
    els.micHint.textContent = "Speech-to-text unavailable in this browser.";
    return;
  }
  const rec = new SR();
  rec.lang = "en-US";
  rec.continuous = false;
  rec.interimResults = true;

  rec.onresult = (ev) => {
    let out = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      out += ev.results[i][0].transcript;
    }
    // Append live transcript into prompt.
    const cur = els.prompt.value;
    els.prompt.value = cur ? `${cur} ${out}` : out;
  };

  rec.onend = () => {
    state.listening = false;
    els.micBtn.textContent = "push-to-talk";
    els.micHint.textContent = "";
  };

  rec.onerror = () => {
    state.listening = false;
    els.micBtn.textContent = "push-to-talk";
    els.micHint.textContent = "Speech recognition error.";
  };

  state.recognition = rec;

  els.micBtn.addEventListener("click", () => {
    if (!state.recognition) return;
    if (state.listening) {
      state.recognition.stop();
      return;
    }
    state.listening = true;
    els.micBtn.textContent = "listening...";
    els.micHint.textContent = "Speak now. (This uses the browser speech engine.)";
    state.recognition.start();
  });
}

function wireUI() {
  els.sendBtn.addEventListener("click", sendPrompt);
  els.clearBtn.addEventListener("click", () => {
    els.chatScroll.innerHTML = "";
    setStatus("cleared", true);
  });
  els.profileSelect.addEventListener("change", async () => {
    state.profile = els.profileSelect.value;
    state.modelId = "";
    await loadProfileModelIds(state.profile);
  });
  els.modelIdSelect.addEventListener("change", () => {
    state.modelId = els.modelIdSelect.value;
  });

  els.prompt.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendPrompt();
    }
  });

  els.docInput.addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files.slice(0, 6)) {
      const text = await f.text().catch(() => "");
      state.docs.push({ name: f.name, text });
    }
    els.docInput.value = "";
    renderAttachments();
  });

  els.imgInput.addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files.slice(0, 3)) {
      const dataUrl = await new Promise((resolve) => {
        const fr = new FileReader();
        fr.onload = () => resolve(String(fr.result || ""));
        fr.onerror = () => resolve("");
        fr.readAsDataURL(f);
      });
      if (dataUrl) state.images.push({ name: f.name, data_url: dataUrl });
    }
    els.imgInput.value = "";
    renderAttachments();
  });

  setupSpeechToText();
}

async function main() {
  setStatus("starting...", true);
  try {
    await newSession();
    await loadProfiles();
    wireUI();
    setStatus("ready", true);
    addMessage("assistant", "Hi. Pick a profile/model and start chatting.");
  } catch (e) {
    setStatus("failed to start", false);
    addMessage("assistant", `Startup error: ${e.message || String(e)}`);
  }
}

main();

