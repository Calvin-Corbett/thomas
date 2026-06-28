/* ===========================================================================
 * 048_ui_studio_canvas.js  —  UI Studio Canvas (THE app_builder "UI Editor")
 * ===========================================================================
 *
 * WHAT THIS FILE IS
 *   Two responsibilities, intentionally in one file so the whole feature is one
 *   additive unit (the demo loads exactly this file + the css):
 *
 *   (1) APP_BUILDER HOST — installs `moduleRenderWorkbenchAppBuilder` so the
 *       "UI Editor" nav (app_builder mode) mounts the design canvas DIRECTLY.
 *       As of 2026-06-16 this canvas IS the UI Editor: the old GridStack
 *       "App Builder" (was in 030) and the 042/044 live-iframe "UI Editor" were
 *       removed, so there is no prior renderer to wrap or fall back to. (This
 *       used to be a flag-gated two-tab host — "Thomas UI" + "Canvas"; the flag
 *       and the old tab are gone, the canvas is the default and only surface.)
 *
 *   (2) CANVAS ENGINE  — a self-contained, dependency-free design canvas:
 *           - UiStudioSpec: a flow-layout-first block tree that is the SINGLE
 *             SOURCE OF TRUTH (export writes it, codegen reads it, AI returns it).
 *           - real screen<->world coordinate transform (Thomas camera model:
 *             worldX = (screenX - panX) / zoom), pointer-relative zoom, pan.
 *           - grid + edge/center snapping with guide lines (Alt to disable).
 *           - draggable + resizable boxes, shape / text / freehand PEN tools.
 *           - multi-select (shift-click + rubber band), layers list, properties.
 *           - spec-snapshot undo/redo (cap 100), localStorage autosave.
 *           - deterministic spec -> React+Tailwind AND spec -> HTML/CSS codegen
 *             + a tokens.css emitter, with .zip-less download + copy.
 *           - "AI Generate Template" button -> POST /api/canvas/template.
 *           - sketch drop-zone -> POST /api/canvas/spec-from-sketch (vision).
 *
 *   The engine renders on a single <canvas> element with its own retained
 *   scene-graph + hit testing (a tiny Konva-shaped projection of the spec). We
 *   deliberately do NOT require a vendored Konva here: keeping the engine
 *   pure-DOM means the standalone demo and the in-app Tab B both run with zero
 *   network and zero build step. The blueprint's wave-2 pen smoothing
 *   (perfect-freehand) degrades gracefully to a polyline when the lib is absent.
 *
 * GLOBALS EXPOSED (so the demo + the tab host share one engine):
 *   window.uiStudioMountCanvas(containerEl, options) -> controller
 *   window.UI_STUDIO = { mount, specToReact, specToHtml, specToTokensCss,
 *                        emptySpec, version }
 *
 * NO frameworks. NO build step. Shares global scope with the other runtime
 * scripts (it is loaded as a plain <script>, same as 001..047).
 * ======================================================================== */

