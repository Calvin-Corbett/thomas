(function () {
  'use strict';

  let view = null;
  let setupMedium = '';
  let armedMedium = '';
  let starting = null, setupOwner = null, armedOwner = null;

  function captureOwner() {
    if (view?.captureConversation) return view.captureConversation();
    const conversation = view?.conversationToken?.();
    return () => !view?.conversationToken || view.conversationToken() === conversation;
  }
  const defaultPlaceholder = 'Message Thomas…  (try “draw how Thomas works” or “make a PDF”)';

  function renderArtifact(artifact, escape) {
    const kind = String(artifact.kind || '');
    const url = String(artifact.url || '');
    if (!['image', 'music', 'video'].includes(kind) || !url.startsWith('/deliverable/')) return '';
    const src = escape(url), name = escape(String(artifact.name || 'Generated media'));
    const player = kind === 'image' ? `<img src="${src}" alt="${name}">`
      : kind === 'music' ? `<audio controls preload="metadata" src="${src}"></audio>`
        : `<video controls preload="metadata" src="${src}"></video>`;
    return `<figure class="tc-media-deliverable">${player}<figcaption><span>${name}</span><a href="${src}${url.includes('?') ? '&amp;' : '?'}download=1" download>Download</a></figcaption></figure>`;
  }

  async function json(response) {
    const body = await response.json();
    if (!response.ok) {
      const failure = new Error(body.error || 'The media service could not complete that request.');
      failure.status = response.status;
      throw failure;
    }
    return body;
  }

  function setupDialog() {
    let dialog = document.getElementById('tc-media-setup');
    if (dialog) return dialog;
    dialog = document.createElement('div');
    dialog.id = 'tc-media-setup';
    dialog.className = 'tc-media-setup';
    dialog.hidden = true;
    dialog.innerHTML = '<div class="tc-media-card" role="dialog" aria-modal="true" aria-labelledby="tc-media-title">' +
      '<div class="tc-media-kicker">CREATE WITH THOMAS</div><h2 id="tc-media-title"></h2><p id="tc-media-copy"></p>' +
      '<div class="tc-media-options"><button type="button" data-media-provider="local"><i class="ph ph-desktop"></i><span><strong>Install and use the local model</strong><small>Runs privately on this PC. Thomas uses the cached model when it is already installed.</small></span></button>' +
      '<div class="tc-media-api"><label for="tc-media-key">Or connect an API provider</label><input id="tc-media-key" type="password" autocomplete="off" placeholder="Enter Hugging Face API key"><button type="button" data-media-provider="api"><i class="ph ph-key"></i>Save API connection</button></div></div>' +
      '<p class="tc-media-error" role="alert"></p><button type="button" class="tc-media-close">Cancel</button></div>';
    document.body.appendChild(dialog);
    dialog.querySelector('.tc-media-close').addEventListener('click', closeSetup);
    dialog.addEventListener('click', event => { if (event.target === dialog) closeSetup(); });
    dialog.querySelectorAll('[data-media-provider]').forEach(button => {
      button.addEventListener('click', () => { void configure(button.dataset.mediaProvider); });
    });
    return dialog;
  }

  function closeSetup() {
    const dialog = document.getElementById('tc-media-setup');
    if (dialog) dialog.hidden = true;
    setupOwner = null;
  }

  function openSetup(medium, owner = captureOwner()) {
    if (!owner() || !['image', 'video', 'music'].includes(medium)) return;
    setupMedium = medium; setupOwner = owner;
    const dialog = setupDialog();
    dialog.querySelector('#tc-media-title').textContent = 'Set up Create ' + medium;
    dialog.querySelector('#tc-media-copy').textContent = 'No ' + medium + ' lane is set up yet. Choose an API connection or the local model to continue.';
    dialog.querySelector('#tc-media-key').value = '';
    dialog.querySelector('.tc-media-error').textContent = '';
    dialog.hidden = false;
    dialog.querySelector('[data-media-provider="local"]').focus();
  }

  function renderArmed() {
    const input = document.getElementById('tc-input');
    const chip = document.getElementById('tc-media-lane-chip');
    if (!input || !chip) return;
    if (!armedMedium) {
      chip.hidden = true;
      chip.replaceChildren();
      // Disarming runs on every mode switch (syncDynamic resets the lane), so
      // put back the words of the mode on screen, not Chat's long hint.
      const modes = window.ThomasUnifiedModes;
      if (modes && typeof modes.mode === 'function' && modes.mode() !== 'chat' && modes.refreshChrome) modes.refreshChrome();
      else input.placeholder = defaultPlaceholder;
      return;
    }
    chip.hidden = false;
    chip.innerHTML = '<span>Create ' + armedMedium + '</span><button type="button" aria-label="Cancel Create ' + armedMedium + '"><i class="ph ph-x"></i></button>';
    chip.querySelector('button').addEventListener('click', disarm);
    input.placeholder = 'Describe the ' + armedMedium + ' you want to create';
  }

  function arm(medium) {
    armedOwner = captureOwner();
    if (!armedOwner()) return;
    armedMedium = medium;
    renderArmed();
    document.getElementById('tc-input')?.focus();
  }

  function disarm() {
    armedMedium = ''; armedOwner = null;
    renderArmed();
  }

  function submitArmed() {
    if (!armedMedium) return false;
    if (!armedOwner?.()) { disarm(); return false; }
    const medium = armedMedium;
    void create(medium);
    return true;
  }

  async function configure(provider) {
    const owner = setupOwner, medium = setupMedium;
    if (!owner?.()) return;
    const dialog = setupDialog();
    const key = dialog.querySelector('#tc-media-key').value.trim();
    const error = dialog.querySelector('.tc-media-error');
    if (provider === 'api' && !key) { error.textContent = 'Enter the API key first.'; return; }
    error.textContent = provider === 'local' ? 'Checking the local model…' : 'Saving the API connection…';
    try {
      await json(await fetch('/api/media/lanes/' + medium, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: provider, api_key: key }),
      }));
      if (!owner() || setupOwner !== owner) return;
      closeSetup();
      arm(medium);
      view.addAssistant((provider === 'local' ? 'The local model' : 'The API connection') + ' is ready for Create ' + medium + '. Describe what you want and press Enter or the arrow.');
    } catch (failure) { if (owner() && setupOwner === owner) error.textContent = failure.message || String(failure); }
  }

  async function poll(jobId, medium, message, sessionId, failures = 0) {
    try {
      const body = await json(await fetch('/api/media/jobs/' + encodeURIComponent(jobId), { cache: 'no-store' }));
      const job = body.job || {};
      if (['completed', 'failed'].includes(job.state)) {
        // The normal completion endpoint owns durable transcript writes. Keep
        // the original session even if the user has selected another chat.
        const announcement = await json(await fetch('/api/v2/chat/session/' + encodeURIComponent(sessionId) +
          '/delegations/' + encodeURIComponent(jobId) + '/announce', { method: 'POST' }));
        if (!announcement.ok || (!announcement.message && announcement.skipped !== 'already_reported')) {
          throw new Error('The result is awaiting its saved conversation receipt.');
        }
        if (announcement.message) {
          view.finish(message, announcement.message, job.deliverable, jobId, job.state);
          return;
        }
      }
      if (job.state === 'completed') {
        view.finish(message, 'Your ' + medium + ' is ready below and saved in Library.', job.deliverable, jobId, 'completed');
        return;
      }
      if (job.state === 'failed') {
        view.finish(message, 'The ' + medium + ' generation failed: ' + (job.error || 'The worker did not return a reason.'), null, jobId);
        return;
      }
      if (job.state === 'cancelled') {
        view.finish(message, 'The ' + medium + ' generation was interrupted before delivery.', null, '', 'cancelled');
        return;
      }
      if (job.state === 'unknown') {
        view.finish(message, 'I cannot verify this ' + medium + ' job: ' + (job.error || 'Its worker status is unavailable.'));
        return;
      }
      view.progress(message, (job.progress_text || ('Generating ' + medium + '…')) + (Number.isFinite(job.progress) ? ' · ' + job.progress + '%' : ''));
      window.setTimeout(() => { void poll(jobId, medium, message, sessionId); }, 1200);
    } catch (failure) {
      if ([400, 401, 403, 404].includes(failure.status)) {
        view.finish(message, 'I cannot retrieve the ' + medium + ' generation status: ' + failure.message);
        return;
      }
      view.progress(message, 'Reconnecting to ' + medium + ' generation status…');
      window.setTimeout(() => { void poll(jobId, medium, message, sessionId, failures + 1); },
        Math.min(30000, 1200 * Math.pow(2, Math.min(failures, 5))));
    }
  }

  async function create(medium, suppliedPrompt, options) {
    if (!view || !['image', 'video', 'music'].includes(medium) || (starting && starting.owns())) return;
    if (view.canCreate && !view.canCreate()) return;
    const operation = { owns: captureOwner() };
    const owns = operation.owns;
    if (!owns()) return;
    starting = operation;
    const opts = options || {};
    const prompt = String(suppliedPrompt || view.prompt(medium) || '').trim();
    let message = null;
    try {
      if (!prompt) { arm(medium); return; }
      const sessionId = view.ensureSession ? await view.ensureSession() : view.sessionId();
      if (!owns()) return;
      if (!sessionId) throw new Error('The conversation could not be saved. Please try again.');
      const lanes = (await json(await fetch('/api/media/lanes', { cache: 'no-store' }))).lanes || {};
      if (!owns() || (view.canCreate && !view.canCreate())) return;
      if (!lanes[medium] || !lanes[medium].configured) {
        view.addAssistant('No ' + medium + ' lane is set up yet. Choose an API connection or the local model to continue.');
        openSetup(medium, owns);
        return;
      }
      disarm();
      if (!opts.userAlreadyShown) view.addUser('Create ' + medium + ': ' + prompt);
      message = view.addAssistant('Starting ' + medium + ' generation in the background…', true);
      const started = await json(await fetch('/api/media/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          medium: medium,
          prompt: prompt,
          session_id: sessionId,
          user_message: String(opts.userMessage || ''),
        }),
      }));
      if (!started.job_id) throw new Error('The media service did not return a job reference.');
      view.started?.(message, started.job_id, medium);
      if (owns()) view.consumePrompt?.(prompt);
      void poll(started.job_id, medium, message, sessionId);
    } catch (failure) {
      const text = 'Create ' + medium + ' could not start: ' + (failure.message || String(failure));
      if (message) view.finish(message, text);
      else if (owns()) view.addAssistant(text);
    } finally {
      if (starting === operation) starting = null;
    }
  }

  document.addEventListener('keydown', event => {
    const dialog = document.getElementById('tc-media-setup');
    if (event.key === 'Escape' && dialog && !dialog.hidden) { event.preventDefault(); closeSetup(); }
    else if (event.key === 'Escape' && armedMedium) { event.preventDefault(); disarm(); }
  });

  window.ThomasMediaGeneration = {
    renderArtifact,
    init(adapter) {
      view = adapter;
      const input = document.getElementById('tc-input');
      const send = document.getElementById('tc-send');
      input?.addEventListener('keydown', event => {
        if (armedMedium && !view.isStopAction?.() && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.stopImmediatePropagation(); submitArmed(); }
      }, true);
      send?.addEventListener('click', event => {
        if (armedMedium && !view.isStopAction?.()) { event.preventDefault(); event.stopImmediatePropagation(); submitArmed(); }
      }, true);
      renderArmed();
    },
    create: create,
    openSetup: openSetup,
    armedMedium: () => armedMedium,
    cancel: disarm,
    resetContext() { starting = null; closeSetup(); disarm(); },
  };
})();
