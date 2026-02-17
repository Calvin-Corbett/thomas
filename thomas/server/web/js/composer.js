/* ============================================================
   Thomas Composer
   ============================================================
   Input area with auto-resize, attachments, mic, send/stop.
   ============================================================ */

import { getState, subscribe, setState } from './store.js';
import { saveSetting } from './db.js';
import { sendMessage, stopStreaming, stopSpeakingTts } from './chat.js';
import { el, icon } from './utils.js';
import { createChip, showToast } from './components.js';
import { openQuickModelPicker } from './models-unified.js';

let _textarea = null;
let _sendBtn = null;
let _micBtn = null;
let _composerEl = null;
let _hintEl = null;
let _voiceOverlayEl = null;
let _voiceCircleEl = null;
let _voiceStatusEl = null;
let _voiceTranscriptEl = null;
let _attachments = [];
let _recognition = null;
let _listening = false;
let _sttBaseText = '';
let _sttFinalSegments = [];
let _sttFinalText = '';
let _sttInterimText = '';
let _sttHadInput = false;
let _sttStopReason = '';
let _sttKeepAlive = false;
let _voiceSessionActive = false;
let _voiceOverlayMode = false;
let _voiceModeState = 'idle';
let _awaitingAssistant = false;
let _voiceEventsBound = false;
let _suppressMicClickUntil = 0;
let _micLongPressTimer = null;
let _micLongPressFired = false;
let _micClickDelayTimer = null;
let _startListening = null;

export function initComposer() {
  _textarea = document.getElementById('composerTextarea');
  _sendBtn = document.getElementById('sendBtn');
  _composerEl = document.getElementById('composer');
  _hintEl = document.getElementById('composerHint');

  if (_sendBtn) _sendBtn.appendChild(icon('send'));
  ensureVoiceOverlay();

  if (_textarea) {
    _textarea.addEventListener('input', autoResize);
    _textarea.addEventListener('input', updateSendButton);
    _textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
    _textarea.addEventListener('paste', handlePaste);
  }

  if (_sendBtn) {
    _sendBtn.addEventListener('click', () => {
      const streaming = !!getState().ui.streaming;
      const hasContent = ((_textarea?.value || '').trim().length > 0) || _attachments.length > 0;
      if (streaming && !hasContent) {
        stopStreaming();
        return;
      }
      handleSend();
    });
  }

  // Attach buttons
  const attachDocBtn = document.getElementById('attachDocBtn');
  const attachImageBtn = document.getElementById('attachImageBtn');
  const docInput = document.getElementById('docFileInput');
  const imageInput = document.getElementById('imageFileInput');

  if (attachDocBtn) {
    attachDocBtn.appendChild(icon('attach'));
    attachDocBtn.addEventListener('click', () => docInput?.click());
  }
  if (attachImageBtn) {
    attachImageBtn.appendChild(icon('image'));
    attachImageBtn.addEventListener('click', () => imageInput?.click());
  }

  if (docInput) {
    docInput.addEventListener('change', async (e) => {
      for (const f of Array.from(e.target.files || []).slice(0, 6)) {
        const text = await f.text().catch(() => '');
        _attachments.push({ type: 'doc', name: f.name, text });
      }
      docInput.value = '';
      renderAttachments();
      updateSendButton();
    });
  }

  if (imageInput) {
    imageInput.addEventListener('change', async (e) => {
      for (const f of Array.from(e.target.files || []).slice(0, 3)) {
        const dataUrl = await readFileAsDataUrl(f);
        if (dataUrl) _attachments.push({ type: 'image', name: f.name, dataUrl });
      }
      imageInput.value = '';
      renderAttachments();
      updateSendButton();
    });
  }

  // Mic
  _micBtn = document.getElementById('micBtn');
  if (_micBtn) {
    _micBtn.appendChild(icon('mic'));
    setupSpeechToText(_micBtn);
  }

  // Drag and drop files onto the composer
  if (_composerEl) {
    _composerEl.addEventListener('dragover', (e) => {
      e.preventDefault();
      _composerEl.classList.add('drag-over');
    });
    _composerEl.addEventListener('dragleave', () => _composerEl.classList.remove('drag-over'));
    _composerEl.addEventListener('drop', async (e) => {
      e.preventDefault();
      _composerEl.classList.remove('drag-over');
      const files = Array.from(e.dataTransfer?.files || []);
      if (files.length > 0) await addFiles(files);
    });
  }

  subscribe('ui', () => {
    updateSendButtonState();
    updateComposerHint();
  });
  syncVoiceUi();
  updateSendButton();
  updateComposerHint();
}

