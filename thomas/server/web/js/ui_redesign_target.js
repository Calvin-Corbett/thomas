(function () {
  'use strict';

  // Addressing anything on screen.
  //
  // Three tiers, best first:
  //   1. data-ui-id        -> the layout book can patch it (geometry, style)
  //   2. data-work-spec    -> the server can patch the saved dashboard entry
  //   3. structural path   -> Thomas still knows exactly what you pointed at
  //
  // A descriptor carries whichever of those apply, so one selection can be
  // both restyled locally and rewritten in the spec.

  const MAX_TEXT = 160;
  const PROMOTE_DEPTH = 4;
  const MAX_PROMOTE_GROWTH = 3;
  const ATOMIC = 'button, a, [role="button"], label, summary';
  // An icon is NOT swallowed by the button around it. Swapping the glyph on a
  // control is one of the first things anyone wants to change, so an icon is
  // always its own target even though its parent is atomic.
  const ICONISH = 'i.ph, [class*="ph-"], svg, .tc-icon';
  // Separator for a minted identity: "<owner id>~~<path inside it>". Two
  // tildes so it cannot collide with the "::" instance-key form.
  const SYNTH = '~~';

  function isEditorChrome(node) {
    return Boolean(node.closest('[data-redesign-ui]') || node.closest('[data-editor-ui]'));
  }

  function depthBetween(child, ancestor) {
    let depth = 0;
    let node = child;
    while (node && node !== ancestor && depth <= PROMOTE_DEPTH) { node = node.parentElement; depth += 1; }
    return node === ancestor ? depth : Infinity;
  }

  function area(node) {
    const rect = node.getBoundingClientRect();
    return Math.max(1, rect.width * rect.height);
  }

  // Clicking the number inside a metric tile means the tile. Clicking the
  // icon inside a button means the button.
  //
  // Three rules, and the distinction that matters is atomic control vs
  // container:
  //   * dashboard items promote freely — the tile IS the meaningful unit
  //   * a button/link promotes regardless of size — its icon is not a thing
  //     you can meaningfully restyle on its own
  //   * a container (aside, section, grid) promotes only when it is a
  //     similar size to what was clicked, or pointing at one line of small
  //     print in the sidebar would select the whole sidebar
  function pick(node) {
    if (!(node instanceof Element)) return null;
    if (node === document.body || node === document.documentElement) return null;
    if (isEditorChrome(node)) return null;
    if (node.matches(ICONISH)) return node;
    const spec = node.closest('[data-work-spec]');
    if (spec && depthBetween(node, spec) <= PROMOTE_DEPTH) return spec;
    const region = node.closest('[data-ui-id]');
    if (!region || region === node) return node;
    if (region.matches(ATOMIC) && depthBetween(node, region) <= PROMOTE_DEPTH) return region;
    if (depthBetween(node, region) <= 2
      && area(region) <= area(node) * MAX_PROMOTE_GROWTH
      && !node.matches('button, a, input, select, textarea, td, th, li')) return region;
    return node;
  }

  // Thomas's icons are not a webfont — chat_shell.css maps each `.ph-<name>`
  // to a literal Unicode glyph, with `.ph::before { content: "•" }` as the
  // catch-all. So the set of icons that actually RENDER is exactly the set of
  // rules in that stylesheet, and it can be read at runtime. Handing the model
  // this list is the difference between icon editing working and it inventing
  // plausible Phosphor names that silently come out as a bullet.
  let vocabularyCache = null;
  function iconVocabulary() {
    if (vocabularyCache) return vocabularyCache;
    const names = new Set();
    for (const sheet of Array.from(document.styleSheets)) {
      let rules;
      try { rules = sheet.cssRules; } catch (_) { continue; }
      // Read selectorText BEFORE recursing. In Chrome with CSS nesting every
      // CSSStyleRule carries an (empty) `cssRules` list, so treating that as
      // "this is a container" skipped every single rule and returned nothing.
      const walk = list => {
        for (const rule of Array.from(list || [])) {
          const selector = String(rule.selectorText || '');
          if (selector.includes('.ph-')) {
            selector.split(',').forEach(part => {
              const match = part.trim().match(/^\.(ph-[a-z0-9-]+)::?before$/);
              if (match) names.add(match[1]);
            });
          }
          if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules);
        }
      };
      walk(rules);
    }
    vocabularyCache = Array.from(names).sort();
    return vocabularyCache;
  }

  function iconName(node) {
    const match = String(node.className || '').match(/\bph-[a-z0-9-]+\b/);
    return match ? match[0] : '';
  }

  function isIcon(node) {
    return node instanceof Element && node.matches(ICONISH);
  }

  // The honest check the stylesheet's own comment asks for: an unmapped name
  // falls through to the bullet, which looks like a broken button rather than
  // an error. Comparing the rendered glyph against the fallback catches it.
  function iconRendersAsFallback(node) {
    try {
      const content = getComputedStyle(node, '::before').content;
      const text = String(content || '').replace(/^["']|["']$/g, '');
      return text === '•';
    } catch (_) { return false; }
  }

  function labelFor(node) {
    // An icon has no text, so the generic path labelled every one of them "i".
    // Name it by its glyph and the control it sits on instead.
    if (isIcon(node)) {
      const name = iconName(node).replace(/^ph-/, '').replace(/-/g, ' ');
      const owner = node.closest('button, a, [role="button"]');
      const ownerLabel = owner ? String(owner.dataset.uiLabel || owner.getAttribute('aria-label') || (owner.textContent || '').trim().slice(0, 24)).trim() : '';
      const base = name ? `${name} icon` : 'icon';
      return ownerLabel ? `${base} on ${ownerLabel}` : base;
    }
    return String(
      node.dataset.uiLabel
      || node.getAttribute('aria-label')
      || node.dataset.uiId
      || (node.textContent || '').trim().slice(0, 48)
      || node.tagName.toLowerCase(),
    ).trim();
  }

  function visibleText(node) {
    return String(node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT);
  }

  // A path relative to the nearest addressable ancestor, so it survives
  // anything happening elsewhere on the page.
  function structuralPath(node) {
    const anchor = node.parentElement ? node.parentElement.closest('[data-ui-id]') : null;
    const segments = [];
    let current = node;
    while (current && current !== anchor && current !== document.body && segments.length < 8) {
      const parent = current.parentElement;
      if (!parent) break;
      const tag = current.tagName.toLowerCase();
      const siblings = Array.from(parent.children).filter(child => child.tagName === current.tagName);
      const index = siblings.indexOf(current) + 1;
      segments.unshift(siblings.length > 1 ? `${tag}:nth-of-type(${index})` : tag);
      current = parent;
    }
    return segments.join(' > ');
  }

  function describe(node) {
    if (!(node instanceof Element)) return null;
    const layout = window.ThomasUiLayout || null;
    const owner = node.closest('[data-ui-id]');
    const spec = String(node.dataset.workSpec || (node.closest('[data-work-spec]') || {}).dataset?.workSpec || '');
    const [specKind, specId] = spec ? spec.split(':') : ['', ''];
    const rect = node.getBoundingClientRect();
    // uiId is the element's OWN identity, never an ancestor's — borrowing the
    // container's id would quietly widen the blast radius, turning "make this
    // line red" into "make the whole sidebar red".
    //
    // An element with no id of its own gets one MINTED from its container
    // plus its path inside it. That address is stable across re-renders and
    // points at exactly the element clicked, so anything on screen can be
    // styled without ever styling something bigger than you picked.
    const exact = Boolean(node.dataset.uiId);
    const ownerUiId = layout && owner ? layout.identity(owner) : String((owner && owner.dataset.uiId) || '');
    const path = structuralPath(node);
    const minted = !exact && ownerUiId && path ? `${ownerUiId}${SYNTH}${path}` : '';
    return {
      uiId: exact ? (layout ? layout.identity(node) : String(node.dataset.uiId || '')) : minted,
      ownerUiId,
      synthetic: Boolean(minted),
      exact,
      specKind: specKind || '',
      specId: specId == null ? '' : String(specId),
      path,
      label: labelFor(node),
      text: visibleText(node),
      component: String(node.dataset.uiComponent || node.tagName.toLowerCase()),
      isIcon: isIcon(node),
      icon: iconName(node),
      box: { width: Math.round(rect.width), height: Math.round(rect.height) },
    };
  }

  // Re-find an element after the surface re-renders, so a locked selection
  // survives Work redrawing its dashboard underneath it.
  function resolve(descriptor) {
    if (!descriptor) return null;
    if (descriptor.specKind && descriptor.specId !== '') {
      const hit = document.querySelector(`[data-work-spec="${CSS.escape(`${descriptor.specKind}:${descriptor.specId}`)}"]`);
      if (hit) return hit;
    }
    const wanted = descriptor.uiId || descriptor.ownerUiId || '';
    const anchor = wanted
      ? Array.from(document.querySelectorAll('[data-ui-id]')).find(node => {
        const layout = window.ThomasUiLayout;
        return (layout ? layout.identity(node) : node.dataset.uiId) === wanted;
      })
      : null;
    if (descriptor.uiId && anchor) return anchor;
    if (!descriptor.path) return anchor || null;
    const scope = anchor || document.body;
    try { return scope.querySelector(descriptor.path) || anchor || null; }
    catch (_) { return anchor || null; }
  }

  window.ThomasRedesignTarget = {
    pick, describe, resolve, labelFor,
    iconVocabulary, iconName, isIcon, iconRendersAsFallback,
  };
})();
