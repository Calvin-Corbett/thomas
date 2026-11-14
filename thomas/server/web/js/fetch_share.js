/* fetch_share.js -- one answer for the same read, asked twice in a moment.

   Opening Thomas asked /api/marketplace/installed, /api/health and /api/settings/index/cards twice each, from
   different scripts that each needed the answer. A repeat inside a couple of seconds now shares the first reply
   (every caller gets its own copy to read). Only these three reads, only GETs to this server; anything else goes
   straight to the real fetch, and a failed request is forgotten at once so a retry really retries. */
(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof window.fetch !== 'function' || window.__thomasFetchShare) return;
  window.__thomasFetchShare = true;
  const real = window.fetch.bind(window);
  const SHARED = /^\/api\/(marketplace\/installed|health|settings\/index\/cards)$/;
  const FRESH_MS = 2500;
  const recent = new Map();

  window.fetch = function (input, init) {
    try {
      const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
      const raw = typeof input === 'string' ? input : (input && input.url) || '';
      if (method !== 'GET' || !raw) return real(input, init);
      const url = new URL(raw, window.location.href);
      if (url.origin !== window.location.origin || !SHARED.test(url.pathname)) return real(input, init);
      const key = url.pathname + url.search;
      const now = Date.now();
      const hit = recent.get(key);
      if (hit && now - hit.at < FRESH_MS) return hit.promise.then(response => response.clone());
      const promise = real(input, init);
      recent.set(key, { at: now, promise });
      promise.catch(() => { if (recent.get(key) && recent.get(key).promise === promise) recent.delete(key); });
      return promise.then(response => response.clone());
    } catch (error) {
      return real(input, init);
    }
  };
}());