function autoResize() {
  if (!_textarea) return;
  _textarea.style.height = 'auto';
  _textarea.style.height = Math.min(_textarea.scrollHeight, 200) + 'px';
}

function updateSendButton() {
  updateSendButtonState();
  updateComposerHint();
}

function updateSendButtonState() {
  if (!_sendBtn || !_textarea) return;
  const streaming = getState().ui.streaming;
  const hasContent = _textarea.value.trim().length > 0 || _attachments.length > 0;
  _sendBtn.innerHTML = '';
  _sendBtn.classList.remove('queue');
  if (streaming && !hasContent) {
    _sendBtn.appendChild(icon('stop'));
    _sendBtn.classList.add('stop');
    _sendBtn.disabled = false;
    _sendBtn.setAttribute('aria-label', 'Stop generation');
  } else {
    _sendBtn.appendChild(icon('send'));
    _sendBtn.classList.remove('stop');
    _sendBtn.disabled = !hasContent;
    if (streaming && hasContent) {
      _sendBtn.classList.add('queue');
      _sendBtn.setAttribute('aria-label', 'Start background run');
      _sendBtn.disabled = false;
    } else {
      _sendBtn.setAttribute('aria-label', 'Send message');
    }
  }
}

function updateComposerHint() {
  if (!_hintEl) return;
  const ui = getState().ui || {};
  const running = Number(ui.concurrentRuns || 0);
  const queued = Number(ui.queuedMessages || 0);
  const streaming = !!ui.streaming;
  if (streaming && (running > 0 || queued > 0)) {
    const parts = [];
    if (running > 0) parts.push(`${running} running`);
    if (queued > 0) parts.push(`${queued} queued`);
    _hintEl.textContent = `Working (${parts.join(', ')})`;
    return;
  }
  if (streaming) {
    _hintEl.textContent = 'Working... press Enter to start another run';
    return;
  }
  if (running > 0) {
    _hintEl.textContent = `${running} running in background`;
    return;
  }
  if (queued > 0) {
    _hintEl.textContent = `${queued} queued`;
    return;
  }
  _hintEl.textContent = 'Enter to send';
}

function ensureVoiceOverlay() {
  if (_voiceOverlayEl) return;
  const inner = _composerEl?.querySelector('.composer-inner');
  if (!inner) return;

  const overlay = el('div', { className: 'voice-overlay', id: 'voiceOverlay' });
  const circle = el('button', {
    className: 'voice-circle',
    id: 'voiceCircle',
    type: 'button',
    'aria-label': 'Voice control',
  });
  circle.appendChild(icon('mic'));

  const status = el('div', { className: 'voice-status', id: 'voiceStatus' }, 'Listening...');
  const transcript = el('div', { className: 'voice-transcript', id: 'voiceTranscript' }, 'Say something...');
  const stopBtn = el('button', { className: 'btn btn-danger btn-sm voice-stop-btn', type: 'button' }, 'Stop voice mode');

  overlay.appendChild(circle);
  overlay.appendChild(status);
  overlay.appendChild(transcript);
  overlay.appendChild(stopBtn);

  const actions = inner.querySelector('.composer-actions');
  if (actions) inner.insertBefore(overlay, actions);
  else inner.appendChild(overlay);

  _voiceOverlayEl = overlay;
  _voiceCircleEl = circle;
  _voiceStatusEl = status;
  _voiceTranscriptEl = transcript;

  stopBtn.addEventListener('click', () => {
    stopVoiceSession({ showToastMessage: true });
  });

  circle.addEventListener('click', () => {
    if (!_recognition || !_voiceOverlayMode) return;
    if (_listening) {
      _sttKeepAlive = false;
      _sttStopReason = 'overlay_pause';
      try { _recognition.stop(); } catch { /* ignore */ }
      return;
    }
    if (_awaitingAssistant || getState().ui.streaming) return;
    _startListening?.({ forceSession: true });
  });
}

