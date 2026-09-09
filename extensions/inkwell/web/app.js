/* Inkwell app shell: pages list, note switching, debounced saving, boot. */
(function () {
  'use strict';
  const IW = window.IW;

  function renderPages() {
    const host = document.getElementById('pageList');
    host.innerHTML = '';
    if (!IW.notes.length) {
      host.innerHTML = '<p class="iw-empty">No pages yet.</p>';
      return;
    }
    IW.notes.forEach((note) => {
      const row = document.createElement('div');
      row.className = 'iw-page' + (note.id === IW.activeNoteId ? ' iw-page-active' : '');
      const title = document.createElement('span');
      title.className = 'iw-page-title';
      title.textContent = note.title || 'Untitled page';
      const del = document.createElement('button');
      del.className = 'iw-mini';
      del.title = 'Delete page';
      del.textContent = '×';
      del.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!confirm('Delete page "' + (note.title || 'Untitled page') + '"?')) return;
        try {
          await IW.deleteItem('notes', note.id);
          if (IW.activeNoteId === note.id) {
            // Migrate pre-rename starter copy living in saved state.
    IW.notes.forEach((n) => (n.blocks || []).forEach((b) => {
      if (b.text && b.text.indexOf('✨ Ask Thomas') >= 0) {
        b.text = b.text.replace('✨ Ask Thomas turns notes into reminders with sounds', 'Thomas reads every note automatically and sorts it — reminders, tracking, next steps');
      }
    }));
    IW.activeNoteId = IW.notes.length ? IW.notes[0].id : null;
            IW.emit('note-switched');
          }
          renderPages();
        } catch (e) { IW.toast('Could not delete page: ' + e.message, 'warn'); }
      });
      row.appendChild(title);
      row.appendChild(del);
      row.addEventListener('click', () => switchTo(note.id));
      row.addEventListener('dblclick', () => renameNote(note, title));
      host.appendChild(row);
    });
  }

  function renameNote(note, titleEl) {
    const next = prompt('Rename page', note.title || 'Untitled page');
    if (next === null) return;
    note.title = next.trim() || 'Untitled page';
    titleEl.textContent = note.title;
    IW.emit('note-dirty');
  }

  function switchTo(id) {
    if (IW.activeNoteId === id) return;
    IW.activeNoteId = id;
    IW.focusedBlockId = null;
    IW.emit('note-switched');
    renderPages();
  }

  async function newPage() {
    try {
      const item = await IW.createItem('notes', {
        title: 'Page ' + (IW.notes.length + 1),
        blocks: [],
        strokes: [],
      });
      switchTo(item.id);
      IW.setMode('text');
      IW.toast('New page — click anywhere and start typing.');
    } catch (e) { IW.toast('Could not create page: ' + e.message, 'warn'); }
  }

  // Debounced autosave: any edit (text, drag, ink, rename) lands here.
  const save = IW.debounce(async function () {
    const note = IW.activeNote();
    if (!note) return;
    try {
      await IW.patchItem('notes', note.id, {
        title: note.title || '',
        blocks: note.blocks || [],
        strokes: note.strokes || [],
      });
    } catch (e) {
      IW.toast('Save failed: ' + e.message, 'warn');
    }
  }, 900);

  async function boot() {
    IW.initSketch();
    IW.initBoard();
    IW.initSpeech();
    IW.initAlarms();
    IW.initSmart();
    IW.on('note-dirty', save);
    document.getElementById('newPageBtn').addEventListener('click', newPage);

    await IW.bootstrap();
    if (!IW.notes.length) {
      // First run: greet with a starter page (offline mode keeps it local).
      try {
        await IW.createItem('notes', {
          title: 'Welcome to Inkwell',
          blocks: [{
            id: IW.uid(), x: 80, y: 70, w: 340, h: 0, color: '',
            text: 'This page is yours.\n\n• T = type anywhere\n• D = draw with the mouse\n• 🎙 = just talk, the mic turns itself off\n• Thomas reads every note automatically — try writing: remind me to stretch tomorrow at 9am',
          }],
          strokes: [],
        });
      } catch (e) { /* starter page is best-effort */ }
    }
    // Migrate pre-rename starter copy living in saved state.
    IW.notes.forEach((n) => (n.blocks || []).forEach((b) => {
      if (b.text && b.text.indexOf('✨ Ask Thomas') >= 0) {
        b.text = b.text.replace('✨ Ask Thomas turns notes into reminders with sounds', 'Thomas reads every note automatically and sorts it — reminders, tracking, next steps');
      }
    }));
    IW.activeNoteId = IW.notes.length ? IW.notes[0].id : null;
    IW.emit('note-switched');
    renderPages();
    IW.renderReminders();
    IW.renderTracker();
    IW.setMode(IW.notes.length ? 'select' : 'text');
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
