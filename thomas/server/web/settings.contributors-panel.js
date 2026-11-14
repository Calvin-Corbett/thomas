/* Settings > Contributors: how many changes to this copy of Thomas were made by Thomas, Claude, Codex and you.

   The numbers come from GET /api/contributors, which only reads the record of changes. This page asks once each time
   you open the section and never again while you stay on it, so a Thomas that answers slowly, or answers 404 because the
   Contributors plugin is off, cannot make it loop. An answer that fails replaces the numbers with one sentence. Every
   word from the server is set as text, because the name of an agent can hold anything.
*/
(function contributorsPanel() {
  'use strict';

  const API = '/api/contributors';
  const SECTION = 'contributors';
  const NAMES = { thomas: 'Thomas', claude: 'Claude', codex: 'Codex', you: 'You' };
  const WAITING = 'Counting...';
  const UNAVAILABLE = 'The counts are not available because Contributors is turned off. You can turn it back on under Plugins.';
  const FAILED = "Thomas couldn't count right now. Leave this page and open it again to try once more.";

  const panel = document.getElementById(SECTION);
  const host = document.getElementById('contributorsHost');
  if (!panel || !host) return;

  let reading = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function nameOf(actor) {
    if (NAMES[actor]) return NAMES[actor];
    const text = String(actor);
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Someone';
  }

  function changes(count) {
    const number = Number.isFinite(Number(count)) ? Number(count) : 0;
    return `${number.toLocaleString()} ${number === 1 ? 'change' : 'changes'}`;
  }

  function group(title, counts) {
    const box = element('div', 'settings-group');
    box.append(element('div', 'group-title', title));
    const actors = Object.keys(counts).sort((a, b) => {
      const known = Object.keys(NAMES);
      const rank = (actor) => (known.includes(actor) ? known.indexOf(actor) : known.length);
      return rank(a) - rank(b) || (counts[b] || 0) - (counts[a] || 0);
    });
    for (const actor of actors) {
      const item = element('div', 'setting-item');
      const label = element('div', 'setting-label');
      label.append(element('div', 'setting-name', nameOf(actor)));
      const control = element('div', 'setting-control');
      control.append(element('span', 'contributors-count', changes(counts[actor])));
      item.append(label, control);
      box.append(item);
    }
    return box;
  }

  function say(text) {
    host.replaceChildren(element('div', 'panel-description contributors-note', text));
  }

  function show(found) {
    if (found.error) return say(found.error);
    const days = Number(found.recent_days) || 30;
    host.replaceChildren(
      group('All time', found.total || {}),
      group(`Last ${days} days`, found.recent || {}),
    );
  }

  async function read() {
    if (reading) return;
    reading = true;
    say(WAITING);
    try {
      const answer = await fetch(API, { headers: { Accept: 'application/json' } });
      if (answer.status === 404) return say(UNAVAILABLE);
      if (!answer.ok) return say(FAILED);
      show(await answer.json());
    } catch (error) {
      say(FAILED);
    } finally {
      reading = false;
    }
  }

  // The section is opened by its button, by a search in Settings or by a link, so watch the section itself.
  let wasOpen = panel.classList.contains('active');
  if (wasOpen) read();
  new MutationObserver(() => {
    const open = panel.classList.contains('active');
    if (open && !wasOpen) read();
    wasOpen = open;
  }).observe(panel, { attributes: true, attributeFilter: ['class'] });
}());
