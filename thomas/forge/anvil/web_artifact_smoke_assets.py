"""Static browser-smoke policy and injected instrumentation."""

from __future__ import annotations

import re

# What the smoke server will hand to a page it is checking. This is a security
# boundary -- generated code runs against it -- so it stays an allowlist of
# formats a browser PARSES rather than executes, plus the scripts and styles the
# page legitimately ships.
#
# The data formats below were missing, and `.json` alone was not enough. A page
# that `fetch`ed a `sales.csv` sitting beside it got a 404 from this harness and
# then honestly reported itself blank, because it had no data to draw. Measured
# on a real Code run: Thomas was asked for a canvas revenue chart reading
# `sales.csv`, wrote both files correctly -- served where the CSV is reachable
# the page prints the grand total `$623,001.25`, matching the CSV summed
# independently, and paints 80,236 non-transparent pixels -- and verification
# still returned `BROWSER_SMOKE_FAILED ... Could not load sales.csv (HTTP 404)
# ... nothing was ever drawn to the canvas`. The run then spent its entire
# ten-pass fix budget repairing a page that was already right, and finished
# `failed`.
#
# These are inert: the browser hands them to the page as text and never runs
# them, which is exactly why `.json` was always safe to serve. Source, secrets,
# dotfiles and databases stay refused -- widening this to "anything in the
# folder" would turn verification into a way to read a project's private files
# out of a page Thomas just generated.
_WEB_ASSET_SUFFIXES = {
    ".avif",
    ".css",
    ".csv",
    ".gif",
    ".html",
    ".htm",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".png",
    ".svg",
    ".tsv",
    ".txt",
    ".wasm",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
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
    // Things worth a reader knowing that are NOT defects. A probe that guesses
    // which control to press cannot call the result a failure, but the attempt
    // is still worth reporting.
    notes: [],
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
  // Which context a canvas is drawn through decides whether its pixels can be
  // read back at all. Recorded here, before application scripts run, because
  // afterwards there is no way to ask a canvas what kind of context it handed
  // out.
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(kind, ...rest) {
    const context = originalGetContext.call(this, kind, ...rest);
    if (context) this.dataset.thomasSmokeContext = String(kind || "");
    return context;
  };
  // "There is a canvas" is not "the page drew something". A game that renders
  // nothing has the same DOM as a game that renders perfectly, so the element
  // alone can never tell them apart -- read the pixels instead.
  //
  // Returns "painted", "blank", or "unverifiable". Unverifiable is deliberate
  // and must not fail a build: a WebGL canvas without preserveDrawingBuffer
  // reads back empty even when it is drawing every frame, and a canvas tainted
  // by a cross-origin image throws. Claiming those are blank would reject
  // working work, which is worse than the gap it closes.
  const paintState = (canvas) => {
    if (!canvas) return "unverifiable";
    const width = Number(canvas.width || 0);
    const height = Number(canvas.height || 0);
    if (width <= 0 || height <= 0) return "unverifiable";
    const kind = String(canvas.dataset.thomasSmokeContext || "").toLowerCase();
    // Nobody ever asked this canvas for a drawing context, so it is leftover
    // markup rather than the application's surface -- Thomas's own shell page
    // carries one, at the default 300x150, while working perfectly by framing
    // the game. Calling that a failed render would block a good delivery, which
    // is the same mistake as passing a bad one, pointed the other way. A script
    // that crashes before reaching getContext is still caught: that throws, and
    // uncaught errors already fail this check.
    if (!kind) return "unverifiable";
    if (kind !== "2d") return "unverifiable";
    try {
      const blank = document.createElement("canvas");
      blank.width = width;
      blank.height = height;
      return canvas.toDataURL() === blank.toDataURL() ? "blank" : "painted";
    } catch (_error) {
      return "unverifiable";
    }
  };
  // Sticky: a game that draws a menu and then clears the canvas for its first
  // frame has still proved it can draw.
  const notePaint = (canvas) => {
    if (state.canvas_paint === "painted") return state.canvas_paint;
    const observed = paintState(canvas);
    if (observed === "painted" || !state.canvas_paint) state.canvas_paint = observed;
    return state.canvas_paint;
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
      client_height: Number(canvas.clientHeight || 0),
      context: String(canvas.dataset.thomasSmokeContext || ""),
      paint: notePaint(canvas)
    } : null;
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(state))));
    document.documentElement.setAttribute("data-thomas-smoke", encoded);
  };
  window.addEventListener("DOMContentLoaded", () => {
    state.dom_ready = true;
    setTimeout(() => {
      try {
        const controls = [...document.querySelectorAll("button, [role='button']")];
        // VISIBLE and enabled. Matching on button words alone picks whichever
        // one happens to come first in the document, and star-catcher.html
        // offers "Start Over", "Start Game" and "Play Again" -- so the restart
        // control from the game-over screen won, was hidden on a fresh load,
        // and clicking it changed nothing. The harness then reported the game
        // as dead. It was fine; the click went to the wrong button.
        //
        // A word match cannot tell a start control from a restart control, so
        // it must not be the only filter. What the screen is actually showing
        // can, and the check already knows how to ask.
        const starter = controls.find((node) => /^(start|play|run|begin|launch)(\b|\s)/i.test(clean(node.textContent)) && !node.disabled && visible(node));
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
            // Recorded, NOT failed. Which button is the start button is decided
            // by matching words in its label, and a word match cannot tell
            // "Start Game" from "Start Over": star-catcher.html offers both, the
            // restart control came first, clicking it on a fresh page correctly
            // did nothing, and this reported a working game as dead. Its canvas
            // was painted and it threw no errors the whole time.
            //
            // A probe that cannot know it pressed the right thing has no
            // standing to call the result a defect. It is good evidence when it
            // DOES see a reaction and no evidence at all when it does not, so
            // it stays as an observation for a reader to weigh.
            if (!starterChanged) pushUnique(state.notes, "clicked a start-like control and saw no change; it may not be the real start control");
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
                // Same reasoning as the start probe above: which control pauses
                // is guessed from its wording, so failing to find a Resume
                // afterwards may mean the game never paused rather than that it
                // cannot resume. An observation, not a verdict.
                pushUnique(state.notes, "paused via a pause-like control and found no Resume; the pause may not have engaged");
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
        notePaint(canvas);  // sample before input, so a title screen counts
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
