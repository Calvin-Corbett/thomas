(function () {
  'use strict';

  // Thomas's icon set, drawn.
  //
  // There is no icon font in this app — `chat_shell.css` maps each `.ph-<name>`
  // to a Unicode character, so most of the shell was rendering approximations
  // (Chat was "≡", Library was "▤", anything unmapped was a bare bullet). These
  // are real paths, defined once and used everywhere.
  //
  // The mode icons are a FAMILY: Chat, Build and Work are the same Thomas head
  // wearing a different tool. The head with two eyes is the Thomas mark itself,
  // so the modes read as aspects of one thing rather than three unrelated tabs.

  const HEAD = '<rect x="2.6" y="3.4" width="18.8" height="17.2" rx="5.2" fill="none" stroke="currentColor" stroke-width="1.9"/>';
  const EYES = '<rect x="7.6" y="9.4" width="2.9" height="5.2" rx="1.4" fill="currentColor"/>'
    + '<rect x="13.5" y="9.4" width="2.9" height="5.2" rx="1.4" fill="currentColor"/>';

  const FACES = {
    // Thomas talking: the mark, plus a speech tail.
    chat: HEAD + EYES + '<path d="M7.4 20.6 6.1 23.4l3.6-2.8Z" fill="currentColor"/>',
    // Thomas building: a forge hammer caught mid-swing.
    build: HEAD
      + '<g transform="rotate(-22 12 12)">'
      + '<rect x="6.2" y="7.6" width="9.4" height="3.9" rx="1.1" fill="currentColor"/>'
      + '<rect x="9.9" y="11.2" width="2.3" height="6.1" rx="1.1" fill="currentColor"/></g>',
    // Thomas on the job: a briefcase.
    work: HEAD
      + '<rect x="6.4" y="10.2" width="11.2" height="6.6" rx="1.6" fill="currentColor"/>'
      + '<path d="M9.8 10.2V9a1.3 1.3 0 0 1 1.3-1.3h1.8A1.3 1.3 0 0 1 14.2 9v1.2" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  };

  // Everything else in the sidebar. Stroke-based to match the heads.
  const S = 'fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"';
  const GLYPHS = {
    mission: `<g ${S}><circle cx="12" cy="12" r="7.2"/><circle cx="12" cy="12" r="2.4"/><path d="M12 1.9v3.2M12 18.9v3.2M1.9 12h3.2M18.9 12h3.2"/></g>`,
    office: `<g ${S}><path d="M3.6 20.8V6.2a1.4 1.4 0 0 1 1.4-1.4h7.2a1.4 1.4 0 0 1 1.4 1.4v14.6"/><path d="M13.6 20.8V10h5.4a1.4 1.4 0 0 1 1.4 1.4v9.4"/><path d="M2.4 20.8h19.2"/><path d="M6.6 8.4h1.6M6.6 12.2h1.6M6.6 16h1.6M10.4 8.4H12M10.4 12.2H12M10.4 16H12M16.4 13.4H18M16.4 16.8H18"/></g>`,
    canvas: `<g ${S}><path d="M3.4 20.6 4.9 16l9.7-9.7a2.1 2.1 0 0 1 3 0l.6.6a2.1 2.1 0 0 1 0 3L8.5 19.6Z"/><path d="m13.2 7.7 3.4 3.4"/></g>`,
    library: `<g ${S}><rect x="3.2" y="4.4" width="5.1" height="15.2" rx="1.4"/><rect x="10" y="4.4" width="5.1" height="15.2" rx="1.4"/><path d="m17.2 6.1 3.1 12.6a1.4 1.4 0 0 1-1 1.7l-1 .2"/></g>`,
    channels: `<g ${S}><circle cx="12" cy="12" r="2.3"/><path d="M7.4 7.4a6.5 6.5 0 0 0 0 9.2M16.6 16.6a6.5 6.5 0 0 0 0-9.2M4.2 4.2a11 11 0 0 0 0 15.6M19.8 19.8a11 11 0 0 0 0-15.6"/></g>`,
    tokens: `<g ${S}><circle cx="12" cy="12" r="8.4"/><path d="M12 7.4v9.2M14.6 9.6a3 3 0 0 0-2.6-1.2c-1.7 0-2.8.9-2.8 2.2 0 2.9 5.6 1.5 5.6 4.4 0 1.3-1.1 2.2-2.8 2.2a3 3 0 0 1-2.6-1.2"/></g>`,
    market: `<g ${S}><path d="M3.4 9.2 5 4.6a1.4 1.4 0 0 1 1.3-.9h11.4a1.4 1.4 0 0 1 1.3.9l1.6 4.6"/><path d="M3.4 9.2a2.9 2.9 0 0 0 5.8 0 2.9 2.9 0 0 0 5.6 0 2.9 2.9 0 0 0 5.8 0"/><path d="M5.2 12.4v6.6a1.4 1.4 0 0 0 1.4 1.4h10.8a1.4 1.4 0 0 0 1.4-1.4v-6.6"/></g>`,
    trading: `<g ${S}><path d="M3.4 19.4h17.2"/><path d="m4.6 15.6 4.6-4.8 3.4 3.2 6.6-7.2"/><path d="M14.8 6.8h4.4v4.4"/></g>`,
    plus: `<g ${S}><path d="M12 5.2v13.6M5.2 12h13.6"/></g>`,
    search: `<g ${S}><circle cx="10.8" cy="10.8" r="6.4"/><path d="m15.5 15.5 4.3 4.3"/></g>`,
    settings: `<g ${S}><circle cx="12" cy="12" r="3.1"/><path d="M18.9 14.8a1.5 1.5 0 0 0 .3 1.7l.1.1a1.9 1.9 0 1 1-2.6 2.6l-.1-.1a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.2a1.9 1.9 0 0 1-3.8 0v-.1a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.9 1.9 0 1 1-2.6-2.6l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9h-.2a1.9 1.9 0 0 1 0-3.8h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1a1.9 1.9 0 1 1 2.6-2.6l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4v-.2a1.9 1.9 0 0 1 3.8 0v.1a1.5 1.5 0 0 0 .9 1.4 1.5 1.5 0 0 0 1.7-.3l.1-.1a1.9 1.9 0 1 1 2.6 2.6l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.2a1.9 1.9 0 0 1 0 3.8h-.1a1.5 1.5 0 0 0-1.4.9Z"/></g>`,
  };

  function svg(body, size, extra) {
    return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" focusable="false"${extra || ''}>${body}</svg>`;
  }

  function face(name, size) {
    const body = FACES[String(name || '').toLowerCase()];
    return body ? svg(body, size || 16) : '';
  }

  const _warnedGlyphs = new Set();
  function glyph(name, size) {
    const key = String(name || '').toLowerCase();
    const body = GLYPHS[key];
    // An unknown name used to return '' and nothing else happened: the control
    // rendered with no icon at all and looked like a deliberate text-only
    // button. A sidebar entry shipped that way, and the only reason it was
    // caught was someone comparing its markup against a neighbour's. Say so,
    // once per name, so the next typo is visible instead of merely invisible.
    if (!body && key && !_warnedGlyphs.has(key)) {
      _warnedGlyphs.add(key);
      const known = Object.keys(GLYPHS).join(', ');
      if (typeof console !== 'undefined' && console.warn) {
        console.warn(`[ThomasIcons] no glyph named "${key}" - the control will render with no icon. Known glyphs: ${known}`);
      }
    }
    return body ? svg(body, size || 17) : '';
  }

  // Static markup asks for an icon by name rather than repeating the path, so
  // there is exactly one definition of each and no chance of the copies
  // drifting apart.
  function hydrate(root) {
    (root || document).querySelectorAll('[data-thomas-icon]').forEach(node => {
      const size = Number(node.dataset.thomasIconSize) || 16;
      const markup = face(node.dataset.thomasIcon, size) || glyph(node.dataset.thomasIcon, size);
      if (markup) node.innerHTML = markup;
    });
  }

  window.ThomasIcons = { face, glyph, svg, hydrate, names: () => Object.keys(GLYPHS), faces: () => Object.keys(FACES) };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => hydrate(), { once: true });
  else hydrate();
})();