(function () {
    'use strict';

    var UI_STUDIO_VERSION = '0.1.0-mvp';
    var GRID_DEFAULT = 8;
    var ZOOM_MIN = 0.1;
    var ZOOM_MAX = 4;
    var SNAP_THRESHOLD = 5;        // px (screen space) for edge/center snapping
    var HISTORY_CAP = 100;
    var HANDLE = 8;                // resize handle hit size (screen px)
    var AUTOSAVE_KEY = 'thomas.ui_studio.spec';
    var AUTOSAVE_DEBOUNCE = 500;

    /* The 12 block types the codegen + AI schema understand. */
    var NODE_TYPES = ['container', 'text', 'button', 'image', 'input', 'card',
        'list', 'nav', 'table', 'modal', 'shape', 'pen'];

    // ── small shared helpers (mirrors the rest of the runtime's defensive style)
    function uuid() {
        try {
            if (window.crypto && typeof window.crypto.randomUUID === 'function') {
                return window.crypto.randomUUID();
            }
        } catch (_e) { /* fall through */ }
        // RFC4122-ish fallback (never Math.random-only ids that collide — we still
        // mix a monotonic counter so two same-ms calls differ).
        uuid._n = (uuid._n || 0) + 1;
        var t = Date.now().toString(16);
        var r = Math.floor(Math.random() * 0xffffffff).toString(16);
        return 'x' + t + '-' + r + '-' + uuid._n.toString(16);
    }
    function nodeId() { return 'node_' + uuid(); }
    function specId() { return 'spec_' + uuid(); }
    function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
    function num(v, fallback) { var n = Number(v); return Number.isFinite(n) ? n : (fallback || 0); }
    function str(v) { return v === null || v === undefined ? '' : String(v); }
    function escapeHtml(s) {
        return str(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function notify(message, opts) {
        // Reuse the host's notifier when present; the demo stubs window.notifyUser.
        try {
            if (typeof window.notifyUser === 'function') { window.notifyUser(message, opts || {}); return; }
        } catch (_e) { /* ignore */ }
        try { console.log('[UI Studio] ' + message); } catch (_e2) { /* ignore */ }
    }

    /* ===================================================================== *
     * SPEC MODEL
     * ===================================================================== */

    function defaultTokens() {
        return {
            color: { primary: '#2563eb', surface: '#1f232c', text: '#ececf1', muted: '#929bb0', accent: '#47d7ac', border: '#3a3f4b' },
            space: { sm: 8, md: 16, lg: 24 },
            radius: { sm: 4, md: 8, lg: 12 },
            font: { sans: 'Manrope, system-ui, sans-serif' }
        };
    }

    function emptySpec(name) {
        var rootId = nodeId();
        return {
            version: 1,
            id: specId(),
            name: str(name) || 'Untitled Layout',
            canvas: { width: 1280, height: 800, background: '#0f1723' },
            grid: { size: GRID_DEFAULT, snap: true },
            tokens: defaultTokens(),
            root: {
                id: rootId, type: 'container', name: 'Root',
                rect: { x: 0, y: 0, w: 1280, h: 800 },
                layout: { mode: 'none', direction: 'col', gap: 16, padding: 16, align: 'start', justify: 'start', sizing: 'fixed' },
                absolute: false,
                style: { bg: '', color: '', radius: 0, border: '', opacity: 1, fontSize: 14, fontWeight: 400, shadow: '' },
                content: { text: '', src: '', placeholder: '' },
                owner: 'user', locked: false, z: 0, children: []
            }
        };
    }

    /* Make a fresh node of `type` at a grid-snapped rect. */
    function makeNode(type, rect, extra) {
        var t = NODE_TYPES.indexOf(type) === -1 ? 'container' : type;
        var n = {
            id: nodeId(), type: t, name: defaultName(t),
            rect: { x: num(rect && rect.x), y: num(rect && rect.y), w: Math.max(8, num(rect && rect.w, 120)), h: Math.max(8, num(rect && rect.h, 60)) },
            layout: { mode: t === 'container' || t === 'card' || t === 'nav' || t === 'list' ? 'flex' : 'none', direction: 'col', gap: 8, padding: 8, align: 'start', justify: 'start', sizing: 'fixed' },
            absolute: false,
            style: defaultStyleFor(t),
            content: defaultContentFor(t),
            owner: 'user', locked: false, z: 0, children: []
        };
        if (t === 'pen') { n.stroke = (extra && extra.stroke) ? extra.stroke : { points: [], width: 3, color: '#ececf1' }; }
        if (extra && extra.content) { n.content = Object.assign(n.content, extra.content); }
        return n;
    }
    function defaultName(t) {
        var map = { container: 'Container', text: 'Text', button: 'Button', image: 'Image', input: 'Input', card: 'Card', list: 'List', nav: 'Nav', table: 'Table', modal: 'Modal', shape: 'Shape', pen: 'Drawing' };
        return map[t] || 'Node';
    }
    function defaultStyleFor(t) {
        var base = { bg: '', color: '', radius: 6, border: '', opacity: 1, fontSize: 14, fontWeight: 400, shadow: '' };
        if (t === 'button') { base.bg = '#2563eb'; base.color = '#ffffff'; base.radius = 6; base.fontWeight = 600; }
        else if (t === 'card' || t === 'container' || t === 'modal') { base.bg = '#1f232c'; base.border = '#3a3f4b'; base.radius = 8; }
        else if (t === 'input') { base.bg = '#16181f'; base.border = '#3a3f4b'; base.radius = 4; base.color = '#ececf1'; }
        else if (t === 'nav') { base.bg = '#181b22'; base.border = '#3a3f4b'; }
        else if (t === 'shape') { base.bg = '#47d7ac'; base.radius = 4; }
        else if (t === 'text') { base.color = '#ececf1'; }
        return base;
    }
    function defaultContentFor(t) {
        if (t === 'text') return { text: 'Text', src: '', placeholder: '' };
        if (t === 'button') return { text: 'Button', src: '', placeholder: '' };
        if (t === 'input') return { text: '', src: '', placeholder: 'Enter value' };
        if (t === 'nav') return { text: 'Navigation', src: '', placeholder: '' };
        return { text: '', src: '', placeholder: '' };
    }

    /* Deep clone (structuredClone where available — faster + handles nesting). */
    function cloneSpec(spec) {
        try { if (typeof structuredClone === 'function') return structuredClone(spec); } catch (_e) { /* fall through */ }
        return JSON.parse(JSON.stringify(spec));
    }

    /* Walk every node depth-first (root included). */
    function walk(node, fn, parent) {
        fn(node, parent);
        var kids = node && node.children;
        if (Array.isArray(kids)) { for (var i = 0; i < kids.length; i++) walk(kids[i], fn, node); }
    }
    function findNode(spec, id) {
        var found = null;
        walk(spec.root, function (n) { if (n.id === id) found = n; });
        return found;
    }
    function findParent(spec, id) {
        var parent = null;
        walk(spec.root, function (n, p) { if (n.id === id) parent = p; });
        return parent;
    }
    /* Flat list of all non-root nodes in z/painter order (root's subtree). */
    function flatNodes(spec) {
        var out = [];
        walk(spec.root, function (n) { if (n !== spec.root) out.push(n); });
        return out;
    }

    /* ===================================================================== *
     * CODE GENERATION  (deterministic — the spec is the input, never pixels)
     * ===================================================================== */

    // FIDELITY CONTRACT: a container whose CHILDREN flow (responsive) is a flow
    // container. When a parent is NOT a flow container, its children are placed
    // at their EXACT drawn coordinates -> "what you draw is what you get".
    function isFlowContainer(node) {
        var L = (node && node.layout) || {};
        return L.mode === 'flex' || L.mode === 'grid';
    }
    // How THIS node is positioned inside its parent:
    //   'root'     -> the outer relative canvas (anchors its absolute children)
    //   'flow'     -> laid out by the parent's flex/grid (coordinates implied)
    //   'absolute' -> placed at its exact rect, local to the parent (faithful)
    function positionMode(node, parent) {
        if (!parent) return 'root';
        if (node.absolute) return 'absolute';        // explicit per-node override
        if (isFlowContainer(parent)) return 'flow';  // parent groups it responsively
        return 'absolute';                           // free placement -> exact coords
    }
    // A flowed free-container with children must still anchor those (absolute)
    // children, so it needs position:relative. Absolute/root nodes already are.
    function needsRelative(node, mode) {
        if (mode === 'absolute' || mode === 'root') return false;
        return Array.isArray(node.children) && node.children.length > 0 && !isFlowContainer(node);
    }
    // Infer grid columns from the distinct x-clusters of a grid container's
    // children, so a 3-across card grid generates 3 columns (not a 1-col stack).
    function gridColumns(node) {
        var kids = Array.isArray(node.children) ? node.children : [];
        if (!kids.length) return 1;
        var xs = {};
        kids.forEach(function (k) { xs[Math.round(num(k.rect.x) / 8) * 8] = 1; });
        return clamp(Object.keys(xs).length, 1, 12);
    }
    // Order a flow container's children to match the drawn arrangement, so the
    // generated flex/grid reads top->bottom (col) / left->right (row) / row-major.
    function orderedChildren(node) {
        var kids = Array.isArray(node.children) ? node.children.slice() : [];
        if (!isFlowContainer(node)) return kids;
        var L = node.layout || {};
        if (L.mode === 'grid') {
            return kids.sort(function (a, b) {
                var dy = num(a.rect.y) - num(b.rect.y);
                return Math.abs(dy) > 4 ? dy : (num(a.rect.x) - num(b.rect.x));
            });
        }
        var row = L.direction === 'row';
        return kids.sort(function (a, b) {
            return row ? (num(a.rect.x) - num(b.rect.x)) : (num(a.rect.y) - num(b.rect.y));
        });
    }

    function tailwindClassesFor(node, parent) {
        var cls = [];
        var L = node.layout || {};
        var mode = positionMode(node, parent);
        // Placement of THIS node inside its parent.
        if (mode === 'root' || needsRelative(node, mode)) {
            cls.push('relative');
        } else if (mode === 'absolute') {
            var px = parent ? num(parent.rect.x) : 0;
            var py = parent ? num(parent.rect.y) : 0;
            cls.push('absolute');
            cls.push('left-[' + Math.round(num(node.rect.x) - px) + 'px]');
            cls.push('top-[' + Math.round(num(node.rect.y) - py) + 'px]');
        }
        // This node's OWN flow layout (controls how ITS children are arranged).
        if (isFlowContainer(node)) {
            if (L.mode === 'flex') {
                cls.push('flex');
                cls.push(L.direction === 'row' ? 'flex-row' : 'flex-col');
                cls.push('gap-' + spToTw(L.gap));
                cls.push('items-' + (L.align || 'start'));
                cls.push('justify-' + (L.justify || 'start'));
            } else {
                cls.push('grid');
                cls.push('grid-cols-[repeat(' + gridColumns(node) + ',auto)]');
                cls.push('gap-' + spToTw(L.gap));
            }
            if (num(L.padding) > 0) cls.push('p-' + spToTw(L.padding));
        }
        cls.push('w-[' + Math.round(num(node.rect.w)) + 'px]');
        cls.push('h-[' + Math.round(num(node.rect.h)) + 'px]');
        return cls.join(' ');
    }
    // map an 8-pt spacing value to the nearest tailwind spacing step (4px units)
    function spToTw(px) {
        var n = Math.round(num(px) / 4);
        return String(clamp(n, 0, 96));
    }
    function resolveColor(spec, value) {
        var v = str(value);
        if (!v) return '';
        // token ref like "color.primary" -> css var (codegen prefers vars over hex)
        if (/^color\.[a-z0-9_]+$/i.test(v)) return 'var(--' + v.replace('.', '-') + ')';
        return v;
    }
    function styleObjFor(spec, node) {
        var s = node.style || {};
        var out = [];
        if (str(s.bg)) out.push('backgroundColor: ' + JSON.stringify(resolveColor(spec, s.bg)));
        if (str(s.color)) out.push('color: ' + JSON.stringify(resolveColor(spec, s.color)));
        if (num(s.radius) > 0) out.push('borderRadius: ' + JSON.stringify(Math.round(num(s.radius)) + 'px'));
        if (str(s.border)) out.push('border: ' + JSON.stringify('1px solid ' + resolveColor(spec, s.border)));
        if (s.opacity !== undefined && num(s.opacity, 1) !== 1) out.push('opacity: ' + num(s.opacity, 1));
        if (num(s.fontSize) && num(s.fontSize) !== 14) out.push('fontSize: ' + JSON.stringify(Math.round(num(s.fontSize)) + 'px'));
        if (num(s.fontWeight) && num(s.fontWeight) !== 400) out.push('fontWeight: ' + num(s.fontWeight));
        if (str(s.shadow)) out.push('boxShadow: ' + JSON.stringify(str(s.shadow)));
        return out.length ? '{{ ' + out.join(', ') + ' }}' : null;
    }

    function tagFor(type) {
        switch (type) {
            case 'button': return 'button';
            case 'input': return 'input';
            case 'image': return 'img';
            case 'nav': return 'nav';
            case 'list': return 'ul';
            case 'text': return 'span';
            default: return 'div';
        }
    }

    function specToReact(spec) {
        var lines = [];
        lines.push('// Auto-generated by Thomas UI Studio — deterministic spec -> React + Tailwind');
        lines.push('// Source of truth: UiStudioSpec "' + str(spec.name) + '" (' + str(spec.id) + ')');
        lines.push('// Tokens are emitted to tokens.css — import it once at your app root.');
        lines.push("import './tokens.css';");
        lines.push('');
        lines.push('export default function GeneratedUI() {');
        lines.push('  return (');
        var body = renderReactNode(spec, spec.root, 2);
        lines.push(body);
        lines.push('  );');
        lines.push('}');
        lines.push('');
        return lines.join('\n');
    }

    function renderReactNode(spec, node, depth, parent) {
        var pad = new Array(depth + 1).join('  ');
        var tag = tagFor(node.type);
        var cls = tailwindClassesFor(node, parent);
        var styleObj = styleObjFor(spec, node);
        var attrs = ' className=' + JSON.stringify(cls);
        if (styleObj) attrs += ' style=' + styleObj;

        // self-closing / leaf content
        if (node.type === 'image') {
            return pad + '<img' + attrs + ' src=' + JSON.stringify(str(node.content && node.content.src) || '') + ' alt=' + JSON.stringify(str(node.name)) + ' />';
        }
        if (node.type === 'input') {
            return pad + '<input' + attrs + ' placeholder=' + JSON.stringify(str(node.content && node.content.placeholder) || '') + ' />';
        }
        if (node.type === 'pen') {
            return pad + '{/* freehand drawing "' + escapeHtml(str(node.name)) + '" — render as <svg><path/></svg> in wave 2 */}';
        }

        var kids = orderedChildren(node);
        var text = str(node.content && node.content.text);
        if (!kids.length && text) {
            return pad + '<' + tag + attrs + '>' + escapeHtml(text) + '</' + tag + '>';
        }
        if (!kids.length) {
            return pad + '<' + tag + attrs + '>' + (text ? escapeHtml(text) : '') + '</' + tag + '>';
        }
        var inner = [];
        if (text) inner.push(pad + '  ' + escapeHtml(text));
        for (var i = 0; i < kids.length; i++) inner.push(renderReactNode(spec, kids[i], depth + 1, node));
        return pad + '<' + tag + attrs + '>\n' + inner.join('\n') + '\n' + pad + '</' + tag + '>';
    }

    function specToTokensCss(spec) {
        var t = spec.tokens || defaultTokens();
        var lines = [':root {'];
        ['color', 'space', 'radius', 'font'].forEach(function (group) {
            var obj = t[group] || {};
            Object.keys(obj).forEach(function (k) {
                var val = obj[k];
                if (group === 'space' || group === 'radius') val = Math.round(num(val)) + 'px';
                lines.push('  --' + group + '-' + k + ': ' + val + ';');
            });
        });
        lines.push('}');
        return lines.join('\n') + '\n';
    }

    /* Plain HTML/CSS generator (the task asks for spec->HTML/CSS too). Inline
       style version so the output is paste-and-open runnable. */
    function specToHtml(spec) {
        var css = [specToTokensCss(spec), '', '* { box-sizing: border-box; }',
            'body { margin: 0; background: ' + (spec.canvas && spec.canvas.background ? spec.canvas.background : '#0f1723') + '; font-family: var(--font-sans, system-ui); }'].join('\n');
        var html = ['<!doctype html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
            '<title>' + escapeHtml(str(spec.name)) + '</title>', '<style>', css, '</style>', '</head>', '<body>'];
        html.push(renderHtmlNode(spec, spec.root, 1));
        html.push('</body>', '</html>', '');
        return html.join('\n');
    }
    function inlineStyleFor(spec, node, parent) {
        var s = node.style || {}, L = node.layout || {}, css = [];
        var mode = positionMode(node, parent);
        if (mode === 'root') {
            css.push('position:relative');
            css.push('width:' + Math.round(num(node.rect.w)) + 'px');
            css.push('min-height:' + Math.round(num(node.rect.h)) + 'px');
            css.push('margin:0 auto');
        } else if (mode === 'absolute') {
            var px = parent ? num(parent.rect.x) : 0;
            var py = parent ? num(parent.rect.y) : 0;
            css.push('position:absolute');
            css.push('left:' + Math.round(num(node.rect.x) - px) + 'px');
            css.push('top:' + Math.round(num(node.rect.y) - py) + 'px');
            css.push('width:' + Math.round(num(node.rect.w)) + 'px');
            css.push('min-height:' + Math.round(num(node.rect.h)) + 'px');
        } else { // flow
            if (needsRelative(node, mode)) css.push('position:relative');
            css.push('width:' + Math.round(num(node.rect.w)) + 'px');
            css.push('min-height:' + Math.round(num(node.rect.h)) + 'px');
        }
        if (isFlowContainer(node)) {
            if (L.mode === 'flex') {
                css.push('display:flex');
                css.push('flex-direction:' + (L.direction === 'row' ? 'row' : 'column'));
                css.push('gap:' + Math.round(num(L.gap)) + 'px');
                css.push('align-items:' + flexAlign(L.align));
                css.push('justify-content:' + flexAlign(L.justify));
            } else {
                css.push('display:grid');
                css.push('grid-template-columns:repeat(' + gridColumns(node) + ',auto)');
                css.push('gap:' + Math.round(num(L.gap)) + 'px');
            }
            if (num(L.padding) > 0) css.push('padding:' + Math.round(num(L.padding)) + 'px');
        }
        if (str(s.bg)) css.push('background:' + resolveCssColor(spec, s.bg));
        if (str(s.color)) css.push('color:' + resolveCssColor(spec, s.color));
        if (num(s.radius) > 0) css.push('border-radius:' + Math.round(num(s.radius)) + 'px');
        if (str(s.border)) css.push('border:1px solid ' + resolveCssColor(spec, s.border));
        if (s.opacity !== undefined && num(s.opacity, 1) !== 1) css.push('opacity:' + num(s.opacity, 1));
        if (num(s.fontSize) && num(s.fontSize) !== 14) css.push('font-size:' + Math.round(num(s.fontSize)) + 'px');
        if (num(s.fontWeight) && num(s.fontWeight) !== 400) css.push('font-weight:' + num(s.fontWeight));
        if (str(s.shadow)) css.push('box-shadow:' + str(s.shadow));
        return css.join(';');
    }
    function flexAlign(v) {
        if (v === 'center') return 'center';
        if (v === 'end') return 'flex-end';
        if (v === 'between') return 'space-between';
        if (v === 'stretch') return 'stretch';
        return 'flex-start';
    }
    function resolveCssColor(spec, value) {
        var v = str(value);
        if (/^color\.[a-z0-9_]+$/i.test(v)) return 'var(--' + v.replace('.', '-') + ')';
        return v;
    }
    function renderHtmlNode(spec, node, depth, parent) {
        var pad = new Array(depth + 1).join('  ');
        var tag = tagFor(node.type);
        var style = inlineStyleFor(spec, node, parent);
        var styleAttr = style ? ' style="' + escapeHtml(style) + '"' : '';
        var dataAttr = ' data-node="' + escapeHtml(str(node.name)) + '"';
        if (node.type === 'image') {
            return pad + '<img' + dataAttr + styleAttr + ' src="' + escapeHtml(str(node.content && node.content.src)) + '" alt="' + escapeHtml(str(node.name)) + '">';
        }
        if (node.type === 'input') {
            return pad + '<input' + dataAttr + styleAttr + ' placeholder="' + escapeHtml(str(node.content && node.content.placeholder)) + '">';
        }
        if (node.type === 'pen') {
            return pad + '<!-- freehand drawing "' + escapeHtml(str(node.name)) + '" (wave 2: emit <svg>) -->';
        }
        var kids = orderedChildren(node);
        var text = str(node.content && node.content.text);
        if (!kids.length) {
            return pad + '<' + tag + dataAttr + styleAttr + '>' + escapeHtml(text) + '</' + tag + '>';
        }
        var inner = [];
        if (text) inner.push(pad + '  ' + escapeHtml(text));
        for (var i = 0; i < kids.length; i++) inner.push(renderHtmlNode(spec, kids[i], depth + 1, node));
        return pad + '<' + tag + dataAttr + styleAttr + '>\n' + inner.join('\n') + '\n' + pad + '</' + tag + '>';
    }

    /* ===================================================================== *
     * CANVAS ENGINE  (retained scene-graph on a single <canvas>)
     * ===================================================================== */

    function mountCanvas(container, options) {
        if (!container) throw new Error('uiStudioMountCanvas: container required');
        options = options || {};
        var api = {
            spec: options.spec ? cloneSpec(options.spec) : restoreOrEmpty(),
            zoom: 1, panX: 60, panY: 60,
            tool: 'select',
            selection: [],           // array of node ids
            history: [], future: [],
            apiBase: str(options.apiBase || '/api/canvas'),
            offline: options.offline === true,
        };

        // ---- DOM scaffold ----------------------------------------------------
        container.innerHTML = '';
        container.classList.add('ui-studio-root');
        var ui = buildChrome(container);
        var canvas = ui.canvas;
        var ctx = canvas.getContext('2d');

        // ---- coordinate transforms (Thomas camera model) --------------------
        // screen->world: worldX = (screenX - panX) / zoom   (workflow_builder ~244)
        function toWorld(sx, sy) { return { x: (sx - api.panX) / api.zoom, y: (sy - api.panY) / api.zoom }; }
        function toScreen(wx, wy) { return { x: wx * api.zoom + api.panX, y: wy * api.zoom + api.panY }; }
        function pointerPos(ev) {
            var r = canvas.getBoundingClientRect();
            return { x: ev.clientX - r.left, y: ev.clientY - r.top };
        }

        // ---- DPR-aware sizing ------------------------------------------------
        function resize() {
            var r = ui.stageWrap.getBoundingClientRect();
            var dpr = window.devicePixelRatio || 1;
            canvas.width = Math.max(1, Math.round(r.width * dpr));
            canvas.height = Math.max(1, Math.round(r.height * dpr));
            canvas.style.width = r.width + 'px';
            canvas.style.height = r.height + 'px';
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            render();
        }

        // ---- world-rect of a node (absolute coords; flow nodes use rect too) --
        function nodeWorldRect(node) { return { x: num(node.rect.x), y: num(node.rect.y), w: num(node.rect.w), h: num(node.rect.h) }; }

        // ---- hit testing -----------------------------------------------------
        // Topmost node whose world-rect contains the world point. Painter order:
        // later siblings / deeper children are on top, so iterate reversed.
        function hitTest(wx, wy) {
            var nodes = flatNodes(api.spec);
            for (var i = nodes.length - 1; i >= 0; i--) {
                var n = nodes[i];
                if (n.locked) continue;
                var rc = nodeWorldRect(n);
                if (wx >= rc.x && wx <= rc.x + rc.w && wy >= rc.y && wy <= rc.y + rc.h) return n;
            }
            return null;
        }
        // resize handle under a screen point for the single selected node
        function handleAt(sx, sy) {
            if (api.selection.length !== 1) return null;
            var n = findNode(api.spec, api.selection[0]);
            if (!n || n.locked) return null;
            var rc = nodeWorldRect(n);
            var tl = toScreen(rc.x, rc.y), br = toScreen(rc.x + rc.w, rc.y + rc.h);
            var handles = {
                nw: { x: tl.x, y: tl.y }, ne: { x: br.x, y: tl.y },
                sw: { x: tl.x, y: br.y }, se: { x: br.x, y: br.y },
                n: { x: (tl.x + br.x) / 2, y: tl.y }, s: { x: (tl.x + br.x) / 2, y: br.y },
                w: { x: tl.x, y: (tl.y + br.y) / 2 }, e: { x: br.x, y: (tl.y + br.y) / 2 }
            };
            for (var k in handles) {
                if (Math.abs(sx - handles[k].x) <= HANDLE && Math.abs(sy - handles[k].y) <= HANDLE) return k;
            }
            return null;
        }

        // ---- snapping --------------------------------------------------------
        function snapGrid(v) {
            var g = (api.spec.grid && api.spec.grid.snap) ? num(api.spec.grid.size, GRID_DEFAULT) : 0;
            return g > 0 ? Math.round(v / g) * g : Math.round(v);
        }
        // Returns { dx, dy, guides:[{x|y, ...}] } snapping a moving rect's edges
        // and center to sibling/parent edges & centers (screen-threshold).
        function computeSnap(movingRect, excludeIds, altDisabled) {
            var result = { dx: 0, dy: 0, guides: [] };
            if (altDisabled) return result;
            var targets = collectSnapLines(excludeIds);
            var thrWorld = SNAP_THRESHOLD / api.zoom;
            // candidate X positions of the moving rect: left, center, right
            var mxs = [{ v: movingRect.x, kind: 'left' }, { v: movingRect.x + movingRect.w / 2, kind: 'cx' }, { v: movingRect.x + movingRect.w, kind: 'right' }];
            var mys = [{ v: movingRect.y, kind: 'top' }, { v: movingRect.y + movingRect.h / 2, kind: 'cy' }, { v: movingRect.y + movingRect.h, kind: 'bottom' }];
            var bestX = null, bestY = null;
            mxs.forEach(function (m) {
                targets.xs.forEach(function (tx) {
                    var d = tx - m.v;
                    if (Math.abs(d) <= thrWorld && (bestX === null || Math.abs(d) < Math.abs(bestX.d))) bestX = { d: d, line: tx };
                });
            });
            mys.forEach(function (m) {
                targets.ys.forEach(function (ty) {
                    var d = ty - m.v;
                    if (Math.abs(d) <= thrWorld && (bestY === null || Math.abs(d) < Math.abs(bestY.d))) bestY = { d: d, line: ty };
                });
            });
            if (bestX) { result.dx = bestX.d; result.guides.push({ axis: 'x', world: bestX.line }); }
            if (bestY) { result.dy = bestY.d; result.guides.push({ axis: 'y', world: bestY.line }); }
            return result;
        }
        function collectSnapLines(excludeIds) {
            var xs = [], ys = [];
            var add = function (rc) {
                xs.push(rc.x, rc.x + rc.w / 2, rc.x + rc.w);
                ys.push(rc.y, rc.y + rc.h / 2, rc.y + rc.h);
            };
            add(nodeWorldRect(api.spec.root));
            flatNodes(api.spec).forEach(function (n) {
                if (excludeIds.indexOf(n.id) !== -1) return;
                add(nodeWorldRect(n));
            });
            return { xs: xs, ys: ys };
        }

        // ---- history (spec snapshots) ---------------------------------------
        function pushHistory() {
            api.history.push(cloneSpec(api.spec));
            if (api.history.length > HISTORY_CAP) api.history.shift();
            api.future = [];
            scheduleAutosave();
        }
        function undo() {
            if (!api.history.length) return;
            api.future.push(cloneSpec(api.spec));
            api.spec = api.history.pop();
            api.selection = api.selection.filter(function (id) { return !!findNode(api.spec, id); });
            fullRefresh();
        }
        function redo() {
            if (!api.future.length) return;
            api.history.push(cloneSpec(api.spec));
            api.spec = api.future.pop();
            api.selection = api.selection.filter(function (id) { return !!findNode(api.spec, id); });
            fullRefresh();
        }

        // ---- autosave --------------------------------------------------------
        var autosaveTimer = null;
        function scheduleAutosave() {
            if (autosaveTimer) clearTimeout(autosaveTimer);
            autosaveTimer = setTimeout(function () {
                try { localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(api.spec)); } catch (_e) { /* quota */ }
            }, AUTOSAVE_DEBOUNCE);
        }

        // ---- rendering -------------------------------------------------------
        function render() {
            var w = canvas.clientWidth, h = canvas.clientHeight;
            ctx.clearRect(0, 0, w, h);
            drawGrid(w, h);
            // canvas frame (root bounds)
            var root = nodeWorldRect(api.spec.root);
            var rtl = toScreen(root.x, root.y);
            ctx.save();
            ctx.fillStyle = api.spec.canvas && api.spec.canvas.background ? api.spec.canvas.background : '#0f1723';
            ctx.fillRect(rtl.x, rtl.y, root.w * api.zoom, root.h * api.zoom);
            ctx.strokeStyle = 'rgba(255,255,255,0.10)';
            ctx.lineWidth = 1;
            ctx.strokeRect(rtl.x, rtl.y, root.w * api.zoom, root.h * api.zoom);
            ctx.restore();
            // nodes in painter order
            flatNodes(api.spec).forEach(drawNode);
            // selection chrome
            drawSelection();
            // active snap guides
            drawGuides();
            // active rubber band / draft shape
            drawDraft();
            ui.readout.textContent = readoutText();
        }
        function drawGrid(w, h) {
            var g = num(api.spec.grid && api.spec.grid.size, GRID_DEFAULT);
            if (g <= 0) return;
            var step = g * api.zoom;
            if (step < 6) return; // too dense to be useful
            ctx.save();
            ctx.fillStyle = 'rgba(255,255,255,0.06)';
            var ox = ((api.panX % step) + step) % step;
            var oy = ((api.panY % step) + step) % step;
            for (var x = ox; x < w; x += step) {
                for (var y = oy; y < h; y += step) { ctx.fillRect(x, y, 1, 1); }
            }
            ctx.restore();
        }
        function drawNode(node) {
            var rc = nodeWorldRect(node);
            var p = toScreen(rc.x, rc.y);
            var sw = rc.w * api.zoom, sh = rc.h * api.zoom;
            ctx.save();
            ctx.globalAlpha = num(node.style && node.style.opacity, 1);
            var s = node.style || {};
            // fill
            if (node.type === 'pen') { drawPenNode(node); ctx.restore(); return; }
            if (str(s.bg)) { ctx.fillStyle = paintColor(s.bg); roundRect(p.x, p.y, sw, sh, num(s.radius) * api.zoom); ctx.fill(); }
            else if (node.type === 'container' || node.type === 'card' || node.type === 'modal') {
                ctx.fillStyle = 'rgba(255,255,255,0.02)'; roundRect(p.x, p.y, sw, sh, num(s.radius) * api.zoom); ctx.fill();
            }
            // border
            if (str(s.border)) { ctx.strokeStyle = paintColor(s.border); ctx.lineWidth = 1; roundRect(p.x, p.y, sw, sh, num(s.radius) * api.zoom); ctx.stroke(); }
            else if (!str(s.bg)) { ctx.strokeStyle = 'rgba(255,255,255,0.16)'; ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.strokeRect(p.x, p.y, sw, sh); ctx.setLineDash([]); }
            // image placeholder
            if (node.type === 'image') {
                ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.beginPath();
                ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + sw, p.y + sh); ctx.moveTo(p.x + sw, p.y); ctx.lineTo(p.x, p.y + sh); ctx.stroke();
            }
            // label / text content
            var label = nodeLabel(node);
            if (label && sh > 12) {
                ctx.fillStyle = str(s.color) ? paintColor(s.color) : '#ececf1';
                ctx.font = (Math.max(9, num(s.fontSize, 14) * api.zoom)) + 'px ' + 'Manrope, system-ui, sans-serif';
                ctx.textBaseline = 'middle';
                var tx = p.x + 8 * api.zoom;
                var ty = node.type === 'text' || node.type === 'button' ? p.y + sh / 2 : p.y + Math.min(sh / 2, 12 * api.zoom);
                clipText(label, tx, ty, sw - 12 * api.zoom);
            }
            // absolute badge
            if (node.absolute) {
                ctx.fillStyle = '#ffd89a'; ctx.font = (9) + 'px ui-monospace, monospace';
                ctx.textBaseline = 'top'; ctx.fillText('abs', p.x + 3, p.y + 3);
            }
            ctx.restore();
        }
        function drawPenNode(node) {
            var pts = (node.stroke && node.stroke.points) || [];
            if (pts.length < 2) return;
            ctx.save();
            ctx.strokeStyle = paintColor((node.stroke && node.stroke.color) || '#ececf1');
            ctx.lineWidth = Math.max(1, num(node.stroke && node.stroke.width, 3) * api.zoom);
            ctx.lineJoin = 'round'; ctx.lineCap = 'round';
            ctx.beginPath();
            var first = toScreen(pts[0].x, pts[0].y);
            ctx.moveTo(first.x, first.y);
            for (var i = 1; i < pts.length; i++) { var pp = toScreen(pts[i].x, pts[i].y); ctx.lineTo(pp.x, pp.y); }
            ctx.stroke();
            ctx.restore();
        }
        function nodeLabel(node) {
            if (node.type === 'input') return str(node.content && node.content.placeholder);
            if (str(node.content && node.content.text)) return str(node.content.text);
            return node.type === 'container' || node.type === 'card' ? '' : str(node.name);
        }
        function clipText(text, x, y, maxW) {
            if (maxW <= 0) return;
            var t = str(text);
            while (t.length && ctx.measureText(t).width > maxW) t = t.slice(0, -1);
            if (t !== text && t.length > 1) t = t.slice(0, -1) + '…';
            ctx.fillText(t, x, y);
        }
        function paintColor(v) {
            var c = str(v);
            if (/^color\.[a-z0-9_]+$/i.test(c)) {
                var key = c.split('.')[1];
                var tk = api.spec.tokens && api.spec.tokens.color;
                return (tk && tk[key]) || '#888';
            }
            return c || '#888';
        }
        function roundRect(x, y, w, h, r) {
            r = Math.max(0, Math.min(r || 0, Math.min(w, h) / 2));
            ctx.beginPath();
            ctx.moveTo(x + r, y);
            ctx.arcTo(x + w, y, x + w, y + h, r);
            ctx.arcTo(x + w, y + h, x, y + h, r);
            ctx.arcTo(x, y + h, x, y, r);
            ctx.arcTo(x, y, x + w, y, r);
            ctx.closePath();
        }
        function drawSelection() {
            api.selection.forEach(function (id, idx) {
                var n = findNode(api.spec, id);
                if (!n) return;
                var rc = nodeWorldRect(n);
                var p = toScreen(rc.x, rc.y);
                var sw = rc.w * api.zoom, sh = rc.h * api.zoom;
                ctx.save();
                ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5;
                ctx.strokeRect(p.x - 0.5, p.y - 0.5, sw + 1, sh + 1);
                // resize handles only for a single selection
                if (api.selection.length === 1) {
                    var hs = [[p.x, p.y], [p.x + sw, p.y], [p.x, p.y + sh], [p.x + sw, p.y + sh],
                    [p.x + sw / 2, p.y], [p.x + sw / 2, p.y + sh], [p.x, p.y + sh / 2], [p.x + sw, p.y + sh / 2]];
                    ctx.fillStyle = '#58a6ff';
                    hs.forEach(function (h) { ctx.fillRect(h[0] - 3, h[1] - 3, 6, 6); });
                }
                ctx.restore();
            });
        }
        var activeGuides = [];
        function drawGuides() {
            if (!activeGuides.length) return;
            ctx.save();
            ctx.strokeStyle = '#ff6b9d'; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
            var w = canvas.clientWidth, h = canvas.clientHeight;
            activeGuides.forEach(function (g) {
                if (g.axis === 'x') { var sx = toScreen(g.world, 0).x; ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke(); }
                else { var sy = toScreen(0, g.world).y; ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke(); }
            });
            ctx.setLineDash([]); ctx.restore();
        }
        var draft = null; // {type:'rubber'|'box'|'pen', ...}
        function drawDraft() {
            if (!draft) return;
            ctx.save();
            if (draft.type === 'rubber') {
                ctx.strokeStyle = '#58a6ff'; ctx.fillStyle = 'rgba(88,166,255,0.10)';
                var r = normRect(draft.x0, draft.y0, draft.x1, draft.y1);
                ctx.fillRect(r.x, r.y, r.w, r.h); ctx.strokeRect(r.x, r.y, r.w, r.h);
            } else if (draft.type === 'box') {
                ctx.strokeStyle = '#47d7ac'; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
                var b = normRect(draft.x0, draft.y0, draft.x1, draft.y1);
                ctx.strokeRect(b.x, b.y, b.w, b.h); ctx.setLineDash([]);
            } else if (draft.type === 'pen' && draft.points.length > 1) {
                ctx.strokeStyle = '#ececf1'; ctx.lineWidth = 3; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
                ctx.beginPath(); ctx.moveTo(draft.points[0].sx, draft.points[0].sy);
                for (var i = 1; i < draft.points.length; i++) ctx.lineTo(draft.points[i].sx, draft.points[i].sy);
                ctx.stroke();
            }
            ctx.restore();
        }
        function normRect(x0, y0, x1, y1) { return { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) }; }
        function readoutText() {
            var sel = api.selection.length === 1 ? findNode(api.spec, api.selection[0]) : null;
            if (sel) { var rc = sel.rect; return sel.type + '  x:' + Math.round(rc.x) + ' y:' + Math.round(rc.y) + ' w:' + Math.round(rc.w) + ' h:' + Math.round(rc.h); }
            if (api.selection.length > 1) return api.selection.length + ' selected';
            return 'zoom ' + Math.round(api.zoom * 100) + '%  ·  grid ' + num(api.spec.grid.size, GRID_DEFAULT) + 'px' + (api.spec.grid.snap ? ' (snap on)' : '');
        }

        // ---- interaction state machine --------------------------------------
        var drag = null; // {mode:'move'|'resize'|'pan', ...}
        function onPointerDown(ev) {
            canvas.setPointerCapture && canvas.setPointerCapture(ev.pointerId);
            var sp = pointerPos(ev);
            var wp = toWorld(sp.x, sp.y);
            // middle button or space-pan -> pan
            if (ev.button === 1 || api.spacePan) {
                drag = { mode: 'pan', sx: sp.x, sy: sp.y, panX: api.panX, panY: api.panY };
                canvas.classList.add('is-panning');
                return;
            }
            if (api.tool === 'pen') {
                draft = { type: 'pen', points: [{ sx: sp.x, sy: sp.y, wx: wp.x, wy: wp.y }] };
                return;
            }
            if (api.tool === 'box' || api.tool === 'shape' || api.tool === 'text') {
                draft = { type: 'box', tool: api.tool, x0: sp.x, y0: sp.y, x1: sp.x, y1: sp.y };
                return;
            }
            // select tool: handle? node? empty?
            var handle = handleAt(sp.x, sp.y);
            if (handle) {
                var n = findNode(api.spec, api.selection[0]);
                pushHistory();
                drag = { mode: 'resize', handle: handle, id: n.id, start: Object.assign({}, n.rect), sx: sp.x, sy: sp.y };
                return;
            }
            var hit = hitTest(wp.x, wp.y);
            if (hit) {
                if (ev.shiftKey) {
                    var i = api.selection.indexOf(hit.id);
                    if (i === -1) api.selection.push(hit.id); else api.selection.splice(i, 1);
                } else if (api.selection.indexOf(hit.id) === -1) {
                    api.selection = [hit.id];
                }
                // begin a move drag; capture EACH node's own start rect (fixes the
                // documented stale-start-position bug on multi-move).
                pushHistory();
                drag = {
                    mode: 'move', sx: sp.x, sy: sp.y,
                    starts: api.selection.map(function (id) { var nn = findNode(api.spec, id); return { id: id, x: nn.rect.x, y: nn.rect.y }; })
                };
                refreshPanels();
            } else {
                if (!ev.shiftKey) api.selection = [];
                draft = { type: 'rubber', x0: sp.x, y0: sp.y, x1: sp.x, y1: sp.y };
                refreshPanels();
            }
            render();
        }
        function onPointerMove(ev) {
            var sp = pointerPos(ev);
            var wp = toWorld(sp.x, sp.y);
            if (drag && drag.mode === 'pan') {
                api.panX = drag.panX + (sp.x - drag.sx);
                api.panY = drag.panY + (sp.y - drag.sy);
                render(); return;
            }
            if (drag && drag.mode === 'move') {
                var rawDX = (sp.x - drag.sx) / api.zoom, rawDY = (sp.y - drag.sy) / api.zoom;
                // snap using the primary (first) selected node's projected rect
                var primary = findNode(api.spec, drag.starts[0].id);
                var proj = { x: snapGrid(drag.starts[0].x + rawDX), y: snapGrid(drag.starts[0].y + rawDY), w: primary.rect.w, h: primary.rect.h };
                var snap = computeSnap(proj, api.selection, ev.altKey);
                activeGuides = snap.guides;
                var appliedDX = (proj.x + snap.dx) - drag.starts[0].x;
                var appliedDY = (proj.y + snap.dy) - drag.starts[0].y;
                drag.starts.forEach(function (st) {
                    var n = findNode(api.spec, st.id);
                    if (!n || n.locked) return;
                    n.rect.x = snapGrid(st.x + appliedDX);
                    n.rect.y = snapGrid(st.y + appliedDY);
                });
                refreshInspectorValues();
                render(); return;
            }
            if (drag && drag.mode === 'resize') {
                var n2 = findNode(api.spec, drag.id);
                var dx = (sp.x - drag.sx) / api.zoom, dy = (sp.y - drag.sy) / api.zoom;
                applyResize(n2, drag.handle, drag.start, dx, dy, ev.altKey);
                refreshInspectorValues();
                render(); return;
            }
            if (draft) {
                if (draft.type === 'pen') { draft.points.push({ sx: sp.x, sy: sp.y, wx: wp.x, wy: wp.y }); }
                else { draft.x1 = sp.x; draft.y1 = sp.y; }
                render(); return;
            }
            // hover cursor feedback for handles
            if (api.tool === 'select') {
                var hh = handleAt(sp.x, sp.y);
                canvas.style.cursor = hh ? handleCursor(hh) : 'default';
            }
        }
        function onPointerUp(ev) {
            var sp = pointerPos(ev);
            if (drag && drag.mode === 'pan') { canvas.classList.remove('is-panning'); drag = null; return; }
            if (drag && (drag.mode === 'move' || drag.mode === 'resize')) {
                activeGuides = []; drag = null; scheduleAutosave(); refreshPanels(); render(); return;
            }
            if (draft) {
                if (draft.type === 'rubber') {
                    var r = normRect(draft.x0, draft.y0, draft.x1, draft.y1);
                    if (r.w > 3 && r.h > 3) selectWithin(r, ev.shiftKey);
                    draft = null; refreshPanels(); render(); return;
                }
                if (draft.type === 'box') {
                    finishBox(draft);
                    draft = null; return;
                }
                if (draft.type === 'pen') {
                    finishPen(draft);
                    draft = null; return;
                }
            }
            drag = null;
        }
        function handleCursor(h) {
            var map = { nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize', n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize' };
            return map[h] || 'default';
        }
        function applyResize(n, handle, start, dx, dy, noSnap) {
            var x = start.x, y = start.y, w = start.w, h = start.h;
            if (handle.indexOf('e') !== -1) w = start.w + dx;
            if (handle.indexOf('s') !== -1) h = start.h + dy;
            if (handle.indexOf('w') !== -1) { x = start.x + dx; w = start.w - dx; }
            if (handle.indexOf('n') !== -1) { y = start.y + dy; h = start.h - dy; }
            if (!noSnap) { x = snapGrid(x); y = snapGrid(y); w = snapGrid(w); h = snapGrid(h); }
            else { x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h); }
            if (w < 8) { if (handle.indexOf('w') !== -1) x = start.x + start.w - 8; w = 8; }
            if (h < 8) { if (handle.indexOf('n') !== -1) y = start.y + start.h - 8; h = 8; }
            n.rect.x = x; n.rect.y = y; n.rect.w = w; n.rect.h = h;
        }
        function selectWithin(screenRect, additive) {
            var sel = additive ? api.selection.slice() : [];
            flatNodes(api.spec).forEach(function (n) {
                if (n.locked) return;
                var rc = nodeWorldRect(n);
                var tl = toScreen(rc.x, rc.y), br = toScreen(rc.x + rc.w, rc.y + rc.h);
                if (tl.x >= screenRect.x && tl.y >= screenRect.y && br.x <= screenRect.x + screenRect.w && br.y <= screenRect.y + screenRect.h) {
                    if (sel.indexOf(n.id) === -1) sel.push(n.id);
                }
            });
            api.selection = sel;
        }
        function finishBox(d) {
            var w0 = toWorld(d.x0, d.y0), w1 = toWorld(d.x1, d.y1);
            var rc = { x: snapGrid(Math.min(w0.x, w1.x)), y: snapGrid(Math.min(w0.y, w1.y)), w: snapGrid(Math.abs(w1.x - w0.x)), h: snapGrid(Math.abs(w1.y - w0.y)) };
            if (rc.w < 8) rc.w = snapGrid(120);
            if (rc.h < 8) rc.h = snapGrid(d.tool === 'text' ? 24 : 60);
            var type = d.tool === 'shape' ? 'shape' : (d.tool === 'text' ? 'text' : 'container');
            pushHistory();
            var node = makeNode(type, rc);
            // drop into root (or into the hit container under the start point)
            var host = hostContainerAt(w0.x, w0.y) || api.spec.root;
            host.children.push(node);
            api.selection = [node.id];
            api.tool = 'select'; ui.syncTools();
            fullRefresh();
        }
        function finishPen(d) {
            if (d.points.length < 2) { render(); return; }
            var xs = d.points.map(function (p) { return p.wx; });
            var ys = d.points.map(function (p) { return p.wy; });
            var minX = Math.min.apply(null, xs), minY = Math.min.apply(null, ys);
            var maxX = Math.max.apply(null, xs), maxY = Math.max.apply(null, ys);
            pushHistory();
            var node = makeNode('pen', { x: minX, y: minY, w: Math.max(8, maxX - minX), h: Math.max(8, maxY - minY) },
                { stroke: { points: d.points.map(function (p) { return { x: p.wx, y: p.wy }; }), width: 3, color: '#ececf1' } });
            api.spec.root.children.push(node);
            api.selection = [node.id];
            api.tool = 'select'; ui.syncTools();
            fullRefresh();
        }
        function hostContainerAt(wx, wy) {
            var nodes = flatNodes(api.spec), best = null;
            nodes.forEach(function (n) {
                if (n.type !== 'container' && n.type !== 'card' && n.type !== 'modal' && n.type !== 'nav') return;
                var rc = nodeWorldRect(n);
                if (wx >= rc.x && wx <= rc.x + rc.w && wy >= rc.y && wy <= rc.y + rc.h) best = n; // deepest in paint order
            });
            return best;
        }

        // ---- zoom (pointer-relative — officeSetZoom pattern) -----------------
        function onWheel(ev) {
            ev.preventDefault();
            var sp = pointerPos(ev);
            var oldZoom = api.zoom;
            var factor = ev.deltaY < 0 ? 1.1 : 1 / 1.1;
            var newZoom = clamp(oldZoom * factor, ZOOM_MIN, ZOOM_MAX);
            if (newZoom === oldZoom) return;
            // keep the world point under the cursor fixed
            var wx = (sp.x - api.panX) / oldZoom;
            var wy = (sp.y - api.panY) / oldZoom;
            api.zoom = newZoom;
            api.panX = sp.x - wx * newZoom;
            api.panY = sp.y - wy * newZoom;
            ui.zoomLabel.textContent = Math.round(api.zoom * 100) + '%';
            render();
        }

        // ---- keyboard --------------------------------------------------------
        function onKeyDown(ev) {
            if (isTypingTarget(ev.target)) return;
            var step = ev.shiftKey ? num(api.spec.grid.size, GRID_DEFAULT) : 1;
            if (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight' || ev.key === 'ArrowUp' || ev.key === 'ArrowDown') {
                if (!api.selection.length) return;
                ev.preventDefault(); pushHistory();
                var dx = ev.key === 'ArrowLeft' ? -step : (ev.key === 'ArrowRight' ? step : 0);
                var dy = ev.key === 'ArrowUp' ? -step : (ev.key === 'ArrowDown' ? step : 0);
                api.selection.forEach(function (id) { var n = findNode(api.spec, id); if (n && !n.locked) { n.rect.x += dx; n.rect.y += dy; } });
                refreshInspectorValues(); render(); return;
            }
            if ((ev.key === 'Delete' || ev.key === 'Backspace') && api.selection.length) { ev.preventDefault(); deleteSelection(); return; }
            if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z' && !ev.shiftKey) { ev.preventDefault(); undo(); return; }
            if ((ev.ctrlKey || ev.metaKey) && (ev.key.toLowerCase() === 'y' || (ev.shiftKey && ev.key.toLowerCase() === 'z'))) { ev.preventDefault(); redo(); return; }
            if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'd' && api.selection.length) { ev.preventDefault(); duplicateSelection(); return; }
            if (ev.key === 'Escape') { api.selection = []; api.tool = 'select'; ui.syncTools(); refreshPanels(); render(); return; }
            if (ev.key === ' ') { api.spacePan = true; }
            // tool hotkeys
            var tk = { v: 'select', b: 'box', s: 'shape', t: 'text', p: 'pen' }[ev.key.toLowerCase()];
            if (tk) { api.tool = tk; ui.syncTools(); render(); }
        }
        function onKeyUp(ev) { if (ev.key === ' ') api.spacePan = false; }
        function isTypingTarget(el) { return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable); }

        function deleteSelection() {
            pushHistory();
            api.selection.forEach(function (id) {
                var parent = findParent(api.spec, id);
                if (parent && Array.isArray(parent.children)) parent.children = parent.children.filter(function (c) { return c.id !== id; });
            });
            api.selection = [];
            fullRefresh();
        }
        function duplicateSelection() {
            pushHistory();
            var newIds = [];
            api.selection.forEach(function (id) {
                var n = findNode(api.spec, id); if (!n) return;
                var parent = findParent(api.spec, id) || api.spec.root;
                var copy = reIdSubtree(cloneSpec(n));
                copy.rect.x = snapGrid(copy.rect.x + 16); copy.rect.y = snapGrid(copy.rect.y + 16);
                parent.children.push(copy); newIds.push(copy.id);
            });
            api.selection = newIds;
            fullRefresh();
        }
        function reIdSubtree(node) {
            node.id = nodeId();
            if (Array.isArray(node.children)) node.children.forEach(reIdSubtree);
            return node;
        }

        // ---- panels (layers + properties) -----------------------------------
        function refreshPanels() { renderLayers(); renderInspector(); }
        function fullRefresh() { refreshPanels(); render(); }
        function refreshInspectorValues() {
            // light update of just the numeric fields during a drag (no rebuild)
            if (api.selection.length !== 1) return;
            var n = findNode(api.spec, api.selection[0]); if (!n) return;
            if (ui.fields.x) { ui.fields.x.value = Math.round(n.rect.x); ui.fields.y.value = Math.round(n.rect.y); ui.fields.w.value = Math.round(n.rect.w); ui.fields.h.value = Math.round(n.rect.h); }
            ui.readout.textContent = readoutText();
        }
        function renderLayers() {
            var host = ui.layers; host.innerHTML = '';
            var nodes = flatNodes(api.spec);
            if (!nodes.length) { host.innerHTML = '<div class="ui-studio-empty">No elements yet. Pick a tool and draw on the canvas.</div>'; return; }
            // show in reverse paint order (topmost first), with simple depth indent
            nodes.slice().reverse().forEach(function (n) {
                var depth = nodeDepth(n);
                var row = document.createElement('div');
                row.className = 'ui-studio-layer' + (api.selection.indexOf(n.id) !== -1 ? ' is-selected' : '');
                row.style.paddingLeft = (6 + depth * 12) + 'px';
                var glyph = document.createElement('span'); glyph.className = 'ui-studio-layer-type'; glyph.textContent = typeGlyph(n.type);
                var name = document.createElement('span'); name.className = 'ui-studio-layer-name'; name.textContent = n.name + (n.absolute ? '  ·abs' : '');
                var lock = document.createElement('button'); lock.className = 'ui-studio-layer-btn'; lock.title = 'Lock/unlock'; lock.textContent = n.locked ? '🔒' : '🔓';
                lock.addEventListener('click', function (e) { e.stopPropagation(); pushHistory(); n.locked = !n.locked; fullRefresh(); });
                row.appendChild(glyph); row.appendChild(name); row.appendChild(lock);
                row.addEventListener('click', function (e) {
                    if (e.shiftKey) { var i = api.selection.indexOf(n.id); if (i === -1) api.selection.push(n.id); else api.selection.splice(i, 1); }
                    else api.selection = [n.id];
                    refreshPanels(); render();
                });
                host.appendChild(row);
            });
        }
        function nodeDepth(node) { var d = 0, p = findParent(api.spec, node.id); while (p && p !== api.spec.root) { d++; p = findParent(api.spec, p.id); } return d; }
        function typeGlyph(t) {
            return { container: '▢', card: '▥', text: 'T', button: '⬚', image: '🖼', input: '▭', list: '☰', nav: '⊟', table: '⊞', modal: '◳', shape: '◆', pen: '✎' }[t] || '•';
        }
        function renderInspector() {
            var host = ui.props; host.innerHTML = '';
            var single = api.selection.length === 1 ? findNode(api.spec, api.selection[0]) : null;
            if (!single) {
                host.innerHTML = api.selection.length > 1
                    ? '<div class="ui-studio-empty">' + api.selection.length + ' elements selected. Move/resize together, or pick one to edit details.</div>'
                    : '<div class="ui-studio-empty">Select an element to edit its position, size, colour and label.</div>';
                ui.fields = {};
                return;
            }
            var grid = document.createElement('div'); grid.className = 'ui-studio-field-grid';
            ui.fields = {};
            function field(key, label, value, opts) {
                opts = opts || {};
                var wrap = document.createElement('label'); wrap.className = 'ui-studio-field' + (opts.wide ? ' is-wide' : '');
                var span = document.createElement('span'); span.textContent = label;
                var input;
                if (opts.type === 'select') {
                    input = document.createElement('select');
                    (opts.options || []).forEach(function (o) { var op = document.createElement('option'); op.value = o; op.textContent = o; input.appendChild(op); });
                    input.value = value;
                } else if (opts.type === 'textarea') {
                    input = document.createElement('textarea'); input.value = str(value);
                } else {
                    input = document.createElement('input'); input.type = opts.type || 'number'; input.value = value;
                    if (opts.type === 'color') input.value = toHexColor(value);
                }
                wrap.appendChild(span); wrap.appendChild(input);
                grid.appendChild(wrap);
                ui.fields[key] = input;
                input.addEventListener('change', function () { commitInspector(); });
                if (opts.type === 'color') input.addEventListener('input', function () { commitInspector(); });
                return input;
            }
            field('x', 'X', Math.round(single.rect.x));
            field('y', 'Y', Math.round(single.rect.y));
            field('w', 'Width', Math.round(single.rect.w));
            field('h', 'Height', Math.round(single.rect.h));
            field('name', 'Name', single.name, { type: 'text', wide: true });
            field('type', 'Type', single.type, { type: 'select', options: NODE_TYPES });
            field('text', 'Label / Text', str(single.content && single.content.text), { type: 'text', wide: true });
            field('bg', 'Background', str(single.style && single.style.bg) || '#000000', { type: 'color' });
            field('color', 'Text colour', str(single.style && single.style.color) || '#ececf1', { type: 'color' });
            field('radius', 'Radius', Math.round(num(single.style && single.style.radius)));
            field('z', 'Z', Math.round(num(single.z)));
            field('layout', 'Layout', (single.layout && single.layout.mode) || 'none', { type: 'select', options: ['none', 'flex', 'grid'] });
            field('direction', 'Direction', (single.layout && single.layout.direction) || 'col', { type: 'select', options: ['col', 'row'] });
            // absolute toggle
            var absWrap = document.createElement('label'); absWrap.className = 'ui-studio-field is-wide';
            var absSpan = document.createElement('span'); absSpan.textContent = 'Position';
            var absSel = document.createElement('select');
            ['flow', 'absolute'].forEach(function (o) { var op = document.createElement('option'); op.value = o; op.textContent = o; absSel.appendChild(op); });
            absSel.value = single.absolute ? 'absolute' : 'flow';
            absSel.addEventListener('change', function () { commitInspector(); });
            absWrap.appendChild(absSpan); absWrap.appendChild(absSel); grid.appendChild(absWrap); ui.fields.absolute = absSel;
            host.appendChild(grid);
        }
        function commitInspector() {
            if (api.selection.length !== 1) return;
            var n = findNode(api.spec, api.selection[0]); if (!n) return;
            pushHistory();
            var f = ui.fields;
            if (f.x) n.rect.x = snapGrid(num(f.x.value, n.rect.x));
            if (f.y) n.rect.y = snapGrid(num(f.y.value, n.rect.y));
            if (f.w) n.rect.w = Math.max(8, snapGrid(num(f.w.value, n.rect.w)));
            if (f.h) n.rect.h = Math.max(8, snapGrid(num(f.h.value, n.rect.h)));
            if (f.name) n.name = str(f.name.value) || n.name;
            if (f.type && NODE_TYPES.indexOf(f.type.value) !== -1) n.type = f.type.value;
            if (f.text) { n.content = n.content || {}; n.content.text = str(f.text.value); }
            if (f.bg) n.style.bg = f.bg.value;
            if (f.color) n.style.color = f.color.value;
            if (f.radius) n.style.radius = Math.max(0, num(f.radius.value));
            if (f.z) n.z = Math.round(num(f.z.value));
            if (f.layout) { n.layout = n.layout || {}; n.layout.mode = f.layout.value; }
            if (f.direction) { n.layout = n.layout || {}; n.layout.direction = f.direction.value; }
            if (f.absolute) n.absolute = f.absolute.value === 'absolute';
            fullRefresh();
        }
        function toHexColor(v) {
            var s = str(v);
            if (/^#([0-9a-f]{6})$/i.test(s)) return s;
            if (/^#([0-9a-f]{3})$/i.test(s)) return '#' + s[1] + s[1] + s[2] + s[2] + s[3] + s[3];
            if (/^color\./i.test(s)) { var key = s.split('.')[1]; var tk = api.spec.tokens && api.spec.tokens.color; if (tk && tk[key]) return tk[key]; }
            return '#000000';
        }

        // ---- toolbar actions -------------------------------------------------
        function generateCode() {
            var react = specToReact(api.spec);
            var tokens = specToTokensCss(api.spec);
            var html = specToHtml(api.spec);
            openCodeModal({ 'App.jsx (React + Tailwind)': react, 'tokens.css': tokens, 'index.html (HTML + CSS)': html });
            // hit the deterministic server route too (best-effort; ignored offline)
            if (!api.offline) {
                postJson(api.apiBase + '/codegen', { spec: api.spec }).catch(function () { /* server optional */ });
            }
        }
        function exportSpec() {
            var json = JSON.stringify(api.spec, null, 2);
            downloadText((slug(api.spec.name) || 'layout') + '.uistudio.json', json, 'application/json');
            copyText(json);
            notify('Layout spec exported and copied to clipboard.', { tone: 'success' });
        }
        function saveToServer() {
            if (api.offline) { notify('Offline demo — save skipped (would POST ' + api.apiBase + '/spec).', { tone: 'info' }); return; }
            postJson(api.apiBase + '/spec', { spec: api.spec }).then(function (res) {
                notify(res && res.ok ? 'Spec saved to .thomas/canvas.' : 'Save failed.', { tone: res && res.ok ? 'success' : 'warn' });
            }).catch(function () { notify('Could not reach the canvas API.', { tone: 'warn' }); });
        }

        // AI Generate Template (wave-2 route; mock when offline)
        function aiTemplate() {
            var prompt = window.prompt('Describe the UI to generate:\n(e.g. "a task dashboard with a left sidebar, a 3-column card grid, and a top bar")');
            if (!prompt) return;
            var selId = api.selection.length === 1 ? api.selection[0] : null;
            ui.aiBtn.disabled = true; ui.aiBtn.textContent = 'Generating…';
            var done = function () { ui.aiBtn.disabled = false; ui.aiBtn.textContent = 'AI Template'; };
            if (api.offline) {
                setTimeout(function () { applyAiSpec(mockTemplateSpec(prompt), 'mock'); done(); }, 350);
                return;
            }
            postJson(api.apiBase + '/template', { prompt: prompt, spec: api.spec, selection_id: selId }).then(function (res) {
                if (res && res.spec) applyAiSpec(res.spec, 'ai');
                else if (res && res.nodes) applyAiNodes(res.nodes);
                else notify('AI returned no layout.', { tone: 'warn' });
                done();
            }).catch(function () { notify('AI route unavailable — showing a sample layout.', { tone: 'warn' }); applyAiSpec(mockTemplateSpec(prompt), 'mock'); done(); });
        }
        function applyAiSpec(spec, source) {
            if (!spec || !spec.root) { notify('Invalid AI spec.', { tone: 'warn' }); return; }
            pushHistory();
            // tag AI-authored nodes; preserve nothing on a full template (fresh canvas)
            walk(spec.root, function (n) { if (n !== spec.root && !n.owner) n.owner = 'ai'; });
            spec.id = api.spec.id; // keep our persistence id
            api.spec = normalizeSpec(spec);
            api.selection = [];
            fullRefresh();
            notify(source === 'mock' ? 'Sample layout placed — drag to rearrange, click to edit.' : 'AI layout placed — your starting point. Drag, edit, or refine with another prompt.', { tone: 'success' });
        }
        function applyAiNodes(nodes) {
            pushHistory();
            (Array.isArray(nodes) ? nodes : []).forEach(function (n) { n.owner = n.owner || 'ai'; api.spec.root.children.push(normalizeNode(n)); });
            fullRefresh();
        }

        // Sketch import drop-zone (wave-2 vision route; mock when offline)
        function handleDrop(file) {
            if (!file || !/^image\//.test(file.type)) { notify('Drop a PNG or JPG image.', { tone: 'warn' }); return; }
            var reader = new FileReader();
            reader.onload = function () {
                var dataUrl = reader.result;
                if (api.offline) { applyAiSpec(mockSketchSpec(), 'mock'); return; }
                ui.readout.textContent = 'Reading sketch…';
                postJson(api.apiBase + '/spec-from-sketch', { image_data_url: dataUrl }).then(function (res) {
                    if (res && res.spec) applyAiSpec(res.spec, 'ai');
                    else notify('Vision route returned no layout.', { tone: 'warn' });
                }).catch(function () { notify('Vision route unavailable — showing a sample.', { tone: 'warn' }); applyAiSpec(mockSketchSpec(), 'mock'); });
            };
            reader.readAsDataURL(file);
        }

        // ---- chrome wiring (buttons -> actions) ------------------------------
        ui.bind({
            onTool: function (t) { api.tool = t; ui.syncTools(); canvas.className = 'ui-studio-stage tool-' + t; render(); },
            onUndo: undo, onRedo: redo,
            onZoomIn: function () { zoomBy(1.2); }, onZoomOut: function () { zoomBy(1 / 1.2); }, onZoomReset: function () { api.zoom = 1; api.panX = 60; api.panY = 60; ui.zoomLabel.textContent = '100%'; render(); },
            onGrid: function (on) { api.spec.grid.snap = on; render(); },
            onAddContainer: function () { quickAdd('container'); }, onAddText: function () { quickAdd('text'); }, onAddButton: function () { quickAdd('button'); }, onAddCard: function () { quickAdd('card'); }, onAddInput: function () { quickAdd('input'); }, onAddImage: function () { quickAdd('image'); },
            onGenerate: generateCode, onExport: exportSpec, onSave: saveToServer,
            onAi: aiTemplate, onSketch: function () { ui.sketchInput.click(); },
            onClear: function () { if (window.confirm('Clear the canvas? This cannot be undone except via Undo.')) { pushHistory(); api.spec = emptySpec(api.spec.name); api.selection = []; fullRefresh(); } }
        });
        function zoomBy(factor) {
            var cx = canvas.clientWidth / 2, cy = canvas.clientHeight / 2;
            var oldZoom = api.zoom, newZoom = clamp(oldZoom * factor, ZOOM_MIN, ZOOM_MAX);
            var wx = (cx - api.panX) / oldZoom, wy = (cy - api.panY) / oldZoom;
            api.zoom = newZoom; api.panX = cx - wx * newZoom; api.panY = cy - wy * newZoom;
            ui.zoomLabel.textContent = Math.round(api.zoom * 100) + '%'; render();
        }
        function quickAdd(type) {
            // place a fresh node near the viewport center, snapped
            var center = toWorld(canvas.clientWidth / 2, canvas.clientHeight / 2);
            var defW = type === 'text' ? 120 : (type === 'button' ? 120 : (type === 'card' || type === 'container' ? 240 : 160));
            var defH = type === 'text' ? 24 : (type === 'button' ? 36 : (type === 'card' || type === 'container' ? 160 : 44));
            var rc = { x: snapGrid(center.x - defW / 2), y: snapGrid(center.y - defH / 2), w: snapGrid(defW), h: snapGrid(defH) };
            pushHistory();
            var node = makeNode(type, rc);
            api.spec.root.children.push(node);
            api.selection = [node.id];
            fullRefresh();
        }

        // ---- sketch input + drop events -------------------------------------
        ui.sketchInput.addEventListener('change', function () { var f = ui.sketchInput.files && ui.sketchInput.files[0]; ui.sketchInput.value = ''; if (f) handleDrop(f); });
        ui.stageWrap.addEventListener('dragover', function (e) { e.preventDefault(); ui.stageWrap.classList.add('is-drop-active'); });
        ui.stageWrap.addEventListener('dragleave', function (e) { if (e.target === ui.stageWrap) ui.stageWrap.classList.remove('is-drop-active'); });
        ui.stageWrap.addEventListener('drop', function (e) {
            e.preventDefault(); ui.stageWrap.classList.remove('is-drop-active');
            var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) handleDrop(f);
        });

        // ---- pointer + key listeners ----------------------------------------
        canvas.addEventListener('pointerdown', onPointerDown);
        canvas.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp);
        canvas.addEventListener('wheel', onWheel, { passive: false });
        document.addEventListener('keydown', onKeyDown);
        document.addEventListener('keyup', onKeyUp);
        var ro = (typeof ResizeObserver === 'function') ? new ResizeObserver(function () { resize(); }) : null;
        if (ro) ro.observe(ui.stageWrap); else window.addEventListener('resize', resize);

        // ---- boot ------------------------------------------------------------
        canvas.className = 'ui-studio-stage tool-select';
        ui.zoomLabel.textContent = Math.round(api.zoom * 100) + '%';
        // initial render after layout settles
        requestAnimationFrame(function () { resize(); refreshPanels(); });
        setTimeout(function () { resize(); }, 60);

        // ---- controller ------------------------------------------------------
        var controller = {
            getSpec: function () { return cloneSpec(api.spec); },
            setSpec: function (s) { api.spec = normalizeSpec(cloneSpec(s)); api.selection = []; fullRefresh(); },
            toReact: function () { return specToReact(api.spec); },
            toHtml: function () { return specToHtml(api.spec); },
            destroy: function () {
                if (ro) ro.disconnect(); else window.removeEventListener('resize', resize);
                window.removeEventListener('pointerup', onPointerUp);
                document.removeEventListener('keydown', onKeyDown);
                document.removeEventListener('keyup', onKeyUp);
            }
        };
        return controller;

        // ---- code modal ------------------------------------------------------
        function openCodeModal(files) {
            var keys = Object.keys(files);
            ui.modal.hidden = false;
            ui.modalTabs.innerHTML = '';
            var active = keys[0];
            var show = function (k) { ui.modalCode.textContent = files[k]; active = k; Array.prototype.forEach.call(ui.modalTabs.children, function (b) { b.classList.toggle('is-accent', b.textContent === k); }); };
            keys.forEach(function (k) {
                var b = document.createElement('button'); b.className = 'ui-studio-btn'; b.textContent = k;
                b.addEventListener('click', function () { show(k); }); ui.modalTabs.appendChild(b);
            });
            ui.modalCopy.onclick = function () { copyText(files[active]); notify('Copied ' + active + '.', { tone: 'success' }); };
            ui.modalDownload.onclick = function () {
                // download each generated file individually (no zip lib in-bundle;
                // blueprint notes the .zip is a wave-2 nicety)
                keys.forEach(function (k) { downloadText(fileNameFor(k), files[k], 'text/plain'); });
                notify('Downloaded ' + keys.length + ' file(s).', { tone: 'success' });
            };
            show(active);
        }
    }

    /* ===================================================================== *
     * CHROME BUILDER (toolbar / rail / side panels / stage / modal DOM)
     * ===================================================================== */
    function buildChrome(root) {
        function el(tag, cls, txt) { var e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; }
        // toolbar
        var toolbar = el('div', 'ui-studio-toolbar');
        toolbar.appendChild(el('span', 'ui-studio-brand', 'UI Studio'));
        var gFile = el('div', 'ui-studio-toolbar-group');
        var btnGen = el('button', 'ui-studio-btn is-accent', 'Generate Code');
        var btnExport = el('button', 'ui-studio-btn', 'Export Spec');
        var btnSave = el('button', 'ui-studio-btn', 'Save');
        gFile.appendChild(btnGen); gFile.appendChild(btnExport); gFile.appendChild(btnSave);
        var gAdd = el('div', 'ui-studio-toolbar-group');
        var addBtns = {
            container: el('button', 'ui-studio-btn', '+ Box'), text: el('button', 'ui-studio-btn', '+ Text'),
            button: el('button', 'ui-studio-btn', '+ Button'), card: el('button', 'ui-studio-btn', '+ Card'),
            input: el('button', 'ui-studio-btn', '+ Input'), image: el('button', 'ui-studio-btn', '+ Image')
        };
        Object.keys(addBtns).forEach(function (k) { gAdd.appendChild(addBtns[k]); });
        var gAi = el('div', 'ui-studio-toolbar-group');
        var btnAi = el('button', 'ui-studio-btn is-mint', 'AI Template');
        var btnSketch = el('button', 'ui-studio-btn is-mint', 'Import Sketch');
        gAi.appendChild(btnAi); gAi.appendChild(btnSketch);
        var gZoom = el('div', 'ui-studio-toolbar-group');
        var btnZoomOut = el('button', 'ui-studio-btn', '−');
        var zoomLabel = el('span', 'ui-studio-zoom-label', '100%');
        var btnZoomIn = el('button', 'ui-studio-btn', '+');
        var btnZoomReset = el('button', 'ui-studio-btn', 'Reset');
        gZoom.appendChild(btnZoomOut); gZoom.appendChild(zoomLabel); gZoom.appendChild(btnZoomIn); gZoom.appendChild(btnZoomReset);
        var gGrid = el('div', 'ui-studio-toolbar-group');
        var gridToggle = el('label', 'ui-studio-toggle');
        var gridCheck = document.createElement('input'); gridCheck.type = 'checkbox'; gridCheck.checked = true;
        gridToggle.appendChild(gridCheck); gridToggle.appendChild(document.createTextNode('Snap to grid'));
        var btnUndo = el('button', 'ui-studio-btn', '↶ Undo');
        var btnRedo = el('button', 'ui-studio-btn', '↷ Redo');
        var btnClear = el('button', 'ui-studio-btn', 'Clear');
        gGrid.appendChild(gridToggle); gGrid.appendChild(btnUndo); gGrid.appendChild(btnRedo); gGrid.appendChild(btnClear);
        toolbar.appendChild(gFile); toolbar.appendChild(gAdd); toolbar.appendChild(gAi); toolbar.appendChild(gZoom); toolbar.appendChild(gGrid);

        // left rail (tools)
        var rail = el('div', 'ui-studio-rail');
        var toolDefs = [['select', '➚', 'Select (V)'], ['box', '▭', 'Box (B)'], ['shape', '◆', 'Shape (S)'], ['text', 'T', 'Text (T)'], ['pen', '✎', 'Pen (P)']];
        var toolButtons = {};
        toolDefs.forEach(function (d) {
            var b = el('button', 'ui-studio-tool' + (d[0] === 'select' ? ' is-active' : ''), d[1]); b.title = d[2]; b.setAttribute('data-tool', d[0]);
            rail.appendChild(b); toolButtons[d[0]] = b;
        });

        // stage
        var stageWrap = el('div', 'ui-studio-stage-wrap');
        var canvas = document.createElement('canvas'); canvas.className = 'ui-studio-stage tool-select';
        var readout = el('div', 'ui-studio-readout', 'ready');
        var sketchInput = document.createElement('input'); sketchInput.type = 'file'; sketchInput.accept = 'image/*'; sketchInput.style.display = 'none';
        stageWrap.appendChild(canvas); stageWrap.appendChild(readout); stageWrap.appendChild(sketchInput);

        // right side: layers + properties
        var side = el('div', 'ui-studio-side');
        var layersSec = el('div', 'ui-studio-side-section is-grow');
        layersSec.appendChild(el('div', 'ui-studio-side-title', 'Layers'));
        var layers = el('div', 'ui-studio-layers'); layersSec.appendChild(layers);
        var propsSec = el('div', 'ui-studio-side-section');
        propsSec.appendChild(el('div', 'ui-studio-side-title', 'Properties'));
        var props = el('div', 'ui-studio-props'); propsSec.appendChild(props);
        side.appendChild(layersSec); side.appendChild(propsSec);

        // code modal
        var modal = el('div', 'ui-studio-modal'); modal.hidden = true;
        var card = el('div', 'ui-studio-modal-card');
        var head = el('div', 'ui-studio-modal-head');
        head.appendChild(el('div', 'ui-studio-modal-title', 'Generated code'));
        var modalTabs = el('div', 'ui-studio-modal-tabs'); head.appendChild(modalTabs);
        var body = el('div', 'ui-studio-modal-body');
        var modalCode = el('pre', 'ui-studio-code', ''); body.appendChild(modalCode);
        var foot = el('div', 'ui-studio-modal-foot');
        var modalCopy = el('button', 'ui-studio-btn', 'Copy');
        var modalDownload = el('button', 'ui-studio-btn is-accent', 'Download files');
        var modalClose = el('button', 'ui-studio-btn', 'Close');
        modalClose.addEventListener('click', function () { modal.hidden = true; });
        foot.appendChild(modalCopy); foot.appendChild(modalDownload); foot.appendChild(modalClose);
        card.appendChild(head); card.appendChild(body); card.appendChild(foot); modal.appendChild(card);
        modal.addEventListener('click', function (e) { if (e.target === modal) modal.hidden = true; });

        root.appendChild(toolbar); root.appendChild(rail); root.appendChild(stageWrap); root.appendChild(side); root.appendChild(modal);

        var ui = {
            canvas: canvas, stageWrap: stageWrap, readout: readout, layers: layers, props: props,
            zoomLabel: zoomLabel, sketchInput: sketchInput, aiBtn: btnAi,
            modal: modal, modalTabs: modalTabs, modalCode: modalCode, modalCopy: modalCopy, modalDownload: modalDownload,
            fields: {},
            // syncTools(activeTool): highlight exactly the live tool. The engine
            // passes api.tool on every call so the rail reflects the real state.
            syncTools: function (activeTool) {
                var t = activeTool || 'select';
                Object.keys(toolButtons).forEach(function (k) { toolButtons[k].classList.toggle('is-active', k === t); });
            },
            bind: function (h) {
                btnGen.onclick = h.onGenerate; btnExport.onclick = h.onExport; btnSave.onclick = h.onSave;
                btnAi.onclick = h.onAi; btnSketch.onclick = h.onSketch;
                btnZoomIn.onclick = h.onZoomIn; btnZoomOut.onclick = h.onZoomOut; btnZoomReset.onclick = h.onZoomReset;
                btnUndo.onclick = h.onUndo; btnRedo.onclick = h.onRedo; btnClear.onclick = h.onClear;
                gridCheck.onchange = function () { h.onGrid(gridCheck.checked); };
                addBtns.container.onclick = h.onAddContainer; addBtns.text.onclick = h.onAddText; addBtns.button.onclick = h.onAddButton;
                addBtns.card.onclick = h.onAddCard; addBtns.input.onclick = h.onAddInput; addBtns.image.onclick = h.onAddImage;
                Object.keys(toolButtons).forEach(function (k) { toolButtons[k].onclick = function () { h.onTool(k); }; });
            }
        };
        return ui;
    }

    /* ===================================================================== *
     * NORMALIZATION (defensive — AI / imported specs may be partial)
     * ===================================================================== */
    function normalizeSpec(spec) {
        if (!spec || typeof spec !== 'object') return emptySpec();
        var out = emptySpec(spec.name);
        out.id = str(spec.id) || out.id;
        if (spec.canvas) out.canvas = Object.assign(out.canvas, spec.canvas);
        if (spec.grid) out.grid = Object.assign(out.grid, spec.grid);
        if (spec.tokens) out.tokens = Object.assign(defaultTokens(), spec.tokens);
        if (spec.root) out.root = normalizeNode(spec.root, true);
        return out;
    }
    function normalizeNode(node, isRoot) {
        if (!node || typeof node !== 'object') node = {};
        var t = NODE_TYPES.indexOf(node.type) === -1 ? (isRoot ? 'container' : 'container') : node.type;
        var base = makeNode(t, node.rect || { x: 0, y: 0, w: 200, h: 100 });
        if (isRoot) { base.name = str(node.name) || 'Root'; base.type = 'container'; }
        base.id = str(node.id) || base.id;
        base.name = str(node.name) || base.name;
        if (node.layout) base.layout = Object.assign(base.layout, node.layout);
        if (node.style) base.style = Object.assign(base.style, node.style);
        if (node.content) base.content = Object.assign(base.content, node.content);
        base.absolute = !!node.absolute;
        base.locked = !!node.locked;
        base.z = num(node.z);
        base.owner = node.owner === 'ai' ? 'ai' : 'user';
        if (node.stroke) base.stroke = node.stroke;
        base.children = Array.isArray(node.children) ? node.children.map(function (c) { return normalizeNode(c, false); }) : [];
        return base;
    }

    /* ===================================================================== *
     * MOCK SPECS (offline fallback for the AI buttons — never a dead end)
     * ===================================================================== */
    function mockTemplateSpec(prompt) {
        var spec = emptySpec('AI: ' + (str(prompt).slice(0, 40) || 'Template'));
        var topbar = makeNode('nav', { x: 0, y: 0, w: 1280, h: 56 }); topbar.name = 'Top Bar'; topbar.owner = 'ai';
        topbar.content.text = 'Dashboard';
        var sidebar = makeNode('container', { x: 0, y: 56, w: 224, h: 744 }); sidebar.name = 'Sidebar'; sidebar.owner = 'ai';
        sidebar.style.bg = '#181b22';
        ['Overview', 'Tasks', 'Reports', 'Settings'].forEach(function (label, i) {
            var item = makeNode('button', { x: 16, y: 72 + i * 44, w: 192, h: 32 }); item.name = label; item.content.text = label; item.owner = 'ai';
            item.style.bg = ''; item.style.color = '#adb3c2';
            sidebar.children.push(item);
        });
        var grid = makeNode('container', { x: 248, y: 80, w: 1008, h: 600 }); grid.name = 'Card Grid'; grid.owner = 'ai';
        grid.layout = { mode: 'grid', direction: 'row', gap: 16, padding: 0, align: 'start', justify: 'start', sizing: 'fixed' };
        for (var i = 0; i < 6; i++) {
            var col = i % 3, rowi = Math.floor(i / 3);
            var c = makeNode('card', { x: 248 + col * 336, y: 80 + rowi * 200, w: 312, h: 176 }); c.name = 'Card ' + (i + 1); c.owner = 'ai';
            var h = makeNode('text', { x: 248 + col * 336 + 16, y: 80 + rowi * 200 + 16, w: 200, h: 22 }); h.content.text = 'Metric ' + (i + 1); h.owner = 'ai';
            c.children.push(h);
            grid.children.push(c);
        }
        spec.root.children.push(topbar, sidebar, grid);
        return spec;
    }
    function mockSketchSpec() {
        var spec = emptySpec('AI: From Sketch');
        var header = makeNode('nav', { x: 0, y: 0, w: 1280, h: 64 }); header.name = 'Header'; header.content.text = 'My App'; header.owner = 'ai';
        var hero = makeNode('card', { x: 64, y: 96, w: 1152, h: 240 }); hero.name = 'Hero'; hero.owner = 'ai';
        var title = makeNode('text', { x: 96, y: 136, w: 600, h: 40 }); title.content.text = 'Welcome'; title.style.fontSize = 28; title.style.fontWeight = 700; title.owner = 'ai';
        var cta = makeNode('button', { x: 96, y: 200, w: 160, h: 44 }); cta.content.text = 'Get Started'; cta.owner = 'ai';
        hero.children.push(title, cta);
        spec.root.children.push(header, hero);
        return spec;
    }

    /* ===================================================================== *
     * IO helpers
     * ===================================================================== */
    function restoreOrEmpty() {
        try { var raw = localStorage.getItem(AUTOSAVE_KEY); if (raw) { var s = JSON.parse(raw); if (s && s.root) return normalizeSpec(s); } } catch (_e) { /* ignore */ }
        return emptySpec();
    }
    function postJson(url, body) {
        // prefer the host helper when present (consistent auth/error handling)
        if (typeof window.fetchJsonSafe === 'function') { return Promise.resolve(window.fetchJsonSafe(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })); }
        return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(function (r) { return r.json(); });
    }
    function downloadText(name, text, mime) {
        try {
            var blob = new Blob([text], { type: mime || 'text/plain' });
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a'); a.href = url; a.download = name;
            document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
        } catch (_e) { /* ignore */ }
    }
    function copyText(text) {
        try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text); return; } } catch (_e) { /* fall through */ }
        try { var ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); } catch (_e2) { /* ignore */ }
    }
    function slug(s) { return str(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''); }
    function fileNameFor(label) {
        if (/jsx/i.test(label)) return 'App.jsx';
        if (/tokens/i.test(label)) return 'tokens.css';
        if (/html/i.test(label)) return 'index.html';
        return slug(label) + '.txt';
    }

    /* ===================================================================== *
     * PUBLIC SURFACE
     * ===================================================================== */
    window.uiStudioMountCanvas = mountCanvas;
    window.UI_STUDIO = {
        mount: mountCanvas,
        specToReact: specToReact,
        specToHtml: specToHtml,
        specToTokensCss: specToTokensCss,
        emptySpec: emptySpec,
        normalizeSpec: normalizeSpec,
        version: UI_STUDIO_VERSION
    };

    /* ===================================================================== *
     * TAB HOST  (re-wraps the prior moduleRenderWorkbenchAppBuilder)
     * ---------------------------------------------------------------------
     * This block is the in-app integration. It is INERT in the standalone demo
     * (there is no prior moduleRenderWorkbenchAppBuilder there). In the real app
     * this file would be loaded LAST (after 044) so `priorAppBuilder` captures
     * 044's override; see ui_studio_demo.html + the blueprint's filesToModify.
     * ===================================================================== */
    (function installAppBuilderCanvas() {
        // UI Studio's coordinate canvas IS the UI Editor now. The previous
        // app_builder surfaces (old GridStack "App Builder" in 030 and the
        // 042/044 "UI Editor") were removed on 2026-06-16, so there is no prior
        // renderer to wrap or fall back to — the canvas mounts directly as the
        // sole app_builder surface. (Was a flag-gated two-tab host; now default.)
        window.moduleRenderWorkbenchAppBuilder = function moduleRenderWorkbenchAppBuilderUiStudio(container, wb) {
            if (!container) { return; }
            container.innerHTML = '';
            var host = document.createElement('div');
            host.className = 'ui-studio-host ui-studio-host-solo';
            container.appendChild(host);
            try {
                var controller = mountCanvas(host, { apiBase: '/api/canvas' });
                if (wb) { wb.uiStudioCanvas = controller; }
            } catch (e) {
                host.innerHTML = '<div class="ui-studio-empty">Canvas failed to load: ' + escapeHtml(str(e && e.message)) + '</div>';
            }
            return host;
        };
    })();

    function ensureTabStyles() {
        // Separate guarded injector (its own id) — do NOT touch 044's shared
        // moduleUiEditorEnsureStyles. If the real css file is already linked
        // (in-app), this is a harmless tiny supplement.
        if (document.getElementById('ui-studio-tab-styles')) return;
        var css = [
            '.ui-studio-host{display:flex;flex-direction:column;width:100%;height:100%;min-height:0}',
            '.ui-studio-tabbar{display:flex;align-items:center;gap:6px;padding:6px 10px;border-bottom:1px solid var(--border-light,rgba(255,255,255,.12));background:var(--bg-surface,#1f232c);flex:0 0 auto}',
            '.ui-studio-tab{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:999px;border:1px solid var(--border-light,rgba(255,255,255,.12));background:transparent;color:var(--text-secondary,#adb3c2);font:600 12px/1.4 var(--font-sans,system-ui);cursor:pointer}',
            '.ui-studio-tab.is-active{background:rgba(88,166,255,.14);border-color:var(--accent,#8a9aad);color:var(--text-primary,#ececf1)}',
            '.ui-studio-tab-spacer{flex:1 1 auto}.ui-studio-tab-hint{font-size:11px;color:var(--text-muted,#929bb0)}',
            '.ui-studio-panes{position:relative;flex:1 1 auto;min-height:0;overflow:hidden}',
            '.ui-studio-pane{position:absolute;inset:0;overflow:auto}.ui-studio-pane[hidden]{display:none}.ui-studio-pane-canvas{overflow:hidden}'
        ].join('');
        var style = document.createElement('style'); style.id = 'ui-studio-tab-styles'; style.textContent = css;
        document.head.appendChild(style);
    }
})();
