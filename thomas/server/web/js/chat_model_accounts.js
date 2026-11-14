/* Chat model accounts. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {


    // Which model handles research, coding, and the rest.
    //
    // This is a feature Thomas already HAD and stopped showing. The whole path
    // works: `worker_runtime._resolve_profile` consults the per-role override
    // before the chat default, `GET /api/models` returns the maps, and
    // `PATCH /api/preferences` writes them (verified by round-trip). The only
    // missing piece was a control -- `persist_user_model_role_preference` has no
    // production caller at all, and nothing in the unified shell ever mentioned
    // `role_profiles`. Set it, and it takes effect immediately.
    //
    // The six ids are the ones the delegation runner accepts; anything else is
    // coerced to "reasoning" (chat_delegation.py: specialist_id not in {...}).
    // Inventing prettier names here would write overrides that never match.
    //
    // It lives behind "Advanced..." at the foot of the model menu
    // (chat_model_advanced.js), one click from where a model is chosen.
    const SPECIALIST_ROLES = [
      ['reasoning', 'Reasoning'],
      ['coding', 'Coding'],
      ['research', 'Research'],
      ['tools', 'Tools'],
      ['writing', 'Writing'],
      ['data', 'Data'],
    ];


    // Re-read the profile list from the server and redraw the menu.
    //
    // The load in boot() is inline and also picks the active profile, which is
    // wrong to redo here: saving a key for Mistral must not silently switch the
    // conversation to Mistral. This refreshes what is USABLE and leaves the
    // selection alone.
    async function reloadModelProfiles() {
      const r = await fetch('/api/models');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      deps.profilesData = Array.isArray(d.profiles) ? d.profiles : [];
      await deps.hydrateProfileModels();
      deps.renderModelMenu();
    }


    // Somewhere to put the key for a provider that needs one.
    //
    // POST /api/secrets/{profile} {api_key} has always existed and the unified
    // shell never called it, so "needs key" was a verdict with no remedy. The
    // input is type=password so the value is not shoulder-readable and does not
    // land in the DOM as text; it is never logged, and the field is cleared the
    // moment the request is sent.
    //
    // On success the whole model list is reloaded rather than patched locally:
    // the server decides what is usable (has_api_key, reachability, per-model
    // availability), and guessing "it works now" in the client is how a menu
    // ends up claiming a provider is ready when the key was rejected.
    function buildKeyRow(profile) {
      const row = document.createElement('div');
      row.style.cssText = 'display: flex; align-items: center; gap: 6px; padding: 4px 9px 8px 26px;';
      const input = document.createElement('input');
      input.type = 'password';
      input.autocomplete = 'off';
      input.spellcheck = false;
      input.placeholder = `Paste ${profile.name} API key`;
      input.setAttribute('aria-label', `API key for ${profile.name}`);
      input.style.cssText = 'flex: 1; min-width: 0; padding: 5px 7px; border-radius: 8px; border: 1px solid var(--c-border); background: var(--c-surface); color: var(--c-text); font-family: inherit; font-size: 11.5px;';
      const save = document.createElement('button');
      save.type = 'button'; save.className = 'hv-soft'; save.textContent = 'Save';
      save.style.cssText = 'flex: 0 0 auto; padding: 5px 10px; border-radius: 8px; border: 1px solid var(--c-border); background: var(--c-surface); color: var(--c-text); font-family: inherit; font-size: 11.5px; cursor: pointer;';
      const note = document.createElement('div');
      note.style.cssText = 'display: none; padding: 0 9px 6px 26px; font-size: 10.5px; color: var(--c-danger, #ff9a9a);';

      const submit = () => {
        const key = input.value.trim();
        if (!key) return;
        input.value = '';
        save.disabled = true; save.textContent = 'Saving…';
        note.style.display = 'none';
        fetch('/api/secrets/' + encodeURIComponent(profile.name), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: key }),
        })
          .then(r => {
            if (!r.ok) return r.text().then(t => { throw new Error(t || ('HTTP ' + r.status)); });
            // Reload from the server; do not assume the key was accepted.
            return reloadModelProfiles();
          })
          .catch(err => {
            save.disabled = false; save.textContent = 'Save';
            note.textContent = String(err && err.message ? err.message : err).slice(0, 90);
            note.style.display = 'block';
          });
      };
      save.addEventListener('click', submit);
      input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } });

      const holder = document.createElement('div');
      row.appendChild(input); row.appendChild(save);
      holder.appendChild(row); holder.appendChild(note);
      return holder;
    }


    // Who is answering, and on whose plan.
    //
    // `/api/openai-codex/status?profile=<name>` has always returned logged_in,
    // email and plan_type; the unified shell read none of it. The old Model
    // Setup modal showed it via model_settings_dropdown.js, which the new shell
    // never loads (it targets #modelSetupModal, an element that no longer
    // exists), so the account behind every answer became invisible.
    //
    // Cached per profile: the menu re-renders on every open and on every
    // accordion toggle, and this must not become a request per keystroke.
    // A failed lookup hides the line rather than guessing -- claiming "signed
    // out" because a fetch failed would be a worse lie than saying nothing.
    const accountByProfile = {};

    function refreshAccountLine() {
      const el = document.getElementById('tc-model-account');
      if (!el) return;
      const profile = deps.profilesData.find(p => p.name === deps.state.profile);
      const isCodex = profile && String(profile.provider || '').replace('-', '_') === 'openai_codex';
      if (!isCodex) { el.style.display = 'none'; el.textContent = ''; return; }

      const paint = (info) => {
        if (!info || !info.logged_in || !info.email) { el.style.display = 'none'; el.textContent = ''; return; }
        el.style.display = 'block';
        el.textContent = '';
        const who = document.createElement('div');
        who.style.cssText = 'overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
        who.textContent = info.email;
        const plan = document.createElement('div');
        plan.style.cssText = 'color: var(--c-muted); font-size: 10.5px;';
        const bits = [String(info.plan_type || '').trim(), 'signed in'].filter(Boolean);
        plan.textContent = bits.join(' · ');
        el.appendChild(who); el.appendChild(plan);
      };

      if (Object.prototype.hasOwnProperty.call(accountByProfile, deps.state.profile)) {
        paint(accountByProfile[deps.state.profile]); return;
      }
      fetch('/api/openai-codex/status?profile=' + encodeURIComponent(deps.state.profile))
        .then(r => (r.ok ? r.json() : null))
        .then(info => { accountByProfile[deps.state.profile] = info; paint(info); })
        .catch(() => { accountByProfile[deps.state.profile] = null; paint(null); });
    }


    async function persistRoleModel(role, profileName, modelId) {
      // Null clears one override; an empty map means no change.
      const body = { advanced: { model: {
        role_profiles: { [role]: profileName || null },
        role_model_ids: { [role]: modelId || null },
      } } };
      const response = await fetch('/api/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error('Could not save this model. Try again.');
      const readback = await fetch('/api/preferences', { cache: 'no-store' });
      if (!readback.ok) throw new Error('Could not confirm the saved model. Try again.');
      const data = await readback.json();
      const saved = data && data.advanced && data.advanced.model;
      if (!saved || !saved.role_profiles || !saved.role_model_ids
          || String(saved.role_profiles[role] || '') !== profileName
          || String(saved.role_model_ids[role] || '') !== modelId) {
        throw new Error('The saved model did not match your choice. Try again.');
      }
      // Replace the maps so a late boot response cannot overwrite this choice.
      const profiles = Object.assign({}, deps.state.roleProfiles || {});
      const models = Object.assign({}, deps.state.roleModelIds || {});
      if (profileName) { profiles[role] = profileName; models[role] = modelId; }
      else { delete profiles[role]; delete models[role]; }
      deps.state.roleProfiles = profiles;
      deps.state.roleModelIds = models;
      if (window.ThomasChatModelSelection && window.ThomasChatModelSelection.roleSaved) {
        window.ThomasChatModelSelection.roleSaved(role, profileName, modelId);
      }
    }

    const BUILD_ROLES = [
      ['build_builder', 'Build builders', true],
      ['build_reviewer', 'Build reviewers'],
    ];
    const pendingRoles = new Set();
    const roleNotices = new Map();
    const roleViews = new Map();

    function roleValue(role) {
      const profile = (deps.state.roleProfiles || {})[role] || '';
      const model = (deps.state.roleModelIds || {})[role] || '';
      return profile ? `${profile}\u0000${model}` : '';
    }

    function paintRole(role) {
      const view = roleViews.get(role);
      if (!view) return;
      view.select.disabled = pendingRoles.has(role);
      if (!pendingRoles.has(role)) view.select.value = roleValue(role);
      const message = roleNotices.get(role);
      view.note.textContent = pendingRoles.has(role) ? 'Saving…' : (message || '');
      view.note.style.color = message && message !== 'Saved' ? 'var(--c-danger, #ff9a9a)' : 'var(--c-muted)';
    }

    // One table: a row per job, with the model that does it.
    function modelCell(role, choices) {
      const sel = document.createElement('select');
      sel.setAttribute('aria-label', `Model for ${role.label}`);
      sel.setAttribute('aria-describedby', `tc-role-${role.id}-status`);
      const option = (value, text) => {
        const item = document.createElement('option');
        item.value = value; item.textContent = text; sel.appendChild(item);
        return item;
      };
      option('', 'Use the default');
      choices.forEach(choice => option(`${choice.profile}\u0000${choice.id}`, choice.label));
      const current = roleValue(role.id);
      if (current && !choices.some(choice => `${choice.profile}\u0000${choice.id}` === current)) {
        option(current, `Unavailable saved model: ${(deps.state.roleModelIds || {})[role.id] || 'unknown'}`).disabled = true;
      }
      sel.value = current;
      const note = document.createElement('div');
      note.id = `tc-role-${role.id}-status`;
      note.className = 'tc-adv-note';
      note.setAttribute('role', 'status');
      roleViews.set(role.id, { select: sel, note });
      paintRole(role.id);
      sel.addEventListener('change', async () => {
        if (pendingRoles.has(role.id)) return;
        const [profileName, modelId] = sel.value ? sel.value.split('\u0000') : ['', ''];
        pendingRoles.add(role.id); roleNotices.delete(role.id); paintRole(role.id);
        try {
          await persistRoleModel(role.id, profileName, modelId);
          roleNotices.set(role.id, 'Saved');
        } catch (error) {
          roleNotices.set(role.id, error instanceof Error ? error.message : 'Could not save this model. Try again.');
        } finally {
          pendingRoles.delete(role.id); paintRole(role.id);
        }
      });
      return { sel, note };
    }

    function renderSpecialistModels(wrap) {
      const usable = [];
      deps.profilesData.forEach(profile => {
        if (!deps.profileIsUsable(profile)) return;
        deps.profileModelOptions(profile).forEach(model => {
          if (model.available === false) return;
          usable.push({ profile: profile.name, id: String(model.id || profile.model || ''),
            label: String(model.display_name || model.id || profile.model || profile.name).split('/').pop(),
            provider: String(profile.provider || '').replace(/-/g, '_') });
        });
      });
      const builders = usable.filter(choice => choice.profile === 'openai_codex'
        && choice.provider === 'openai_codex' && choice.id.startsWith('gpt-'));
      const intro = document.createElement('p');
      intro.className = 'tc-adv-intro';
      intro.textContent = 'Task manager uses the model chosen in Models. Saved defaults for new Build runs.';
      wrap.appendChild(intro);
      const table = document.createElement('table');
      table.className = 'tc-adv-table';
      const row = (tag, cells) => {
        const tr = document.createElement('tr');
        cells.forEach(cell => {
          const td = document.createElement(tag);
          if (cell && typeof cell === 'object') td.appendChild(cell); else td.textContent = String(cell || '');
          tr.appendChild(td);
        });
        table.appendChild(tr);
        return tr;
      };
      row('th', ['Job', 'Model']);
      const addRoles = (roles, choicesFor) => roles.forEach(([id, label]) => {
        const role = { id, label };
        const { sel, note } = modelCell(role, choicesFor(id));
        const holder = document.createElement('div');
        holder.appendChild(sel); holder.appendChild(note);
        const tr = row('td', [label, holder]);
        tr.children[0].className = 'tc-adv-role';
      });
      addRoles(SPECIALIST_ROLES, () => usable);
      const section = document.createElement('tr');
      section.className = 'tc-adv-section';
      const heading = document.createElement('th');
      heading.setAttribute('colspan', '2'); heading.textContent = 'Build teams';
      section.appendChild(heading); table.appendChild(section);
      addRoles(BUILD_ROLES, id => (id === 'build_builder' ? builders : usable));
      wrap.appendChild(table);
    }
    return { reloadModelProfiles, buildKeyRow, refreshAccountLine, persistRoleModel, renderSpecialistModels };
  }
  window.ThomasChatModelAccounts = { create };
})();
