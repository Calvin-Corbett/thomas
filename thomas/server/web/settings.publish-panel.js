/* Settings > Publish to GitHub: look at what would go public, then send a review copy to GitHub.

   Opening the page asks the server nothing. A button starts the preview, which takes a few minutes, so the page asks
   again every three seconds while it works and stops the moment it has an answer. A server that answers 404 has this
   turned off, and the page says so once and never asks again until you press a button. Every word is set as text.
*/
(function publishPanel() {
  'use strict';

  const PREVIEW = '/api/public-release/preview';
  const PUBLISH = '/api/public-release/publish';
  const EVERY = 3000;
  const HEADERS = { Accept: 'application/json', 'Content-Type': 'application/json' };
  const WORDS = {
    look: 'Look at what would go public',
    again: 'Look again',
    working: 'Working on it. This takes a few minutes, and nothing is being sent.',
    heading: 'What would go public',
    send: 'Publish a review copy to GitHub',
    notSafe: 'Not safe to publish yet. Fix the red items first.',
    signIn: 'Sign in with Windows to go on. Nothing is sent until you do.',
    off: 'Publishing is turned off. Turn Publish to GitHub back on in Plugins to use this page.',
    gone: 'Thomas could not be reached. Try again.',
    reload: 'This preview is no longer the one on the server. Look again.',
  };

  let host = null;
  let timer = null;
  let current = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(label, className, onClick) {
    const node = el('button', className, label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }

  function show(...parts) {
    host.replaceChildren(...parts);
  }

  function plural(count, one, many) {
    return `${count} ${count === 1 ? one : many}`;
  }

  function note(text, tone) {
    const node = el('div', 'publish-note', text);
    if (tone) node.dataset.tone = tone;
    node.setAttribute('role', 'status');
    return node;
  }

  async function ask(url, options) {
    try {
      const answer = await fetch(url, options);
      let body = {};
      try {
        body = await answer.json();
      } catch (error) {
        body = {};
      }
      return { status: answer.status, body };
    } catch (error) {
      return { status: 0, body: {} };
    }
  }

  function stopWatching() {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  function start() {
    stopWatching();
    show(note(WORDS.working));
    ask(`${PREVIEW}?fresh=1`, { headers: HEADERS }).then(handle);
  }

  function handle({ status, body }) {
    stopWatching();
    if (status === 404) return show(note(WORDS.off, 'warn'), button(WORDS.look, 'btn btn-secondary', start));
    if (status === 0) return show(note(WORDS.gone, 'bad'), button(WORDS.look, 'btn btn-secondary', start));
    if (body.state === 'working') {
      show(note(WORDS.working));
      timer = setTimeout(poll, EVERY);
      return undefined;
    }
    if (body.state === 'ready' && body.preview) return paint(body.preview);
    return show(note(body.message || WORDS.gone, 'bad'), button(WORDS.look, 'btn btn-secondary', start));
  }

  function poll() {
    ask(PREVIEW, { headers: HEADERS }).then(handle);
  }

  function reasons(removed) {
    const counts = new Map();
    Object.values(removed || {}).forEach((why) => counts.set(why, (counts.get(why) || 0) + 1));
    const list = el('ul', 'publish-removed');
    counts.forEach((count, why) => list.append(el('li', '', `${count} × ${why}`)));
    return list;
  }

  function checks(list) {
    const box = el('ul', 'publish-checks');
    list.forEach((check) => {
      const row = el('li', check.ok ? 'publish-check is-ok' : 'publish-check is-bad');
      row.append(el('span', 'publish-tick', check.ok ? '✓' : '✗'), el('strong', '', ` ${check.name}: `));
      row.append(el('span', '', check.reason));
      box.append(row);
    });
    return box;
  }

  function paint(preview) {
    current = preview;
    const where = preview.branch
      ? `Where it goes: ${preview.remote_url}, as the branch ${preview.branch}. The main branch is not changed.`
      : 'No public repository is named, so nothing can be sent.';
    const parts = [
      el('h3', 'publish-heading', WORDS.heading),
      el('p', '', `Version ${preview.version}: ${plural(preview.files, 'file', 'files')} would go public.`),
      el('p', '', `${plural(Object.keys(preview.removed || {}).length, 'private file is', 'private files are')} left out:`),
      reasons(preview.removed),
    ];
    if (preview.changed !== null && preview.changed !== undefined) {
      parts.push(el('p', '', `${plural(preview.changed, 'file differs', 'files differ')} from the public copy now.`));
    }
    parts.push(el('p', '', where), checks(preview.checks || []));
    const send = button(WORDS.send, 'btn btn-primary publish-send', () => publish(send));
    send.disabled = !preview.safe_to_publish;
    parts.push(send);
    parts.push(preview.safe_to_publish ? note(WORDS.signIn) : note(WORDS.notSafe, 'bad'));
    parts.push(button(WORDS.again, 'btn btn-secondary', start));
    show(...parts);
  }

  async function publish(send) {
    send.disabled = true;
    const result = await ask(PUBLISH, {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ preview_digest: current.digest }),
    });
    if (result.status === 404) return show(note(WORDS.off, 'warn'), button(WORDS.look, 'btn btn-secondary', start));
    const body = result.body || {};
    const lines = (body.lines || []).map((line) => el('p', '', line));
    if (result.status === 200 && body.ok) {
      const done = [note(`Sent to the branch ${body.branch}.`, 'ok'), ...lines];
      if (body.branch_url) {
        const link = el('a', 'publish-link', 'Open the branch on GitHub');
        link.href = body.branch_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        done.push(link);
      }
      return show(...done);
    }
    if (result.status === 0) return show(note(WORDS.gone, 'bad'), button(WORDS.look, 'btn btn-secondary', start));
    const why = lines.length ? lines : [note(WORDS.reload, 'bad')];
    return show(...why, button(WORDS.look, 'btn btn-secondary', start));
  }

  function init() {
    host = document.getElementById('publishHost');
    if (!host) return;
    show(button(WORDS.look, 'btn btn-primary', start));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
}());
