/* Chat activity view. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // ---------- Artifact detection (mirrors _detectArtifact) ----------
    function detectArtifact(text) {
      const lc = text.toLowerCase();
      if (/\b(pdf|document|\bdoc\b|report|write[- ]?up|memo|brief|letter|note|draft)\b/.test(lc)) return { kind: 'pdf', title: 'Launch note', sub: 'PDF · 1 page', icon: 'ph-file-text' };
      if (/\b(chart|graph|plot|data|metrics|numbers|trend|stats|compare|breakdown)\b/.test(lc)) return { kind: 'chart', title: 'Weekly active by theme', sub: 'Chart · live', icon: 'ph-chart-bar' };
      if (/\b(draw|sketch|diagram|whiteboard|board|flow|map|explain|show me|visual|architecture|wireframe|how .* works)\b/.test(lc)) return { kind: 'board', title: 'How Thomas works', sub: 'Sketch · whiteboard', icon: 'ph-scribble-loop' };
      return null;
    }

    // Broader "this turn wants something on the Canvas" test: the artifact intents
    // above PLUS written content Thomas streams directly (recipe, essay, list…), so
    // we can render it live as he writes it — the real "watch it build" effect.
    // A VISUAL request (chart, design, drawing, UI) — these go to the canvas WORKER,
    // which makes a real visual. Thomas's chat text must NEVER stand in for one.
    function detectVisualIntent(text) {
      const lc = String(text).toLowerCase().replace(/\b(chart of accounts|graph (database|query|theory)|(medical|patient|astrology|birth) chart|plot (summary|of (the )?(story|book|movie)))\b/g, ' ');
      const visual = /\b((pie|bar|line|area|scatter|gantt|org(anizational)?) (chart|graph|plot)|chart|graph|plot|dashboard|histogram|heat ?map|timeline|mind ?map|flow ?chart|diagram|mock ?up|wireframe|infographic|poster|banner|logo|landing page|web ?page|ui (design|mockup)|illustration|drawing|picture|image|svg|playable (browser )?game|interactive (chart|graph|dashboard|site|app|visual))\b/, action = /\b(create|make|draw|sketch|design|paint|illustrate|render|visuali[sz]e|generate|build|show|display|present)\b/, leading = /^\s*((please|can you|could you)\s+)?(a |an |the )?(chart|graph|plot|dashboard|histogram|heat ?map|timeline|mind ?map|flow ?chart|diagram|mock ?up|wireframe|infographic|logo|poster|banner|landing page|illustration|drawing)\b/;
      return visual.test(lc) && (action.test(lc) || leading.test(lc));
    }

    function detectCanvasIntent(text) {
      if (detectArtifact(text)) return true;
      if (detectVisualIntent(text)) return true;
      const lc = String(text).toLowerCase();
      const verb = /\b(write|draft|compose|create|make|generate|build|design|put together|give me|outline|plan|list out|draw up|prepare|format)\b/;
      const noun = /\b(recipe|essay|letter|story|poem|poems|lyric|lyrics|song|list|plan|outline|guide|itinerary|schedule|agenda|table|article|post|blog|script|screenplay|instructions|steps|checklist|tutorial|walkthrough|summary|report|resume|cv|cover letter|email|template|menu|workout|routine|playbook|spec|readme|paragraph|paragraphs|write[- ]?up|document|doc)\b/;
      return verb.test(lc) && noun.test(lc);
    }


    // ---------- Activity: thinking, tools, and the REAL handoff (delegation events) ----------
    // ONE consolidated, expandable activity card per turn. Header = current
    // "Handed off to <worker>" + the action underneath + status; the ▾ caret
    // drops down the full step log (handoffs as bold milestones, tools/progress
    // as smaller lines, reasoning at the bottom). Steps update in place — never
    // duplicate bubbles.
    function _handoffStep(a, id) { return a.steps.find(s => s.kind === 'handoff' && s.id === id); }

    // "12s", "3m 48s", "1h 04m" — short, and always moving.
    function elapsedLabel(ms) {
      const total = Math.max(0, Math.round(Number(ms || 0) / 1000));
      if (total < 60) return total + 's';
      const m = Math.floor(total / 60), s = total % 60;
      if (m < 60) return m + 'm ' + String(s).padStart(2, '0') + 's';
      return Math.floor(m / 60) + 'h ' + String(m % 60).padStart(2, '0') + 'm';
    }

    function activityHTML(m) {
      const a = m.activity; if (!a) return '';
      const streaming = m.streaming, hasReply = !!(m.text && m.text.trim());
      const thinking = (a.thinking || '').trim();
      const steps = a.steps || [];
      if (!steps.length) {
        // While thinking with no reply yet, the bubble's big dots ARE the indicator —
        // no separate "Thinking…" label. Once a reply exists, the reasoning is
        // available as a collapsed "Thought process".
        if (!thinking || (streaming && !hasReply)) return '';
        return _thinkingCard(a, thinking, false);
      }
      const anyRunning = steps.some(s => s.status === 'running');
      const anyCancelled = a.cancelled || steps.some(s => s.status === 'cancelled');
      const anyFailed = steps.some(s => s.status === 'failed');
      const overall = anyRunning ? '' : anyCancelled ? 'Cancelled' : anyFailed ? 'Failed' : 'Done';
      const overallColor = anyFailed ? '#ff7a7a' : anyCancelled ? 'var(--c-muted)' : 'var(--c-accent)';
      const handoffSteps = steps.filter(s => s.kind === 'handoff');
      const primary = handoffSteps.length ? handoffSteps[handoffSteps.length - 1] : null;
      const groupSize = Math.max(handoffSteps.length, Number(a.expectedHandoffCount || 0));
      const grouped = groupSize > 1;
      const completedWorkers = handoffSteps.filter(s => s.status === 'completed').length;
      const failedWorkers = handoffSteps.filter(s => s.status === 'failed' || s.status === 'cancelled').length;
      // Thomas-first framing: the header reads like Thomas is doing the work
      // (he is — the crew is his, not a separate "task manager" the user must
      // think about). Worker attribution lives in the expanded step detail.
      const title = grouped
        ? (completedWorkers === groupSize ? `Done — ${groupSize} results` : anyRunning ? `Working on ${groupSize} things` : `${completedWorkers} of ${groupSize} done`)
        : (anyRunning ? 'On it — working on this' : anyFailed ? 'Ran into a problem' : anyCancelled ? 'Stopped' : 'Done');
      const latest = steps[steps.length - 1];
      // How long this has been going. A real run can sit on one status line for
      // minutes -- one chart here spent 3m 48s on "Planning the design…" while
      // emitting 1,926 events nobody surfaced -- and a frozen sentence with no
      // clock is indistinguishable from a hang. The owner reasonably gave up on
      // work that then finished. The elapsed figure is the cheapest honest
      // signal available: it always moves, even when nothing else does.
      if (anyRunning && !a.startedAt) a.startedAt = Date.now();
      const elapsed = (anyRunning && a.startedAt) ? elapsedLabel(Date.now() - a.startedAt) : '';
      // The header's second line is the task's STATUS, and only that. It used to
      // reach into the recorded history for the newest line instead, from before
      // the updates panel existed and the header was the only place that line
      // could appear. The panel now sits directly beneath this header on a
      // COLLAPSED card and heads the very same line "Latest recorded update", so
      // reading it up here printed it twice — once ellipsised at 280px, once in
      // full immediately below. And fetchActivityDetail prefixes each merged line
      // with "[worker] " so a card's several handoffs can be told apart, while
      // this header is deliberately worker-free ("attribution lives in the
      // expanded step detail"), so a multi-handoff card leaked that bracket tag
      // into the one line it shows — the same internal marker progressLabel and
      // _card_step_summary strip everywhere else.
      const current = grouped
        ? (anyRunning ? `${completedWorkers + failedWorkers} of ${groupSize} finished` : (failedWorkers ? `${completedWorkers} completed, ${failedWorkers} failed` : ''))
        : ((primary && primary.label) || (latest && latest.label) || '');
      // Card fits its content (left-aligned, not full width). One status indicator;
      // a Cancel (✕) button appears while the task is still running.
      let html = `<div style="align-self:flex-start;width:fit-content;max-width:min(480px, 100%);box-sizing:border-box;border:1px solid var(--c-accent-line);border-radius:12px;background:var(--c-accent-soft);overflow:hidden;">
        <div data-act-toggle style="display:flex;align-items:center;gap:10px;padding:9px 11px;cursor:pointer;">
          <span style="width:28px;height:28px;border-radius:8px;background:var(--c-accent);color:var(--c-accent-ink);display:grid;place-items:center;flex:0 0 auto;"><i class="ph ph-arrow-bend-down-right" style="font-size:15px;"></i></span>
          <span style="min-width:0;flex:1;display:flex;flex-direction:column;gap:1px;">
            <span style="font-size:13px;font-weight:700;overflow-wrap:anywhere;">${title}${elapsed ? `<span data-act-elapsed data-started="${a.startedAt}" style="font-weight:600;color:var(--c-muted);font-size:11.5px;margin-left:7px;font-variant-numeric:tabular-nums;">${elapsed}</span>` : ''}</span>
            ${current ? `<span style="font-size:11px;color:var(--c-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:280px;">${deps.esc(deps.deMd(current))}</span>` : ''}
          </span>
          <span style="flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;font-size:11.5px;font-weight:600;color:${overallColor};">${anyRunning ? '<i class="ph ph-circle-notch" style="animation:tc-spin 1s linear infinite;font-size:14px;color:var(--c-dim);"></i>' : overall}</span>
          ${anyRunning ? `<button data-act-cancel aria-label="${a.cancelling ? 'Cancelling task' : 'Cancel task'}" title="${a.cancelling ? 'Cancelling task' : 'Cancel task'}" ${a.cancelling ? 'disabled' : ''} style="flex:0 0 auto;width:22px;height:22px;border-radius:6px;border:1px solid var(--c-border-2);background:transparent;color:var(--c-muted);display:grid;place-items:center;cursor:${a.cancelling ? 'wait' : 'pointer'};padding:0;"><i class="ph ${a.cancelling ? 'ph-circle-notch' : 'ph-x'}" style="font-size:12px;${a.cancelling ? 'animation:tc-spin 1s linear infinite;' : ''}"></i></button>` : ''}
          <i class="ph ph-caret-${a.expanded ? 'up' : 'down'}" style="font-size:13px;color:var(--c-muted);flex:0 0 auto;"></i>
        </div>
        ${primary?.buildId ? `<button type="button" data-open-build="${deps.esc(primary.buildId)}" style="margin:0 12px 10px;padding:7px 11px;border:1px solid var(--c-accent-line);border-radius:8px;background:var(--c-surface);color:var(--c-accent);font:600 12px var(--font-sans);cursor:pointer;">Open in Build <i class="ph ph-arrow-up-right"></i></button>` : ''}
        ${_updatesPanelStep(a) ? _taskUpdatesSection(a) : ''}
        ${a.cancelError ? `<div role="alert" style="padding:0 12px 9px;color:var(--c-danger, #ff9a9a);font-size:11.5px;">${deps.esc(a.cancelError)}</div>` : ''}
        <div style="display:${a.expanded ? 'block' : 'none'};padding:4px 12px 11px;border-top:1px solid var(--c-border);">${_stepsLog(steps, thinking)}${_activityDetail(a)}</div>
      </div>`;
      // The completion bubble presents the artifact; don't duplicate it here.
      if (!a.artifactMovedToAnnouncement) html += artifactHTML(a);
      html += window.ThomasChatTurnFlow.partialArtifactsHTML(a, deps.esc);
      return html;
    }

    // Inline document preview: a mini first-page thumbnail; click to render the
    // PDF right inside the chat (no new tab). Non-PDF falls back to an open chip.
    function artifactDownloadUrl(url) {
      const value = String(url || '');
      return value + (value.includes('?') ? '&' : '?') + 'download=1';
    }

    function artifactHTML(a) {
      const many = Array.isArray(a.artifacts) ? a.artifacts.filter(art => art && (art.url || art.name)) : [];
      if (many.length > 1) {
        return `<div style="margin-top:8px;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c-muted);">${many.length} verified deliverables</div><div data-artifact-list style="display:flex;flex-direction:column;gap:7px;margin-top:7px;width:100%;max-width:420px;">${many.map((art, index) => {
          const name = String(art.name || art.path || ('Deliverable ' + (index + 1)));
          const url = String(art.url || '');
          const icon = String(art.kind || '') === 'web' ? 'ph-browser' : String(art.kind || '') === 'image' ? 'ph-image' : 'ph-file-text';
          return `<div style="display:flex;align-items:stretch;gap:7px;"><button type="button" data-artifact-open="${index}" data-artifact-url="${deps.esc(url)}" data-artifact-name="${deps.esc(name)}" data-artifact-kind="${deps.esc(String(art.kind || ''))}" ${url ? '' : 'disabled'} style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;padding:10px 12px;border:1px solid var(--c-border-2);border-radius:11px;background:var(--c-surface);color:var(--c-text);font-family:inherit;text-align:left;cursor:${url ? 'pointer' : 'default'};opacity:${url ? '1' : '.72'};"><span style="width:30px;height:30px;border-radius:8px;background:var(--c-accent-soft);color:var(--c-accent);display:grid;place-items:center;flex:0 0 auto;"><i class="ph ${icon}" style="font-size:16px;"></i></span><span style="min-width:0;flex:1;"><span style="display:block;font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${deps.esc(name)}</span><span style="display:block;margin-top:2px;font-size:11px;color:var(--c-muted);">${url ? 'Open verified result' : 'Verified result recorded'}</span></span>${url ? '<i class="ph ph-arrow-right" style="font-size:14px;color:var(--c-muted);"></i>' : ''}</button>${url ? `<a data-artifact-download href="${deps.esc(artifactDownloadUrl(url))}" download="${deps.esc(name)}" title="Download ${deps.esc(name)}" style="display:grid;place-items:center;width:42px;border:1px solid var(--c-border-2);border-radius:11px;background:var(--c-surface);color:var(--c-accent);text-decoration:none;"><i class="ph ph-download-simple" style="font-size:17px;"></i><span class="sr-only">Download ${deps.esc(name)}</span></a>` : ''}</div>`;
        }).join('')}</div>`;
      }
      const art = a.artifact; if (!art || !(art.url || art.name)) return '';
      const media = window.ThomasMediaGeneration.renderArtifact(art, deps.esc); if (media) return media;
      const url = art.url || '', name = art.name || 'document';
      // No URL → just show the name (nothing to open). With a URL → ALWAYS render
      // the inline preview (click expands it in-chat, never a new tab).
      if (!url) {
        return `<span style="display:inline-flex;align-items:center;gap:8px;margin-top:8px;padding:8px 12px;border:1px solid var(--c-border-2);border-radius:10px;background:var(--c-surface);color:var(--c-text);font-size:12.5px;width:max-content;"><i class="ph ph-file-text" style="color:var(--c-accent);font-size:15px;"></i> ${deps.esc(name)}</span>`;
      }
      if (deps._isTextArtifact(art.kind, url, name)) {
        return `<div style="display:flex;align-items:stretch;gap:7px;margin-top:8px;width:100%;max-width:390px;"><button type="button" data-artifact-open="0" data-artifact-url="${deps.esc(url)}" data-artifact-name="${deps.esc(name)}" data-artifact-kind="${deps.esc(String(art.kind || ''))}" style="display:flex;align-items:center;gap:10px;min-width:0;flex:1;padding:11px 13px;border:1px solid var(--c-border-2);border-radius:12px;background:var(--c-surface);color:var(--c-text);cursor:pointer;text-align:left;font-family:inherit;"><i class="ph ph-file-text" style="color:var(--c-accent);font-size:17px;"></i><span style="flex:1;min-width:0;"><span style="display:block;font-size:13px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${deps.esc(name)}</span><span style="display:block;margin-top:2px;font-size:11.5px;color:var(--c-muted);">Preview</span></span><i class="ph ph-arrow-right" style="font-size:14px;color:var(--c-muted);"></i></button><a data-artifact-download href="${deps.esc(artifactDownloadUrl(url))}" download="${deps.esc(name)}" title="Download ${deps.esc(name)}" style="display:grid;place-items:center;width:42px;border:1px solid var(--c-border-2);border-radius:12px;background:var(--c-surface);color:var(--c-accent);text-decoration:none;"><i class="ph ph-download-simple" style="font-size:17px;"></i><span class="sr-only">Download ${deps.esc(name)}</span></a></div>`;
      }
      const src = url + '#toolbar=0&navpanes=0&view=FitH';
      if (a.artifactOpen) {
        return `<div style="margin-top:8px;border:1px solid var(--c-border-2);border-radius:12px;overflow:hidden;background:var(--c-surface);width:100%;max-width:560px;">
          <div style="display:flex;align-items:center;gap:8px;padding:8px 11px;border-bottom:1px solid var(--c-border);">
            <i class="ph ph-file-text" style="color:var(--c-accent);font-size:15px;flex:0 0 auto;"></i>
            <span style="flex:1;min-width:0;font-size:12.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${deps.esc(name)}</span>
            <a data-artifact-download href="${deps.esc(artifactDownloadUrl(url))}" download="${deps.esc(name)}" title="Download ${deps.esc(name)}" style="color:var(--c-accent);display:flex;"><i class="ph ph-download-simple" style="font-size:14px;"></i><span class="sr-only">Download ${deps.esc(name)}</span></a>
            <a href="${deps.esc(url)}" target="_blank" rel="noopener" title="Open in new tab" style="color:var(--c-muted);display:flex;"><i class="ph ph-arrow-square-out" style="font-size:14px;"></i></a>
            <button data-artifact-toggle title="Collapse" style="border:0;background:transparent;color:var(--c-muted);cursor:pointer;display:flex;padding:0;"><i class="ph ph-caret-up" style="font-size:14px;"></i></button>
          </div>
          <!-- Deliberately NOT sandboxed, unlike the library previews. These
               frames show whatever the deliverable is, and most of them are
               PDFs; Chrome refuses to instantiate its PDF viewer inside a
               sandboxed frame, so the attribute renders a blank white box
               instead of the document (measured side by side). Containment
               here comes from the response: the preview is served from its own
               ephemeral origin under a CSP carrying sandbox, connect-src self
               and frame-ancestors. The library frames can carry the attribute
               because they only ever point at HTML. -->
          <iframe src="${deps.esc(src)}" title="${deps.esc(name)}" style="display:block;width:100%;height:600px;border:0;background:#fff;"></iframe>
        </div>`;
      }
      return `<div style="display:flex;align-items:stretch;gap:7px;margin-top:8px;width:100%;max-width:390px;"><button data-artifact-toggle title="Preview ${deps.esc(name)}" style="display:flex;align-items:stretch;min-width:0;flex:1;border:1px solid var(--c-border-2);border-radius:12px;overflow:hidden;background:var(--c-surface);cursor:pointer;text-align:left;font-family:inherit;padding:0;">
        <span style="position:relative;width:86px;height:96px;flex:0 0 auto;background:#fff;overflow:hidden;border-right:1px solid var(--c-border);">
          <iframe src="${deps.esc(src)}" tabindex="-1" aria-hidden="true" scrolling="no" style="position:absolute;top:0;left:0;width:245px;height:317px;border:0;transform:scale(0.351);transform-origin:top left;pointer-events:none;"></iframe>
        </span>
        <span style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:4px;padding:0 13px;">
          <span style="display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:var(--c-text);min-width:0;"><i class="ph ph-file-text" style="color:var(--c-accent);font-size:15px;flex:0 0 auto;"></i> <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${deps.esc(name)}</span></span>
          <span style="font-size:11.5px;color:var(--c-muted);">Click to preview in chat</span>
        </span>
      </button><a data-artifact-download href="${deps.esc(artifactDownloadUrl(url))}" download="${deps.esc(name)}" title="Download ${deps.esc(name)}" style="display:grid;place-items:center;width:42px;border:1px solid var(--c-border-2);border-radius:12px;background:var(--c-surface);color:var(--c-accent);text-decoration:none;"><i class="ph ph-download-simple" style="font-size:17px;"></i><span class="sr-only">Download ${deps.esc(name)}</span></a></div>`;
    }

    function _thinkingCard(a, thinking, live) {
      return `<div style="border:1px solid var(--c-border);border-radius:10px;background:var(--c-surface);overflow:hidden;width:100%;max-width:560px;">
        <button data-act-toggle style="width:100%;display:flex;align-items:center;gap:8px;padding:8px 11px;border:0;background:transparent;color:var(--c-dim);font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer;">
          <i class="ph ph-brain" style="font-size:14px;color:var(--c-accent);${live ? 'animation:tc-twinkle 1.4s ease-in-out infinite;' : ''}"></i> ${live ? 'Thinking&hellip;' : 'Thought process'} <i class="ph ph-caret-${a.expanded ? 'up' : 'down'}" style="margin-left:auto;font-size:12px;"></i>
        </button>
        <div style="display:${a.expanded ? 'block' : 'none'};padding:10px 12px 11px;font-size:12.5px;color:var(--c-dim);line-height:1.6;white-space:pre-wrap;border-top:1px solid var(--c-border);">${deps.esc(thinking)}</div>
      </div>`;
    }

    function _stepsLog(steps, thinking) {
      const statusWord = (st) => st === 'running' ? 'working' : st === 'failed' ? 'failed' : st === 'cancelled' ? 'cancelled' : 'done';
      const statusCol = (st) => st === 'failed' ? '#ff7a7a' : st === 'cancelled' ? 'var(--c-muted)' : st === 'running' ? 'var(--c-dim)' : 'var(--c-accent)';
      // With a SINGLE handoff the card header already reads "Handed off to
      // <worker>" + latest action — repeating the same milestone inside the
      // expanded log looked like a duplicated task card. Only multi-worker
      // logs need the per-worker milestone rows.
      const soleHandoff = steps.filter(s => s.kind === 'handoff').length === 1;
      let h = '';
      steps.forEach(s => {
        if (s.kind === 'handoff') {
          if (soleHandoff) return;
          // big milestone — no spinner here (the header carries the one spinner)
          h += `<div style="display:flex;align-items:center;gap:8px;padding:8px 0 2px;font-size:13px;">
            <i class="ph ph-arrow-bend-down-right" style="color:var(--c-accent);font-size:15px;flex:0 0 auto;"></i>
            <span style="font-weight:700;flex:1;min-width:0;">Handed off to ${deps.esc(s.worker || 'a worker')}</span>
            <span style="font-size:11px;color:${statusCol(s.status)};flex:0 0 auto;">${statusWord(s.status)}</span>
          </div>`;
          if (s.label) h += `<div style="font-size:11.5px;color:var(--c-muted);padding:0 0 4px 23px;line-height:1.5;">${deps.esc(deps.deMd(s.label))}</div>`;
        } else if (s.kind === 'tool') {
          h += `<div style="display:flex;align-items:center;gap:8px;padding:4px 0 4px 4px;font-size:12.5px;color:var(--c-dim);">
            <span style="width:5px;height:5px;border-radius:50%;background:${statusCol(s.status)};flex:0 0 auto;"></span> <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${deps.esc(deps.deMd(s.label))}</span> <span style="font-size:11px;color:${statusCol(s.status)};flex:0 0 auto;">${statusWord(s.status)}</span>
          </div>`;
        } else {
          h += `<div style="display:flex;align-items:center;gap:8px;padding:4px 0 4px 4px;font-size:12.5px;color:var(--c-dim);"><span style="width:5px;height:5px;border-radius:50%;background:var(--c-muted);flex:0 0 auto;"></span> ${deps.esc(deps.deMd(s.label))}</div>`;
        }
      });
      if (thinking) h += `<div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--c-border);font-size:12px;color:var(--c-dim);line-height:1.55;white-space:pre-wrap;"><i class="ph ph-brain" style="color:var(--c-accent);"></i> ${deps.esc(thinking)}</div>`;
      return h;
    }

    function _fmtStepTime(at) {
      if (!at) return '';
      const t = Date.parse(at); if (isNaN(t)) return '';
      const d = new Date(t);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    // Which delegation this card reads its recorded history from — the last
    // handoff with a real execution id. EVERY dispatched task records
    // transitions[] (thomas/core/task_bot_runtime.py writes one per state,
    // summary or blocker change), so the updates panel is not a Thomas-project
    // feature: gating it on buildId left an ordinary worker card showing one
    // status sentence with its whole recorded history sitting unread behind
    // /detail. _activityDetail checks the same thing so history is never
    // printed twice on one card.
    function _updatesPanelStep(a) {
      const handoffs = (a.steps || []).filter(s => s && s.kind === 'handoff' && s.id);
      return handoffs.length ? handoffs[handoffs.length - 1] : null;
    }

    // The recorded history for a task card. Collapsed it shows the latest few
    // updates; expanded it shows the whole run. A list permanently capped at
    // four reads as "basic" exactly when a long task has the most to say, and
    // the only way on to the rest was leaving Chat for Build.
    //
    // Every line here is durable text the server recorded, never inferred: the
    // state and blocker come from the transition itself, so a step that failed
    // says so and says why instead of sitting in the list looking like progress
    // — and a step where the reader stopped the run says only that.
    function _taskUpdatesSection(a) {
      const all = Array.isArray(a.timeline) ? a.timeline : [];
      // Where these lines came from, said only where it is true: a Thomas
      // project's history is readable in Build, a worker's is not. A card can
      // carry SEVERAL handoffs and this list is their merged history
      // (fetchActivityDetail reads every handoff with an id and tags each line
      // with its worker), so "one of them was a Build run" is not enough to
      // head the whole list "Recorded in Build" — on a mixed card that claimed
      // a home in Build for worker lines that were never there, and the card's
      // "Open in Build" button follows the LAST handoff, so it need not even be
      // offered. Every source has to be a Build run for the label to be true.
      const sources = (a.steps || []).filter(s => s && s.kind === 'handoff' && s.id);
      const fromBuild = sources.length > 0 && sources.every(s => s.buildId);
      const source = fromBuild ? 'Recorded in Build' : 'Recorded as it happened';
      // "Waiting" is a promise, and it is only true while the task is still
      // running. A settled task with an empty history has nothing more coming,
      // so a card that keeps saying "waiting for the first update" is inventing
      // a status — the exact failure this panel exists to end.
      const running = (a.steps || []).some(s => s && s.kind === 'handoff' && s.status === 'running');
      const waiting = !running
        ? 'No updates were recorded before this task finished; the status above is what there is.'
        : fromBuild ? 'Waiting for recorded updates from Build.' : 'Waiting for the first recorded update.';
      // An empty ARRAY is a read that came back with nothing. No array at all is
      // a read that has not happened yet: the card paints before renderActivity
      // issues its /detail request, so an unread card announcing "no updates
      // were recorded before this task finished" states the answer to a
      // question it has not asked — false for the whole width of the round
      // trip, on every revisit of a finished task, and then replaced by the
      // history it just denied.
      const read = Array.isArray(a.timeline);
      // A read in flight outranks the verdict of the one before it. After a
      // failed read the card still has no timeline, so "not read yet" cannot
      // stand in for "reading now" — otherwise a retry repaints to the same
      // "temporarily unavailable" it was sent to clear, and looks dead.
      const reading = !!a.detailLoading || (!read && !a.detailUnavailable && !a.detailMissing);
      const empty = a.detailMissing
        ? 'No recorded history is kept for this task; the status above is what there is.'
        : reading ? 'Reading the recorded history…'
        : a.detailUnavailable ? 'Task history is temporarily unavailable; the current status is still shown above.'
        // A read that reached some of the card's sources and not others cannot
        // fall back to "no updates were recorded before this task finished" —
        // the part that went unread is exactly where those updates would be.
        : a.detailPartial ? 'Some of this task’s history could not be read; no updates came back from the rest.'
        : waiting;
      // "Temporarily" is only true if something tries again. The delegation
      // poll is the sole automatic retry and it runs solely while a task is
      // running, so on a SETTLED card that word was a promise nothing kept
      // unless the reader happened to guess the card header was clickable. A
      // part-read card needs the same control for the same reason.
      const retry = (a.detailUnavailable || a.detailPartial) && !a.detailMissing && !reading
        ? `<button type="button" data-act-retry-detail style="display:block;margin-top:6px;padding:0;border:0;background:transparent;color:var(--c-accent);font:600 10.5px var(--font-sans);text-align:left;cursor:pointer;">Try again</button>`
        : '';
      // The same three states for a card that already has history below the
      // notice. A read in flight has to say so here too: otherwise "Try again"
      // removes itself and nothing else on screen changes. Only a card in
      // trouble carries a notice at all — a healthy one refreshes every few
      // seconds and would flash this on every poll.
      const notice = (a.detailUnavailable || a.detailMissing || a.detailPartial) && all.length
        ? a.detailMissing
          ? 'No task record is kept for this task any more; these are the updates already read.'
          : reading ? 'Checking for newer updates…'
          : a.detailUnavailable ? 'Latest task history is temporarily unavailable; showing recorded updates.'
          : 'Some of this task’s history could not be read; these are the updates that came back.'
        : '';
      // The card is rebuilt from innerHTML wholesale, and a RUNNING one is
      // rebuilt every three seconds, so these two lines are never updated in
      // place — they are new nodes on every paint. A live region that is
      // re-inserted is announced again, so an unchanged "Waiting for the first
      // recorded update." was read out to a screen reader every three seconds
      // for as long as the task ran, drowning the updates it was waiting for.
      // Announce a line only on the paint where what it says changed — and only
      // rendered text can have been announced. The empty line appears solely on
      // a card with no updates (the panel prints the history instead), so
      // recording `empty` as spoken on a card that never showed it silenced that
      // sentence on the paint where it first reached the screen: a task whose
      // history came back, then emptied, announced nothing at all.
      const spoken = (all.length ? '' : empty) + '\n' + notice;
      const announce = a.spokenUpdateStatus !== spoken ? ' role="status"' : '';
      a.spokenUpdateStatus = spoken;
      const shown = a.expanded ? all : all.slice(-4);
      const rows = shown.map((step, index) => {
        const latest = index === shown.length - 1;
        const state = String(step.state || '').toLowerCase();
        // A run the reader stopped is not a failure — the module that records it
        // says so ("Every Stop used to be recorded with fail_execution(...), so a
        // deliberate stop was indistinguishable from a crash"). It is recorded
        // with blocker="cancelled", which is why a stopped step must not take the
        // failure colour or the "Blocked:" line: the state already says stopped
        // and the summary already reads "Stopped by you."
        const stopped = state === 'cancelled' || state === 'canceled';
        const stalled = !stopped && (state === 'failed' || state === 'blocked' || !!String(step.blocker || '').trim());
        const label = latest ? 'Latest recorded update' : 'Earlier update';
        const ink = stalled ? 'var(--c-danger, #ff9a9a)' : stopped || !latest ? 'var(--c-muted)' : 'var(--c-accent)';
        const dot = stalled ? 'var(--c-danger, #ff9a9a)' : stopped || !latest ? 'var(--c-border-2)' : 'var(--c-accent)';
        return `<div style="display:flex;gap:9px;padding:8px 0;line-height:1.45;${index ? 'border-top:1px solid var(--c-border);' : ''}">
          <span aria-hidden="true" style="width:7px;height:7px;margin-top:5px;flex:0 0 7px;border-radius:50%;background:${dot};"></span>
          <div style="min-width:0;flex:1;">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline;">
              <span style="font-size:10px;font-weight:700;color:${ink};">${label}</span>
              ${step.at && _fmtStepTime(step.at) ? `<time style="font-size:10px;color:var(--c-muted);flex:0 0 auto;">${deps.esc(_fmtStepTime(step.at))}</time>` : ''}
            </div>
            <div style="font-size:12px;overflow-wrap:anywhere;color:var(--c-text);margin-top:2px;">${deps.esc(deps.deMd(step.summary || ''))}</div>
            ${stalled && String(step.blocker || '').trim() ? `<div style="font-size:11px;color:var(--c-danger, #ff9a9a);margin-top:3px;overflow-wrap:anywhere;">Blocked: ${deps.esc(step.blocker)}</div>` : ''}
          </div>
        </div>`;
      }).join('');
      // The panel scrolls, so it needs to be reachable by keyboard: without a
      // tab stop the updates past its height are pointer-only. With nothing to
      // scroll there is nothing to tab to, so the empty line takes tabindex="-1"
      // instead — not a tab stop, but somewhere renderActivity can put the
      // keyboard when the control it was on ("Try again") removes itself.
      return `<section ${all.length ? 'tabindex="0" ' : ''}style="margin:0 12px 10px;padding:10px 12px;border:1px solid var(--c-border);border-radius:9px;background:var(--c-surface);max-height:${a.expanded ? '420px' : '228px'};overflow-y:auto;min-width:0;" aria-label="Task updates">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:7px;">
          <strong style="font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--c-muted);">Task updates${all.length ? ` · ${all.length}` : ''}</strong>
          ${all.length ? `<span style="font-size:10px;color:var(--c-muted);">${source}</span>` : ''}
        </div>
        ${rows}
        ${!all.length ? `<div data-act-status tabindex="-1"${announce} style="font-size:11.5px;color:var(--c-muted);">${empty}</div>` : ''}
        ${all.length > shown.length ? `<button type="button" data-act-expand style="display:block;width:100%;margin-top:5px;padding:5px 0 0;border:0;border-top:1px solid var(--c-border);background:transparent;color:var(--c-accent);font:600 10.5px var(--font-sans);text-align:left;cursor:pointer;">Latest ${shown.length} of ${all.length} updates · Show all ${all.length}</button>` : ''}
        ${notice ? `<div${announce} style="font-size:11px;color:var(--c-muted);margin-top:5px;">${notice}</div>` : ''}
        ${retry}
      </section>`;
    }

    // The REAL "what the agent did" timeline (fetched per-execution) + a steer
    // box to jump in on a running agent. This is what the drawer shows on click.
    function _activityDetail(a) {
      let h = '';
      const tl = Array.isArray(a.timeline) ? a.timeline : [];
      // The updates panel above already carries the recorded history and its
      // own loading/unavailable states. Only a card without one falls back to
      // printing them down here.
      const panelled = !!_updatesPanelStep(a);
      if (a.detailLoading && !tl.length && !panelled) {
        h += `<div style="font-size:11.5px;color:var(--c-muted);padding:6px 0;">Loading what Thomas did…</div>`;
      } else if (a.detailUnavailable && !tl.length && !panelled) {
        h += `<div role="status" style="font-size:11.5px;color:var(--c-muted);padding:6px 0;">Task history is temporarily unavailable. The current status is still shown above.</div>`;
      } else if (tl.length && !panelled) {
        h += `<div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--c-border);">
          <div style="font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c-muted);margin-bottom:6px;">Step by step</div>
          ${tl.map(step => `<div style="display:flex;gap:8px;padding:3px 0;font-size:12px;color:var(--c-dim);line-height:1.5;">
            <span style="flex:0 0 auto;width:5px;height:5px;margin-top:6px;border-radius:50%;background:var(--c-accent);opacity:.7;"></span>
            <span style="flex:1;min-width:0;">${deps.esc(deps.deMd(step.summary || ''))}${step.blocker ? ` <span style="color:var(--c-danger, #ff9a9a);">(${deps.esc(step.blocker)})</span>` : ''}</span>
            ${step.at ? `<span style="flex:0 0 auto;font-size:10px;color:var(--c-muted);">${deps.esc(_fmtStepTime(step.at))}</span>` : ''}
          </div>`).join('')}
        </div>`;
      }
      const anyRunning = (a.steps || []).some(s => s.kind === 'handoff' && s.status === 'running');
      if (anyRunning) {
        // Named for what it does. "JUMP IN" over an empty box never said that
        // typing here changes the task already running instead of starting
        // another one — the same control on the Work card says so out loud.
        //
        // Value, busy state and note all come from the activity, never from the
        // live node: this card is repainted from state on every delegation poll,
        // so anything held only in the DOM was erased within a second.
        const busy = a.steerBusy === true;
        // Several of these cards can be on screen at once (a revisit restores a
        // card per row), so the label has to point at this card's own input
        // rather than at a shared id.
        const runningStep = (a.steps || []).find(s => s.kind === 'handoff' && s.status === 'running');
        const inputId = deps.esc('tc-steer-' + String((runningStep && runningStep.id) || 'task'));
        h += `<div style="margin-top:10px;padding-top:9px;border-top:1px dashed var(--c-border);">
          <label for="${inputId}" style="display:block;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c-muted);margin-bottom:6px;">Steer this running task</label>
          <form data-steer-form style="display:flex;gap:6px;">
            <input data-steer-input id="${inputId}" type="text" value="${deps.esc(a.steerDraft || '')}" ${busy ? 'disabled' : ''} placeholder="Tell Thomas what to change…" style="flex:1;min-width:0;padding:8px 10px;border:1px solid var(--c-border-2);border-radius:9px;background:var(--c-surface);color:var(--c-text);font:inherit;font-size:12.5px;">
            <button type="submit" ${busy ? 'disabled' : ''} style="flex:0 0 auto;padding:8px 12px;border:1px solid var(--c-accent-line);border-radius:9px;background:var(--c-accent-soft);color:var(--c-accent);font:600 12px var(--font-sans);cursor:${busy ? 'wait' : 'pointer'};">${busy ? 'Sending…' : 'Send update'}</button>
          </form>
          <small style="display:block;margin-top:5px;font-size:11px;color:var(--c-muted);">Applies to this running task, not a new one.</small>
          ${a.steerNote ? `<div ${a.steerFailed ? 'role="alert"' : 'role="status"'} style="margin-top:5px;font-size:11px;color:${a.steerFailed ? 'var(--c-danger, #ff9a9a)' : 'var(--c-muted)'};">${deps.esc(a.steerNote)}</div>` : ''}
        </div>`;
      }
      return h;
    }
    return { detectArtifact, detectVisualIntent, detectCanvasIntent, _handoffStep, elapsedLabel, activityHTML, artifactDownloadUrl, artifactHTML, _thinkingCard, _stepsLog, _fmtStepTime, _updatesPanelStep, _taskUpdatesSection, _activityDetail };
  }
  window.ThomasChatActivityView = { create };
})();
