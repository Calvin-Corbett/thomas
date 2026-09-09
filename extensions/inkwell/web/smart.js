/* Inkwell smart pipeline: every note runs through Thomas and gets sorted.
   Auto-sorting is ON by default (settings can turn it off). "remind me"-style
   phrases are keyword-indexed immediately — notes are data to index. */
(function () {
  'use strict';
  const IW = window.IW;

  let busy = false;
  let lastAnalyzedText = '';
  const REMIND_CUE = /\b(remind me|remember to|don'?t forget|need to .{1,60}\b(?:by|at|on|tomorrow|tonight)\b)\b/i;
  let lastCuedText = '';

  function setMeta(text) {
    document.getElementById('smartMeta').textContent = text || '';
  }

  function whenLabel(when) {
    const d = new Date(when);
    return isNaN(d) ? when : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  }

  function reminderExists(rem) {
    return IW.reminders.some((r) => r.title === rem.title && String(r.when) === String(rem.when));
  }

  function insightExists(text) {
    return IW.insights.some((i) => i.text === text);
  }

  // ---- "Thomas is tracking" (left rail): insights + his reminders --------
  function renderTracker() {
    const host = document.getElementById('trackerList');
    const meta = document.getElementById('trackerMeta');
    const thomasReminders = IW.reminders.filter((r) => r.source === 'thomas' && !r.fired_at);
    const total = IW.insights.length + thomasReminders.length;
    meta.textContent = String(total);
    host.innerHTML = '';
    if (!total) {
      host.innerHTML = '<p class="iw-empty">As you write, what Thomas notices and remembers about you shows up here.</p>';
      return;
    }
    thomasReminders.forEach((r) => {
      const row = document.createElement('div');
      row.className = 'iw-track-item';
      row.innerHTML = '<span class="iw-track-kind">⏰</span><div><strong></strong>' +
        '<span class="iw-item-sub">' + whenLabel(r.when) + (r.why ? ' · from: “' + '' + '”' : '') + '</span></div>';
      row.querySelector('strong').textContent = r.title;
      if (r.why) row.querySelector('.iw-item-sub').textContent = whenLabel(r.when) + ' · from: “' + r.why + '”';
      host.appendChild(row);
    });
    IW.insights.forEach((insight) => {
      const row = document.createElement('div');
      row.className = 'iw-track-item';
      const icon = insight.kind === 'category' ? '🗂' : insight.kind === 'purpose' ? '🎯' : '👁';
      row.innerHTML = '<span class="iw-track-kind">' + icon + '</span><div><strong></strong><span class="iw-item-sub"></span></div>';
      row.querySelector('strong').textContent = insight.text;
      row.querySelector('.iw-item-sub').textContent = insight.why ? 'from: “' + insight.why + '”' : '';
      const del = document.createElement('button');
      del.className = 'iw-mini iw-track-del';
      del.textContent = '×';
      del.title = 'Stop tracking this';
      del.addEventListener('click', async () => {
        await IW.deleteItem('insights', insight.id).catch(() => {});
        renderTracker();
      });
      row.appendChild(del);
      host.appendChild(row);
    });
  }
  IW.renderTracker = renderTracker;

  // ---- "Thomas noticed" (right rail): the sorting result -----------------
  function renderAnalysis(analysis, pendingReminders) {
    const host = document.getElementById('smartList');
    host.innerHTML = '';
    if (analysis.summary || analysis.category) {
      const head = document.createElement('div');
      head.className = 'iw-smart-summary';
      const cat = analysis.category && analysis.category !== 'other' ? '🗂 ' + analysis.category + ' — ' : '';
      head.textContent = cat + (analysis.summary || '');
      host.appendChild(head);
    }
    if (analysis.purpose) {
      const purpose = document.createElement('p');
      purpose.className = 'iw-smart-summary';
      purpose.textContent = '🎯 ' + analysis.purpose;
      host.appendChild(purpose);
    }
    (pendingReminders || []).forEach((reminder) => {
      const card = document.createElement('div');
      card.className = 'iw-smart-card';
      card.innerHTML = '<div class="iw-item-main"><strong></strong><span class="iw-item-sub"></span></div>';
      card.querySelector('strong').textContent = reminder.title;
      card.querySelector('.iw-item-sub').textContent =
        '⏰ ' + whenLabel(reminder.when) + ' · ' + reminder.sound + (reminder.why ? ' · “' + reminder.why + '”' : '');
      const actions = document.createElement('div');
      actions.className = 'iw-item-actions';
      const accept = document.createElement('button');
      accept.className = 'iw-accept';
      accept.textContent = '✓ Set it';
      accept.addEventListener('click', async () => {
        try {
          await IW.addReminder(Object.assign({}, reminder, { source: 'thomas' }));
          IW.playSound(reminder.sound);
          card.remove();
          renderTracker();
        } catch (e) { IW.toast('Could not set reminder: ' + e.message, 'warn'); }
      });
      const dismiss = document.createElement('button');
      dismiss.textContent = '×';
      dismiss.title = 'Dismiss';
      dismiss.addEventListener('click', () => card.remove());
      actions.appendChild(accept);
      actions.appendChild(dismiss);
      card.appendChild(actions);
      host.appendChild(card);
    });
    (analysis.observations || []).forEach((obs) => {
      const tip = document.createElement('div');
      tip.className = 'iw-smart-tip';
      tip.textContent = '👁 ' + obs.text + (obs.why ? '  —  “' + obs.why + '”' : '');
      host.appendChild(tip);
    });
    (analysis.suggestions || []).forEach((text) => {
      const tip = document.createElement('div');
      tip.className = 'iw-smart-tip';
      tip.textContent = '💡 ' + text;
      host.appendChild(tip);
    });
    if (!host.children.length) {
      host.innerHTML = '<p class="iw-empty">Thomas read the page and found nothing new to sort. Keep writing!</p>';
    }
  }

  async function recordInsights(analysis, noteId) {
    const wanted = [];
    if (analysis.category && analysis.category !== 'other') {
      wanted.push({ kind: 'category', text: 'This page is a ' + analysis.category + ' page', why: analysis.summary || '', note_id: noteId });
    }
    (analysis.observations || []).forEach((obs) => {
      wanted.push({ kind: 'observation', text: obs.text, why: obs.why || '', note_id: noteId });
    });
    for (const item of wanted) {
      if (!insightExists(item.text)) {
        try { await IW.createItem('insights', item); } catch (e) { /* tracker is best-effort */ }
      }
    }
  }

  async function analyze(manual) {
    if (busy) return;
    const text = IW.pageText();
    if (!text.trim()) {
      if (manual) IW.toast('The page is empty — write or dictate something first.');
      return;
    }
    if (!manual && text === lastAnalyzedText) return;
    if (IW.offline) {
      if (manual) IW.toast('Smart sorting needs the Thomas server (local draft mode is offline).', 'warn');
      return;
    }
    busy = true;
    setMeta('Thomas is reading…');
    document.getElementById('askThomasBtn').classList.add('iw-busy');
    try {
      const payload = await IW.requestJson(IW.apiBase + '/analyze', {
        method: 'POST',
        body: JSON.stringify({ text: text, local_now: IW.localNow() }),
      });
      lastAnalyzedText = text;
      const analysis = payload.analysis || {};
      const noteId = IW.activeNoteId || '';
      const fresh = (analysis.reminders || []).filter((r) => !reminderExists(r));
      let pending = fresh;
      if (IW.settings.auto_create_reminders && fresh.length) {
        pending = [];
        for (const reminder of fresh) {
          try {
            await IW.addReminder(Object.assign({}, reminder, { source: 'thomas', note_id: noteId }));
            IW.toast('⏰ Thomas set a reminder: ' + reminder.title);
          } catch (e) { pending.push(reminder); }
        }
        if (fresh.length && !pending.length) IW.playSound('chime');
      }
      await recordInsights(analysis, noteId);
      renderAnalysis(analysis, pending);
      renderTracker();
      setMeta('');
    } catch (e) {
      setMeta('');
      IW.toast('Thomas could not sort the page: ' + e.message, 'warn');
    } finally {
      busy = false;
      document.getElementById('askThomasBtn').classList.remove('iw-busy');
    }
  }

  // Keyword indexing: a literal "remind me…" cue gets picked up right away —
  // no waiting for the slow auto pass. Notes are data to index.
  const cueAnalyze = IW.debounce(() => analyze(false), 2500);
  const autoAnalyze = IW.debounce(() => { if (IW.settings.auto_smart) analyze(false); }, 9000);

  function onNoteDirty() {
    const text = IW.pageText();
    if (REMIND_CUE.test(text) && text !== lastCuedText && !IW.offline && IW.settings.auto_smart) {
      lastCuedText = text;
      setMeta('reminder spotted…');
      cueAnalyze();
    }
    autoAnalyze();
  }

  // ---- settings panel ------------------------------------------------------
  function openSettings() {
    document.getElementById('setAutoSmart').checked = !!IW.settings.auto_smart;
    document.getElementById('setAutoReminders').checked = !!IW.settings.auto_create_reminders;
    document.getElementById('setMicSilence').value = IW.settings.mic_silence_s || 8;
    document.getElementById('settingsPanel').hidden = false;
  }

  function bindSettings() {
    document.getElementById('settingsBtn').addEventListener('click', openSettings);
    document.getElementById('settingsClose').addEventListener('click', () => {
      document.getElementById('settingsPanel').hidden = true;
    });
    document.getElementById('settingsPanel').addEventListener('click', (e) => {
      if (e.target.id === 'settingsPanel') document.getElementById('settingsPanel').hidden = true;
    });
    document.getElementById('setAutoSmart').addEventListener('change', (e) => {
      IW.saveSettings({ auto_smart: e.target.checked });
      IW.toast(e.target.checked ? 'Smart auto-sorting is ON.' : 'Auto-sorting off — Inkwell is a plain notepad until you turn it back on.');
    });
    document.getElementById('setAutoReminders').addEventListener('change', (e) => {
      IW.saveSettings({ auto_create_reminders: e.target.checked });
    });
    document.getElementById('setMicSilence').addEventListener('change', (e) => {
      IW.saveSettings({ mic_silence_s: Number(e.target.value) || 8 });
    });
  }

  IW.initSmart = function () {
    document.getElementById('askThomasBtn').addEventListener('click', () => analyze(true));
    bindSettings();
    IW.on('note-dirty', onNoteDirty);
  };
})();
