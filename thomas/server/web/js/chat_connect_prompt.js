/* The ChatGPT-connect prompt (OAuth nudge overlay) for the chat shell.
   Extracted verbatim from chat.html; page state comes in through the
   factory options so the module owns no globals of its own. */
(function () {
  "use strict";
  function create(opts) {
    function isChatGPTOAuthProfile(profileName) {
      const key = String(profileName || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      if (['chatgpt', 'codex', 'openaicodex'].includes(key)) return true;
      const profile = opts.getProfiles().find(p => String(p && p.name || '').toLowerCase().replace(/[^a-z0-9]/g, '') === key);
      const provider = String(profile && profile.provider || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      return ['chatgpt', 'codex', 'openaicodex'].includes(provider);
    }
    function shouldPromptChatGPTConnection(assistantText) {
      if (!isChatGPTOAuthProfile(opts.getProfile())) return false;
      const normalized = String(assistantText || '').replace(/[*_`>#]/g, ' ').replace(/\s+/g, ' ').trim();
      if (!normalized || normalized.length > 500) return false;
      return /^(?:the )?chatgpt(?: oauth| model)? (?:is not|isn't) connected\b/i.test(normalized);
    }
    async function maybePromptChatGPTConnection(assistantText) {
      if (!shouldPromptChatGPTConnection(assistantText)) return false;
      let needsLogin = false;
      // The try guards the STATUS LOOKUP and nothing else. It used to wrap the
      // overlay call too, so a ReferenceError while building the prompt was
      // caught here and read as "the lookup failed" -- the prompt could never
      // appear and nothing ever said why. A fault in our own rendering must
      // surface, not disguise itself as a network problem.
      try {
        const response = await fetch('/api/openai-codex/status?profile=' + encodeURIComponent(opts.getProfile()), { cache: 'no-store' });
        const status = await response.json();
        // Natural-language output is never authoritative auth state. Only a
        // fresh, typed status response may open the reconnect prompt.
        needsLogin = !!(response.ok && status && status.needs_login === true && status.logged_in !== true);
      } catch (error) {
        // A status lookup failure must not falsely tell a signed-in user to reconnect.
        return false;
      }
      if (!needsLogin) return false;
      showChatGPTConnectionPrompt();
      return true;
    }
    function closeChatGPTConnectionPrompt() {
      const overlay = document.getElementById('tc-chatgpt-connect-prompt');
      if (overlay) overlay.style.display = 'none';
    }
    function ensureChatGPTConnectionPrompt() {
      let overlay = document.getElementById('tc-chatgpt-connect-prompt');
      if (overlay) return overlay;
      overlay = document.createElement('div');
      overlay.id = 'tc-chatgpt-connect-prompt';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.setAttribute('aria-labelledby', 'tc-chatgpt-connect-title');
      overlay.style.cssText = 'display:none;position:absolute;inset:0;z-index:120;align-items:center;justify-content:center;padding:24px;background:rgba(2,4,12,.72);backdrop-filter:blur(8px);';
      overlay.innerHTML = `<section style="width:min(460px,100%);border:1px solid var(--c-border-2);border-radius:18px;background:var(--c-menu-bg);box-shadow:var(--c-shadow);padding:22px;color:var(--c-text);">
        <div style="display:flex;align-items:flex-start;gap:14px;">
          <span style="width:42px;height:42px;border-radius:12px;background:var(--c-accent);color:var(--c-accent-ink);display:grid;place-items:center;flex:0 0 auto;"><i class="ph ph-plugs-connected" style="font-size:22px;"></i></span>
          <span style="min-width:0;flex:1;">
            <h2 id="tc-chatgpt-connect-title" style="margin:0 0 6px;font:700 19px/1.25 var(--font-head);">Connect ChatGPT to Thomas</h2>
            <p style="margin:0;color:var(--c-dim);font-size:13.5px;line-height:1.55;">Your ChatGPT or Codex app sign-in is separate from Thomas's local connection. Connect once here so Thomas can use your ChatGPT models.</p>
          </span>
          <button id="tc-chatgpt-connect-close" type="button" aria-label="Close" class="hv-soft" style="width:32px;height:32px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;"><i class="ph ph-x" style="font-size:17px;"></i></button>
        </div>
        <p id="tc-chatgpt-connect-status" role="status" style="margin:18px 0 0;padding:11px 12px;border-radius:10px;background:var(--c-surface);color:var(--c-dim);font-size:12.5px;line-height:1.5;">A ChatGPT sign-in window will open. If you're already signed in, approve Thomas and return here.</p>
        <div style="display:flex;justify-content:flex-end;gap:9px;margin-top:18px;">
          <button id="tc-chatgpt-connect-later" type="button" class="hv-soft" style="padding:9px 13px;border:1px solid var(--c-border-2);border-radius:10px;background:transparent;color:var(--c-text);font:600 13px var(--font-sans);cursor:pointer;">Not now</button>
          <button id="tc-chatgpt-connect-start" type="button" style="padding:9px 14px;border:1px solid var(--c-accent-line);border-radius:10px;background:var(--c-accent);color:var(--c-accent-ink);font:700 13px var(--font-sans);cursor:pointer;">Connect ChatGPT</button>
        </div>
      </section>`;
      // `shell` was left behind as a bare global when this module was extracted
      // "verbatim" from chat.html, where it is a const inside the page IIFE and
      // therefore invisible here. Every attempt to show the prompt threw
      // ReferenceError. The container now arrives through the factory, like the
      // rest of the page state this module borrows.
      const host = (typeof opts.getShell === 'function' && opts.getShell()) || document.body;
      host.appendChild(overlay);
      overlay.addEventListener('click', e => { if (e.target === overlay) closeChatGPTConnectionPrompt(); });
      overlay.querySelector('#tc-chatgpt-connect-close').addEventListener('click', closeChatGPTConnectionPrompt);
      overlay.querySelector('#tc-chatgpt-connect-later').addEventListener('click', closeChatGPTConnectionPrompt);
      overlay.querySelector('#tc-chatgpt-connect-start').addEventListener('click', connectChatGPTFromPrompt);
      return overlay;
    }
    function showChatGPTConnectionPrompt() {
      const overlay = ensureChatGPTConnectionPrompt();
      const status = overlay.querySelector('#tc-chatgpt-connect-status');
      const button = overlay.querySelector('#tc-chatgpt-connect-start');
      status.textContent = "A ChatGPT sign-in window will open. If you're already signed in, approve Thomas and return here.";
      status.style.color = 'var(--c-dim)';
      button.disabled = false;
      button.textContent = 'Connect ChatGPT';
      overlay.style.display = 'flex';
      requestAnimationFrame(() => button.focus());
    }
    async function connectChatGPTFromPrompt() {
      const overlay = ensureChatGPTConnectionPrompt();
      const status = overlay.querySelector('#tc-chatgpt-connect-status');
      const button = overlay.querySelector('#tc-chatgpt-connect-start');
      button.disabled = true;
      button.textContent = 'Waiting for ChatGPT...';
      status.textContent = 'Complete the ChatGPT approval window. Thomas will finish the connection automatically.';
      status.style.color = 'var(--c-dim)';
      try {
        const res = await fetch('/api/openai-codex/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ profile: opts.getProfile() || 'openai_codex', timeout_s: 300 }),
        });
        let data = {}; try { data = await res.json(); } catch (e) {}
        if (res.ok && data.ok && data.logged_in !== false) {
          status.textContent = 'Connected. Thomas can now use your ChatGPT models.';
          status.style.color = 'var(--c-accent)';
          button.textContent = 'Connected';
          return;
        }
        const pending = !!(data.pending || data.needs_paste);
        status.textContent = pending
          ? 'The sign-in is still waiting. Finish it in the browser, then choose Connect ChatGPT again.'
          : String(data.error || 'ChatGPT connection failed. Please try again.');
      } catch (err) {
        status.textContent = String(err && err.message || 'ChatGPT connection failed. Please try again.');
      }
      status.style.color = '#ff9a9a';
      button.disabled = false;
      button.textContent = 'Try again';
    }
    let _pendingCanvasIntent = false; // set on send(): does THIS turn want a renderable result?
    return { maybePromptChatGPTConnection: maybePromptChatGPTConnection };
  }
  window.ThomasChatConnectPrompt = { create: create };
}());
