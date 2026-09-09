/* Inkwell alarms: synthesized alert sounds + the reminder clock-watcher. */
(function () {
  'use strict';
  const IW = window.IW;

  let audioCtx = null;
  const CHECK_INTERVAL_MS = 15000;

  function ensureAudio() {
    if (!audioCtx) {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      audioCtx = new Ctor();
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }

  function tone(ctx, { freq, at, dur, type, gain }) {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    amp.gain.setValueAtTime(0.0001, ctx.currentTime + at);
    amp.gain.exponentialRampToValueAtTime(gain || 0.25, ctx.currentTime + at + 0.02);
    amp.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + dur);
    osc.connect(amp).connect(ctx.destination);
    osc.start(ctx.currentTime + at);
    osc.stop(ctx.currentTime + at + dur + 0.05);
  }

  const SOUNDS = {
    chime: (ctx) => { tone(ctx, { freq: 880, at: 0, dur: 0.5 }); tone(ctx, { freq: 1320, at: 0.18, dur: 0.7 }); },
    bell: (ctx) => {
      tone(ctx, { freq: 660, at: 0, dur: 1.4, type: 'triangle', gain: 0.3 });
      tone(ctx, { freq: 1320, at: 0, dur: 0.9, gain: 0.12 });
    },
    alarm: (ctx) => {
      for (let i = 0; i < 4; i++) {
        tone(ctx, { freq: 920, at: i * 0.3, dur: 0.16, type: 'square', gain: 0.18 });
        tone(ctx, { freq: 700, at: i * 0.3 + 0.15, dur: 0.14, type: 'square', gain: 0.18 });
      }
    },
    pulse: (ctx) => {
      for (let i = 0; i < 3; i++) tone(ctx, { freq: 520, at: i * 0.45, dur: 0.22, type: 'sine', gain: 0.2 });
    },
  };

  IW.playSound = function (name) {
    try {
      const ctx = ensureAudio();
      (SOUNDS[name] || SOUNDS.chime)(ctx);
    } catch (e) { console.warn('[inkwell] audio blocked', e); }
  };

  function nextOccurrence(whenIso, repeat) {
    const date = new Date(whenIso);
    if (repeat === 'daily') date.setDate(date.getDate() + 1);
    else if (repeat === 'weekly') date.setDate(date.getDate() + 7);
    const pad = (n) => String(n).padStart(2, '0');
    return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()) +
      'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }

  async function fire(reminder) {
    IW.playSound(reminder.sound || 'chime');
    IW.toast('⏰ ' + reminder.title, 'alert');
    if (window.Notification && Notification.permission === 'granted') {
      try { new Notification('Inkwell reminder', { body: reminder.title }); } catch (e) { /* fine */ }
    }
    try {
      if (reminder.repeat && reminder.repeat !== 'none') {
        await IW.patchItem('reminders', reminder.id, { when: nextOccurrence(reminder.when, reminder.repeat) });
      } else {
        await IW.patchItem('reminders', reminder.id, { fired_at: new Date().toISOString() });
      }
    } catch (e) { console.warn('[inkwell] could not mark reminder fired', e); }
    renderReminders();
  }

  function checkDue() {
    const now = new Date();
    IW.reminders.forEach((reminder) => {
      if (!reminder.when || reminder.fired_at) return;
      const due = new Date(reminder.when);
      if (!isNaN(due) && due <= now) fire(reminder);
    });
  }

  function renderReminders() {
    const host = document.getElementById('reminderList');
    const meta = document.getElementById('reminderMeta');
    const pending = IW.reminders.filter((r) => !r.fired_at);
    meta.textContent = String(pending.length);
    host.innerHTML = '';
    if (!IW.reminders.length) {
      host.innerHTML = '<p class="iw-empty">No reminders yet — set one, or let Thomas find them in your notes.</p>';
      return;
    }
    const sorted = IW.reminders.slice().sort((a, b) => String(a.when).localeCompare(String(b.when)));
    sorted.forEach((reminder) => {
      const row = document.createElement('div');
      row.className = 'iw-item' + (reminder.fired_at ? ' iw-item-done' : '');
      const whenLabel = reminder.when ? new Date(reminder.when).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '—';
      row.innerHTML =
        '<div class="iw-item-main"><strong></strong><span class="iw-item-sub">' +
        whenLabel + ' · ' + (reminder.sound || 'chime') +
        (reminder.repeat && reminder.repeat !== 'none' ? ' · ' + reminder.repeat : '') +
        (reminder.source === 'thomas' ? ' · ✒ Thomas' : '') +
        '</span></div>';
      row.querySelector('strong').textContent = reminder.title;
      const actions = document.createElement('div');
      actions.className = 'iw-item-actions';
      const test = document.createElement('button');
      test.title = 'Preview sound';
      test.textContent = '▶';
      test.addEventListener('click', () => IW.playSound(reminder.sound || 'chime'));
      const del = document.createElement('button');
      del.title = 'Delete reminder';
      del.textContent = '×';
      del.addEventListener('click', async () => {
        await IW.deleteItem('reminders', reminder.id).catch((e) => IW.toast(e.message, 'warn'));
        renderReminders();
      });
      actions.appendChild(test);
      actions.appendChild(del);
      row.appendChild(actions);
      host.appendChild(row);
    });
  }
  IW.renderReminders = renderReminders;

  IW.addReminder = async function (fields) {
    if (window.Notification && Notification.permission === 'default') {
      Notification.requestPermission();
    }
    const item = await IW.createItem('reminders', fields);
    renderReminders();
    return item;
  };

  IW.initAlarms = function () {
    const form = document.getElementById('reminderForm');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      try {
        await IW.addReminder({
          title: String(data.get('title') || '').trim(),
          when: String(data.get('when') || ''),
          sound: String(data.get('sound') || 'chime'),
          repeat: String(data.get('repeat') || 'none'),
          source: 'manual',
        });
        form.reset();
        IW.playSound('chime');
      } catch (e) { IW.toast('Could not save reminder: ' + e.message, 'warn'); }
    });
    // Unlock WebAudio on first user gesture (browser autoplay policy).
    document.addEventListener('pointerdown', function unlock() {
      ensureAudio();
      document.removeEventListener('pointerdown', unlock);
    }, { once: true });
    setInterval(checkDue, CHECK_INTERVAL_MS);
  };
})();