function setVoiceModeState(next, transcript = null) {
  _voiceModeState = next || 'idle';

  if (_voiceStatusEl) {
    if (_voiceModeState === 'listening') _voiceStatusEl.textContent = 'Listening...';
    else if (_voiceModeState === 'thinking') _voiceStatusEl.textContent = 'Thinking...';
    else if (_voiceModeState === 'speaking') _voiceStatusEl.textContent = 'Speaking...';
    else _voiceStatusEl.textContent = 'Voice mode ready';
  }

  if (_voiceCircleEl) {
    _voiceCircleEl.classList.toggle('listening', _voiceModeState === 'listening');
    _voiceCircleEl.classList.toggle('thinking', _voiceModeState === 'thinking');
    _voiceCircleEl.classList.toggle('speaking', _voiceModeState === 'speaking');
  }

  if (typeof transcript === 'string' && _voiceTranscriptEl) {
    const t = transcript.trim();
    _voiceTranscriptEl.textContent = t || 'Say something...';
  }

  syncVoiceUi();
}

function syncVoiceUi() {
  const voiceModeActive = !!(_voiceOverlayMode && _voiceSessionActive);
  if (_composerEl) _composerEl.classList.toggle('voice-mode', voiceModeActive);
  if (_micBtn) {
    _micBtn.classList.toggle('listening', _listening);
    _micBtn.classList.toggle('voice-session', voiceModeActive || _awaitingAssistant);
  }
}

function stopVoiceSession({ showToastMessage = false } = {}) {
  _voiceOverlayMode = false;
  _voiceSessionActive = false;
  _awaitingAssistant = false;
  _sttKeepAlive = false;

  if (_listening && _recognition) {
    _sttStopReason = 'toggle';
    try { _recognition.stop(); } catch { /* ignore */ }
  }
  _listening = false;
  if (_micBtn) _micBtn.style.color = '';
  try { stopSpeakingTts(); } catch { /* ignore */ }

  setVoiceModeState('idle', '');
  syncVoiceUi();
  if (showToastMessage) showToast('Voice conversation stopped.', 'info');
}

function enableVoiceConversationSettings() {
  const s = getState().settings || {};
  if (!s.voiceConversation) {
    setState('settings', { voiceConversation: true });
    saveSetting('voiceConversation', true);
  }
  if (!s.ttsEnabled) {
    setState('settings', { ttsEnabled: true });
    saveSetting('ttsEnabled', true);
  }
}

function enterVoiceOverlayMode() {
  if (!_recognition) return;
  if (getState().ui.streaming) {
    showToast('Stop current reply before starting voice mode.', 'info');
    return;
  }

  _suppressMicClickUntil = Date.now() + 500;
  enableVoiceConversationSettings();
  _voiceOverlayMode = true;
  _voiceSessionActive = true;
  _awaitingAssistant = false;
  setVoiceModeState('listening', '');
  if (!_listening) _startListening?.({ forceSession: true });
}

function handleSend() {
  if (!_textarea) return;
  if (_listening && _recognition) {
    _sttKeepAlive = false;
    _sttStopReason = 'send';
    try { _recognition.stop(); } catch { /* ignore */ }
    _listening = false;
    if (_micBtn) _micBtn.style.color = '';
    syncVoiceUi();
  }
  const text = _textarea.value.trim();
  if (!text && _attachments.length === 0) return;

  // Slash commands
  const lower = text.toLowerCase();
  if (lower === '/model' || lower.startsWith('/model ')) {
    if (_attachments.length > 0) {
      showToast('Remove attachments before using /model', 'error');
      return;
    }

    const search = text.slice('/model'.length).trim();
    _textarea.value = '';
    autoResize();
    updateSendButton();
    openQuickModelPicker({ search });
    return;
  }

  const docs = _attachments.filter(a => a.type === 'doc');
  const images = _attachments.filter(a => a.type === 'image');

  _textarea.value = '';
  _attachments = [];
  autoResize();
  renderAttachments();
  updateSendButton();

  const s = getState().settings || {};
  if (_voiceSessionActive && s.voiceConversation) {
    _awaitingAssistant = true;
    if (_voiceOverlayMode) setVoiceModeState('thinking');
  }

  sendMessage(text, docs, images);
}

