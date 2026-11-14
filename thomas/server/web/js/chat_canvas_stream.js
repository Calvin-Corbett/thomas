/* Chat canvas stream. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    function _stripFence(h) {
      let s = String(h || '').trim();
      const m = s.match(/```(?:html)?\s*([\s\S]*?)```/i);
      if (m) return m[1].trim();
      const i = s.search(/<!doctype html|<html\b|<svg\b/i);
      return i >= 0 ? s.slice(i).trim() : s;
    }

    // The render bot now OWNS its entrance (it emits #tc-stage[data-reveal] and animates its
    // own elements in). When the doc carries that contract we must NOT add our own wipe (it
    // would double-animate and fight the choreography) — we only guarantee reduced-motion
    // support and a host-side "stuck-hidden" safety net (flip data-reveal=play after 2.6s if
    // the doc's own script ever failed before flipping it). Only a LEGACY doc with no entrance
    // of its own gets the old left-to-right wipe as a fallback.
    function _injectReveal(html) {
      const ownsEntrance = /\bdata-reveal\b/.test(html) || /id=["']tc-stage["']/.test(html);
      let style;
      if (ownsEntrance) {
        style = '<style>@media (prefers-reduced-motion: reduce){#tc-stage [style*="--i"],#tc-stage *{transition:none !important;animation:none !important}}</style>'
              + '<script>(function(){try{var s=document.getElementById("tc-stage");if(s)setTimeout(function(){if(s.getAttribute("data-reveal")!=="play")s.setAttribute("data-reveal","play");},2600);}catch(e){}})()<\/script>';
      } else {
        style = '<style>@keyframes tcCanvasReveal{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}@media (prefers-reduced-motion:no-preference){html{animation:tcCanvasReveal 1.15s cubic-bezier(.4,0,.2,1) both}}</style>';
      }
      if (/<\/head>/i.test(html)) return html.replace(/<\/head>/i, style + '</head>');
      if (/<body[^>]*>/i.test(html)) return html.replace(/(<body[^>]*>)/i, '$1' + style);
      return style + html;
    }

    // Strip the entrance: pin the stage to its final 'play' state and kill all transitions/
    // animations, so the visual appears already-built with no motion.
    function _staticDoc(html) {
      return String(html)
        .replace('data-reveal="pending"', 'data-reveal="play" data-static="1"')
        .replace('<style>', '<style>#tc-stage *,#tc-stage::after{transition:none !important;animation:none !important}#tc-stage::after{opacity:0 !important}');
    }

    function _buildDeliver() {
      const f = deps.canvasBody.querySelector('iframe.tc-build-frame');
      if (!f || !f.contentWindow || !deps._build.ready) return;
      for (let i = deps._build.delivered; i < deps._build.els.length; i++) {
        const el = deps._build.els[i] || {};
        f.contentWindow.postMessage({ t: 'el', layer: el.layer, html: el.html, idx: i }, '*');
      }
      deps._build.delivered = deps._build.els.length;
      if (deps._build.done) f.contentWindow.postMessage({ t: 'done' }, '*');
    }

    function canvasConstruct(execId, shellHtml, elements, done, finalHtml) {
      if (deps.canvasState.mode === 'render') return;
      const fresh = !(deps.canvasState.mode === 'construct' && deps._build.execId === execId);
      if (fresh) deps._build = { execId: execId, els: [], delivered: 0, ready: false, done: false };
      deps._build.els = elements || [];
      deps._build.done = !!done;
      deps.canvasState = { mode: 'construct', worker: deps.canvasState.worker || '', name: 'Canvas',
                      shell: shellHtml || '', finalHtml: finalHtml || '', done: !!done, execId: execId };
      if (!deps.state.artifactOpen) deps.openCanvas(); else deps.renderCanvas();
      _buildDeliver();
    }

    function _liveSourceShell(source) {
      const tail = String(source || '').slice(-3000);
      return '<!DOCTYPE html><html><head><style>html,body{margin:0;min-height:100%;background:#fff;color:#1d2330;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}body{display:flex;flex-direction:column;padding:18px}.label{font:700 12px/1.3 system-ui,-apple-system,Segoe UI,sans-serif;color:#2f6bff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}.hint{font:12px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;color:#647084;margin-bottom:14px}pre{white-space:pre-wrap;word-break:break-word;margin:0;padding:14px;border-radius:10px;background:#f5f7fb;border:1px solid #e4e8f0;box-shadow:inset 0 0 0 1px rgba(255,255,255,.55)}.cursor{display:inline-block;width:7px;height:1em;background:#2f6bff;margin-left:2px;vertical-align:-2px;animation:blink 1s step-end infinite}@keyframes blink{0%,50%{opacity:1}50.01%,100%{opacity:0}}</style></head><body><div class="label">Receiving HTML</div><div class="hint">Thomas is still writing the document head. The visual preview starts as soon as renderable markup arrives.</div><pre>' + deps.esc(tail) + '<span class="cursor"></span></pre></body></html>';
    }

    function _closePartialHtml(html) {
      let s = String(html || '');
      const lower = s.toLowerCase();
      const openStyle = lower.lastIndexOf('<style');
      const closeStyle = lower.lastIndexOf('</style>');
      if (openStyle > closeStyle) s = s.slice(0, openStyle);
      s = s.replace(/<script\b[\s\S]*?<\/script>/gi, '');
      s = s.replace(/<script\b[\s\S]*$/i, '');
      const lastLt = s.lastIndexOf('<');
      const lastGt = s.lastIndexOf('>');
      if (lastLt > lastGt) s = s.slice(0, lastLt);
      if (/<body\b/i.test(s) && !/<\/body>/i.test(s)) s += '</body>';
      if (/<html\b/i.test(s) && !/<\/html>/i.test(s)) s += '</html>';
      return s;
    }

    function _injectLivePreviewStyle(html) {
      const style = '<style data-thomas-live-preview>@keyframes tcCanvasChunkIn{from{opacity:.35;transform:translateY(3px)}to{opacity:1;transform:none}}html,body{min-height:100%;background:#fff}body>*{animation:tcCanvasChunkIn .28s ease both}svg path,svg line,svg polyline,svg polygon,svg rect,svg circle{transition:opacity .18s ease,transform .18s ease}</style>';
      if (/<\/head>/i.test(html)) return html.replace(/<\/head>/i, style + '</head>');
      if (/<body[^>]*>/i.test(html)) return html.replace(/(<body[^>]*>)/i, '$1' + style);
      return '<!DOCTYPE html><html><head>' + style + '</head><body style="margin:0;background:#fff;color:#1d2330;">' + html + '</body></html>';
    }

    function _livePreviewHtml(html, done) {
      const raw = _stripFence(html);
      if (done) return _injectReveal(raw || '<!DOCTYPE html><body style="margin:0;background:#fff"></body>');
      if (!raw.trim()) return _liveSourceShell('');
      const hasRenderableMarkup = /<body\b|<svg\b|<main\b|<section\b|<article\b|<div\b|<canvas\b/i.test(raw);
      if (!hasRenderableMarkup) return _liveSourceShell(raw);
      return _injectLivePreviewStyle(_closePartialHtml(raw));
    }

    // Live canvas worker: render the streaming HTML in an iframe srcdoc, growing as the
    // worker draws it (the watch-it-build effect). A finished artifact still wins.
    function canvasLiveHTML(html, done) {
      if (deps.canvasState.mode === 'render') return;
      const fresh = deps.canvasState.mode !== 'live';
      const written = fresh ? 0 : (deps.canvasState._written || 0);
      deps.canvasState = { mode: 'live', worker: deps.canvasState.worker || '', progress: '', url: '', name: 'Canvas', html: _stripFence(html), live: !done, _written: written, _fresh: fresh };
      if (!deps.state.artifactOpen) deps.openCanvas(); else deps.renderCanvas();
    }

    // Live document: render Thomas's directly-streamed content into the Canvas as a
    // real page, growing as he writes it. A worker handoff (building) or finished
    // artifact (render) always takes precedence over this.
    function canvasDocument(md) {
      if (deps.canvasState.mode === 'render' || deps.canvasState.mode === 'building' || deps.canvasState.mode === 'ended') return;
      deps.canvasState = { mode: 'document', worker: '', progress: '', url: '', name: 'Document', md: String(md || ''), live: true };
      if (!deps.state.artifactOpen) deps.openCanvas(); else deps.renderCanvas();
    }

    function canvasDocumentDone() {
      if (deps.canvasState.mode !== 'document') return;
      deps.canvasState.live = false;
      if (deps.state.artifactOpen) deps.renderCanvas();
    }
    return { _stripFence, _injectReveal, _staticDoc, _buildDeliver, canvasConstruct, _liveSourceShell, _closePartialHtml, _injectLivePreviewStyle, _livePreviewHtml, canvasLiveHTML, canvasDocument, canvasDocumentDone };
  }
  window.ThomasChatCanvasStream = { create };
})();
