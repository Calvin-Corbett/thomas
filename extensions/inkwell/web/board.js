/* Inkwell board: free-form draggable text blocks, any spot, any order. */
(function () {
  'use strict';
  const IW = window.IW;

  let layer;   // #blocksLayer
  let board;   // #board

  function blocks() {
    const note = IW.activeNote();
    if (!note) return [];
    if (!Array.isArray(note.blocks)) note.blocks = [];
    return note.blocks;
  }

  function renderBlocks() {
    layer.innerHTML = '';
    blocks().forEach((block) => layer.appendChild(buildBlockEl(block)));
  }
  IW.renderBlocks = renderBlocks;

  function buildBlockEl(block) {
    const el = document.createElement('div');
    el.className = 'iw-block';
    el.dataset.id = block.id;
    el.style.left = block.x + 'px';
    el.style.top = block.y + 'px';
    el.style.width = (block.w || 240) + 'px';
    if (block.color) el.style.borderTopColor = block.color;

    const grip = document.createElement('div');
    grip.className = 'iw-block-grip';
    grip.title = 'Drag to move';
    grip.innerHTML = '<span>⋮⋮</span>';

    const close = document.createElement('button');
    close.className = 'iw-block-close';
    close.title = 'Delete block';
    close.textContent = '×';
    close.addEventListener('click', (e) => {
      e.stopPropagation();
      const note = IW.activeNote();
      if (!note) return;
      note.blocks = blocks().filter((b) => b.id !== block.id);
      el.remove();
      IW.emit('note-dirty');
    });
    grip.appendChild(close);

    const body = document.createElement('div');
    body.className = 'iw-block-text';
    body.contentEditable = 'true';
    body.spellcheck = true;
    body.textContent = block.text || '';
    body.dataset.placeholder = 'Type here… (or hit 🎙 and talk)';
    body.addEventListener('input', () => {
      block.text = body.innerText;
      IW.emit('note-dirty');
    });
    body.addEventListener('focus', () => { IW.focusedBlockId = block.id; });

    enableDrag(el, grip, block);
    el.appendChild(grip);
    el.appendChild(body);
    return el;
  }

  function enableDrag(el, grip, block) {
    grip.addEventListener('pointerdown', (event) => {
      if (event.target.closest('.iw-block-close')) return;
      event.preventDefault();
      grip.setPointerCapture(event.pointerId);
      const startX = event.clientX, startY = event.clientY;
      const baseX = block.x, baseY = block.y;
      const onMove = (ev) => {
        block.x = Math.max(0, baseX + (ev.clientX - startX));
        block.y = Math.max(0, baseY + (ev.clientY - startY));
        el.style.left = block.x + 'px';
        el.style.top = block.y + 'px';
      };
      const onUp = () => {
        grip.removeEventListener('pointermove', onMove);
        grip.removeEventListener('pointerup', onUp);
        IW.emit('note-dirty');
      };
      grip.addEventListener('pointermove', onMove);
      grip.addEventListener('pointerup', onUp);
    });
  }

  function addBlockAt(x, y, text) {
    const note = IW.activeNote();
    if (!note) return null;
    const block = { id: IW.uid(), x: Math.max(0, x - 10), y: Math.max(0, y - 10), w: 260, h: 0, text: text || '', color: '' };
    blocks().push(block);
    const el = buildBlockEl(block);
    layer.appendChild(el);
    IW.emit('note-dirty');
    const body = el.querySelector('.iw-block-text');
    setTimeout(() => body.focus(), 0);
    return block;
  }
  IW.addBlockAt = addBlockAt;

  // Speech lands here: append into the focused block, else make a new one.
  IW.appendDictation = function (text) {
    const trimmed = (text || '').trim();
    if (!trimmed) return;
    const note = IW.activeNote();
    if (!note) return;
    const focused = blocks().find((b) => b.id === IW.focusedBlockId);
    if (focused) {
      focused.text = (focused.text ? focused.text + ' ' : '') + trimmed;
      const el = layer.querySelector('.iw-block[data-id="' + focused.id + '"] .iw-block-text');
      if (el) el.textContent = focused.text;
    } else {
      addBlockAt(60 + Math.random() * 80, 60 + Math.random() * 80, trimmed);
    }
    IW.emit('note-dirty');
  };

  // Everything on the page as plain text, for Thomas to read.
  IW.pageText = function () {
    const note = IW.activeNote();
    if (!note) return '';
    const parts = blocks().map((b) => (b.text || '').trim()).filter(Boolean);
    const title = (note.title || '').trim();
    return (title ? 'Page title: ' + title + '\n\n' : '') + parts.join('\n---\n');
  };

  // A new box is created only on a deliberate, clean click: the press must
  // START on empty board (not inside a block — drag-selecting text and
  // slipping off a box must NOT spawn one) and barely move before release.
  let pressStart = null;
  function onBoardPointerDown(event) {
    pressStart = {
      x: event.clientX,
      y: event.clientY,
      onEmptyBoard: !event.target.closest('.iw-block'),
    };
  }
  function onBoardClick(event) {
    if (IW.mode !== 'text') return;
    if (event.target.closest('.iw-block')) return;
    const press = pressStart;
    pressStart = null;
    if (!press || !press.onEmptyBoard) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > 6) return;
    const rect = board.getBoundingClientRect();
    addBlockAt(event.clientX - rect.left, event.clientY - rect.top);
  }

  IW.setMode = function (mode) {
    IW.mode = mode;
    document.querySelectorAll('#toolGroup .iw-tool[data-mode]').forEach((btn) => {
      btn.classList.toggle('iw-tool-active', btn.dataset.mode === mode);
    });
    const canvas = document.getElementById('inkCanvas');
    const drawing = (mode === 'draw' || mode === 'erase');
    canvas.style.pointerEvents = drawing ? 'auto' : 'none';
    // The blocks layer sits ABOVE the canvas; while drawing it must let the
    // mouse through, or every stroke gets swallowed before reaching the ink.
    layer.style.pointerEvents = drawing ? 'none' : 'auto';
    board.classList.toggle('iw-board-text', mode === 'text');
    board.classList.toggle('iw-board-draw', mode === 'draw' || mode === 'erase');
  };

  IW.initBoard = function () {
    layer = document.getElementById('blocksLayer');
    board = document.getElementById('board');
    board.addEventListener('pointerdown', onBoardPointerDown);
    board.addEventListener('click', onBoardClick);
    document.querySelectorAll('#toolGroup .iw-tool[data-mode]').forEach((btn) => {
      btn.addEventListener('click', () => IW.setMode(btn.dataset.mode));
    });
    document.addEventListener('keydown', (event) => {
      if (event.target.closest('input, [contenteditable]')) return;
      const key = event.key.toLowerCase();
      if (key === 'v') IW.setMode('select');
      else if (key === 't') IW.setMode('text');
      else if (key === 'd') IW.setMode('draw');
      else if (key === 'e') IW.setMode('erase');
      else if (key === 'z' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); IW.undoStroke(); }
    });
    IW.on('note-switched', renderBlocks);
  };
})();
