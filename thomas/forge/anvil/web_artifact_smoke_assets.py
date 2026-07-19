"""Static browser-smoke policy and injected instrumentation."""

from __future__ import annotations

import re

_WEB_ASSET_SUFFIXES = {
    ".avif",
    ".css",
    ".gif",
    ".html",
    ".htm",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mjs",
    ".png",
    ".svg",
    ".wasm",
    ".webp",
    ".woff",
    ".woff2",
}
_MAX_ASSET_BYTES = 16 * 1024 * 1024
_RECEIPT_RE = re.compile(r"\bdata-thomas-smoke=(?:\"([^\"]+)\"|'([^']+)')", re.IGNORECASE)
_SMOKE_HOST = "thomas-smoke.invalid"
_SMOKE_ORIGIN = f"http://{_SMOKE_HOST}"
_SMOKE_CSP = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob:",
        "style-src 'self' 'unsafe-inline' data:",
        "connect-src 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "media-src 'self' data: blob:",
        "worker-src 'self' blob:",
        "frame-src 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    )
)

_SMOKE_HARNESS = r"""
<script id="thomas-browser-smoke-harness">
(() => {
  const state = {
    dom_ready: false,
    errors: [],
    console_errors: [],
    resource_errors: [],
    interactions: [],
    input_listeners: {keyboard: 0, pointer: 0}
  };
  const clean = (value) => String(value ?? "").replace(/\s+/g, " ").trim().slice(0, 500);
  const visible = (node) => Boolean(node && !node.hidden && node.getClientRects().length
    && getComputedStyle(node).visibility !== "hidden" && getComputedStyle(node).display !== "none");
  const pushUnique = (bucket, value) => {
    const text = clean(value);
    if (text && !bucket.includes(text)) bucket.push(text);
  };
  const originalAddEventListener = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type, listener, options) {
    if (/^key(?:down|up|press)$/i.test(String(type))) state.input_listeners.keyboard += 1;
    if (/^(?:pointer|mouse|touch)/i.test(String(type))) state.input_listeners.pointer += 1;
    return originalAddEventListener.call(this, type, listener, options);
  };
  const observableSignature = (canvas) => {
    const controls = [...document.querySelectorAll("button, [role='button'], input, select, textarea")]
      .map((node) => `${clean(node.textContent)}:${visible(node)}:${Boolean(node.disabled)}`).join("|");
    let canvasHash = "";
    try {
      const data = canvas?.toDataURL?.() || "";
      let hash = 2166136261;
      for (let index = 0; index < data.length; index += 1) {
        hash ^= data.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      canvasHash = String(hash >>> 0);
    } catch (_error) {
      canvasHash = "unreadable";
    }
    return `${clean(document.body?.innerText || "")}|${controls}|${canvasHash}`;
  };
  window.addEventListener("error", (event) => {
    if (event.target && event.target !== window) {
      const target = event.target;
      pushUnique(state.resource_errors, `${target.tagName || "resource"}: ${target.src || target.href || "load failed"}`);
      return;
    }
    pushUnique(state.errors, event.message || event.error || "window error");
  }, true);
  window.addEventListener("unhandledrejection", (event) => {
    pushUnique(state.errors, event.reason || "unhandled promise rejection");
  });
  const originalConsoleError = console.error.bind(console);
  console.error = (...args) => {
    pushUnique(state.console_errors, args.map(clean).join(" "));
    originalConsoleError(...args);
  };
  const publish = () => {
    const canvas = document.querySelector("canvas");
    state.title = clean(document.title);
    state.body_text_chars = clean(document.body?.innerText || "").length;
    state.interactive_count = document.querySelectorAll("button, a[href], input, select, textarea, [role='button']").length;
    state.canvas = canvas ? {
      width: Number(canvas.width || 0),
      height: Number(canvas.height || 0),
      client_width: Number(canvas.clientWidth || 0),
      client_height: Number(canvas.clientHeight || 0)
    } : null;
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(state))));
    document.documentElement.setAttribute("data-thomas-smoke", encoded);
  };
  window.addEventListener("DOMContentLoaded", () => {
    state.dom_ready = true;
    setTimeout(() => {
      try {
        const controls = [...document.querySelectorAll("button, [role='button']")];
        const starter = controls.find((node) => /^(start|play|run|begin|launch)(\b|\s)/i.test(clean(node.textContent)) && !node.disabled);
        if (starter) {
          const starterLabel = clean(starter.textContent);
          const bodyBefore = clean(document.body?.innerText || "");
          starter.click();
          state.interactions.push(`clicked:${starterLabel}`);
          setTimeout(() => {
            const starterChanged = !visible(starter) || starter.disabled
              || clean(starter.textContent) !== starterLabel
              || clean(document.body?.innerText || "") !== bodyBefore;
            state.start_effect = starterChanged;
            if (!starterChanged) pushUnique(state.errors, "Start control produced no visible state change");
          }, 80);

          setTimeout(() => {
            const pause = [...document.querySelectorAll("button, [role='button']")].find((node) => {
              const label = `${node.getAttribute("aria-label") || ""} ${clean(node.textContent)}`;
              return visible(node) && !node.disabled && /\bpause\b/i.test(label);
            });
            if (!pause) return;
            document.dispatchEvent(new KeyboardEvent("keydown", {key: "p", bubbles: true}));
            document.dispatchEvent(new KeyboardEvent("keyup", {key: "p", bubbles: true}));
            setTimeout(() => {
              const candidates = [...document.querySelectorAll("button, [role='button']")];
              const dedicatedResume = [...document.querySelectorAll(
                "[id*='resume' i], [data-action*='resume' i]"
              )].find(visible);
              const resume = dedicatedResume || candidates.find((node) => visible(node) && /^resume\b/i.test(
                `${node.getAttribute("aria-label") || ""} ${clean(node.textContent)}`.trim()
              ));
              if (!resume) {
                pushUnique(state.errors, "Pause control produced no visible Resume control");
                return;
              }
              state.interactions.push("pause:P", "clicked:Resume");
              resume.click();
              setTimeout(() => {
                const resumed = !visible(resume) || !/^resume\b/i.test(
                  `${resume.getAttribute("aria-label") || ""} ${clean(resume.textContent)}`.trim()
                );
                state.pause_cycle = resumed;
                if (!resumed) pushUnique(state.errors, "Resume control did not return to play");
              }, 60);
            }, 60);
          }, 120);
        }
        const canvas = document.querySelector("canvas");
        const keyTarget = canvas || document.body || document;
        if (canvas && Number(canvas.clientWidth || canvas.width) > 0 && Number(canvas.clientHeight || canvas.height) > 0) {
          const keyboardBefore = observableSignature(canvas);
          keyTarget.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true}));
          keyTarget.dispatchEvent(new KeyboardEvent("keyup", {key: "ArrowRight", bubbles: true}));
          setTimeout(() => {
            if (state.input_listeners.keyboard > 0 && observableSignature(canvas) !== keyboardBefore) {
              state.interactions.push("keyboard:ArrowRight");
            }
            const pointerBefore = observableSignature(canvas);
            const rect = canvas.getBoundingClientRect();
            const eventType = typeof PointerEvent === "function" ? PointerEvent : MouseEvent;
            canvas.dispatchEvent(new eventType("pointermove", {
              clientX: rect.left + rect.width * 0.75,
              clientY: rect.top + rect.height * 0.75,
              pointerType: "mouse",
              bubbles: true
            }));
            setTimeout(() => {
              if (state.input_listeners.pointer > 0 && observableSignature(canvas) !== pointerBefore) {
                state.interactions.push("pointer:canvas");
              }
            }, 60);
          }, 60);
        }
      } catch (error) {
        pushUnique(state.errors, error);
      }
      setTimeout(publish, 350);
    }, 0);
  }, {once: true});
  setTimeout(publish, 950);
})();
</script>
"""
