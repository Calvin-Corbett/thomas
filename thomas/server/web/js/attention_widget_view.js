/* How a widget's blocks are drawn. Strings in, markup out, so it can be checked without a browser.
 *
 * A widget is a card whose body is a short list of blocks (thomas/core/attention_blocks.py): text, a reading, a
 * meter, rows, steps, a spark line, buttons, a toggle. Thomas names the blocks; this draws them the way the Context
 * window and Steps panels in Build are drawn, with the same sizes, weights and bars, so a widget he makes on the fly
 * reads as part of the app. Every word is escaped. Nothing here is a frame or runs anything a widget carries.
 */
(function () {
  'use strict';

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const percent = value => (value == null || value === '' || Number.isNaN(Number(value)) ? null : Math.min(100, Math.max(0, Number(value))));
  const hint = text => (text ? `<small class="tc-attn-hint">${esc(text)}</small>` : '');
  const heading = text => (text ? `<span class="tc-attn-label">${esc(text)}</span>` : '');

  function meter(block) {
    const value = percent(block.value), mark = percent(block.mark);
    const over = value != null && mark != null && value >= mark;
    return `<div class="tc-attn-meter${over ? ' is-over' : ''}"><div class="tc-attn-line"><span>${esc(block.label || '')}</span><b>${value == null ? '—' : `${Math.round(value)}%`}</b></div>`
      + `<div class="tc-attn-track" role="meter" aria-label="${esc(block.label || 'Reading')}" aria-valuemin="0" aria-valuemax="100"${value == null ? '' : ` aria-valuenow="${Math.round(value)}"`}>`
      + `<i style="width:${value == null ? 0 : value}%"></i>${mark == null ? '' : `<u style="left:${mark}%" title="Limit ${Math.round(mark)}%"></u>`}</div>${hint(block.hint)}</div>`;
  }

  function reading(block) {
    return `<div class="tc-attn-reading">${heading(block.label)}<div class="tc-attn-total"><b>${esc(block.value === '' || block.value == null ? '—' : block.value)}</b>${block.unit ? `<span>${esc(block.unit)}</span>` : ''}</div>${hint(block.hint)}</div>`;
  }

  function rows(block) {
    const list = (Array.isArray(block.rows) ? block.rows : []).map(row => (
      `<div class="tc-attn-row"><span>${esc(row.label)}</span><b>${esc(row.value || '')}</b>${row.note ? `<em>${esc(row.note)}</em>` : ''}</div>`
    )).join('');
    return `<div class="tc-attn-rows">${heading(block.label)}${list || '<p class="tc-attn-body">Nothing to show yet.</p>'}</div>`;
  }

  function steps(block) {
    const list = Array.isArray(block.steps) ? block.steps : [];
    const done = list.filter(step => step.state === 'done').length;
    const items = list.map(step => (
      `<li class="tc-attn-step is-${esc(step.state || 'pending')}"><span class="tc-attn-step-mark" aria-hidden="true">${step.state === 'done' ? '✓' : ''}</span><span class="tc-attn-step-text">${esc(step.label)}</span>${step.note ? `<em>${esc(step.note)}</em>` : ''}</li>`
    )).join('');
    return `<div class="tc-attn-steps"><div class="tc-attn-steps-head"><span class="tc-attn-label">${esc(block.label || 'Steps')}</span><span class="tc-attn-steps-bar"><i style="width:${list.length ? Math.round((done / list.length) * 100) : 0}%"></i></span><span class="tc-attn-steps-count">${done} of ${list.length}</span></div><ol>${items}</ol></div>`;
  }

  function spark(block) {
    const points = (Array.isArray(block.points) ? block.points : []).map(Number).filter(point => !Number.isNaN(point));
    const last = points.length ? points[points.length - 1] : null;
    let line = '';
    if (points.length > 1) {
      const low = Math.min.apply(null, points), high = Math.max.apply(null, points), range = high - low || 1;
      const path = points.map((point, index) => `${((index / (points.length - 1)) * 100).toFixed(1)},${(26 - ((point - low) / range) * 24).toFixed(1)}`).join(' ');
      line = `<svg class="tc-attn-spark-line" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><polyline points="${path}" fill="none" vector-effect="non-scaling-stroke"/></svg>`;
    }
    return `<div class="tc-attn-spark"><div class="tc-attn-line"><span>${esc(block.label || '')}</span><b>${last == null ? '—' : `${Math.round(last)}${esc(block.unit || '')}`}</b></div>${line || '<p class="tc-attn-body">Collecting readings…</p>'}</div>`;
  }

  function buttons(block) {
    return `<div class="tc-attn-actions">${(Array.isArray(block.options) ? block.options : []).map((row, index) => (
      `<button type="button" class="tc-attn-option${index === 0 ? ' is-first' : ''}" data-attn-option="${esc(row.id)}">${esc(row.label)}</button>`
    )).join('')}</div>`;
  }

  // A switch for one plugin row. The server wrote its label and position from the row itself.
  function toggle(block) {
    const on = block.on === true;
    return `<div class="tc-attn-toggle"><span>${esc(block.label || block.setting)}</span>`
      + `<button type="button" role="switch" aria-checked="${on}" aria-label="${esc(block.label || block.setting)}" data-attn-toggle="${esc(block.setting)}"${block.locked ? ' disabled title="This one cannot be switched here."' : ''}><i></i></button></div>`;
  }

  const DRAW = { text: block => (block.text ? `<p class="tc-attn-body">${esc(block.text)}</p>` : ''), reading, meter, rows, steps, spark, buttons, toggle };

  function blocksHtml(blocks) {
    return (Array.isArray(blocks) ? blocks : []).map(block => (block && DRAW[block.type] ? DRAW[block.type](block) : '')).join('');
  }

  const api = { blocksHtml };
  if (typeof window !== 'undefined') window.ThomasAttentionWidgetView = api;
})();
