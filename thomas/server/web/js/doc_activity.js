/**
 * Is this document the one the user is actually looking at?
 *
 * Every Chat/Build/Work tab is its own chat.html document in an iframe, and the
 * shell hides the inactive ones with visibility:hidden + inert, then marks them
 * by putting `bt-doc-hidden` on <html> (browser_shell_docs.js, pauseWorld).
 *
 * Until this file existed that mark had exactly one consumer -- a CSS rule that
 * pauses animations -- so a hidden tab stopped animating but kept polling the
 * server at full rate. Measured on an idle page (2026-09-08): two pollers at
 * 1.5s each, 79 requests a minute, multiplied by every tab left open.
 *
 * `document.hidden` cannot see this. It is only true when the whole browser tab
 * is in the background, so inside a hidden Thomas tab it reads false and every
 * guard written against it does nothing.
 *
 * Work scheduled through here is not dropped, only deferred: a paused document
 * waits instead of asking, and `onChange` fires the moment it is shown again so
 * the caller can refresh immediately. What the user is looking at is unaffected.
 */
(function () {
  'use strict';
  if (window.ThomasDocActivity) return;

  var PAUSED_CLASS = 'bt-doc-hidden';
  var callbacks = [];
  var last = null;

  function isPaused() {
    if (document.hidden) return true;
    var root = document.documentElement;
    return !!(root && root.classList && root.classList.contains(PAUSED_CLASS));
  }

  function announce() {
    var now = isPaused();
    if (now === last) return;
    last = now;
    for (var i = 0; i < callbacks.length; i++) {
      // One bad listener must not stop the others from being told.
      try { callbacks[i](now); } catch (err) { /* listener's problem, not ours */ }
    }
  }

  function onChange(fn) {
    if (typeof fn !== 'function') return function () {};
    callbacks.push(fn);
    return function () {
      var at = callbacks.indexOf(fn);
      if (at >= 0) callbacks.splice(at, 1);
    };
  }

  document.addEventListener('visibilitychange', announce);

  // The shell toggles the class on <html>; watching that one attribute is the
  // whole cost of knowing when this tab is shown or hidden.
  if (typeof MutationObserver === 'function' && document.documentElement) {
    new MutationObserver(announce).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });
  }

  last = isPaused();

  window.ThomasDocActivity = {
    isPaused: isPaused,
    onChange: onChange,
    PAUSED_CLASS: PAUSED_CLASS,
  };
})();
