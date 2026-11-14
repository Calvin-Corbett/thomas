/* Display kernel. A reply is a list of blocks: {type, version, data, fallback_text}. A renderer is plugged in by
   ThomasDisplay.register(type, {render, css, version}). Each block draws inside a try/catch; a type with no renderer, a type
   switched off, a block newer than its renderer, or a renderer that throws shows the block's fallback_text instead.
   fallback_text is mandatory, so a block can always be read as words. Nothing but register() adds a renderer.
   Spec: DISPLAY-KERNEL-PLAN.md (step 1). The built-in renderers are in display_builtins.js. */
(function () {
  'use strict';
  const root = typeof window !== 'undefined' ? window : globalThis;
  const TYPE_NAME = /^[a-z][a-z0-9_-]{0,39}$/;
  const renderers = new Map();   // type -> {render, css, version}
  const switchedOff = new Set(); // types the server list says to show as words
  const BASE_CSS = '.tc-display-fallback{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 10px}';

  function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function injectCss(id, css) {
    if (typeof document === 'undefined' || !document.head) return;
    let tag = document.querySelector('style[data-display-css="' + id + '"]');
    if (!css) { if (tag) tag.remove(); return; }
    if (!tag) { tag = document.createElement('style'); tag.setAttribute('data-display-css', id); document.head.appendChild(tag); }
    tag.textContent = css;
  }

  // The reason a block breaks the contract, or '' when it keeps it.
  function validate(block) {
    if (!block || typeof block !== 'object') return 'a block is an object';
    if (typeof block.type !== 'string' || !TYPE_NAME.test(block.type)) return 'a block needs a type like "table"';
    if (typeof block.fallback_text !== 'string' || !block.fallback_text.trim()) return 'a block needs fallback_text, the words to show when it cannot be drawn';
    if (block.version !== undefined && !(Number.isInteger(block.version) && block.version >= 1)) return 'version is a whole number from 1';
    return '';
  }

  // The one way producers build a block: it refuses a block with no fallback_text.
  function makeBlock(type, data, fallbackText, version) {
    const block = { type, version: version || 1, data, fallback_text: fallbackText };
    const problem = validate(block);
    if (problem) throw new TypeError(problem);
    return block;
  }

  // Add or replace the renderer for a type. One renderer is active per type, so registering again swaps it in place.
  function register(type, spec) {
    if (typeof type !== 'string' || !TYPE_NAME.test(type)) throw new TypeError('ThomasDisplay.register needs a type like "table"');
    if (!spec || typeof spec.render !== 'function') throw new TypeError('ThomasDisplay.register("' + type + '") needs render(data, ctx)');
    if (spec.css !== undefined && typeof spec.css !== 'string') throw new TypeError('css is a string');
    const version = spec.version === undefined ? 1 : spec.version;
    if (!(Number.isInteger(version) && version >= 1)) throw new TypeError('version is a whole number from 1');
    renderers.set(type, { render: spec.render, css: spec.css || '', version });
    injectCss(type, spec.css || '');
    return true;
  }

  function unregister(type) { injectCss(type, ''); return renderers.delete(type); }
  function has(type) { return renderers.has(type); }
  function types() { return Array.from(renderers.keys()).map(type => ({ type, version: renderers.get(type).version, enabled: !switchedOff.has(type) })); }
  function isEnabled(type) { return !switchedOff.has(type); }
  function setEnabled(type, enabled) { if (enabled) switchedOff.delete(type); else switchedOff.add(type); }

  function fallbackHtml(block) {
    const words = block && typeof block.fallback_text === 'string' ? block.fallback_text : '';
    return words.trim() ? '<div class="tc-display-fallback">' + esc(words) + '</div>' : '';
  }

  // One block to HTML. Never throws: every failure path ends in the block's own words.
  function renderBlock(block, ctx) {
    const problem = validate(block);
    if (problem) {
      if (typeof console !== 'undefined') console.warn('ThomasDisplay: a block broke the contract: ' + problem);
      return fallbackHtml(block);
    }
    const entry = renderers.get(block.type);
    if (!entry || switchedOff.has(block.type) || (block.version || 1) > entry.version) return fallbackHtml(block);
    try {
      const html = entry.render(block.data, ctx || {});
      if (typeof html !== 'string') throw new TypeError('render returned ' + typeof html + ', not a string');
      return html;
    } catch (err) {
      if (typeof console !== 'undefined') console.warn('ThomasDisplay: the "' + block.type + '" renderer failed, showing its words instead', err);
      return fallbackHtml(block);
    }
  }

  function renderBlocks(blocks, ctx) { return (Array.isArray(blocks) ? blocks : []).map(block => renderBlock(block, ctx)).join(''); }

  // Read which types the server has switched off. A page that cannot read the list keeps every type on.
  async function loadConfig(fetchFn) {
    try {
      const res = await (fetchFn || root.fetch)('/api/display/types', { cache: 'no-store' });
      if (!res.ok) return false;
      const body = await res.json();
      if (!body || !Array.isArray(body.disabled)) return false;
      switchedOff.clear();
      body.disabled.forEach(type => switchedOff.add(String(type)));
      return true;
    } catch (_) { return false; }
  }

  injectCss('kernel', BASE_CSS);
  root.ThomasDisplay = { register, unregister, has, types, isEnabled, setEnabled, validate, makeBlock, renderBlock, renderBlocks, loadConfig, esc, blocks: {} };
  if (typeof document !== 'undefined' && typeof root.fetch === 'function') loadConfig();
})();