function renderAttachments() {
  const container = document.getElementById('composerAttachments');
  if (!container) return;
  container.innerHTML = '';
  for (let i = 0; i < _attachments.length; i++) {
    const att = _attachments[i];
    const idx = i;
    if (att.type === 'image' && att.dataUrl) {
      const chip = el('span', { className: 'attachment' });
      const img = el('img', { className: 'attachment-thumb', src: att.dataUrl, alt: att.name });
      chip.appendChild(img);
      chip.appendChild(el('span', { className: 'truncate', style: { maxWidth: '160px' } }, att.name));
      const rm = el('button', { className: 'attachment-remove', type: 'button', 'aria-label': 'Remove attachment' }, 'x');
      rm.addEventListener('click', () => {
        _attachments.splice(idx, 1);
        renderAttachments();
        updateSendButton();
      });
      chip.appendChild(rm);
      container.appendChild(chip);
    } else {
      container.appendChild(createChip({
        label: `doc ${att.name}`,
        onRemove: () => {
          _attachments.splice(idx, 1);
          renderAttachments();
          updateSendButton();
        },
      }));
    }
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

async function addFiles(files) {
  const docs = [];
  const images = [];
  for (const f of files) {
    if (f.type && f.type.startsWith('image/')) images.push(f);
    else docs.push(f);
  }

  // Docs
  for (const f of docs.slice(0, Math.max(0, 6 - _attachments.filter(a => a.type === 'doc').length))) {
    if (f.size > 2_000_000) {
      showToast(`Skipping ${f.name} (too large)`, 'error');
      continue;
    }
    const text = await f.text().catch(() => '');
    _attachments.push({ type: 'doc', name: f.name, text });
  }

  // Images
  for (const f of images.slice(0, Math.max(0, 3 - _attachments.filter(a => a.type === 'image').length))) {
    if (f.size > 8_000_000) {
      showToast(`Skipping ${f.name} (too large)`, 'error');
      continue;
    }
    const dataUrl = await readFileAsDataUrl(f);
    if (dataUrl) _attachments.push({ type: 'image', name: f.name, dataUrl });
  }

  renderAttachments();
  updateSendButton();
}

async function handlePaste(e) {
  const items = Array.from(e.clipboardData?.items || []);
  const files = [];
  for (const it of items) {
    if (it.kind === 'file') {
      const f = it.getAsFile();
      if (f) files.push(f);
    }
  }
  if (files.length > 0) {
    e.preventDefault();
    await addFiles(files);
  }
}

function setupSpeechToText(micBtn) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { micBtn.disabled = true; micBtn.title = 'Speech-to-text unavailable'; return; }

  _recognition = new SR();
  _recognition.lang = 'en-US';
  // Keep listening until explicitly stopped by the user.
  _recognition.continuous = true;
  _recognition.interimResults = true;

  const isVoiceConversationEnabled = () => {
    const s = getState().settings || {};
    return !!s.voiceConversation;
  };

  const resetSttBuffers = () => {
    _sttBaseText = '';
    _sttFinalSegments = [];
    _sttFinalText = '';
    _sttInterimText = '';
    _sttHadInput = false;
    _sttStopReason = '';
  };

  const startListening = ({ forceSession = false } = {}) => {
    if (!_recognition) return false;
    if (getState().ui.streaming) {
      showToast('Stop current reply before starting voice input.', 'info');
      return false;
    }

    _sttBaseText = _textarea ? String(_textarea.value || '') : '';
    _sttFinalSegments = [];
    _sttFinalText = '';
    _sttInterimText = '';
    _sttHadInput = false;
    _sttStopReason = '';
    _sttKeepAlive = true;
    _listening = true;

    if (isVoiceConversationEnabled() || forceSession) {
      _voiceSessionActive = true;
    }

    try { stopSpeakingTts(); } catch { /* ignore */ }
    micBtn.style.color = 'var(--danger)';
    syncVoiceUi();
    if (_voiceOverlayMode) setVoiceModeState('listening');
    try {
      _recognition.start();
      return true;
    } catch {
      _listening = false;
      _sttKeepAlive = false;
      micBtn.style.color = '';
       syncVoiceUi();
      resetSttBuffers();
      showToast('Microphone start failed. Check browser mic permission.', 'error');
      return false;
    }
  };
  _startListening = startListening;

  const maybeResumeVoiceLoop = (source, detail = {}) => {
    if (!_voiceSessionActive || !_awaitingAssistant) return;
    if (getState().ui.streaming || _listening) return;
    if (_voiceOverlayMode) setVoiceModeState('thinking');

    // If speech actually started, prefer waiting for tts_end to avoid barge-in.
    const canTts = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);
    if (source === 'assistant_done' && canTts && getState().settings?.ttsEnabled && detail?.spoke) {
      return;
    }

    _awaitingAssistant = false;
    startListening({ forceSession: true });
  };

  if (!_voiceEventsBound) {
    window.addEventListener('thomas:assistant_done', (ev) => {
      maybeResumeVoiceLoop('assistant_done', ev?.detail || {});
    });
    window.addEventListener('thomas:tts_start', () => {
      if (_voiceOverlayMode && _voiceSessionActive) setVoiceModeState('speaking');
    });
    window.addEventListener('thomas:tts_end', (ev) => {
      maybeResumeVoiceLoop('tts_end', ev?.detail || {});
    });
    _voiceEventsBound = true;
  }

  const applySttToComposer = (includeInterim = true) => {
    if (!_textarea) return;
    const parts = [];
    const base = String(_sttBaseText || '').trim();
    const finalText = String(_sttFinalText || '').trim();
    const interimText = includeInterim ? String(_sttInterimText || '').trim() : '';
    if (base) parts.push(base);
    if (finalText) parts.push(finalText);
    if (interimText) parts.push(interimText);
    _textarea.value = parts.join(' ').trim();
    autoResize();
    updateSendButton();

    if (_voiceOverlayMode) {
      const preview = interimText || finalText || '';
      setVoiceModeState(_listening ? 'listening' : _voiceModeState, preview);
    }
  };

  _recognition.onresult = (ev) => {
    const startIdx = Number.isInteger(ev?.resultIndex) ? Number(ev.resultIndex) : 0;
    const interim = [];
    for (let i = startIdx; i < ev.results.length; i++) {
      const r = ev.results[i];
      const t = String(r?.[0]?.transcript || '').trim();
      if (!t) continue;
      if (r.isFinal) {
        const last = _sttFinalSegments[_sttFinalSegments.length - 1] || '';
        // Browsers may re-emit/extend the same finalized phrase; fold it.
        if (!last) {
          _sttFinalSegments.push(t);
        } else if (t === last) {
          // no-op
        } else if (t.startsWith(last)) {
          _sttFinalSegments[_sttFinalSegments.length - 1] = t;
        } else {
          _sttFinalSegments.push(t);
        }
      } else {
        interim.push(t);
      }
    }

    _sttFinalText = _sttFinalSegments.join(' ').replace(/\s+/g, ' ').trim();
    _sttInterimText = interim.join(' ').replace(/\s+/g, ' ').trim();
    _sttHadInput = !!(_sttFinalText || _sttInterimText);
    applySttToComposer(true);
  };

  _recognition.onend = () => {
    const reason = _sttStopReason || '';
    _listening = false;
    micBtn.style.color = '';
    syncVoiceUi();

    // If browser ended recognition unexpectedly, restart while in keep-alive mode.
    if (_sttKeepAlive && !reason && !getState().ui.streaming) {
      try {
        _recognition.start();
        _listening = true;
        micBtn.style.color = 'var(--danger)';
        syncVoiceUi();
        if (_voiceOverlayMode) setVoiceModeState('listening');
        return;
      } catch {
        // Fall through and finalize current transcript.
      }
    }

    // On completion, keep only finalized transcript text unless this stop came from Send.
    if (_sttHadInput && reason !== 'send') {
      applySttToComposer(false);
      const s = getState().settings || {};
      const shouldAutoSend =
        reason !== 'send' &&
        !!s.voiceConversation &&
        s.voiceAutoSend !== false &&
        !getState().ui.streaming &&
        String(_sttFinalText || '').trim().length > 0;
      if (shouldAutoSend) {
        _awaitingAssistant = true;
        if (_voiceOverlayMode) setVoiceModeState('thinking');
        handleSend();
      }
    }
    _sttKeepAlive = false;
    if (reason === 'toggle') {
      _voiceSessionActive = false;
      _awaitingAssistant = false;
      _voiceOverlayMode = false;
      setVoiceModeState('idle', '');
    } else if (_voiceOverlayMode && _voiceSessionActive && !_awaitingAssistant) {
      setVoiceModeState('idle', _sttFinalText || '');
    }
    syncVoiceUi();
    resetSttBuffers();
  };

  _recognition.onerror = () => {
    _listening = false;
    micBtn.style.color = '';
    syncVoiceUi();
    if (_sttHadInput && _sttStopReason !== 'send') applySttToComposer(false);
    _sttKeepAlive = false;
    if (_sttStopReason === 'toggle') {
      _voiceSessionActive = false;
      _awaitingAssistant = false;
      _voiceOverlayMode = false;
    }
    if (_voiceOverlayMode && _voiceSessionActive) setVoiceModeState('idle', _sttFinalText || '');
    resetSttBuffers();
  };

  function clearLongPress() {
    if (_micLongPressTimer) clearTimeout(_micLongPressTimer);
    _micLongPressTimer = null;
  }

  micBtn.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    _micLongPressFired = false;
    clearLongPress();
    _micLongPressTimer = setTimeout(() => {
      _micLongPressFired = true;
      enterVoiceOverlayMode();
    }, 420);
  });
  micBtn.addEventListener('pointerup', clearLongPress);
  micBtn.addEventListener('pointerleave', clearLongPress);
  micBtn.addEventListener('pointercancel', clearLongPress);

  micBtn.addEventListener('dblclick', (e) => {
    e.preventDefault();
    clearLongPress();
    if (_micClickDelayTimer) {
      clearTimeout(_micClickDelayTimer);
      _micClickDelayTimer = null;
    }
    _micLongPressFired = true;
    enterVoiceOverlayMode();
  });

  micBtn.addEventListener('click', () => {
    clearLongPress();
    if (_micClickDelayTimer) clearTimeout(_micClickDelayTimer);
    _micClickDelayTimer = setTimeout(() => {
      _micClickDelayTimer = null;
      if (Date.now() < _suppressMicClickUntil || _micLongPressFired) {
        _micLongPressFired = false;
        return;
      }
      if (_voiceOverlayMode && (_voiceSessionActive || _listening || _awaitingAssistant)) {
        stopVoiceSession({ showToastMessage: true });
        return;
      }
      if (_listening) {
        _sttKeepAlive = false;
        _sttStopReason = 'toggle';
        _recognition.stop();
        return;
      }
      if (_voiceSessionActive && _awaitingAssistant) {
        _voiceSessionActive = false;
        _awaitingAssistant = false;
        try { stopSpeakingTts(); } catch { /* ignore */ }
        syncVoiceUi();
        showToast('Voice conversation stopped.', 'info');
        return;
      }
      if (getState().ui.streaming) {
        showToast('Stop current reply before starting voice input.', 'info');
        return;
      }
      startListening({ forceSession: false });
    }, 230);
  });
}

export function focusComposer() { _textarea?.focus(); }

export function setComposerText(text, { append = false } = {}) {
  if (!_textarea) return;
  const cur = _textarea.value || '';
  _textarea.value = append && cur ? (cur + '\n' + text) : text;
  autoResize();
  updateSendButton();
}

export function getComposerText() {
  return _textarea ? (_textarea.value || '') : '';
}
