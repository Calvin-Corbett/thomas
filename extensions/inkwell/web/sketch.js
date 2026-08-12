/* Inkwell sketch layer: mouse/pen drawing on the page canvas. */
(function () {
  'use strict';
  const IW = window.IW;

  const COLORS = ['#1d1d2e', '#c0392b', '#1f7a4d', '#1c5fae', '#b07d12', '#7d3cb5'];
  let canvas, ctx;
  let drawing = false;
  let current = null;          // stroke being drawn
  let penColor = COLORS[0];
  let penSize = 4;

  function strokes() {
    const note = IW.activeNote();
    if (!note) return [];
    if (!Array.isArray(note.strokes)) note.strokes = [];
    return note.strokes;
  }

  function redraw() {
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    strokes().forEach(paintStroke);
    if (current) paintStroke(current);
  }
  IW.redrawInk = redraw;

  function paintStroke(stroke) {
    const pts = stroke.points;
    if (!pts || pts.length < 1) return;
    ctx.save();
    if (stroke.tool === 'highlight') {
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = stroke.size * 3;
    } else {
      ctx.lineWidth = stroke.size;
    }
    ctx.strokeStyle = stroke.color;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if (pts.length === 1) ctx.lineTo(pts[0][0] + 0.1, pts[0][1] + 0.1);
    ctx.stroke();
    ctx.restore();
  }

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return [
      (event.clientX - rect.left) * (canvas.width / rect.width),
      (event.clientY - rect.top) * (canvas.height / rect.height),
    ];
  }

  function eraseNear(point) {
    const radius = Math.max(14, penSize * 3);
    const list = strokes();
    const keep = list.filter((stroke) =>
      !stroke.points.some((p) => Math.hypot(p[0] - point[0], p[1] - point[1]) < radius));
    if (keep.length !== list.length) {
      const note = IW.activeNote();
      if (note) note.strokes = keep;
      redraw();
      IW.emit('note-dirty');
    }
  }

  function onPointerDown(event) {
    if (IW.mode !== 'draw' && IW.mode !== 'erase') return;
    if (!IW.activeNote()) return;
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    drawing = true;
    const point = canvasPoint(event);
    if (IW.mode === 'erase') { eraseNear(point); return; }
    current = {
      tool: event.shiftKey ? 'highlight' : 'pen',
      color: penColor,
      size: penSize,
      points: [point],
    };
    redraw();
  }

  function onPointerMove(event) {
    if (!drawing) return;
    const point = canvasPoint(event);
    if (IW.mode === 'erase') { eraseNear(point); return; }
    if (!current) return;
    const last = current.points[current.points.length - 1];
    if (Math.hypot(point[0] - last[0], point[1] - last[1]) < 1.5) return;
    current.points.push(point);
    redraw();
  }

  function onPointerUp() {
    if (!drawing) return;
    drawing = false;
    if (current && current.points.length) {
      strokes().push(current);
      IW.emit('note-dirty');
    }
    current = null;
    redraw();
  }

  IW.undoStroke = function () {
    const list = strokes();
    if (list.length) {
      list.pop();
      redraw();
      IW.emit('note-dirty');
      IW.toast('Stroke undone');
    }
  };

  function buildPalette() {
    const host = document.getElementById('penColors');
    COLORS.forEach((color, i) => {
      const dot = document.createElement('button');
      dot.className = 'iw-pen-dot' + (i === 0 ? ' iw-pen-active' : '');
      dot.style.background = color;
      dot.title = 'Pen color';
      dot.addEventListener('click', () => {
        penColor = color;
        host.querySelectorAll('.iw-pen-dot').forEach((d) => d.classList.remove('iw-pen-active'));
        dot.classList.add('iw-pen-active');
        if (IW.mode !== 'draw') IW.setMode('draw');
      });
      host.appendChild(dot);
    });
  }

  IW.initSketch = function () {
    canvas = document.getElementById('inkCanvas');
    ctx = canvas.getContext('2d');
    buildPalette();
    document.getElementById('penSize').addEventListener('input', (e) => {
      penSize = Number(e.target.value) || 4;
    });
    document.getElementById('undoBtn').addEventListener('click', IW.undoStroke);
    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('pointercancel', onPointerUp);
    IW.on('note-switched', redraw);
  };
})();
