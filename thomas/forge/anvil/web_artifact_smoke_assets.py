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
          // A CONTROL WINDOW FIRST: does this page change on its own?
          //
          // "The signature differs 60ms after I sent a key" only means the key
          // did something if nothing ELSE could have moved the page in those
          // 60ms. Two things routinely do. A canvas with an animation loop
          // redraws every frame, so its hash differs whatever you send it. And
          // the nav/type/press probes below run synchronously between the old
          // baseline and the deferred comparison, so their clicks landed inside
          // the very window being attributed to the key.
          //
          // Measured by sending the key to a DETACHED <div> the page can never
          // receive -- everything else byte-identical -- across 10 real
          // deliverables. On the 5 that claimed an input response, the deaf run
          // claimed exactly the same thing:
          //     expenses.html      keyboard:ArrowRight   (real == deaf)
          //     snake.html         keyboard:ArrowRight   (real == deaf)
          //     star-catcher.html  keyboard:ArrowRight   (real == deaf)
          //     pacman.html        keyboard:ArrowRight   (real == deaf)
          //     exec-5d2d398f...   keyboard:ArrowRight, pointer:canvas (real == deaf)
          // Not one claim was caused by the input. expenses.html is the plainest
          // case: it registers no key handler that reacts, a real
          // `keyboard.press("ArrowRight")` changes nothing, and its totals are
          // correct by hand -- yet its summary read
          // "nav:List, nav:Summary, pressed:Add, pressed:List, pressed:Summary,
          // keyboard:ArrowRight". The keyboard entry was the tab clicks.
          //
          // So spend one identical idle window with no input at all. If the page
          // moved by itself, a later difference proves nothing and nothing is
          // claimed. Silent when it declines, deliberately: a note that fires on
          // every animating game is the permanently-red signal this file's own
          // press-probe comment warns about.
          const idleBefore = observableSignature(canvas);
          setTimeout(() => {
            const settled = observableSignature(canvas);
            const selfChanging = settled !== idleBefore;
            keyTarget.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowRight", bubbles: true}));
            keyTarget.dispatchEvent(new KeyboardEvent("keyup", {key: "ArrowRight", bubbles: true}));
            setTimeout(() => {
              if (!selfChanging && state.input_listeners.keyboard > 0 && observableSignature(canvas) !== settled) {
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
                if (!selfChanging && state.input_listeners.pointer > 0 && observableSignature(canvas) !== pointerBefore) {
                  state.interactions.push("pointer:canvas");
                }
              }, 60);
            }, 60);
          }, 60);
        }
        // Does the page's own navigation DO anything?
        //
        // A generated app is often a convincing shell: the delivered "calculator
        // for ideas" shipped a five-item workspace sidebar -- Calculator,
        // Conversions, Graph studio, History, Saved formulas -- where the script
        // never mentions "conversions" or "graph" at all and not one of the five
        // carries a handler. Every existing check passed it: the page boots, has
        // no errors, and its keypad genuinely works. "Boot only" verification
        // clicked nothing, so nobody found out until a person clicked a tab.
        //
        // Reported as a NOTE with counts, never a failure, for the same reason
        // the start and pause probes are notes: which control is navigation is
        // guessed from its position and wording, and a tab that is ALREADY the
        // open one correctly changes nothing when clicked. It is good evidence
        // when things do change and weak evidence when they do not, so it states
        // the numbers and lets a reader weigh them.
        const navScope = document.querySelector("aside, nav, [class*='sidebar' i], [class*='nav' i]");
        if (navScope) {
          const navControls = [...navScope.querySelectorAll("button, [role='button'], a[href^='#']")]
            .filter((node) => visible(node) && !node.disabled && clean(node.textContent).length > 0)
            .filter((node) => !/^(start|play|run|begin|launch|pause|resume|reset|restart)\b/i.test(clean(node.textContent)))
            .slice(0, 8);
          let inert = 0;
          navControls.forEach((node) => {
            const label = clean(node.textContent).slice(0, 24);
            const before = observableSignature(document.querySelector("canvas"));
            try { node.click(); } catch (_error) { return; }
            if (observableSignature(document.querySelector("canvas")) === before) inert += 1;
            else state.interactions.push(`nav:${label}`);
          });
          if (navControls.length >= 3 && inert === navControls.length) {
            pushUnique(state.notes, `clicked ${inert} navigation control(s) and the page never changed; the navigation may be decoration`);
          } else if (inert > 0) {
            pushUnique(state.notes, `${inert} of ${navControls.length} navigation control(s) changed nothing when clicked`);
          }
        }
        // How much of the page did this check NOT exercise?
        //
        // The navigation probe above only fires inside a nav-ish container, so
        // an app whose whole function is buttons goes untouched. Measured across
        // 57 recorded runs: 29 (51%) reported "boot only". For most that is
        // honest -- 0 of 12 sampled had navigation the scope missed. But among
        // them sat a 9x9 Minesweeper (81 cells + 1 button), "build me the future
        // of calculator apps", and a tip calculator. Those read
        // "browser boot clean; boot only", which a reader takes as checked.
        //
        // COUNTED, NOT CLICKED, and that was settled by experiment rather than
        // taste. Pressing one non-destructive control was built and run against
        // the real deliverables; it fired on 3 of 4 button-carrying apps and was
        // wrong every time:
        //     minesweeper     pressed the reset face on a fresh board
        //     tip calculator  pressed a 10% preset with no bill entered
        //     to-do list      pressed "Add task" with an empty field
        // Each correctly does nothing until something else happens first. A note
        // that fires on working apps teaches the reader to skip it, which is how
        // a permanently-red signal ends up hiding a real one. Reverted; do not
        // rebuild it without solving "this control needs input first".
        //
        // The coverage count itself lives in web_artifact_smoke.py, reading the
        // `interactive_count` this file already published.
        //
        // WHAT IS DRIVEN HERE INSTEAD: type, then press. The reverted probe
        // failed because it pressed controls that legitimately do nothing until
        // something else happens first. Supplying the input removes that excuse,
        // and it is what a person does: fill the one field, press the one button,
        // see whether the page responds.
        //
        // Deliberately narrow. Only when the page has exactly one obvious text
        // entry and a non-destructive submit-ish control. A form needing a date
        // format, a chosen category, or two fields is NOT driven -- guessing
        // there is how the last attempt produced three wrong answers out of four.
        //
        // The value is what it can then say truthfully: "typed:x, clicked:Add
        // task" is real evidence the app works, where before the same run
        // reported "boot only" and proved nothing.
        if (!state.interactions.length) {
          // A <textarea> has no type attribute, so `node.type` reports the
          // string "textarea" -- which this filter's regex rejected, silently
          // excluding every textarea on the page. The branch below that reads
          // `field.tagName === "TEXTAREA"` could therefore never run.
          //
          // Measured on wordfreq.html (one textarea, buttons Count words /
          // Clear / Download CSV): entries was 0, the probe never fired, and the
          // receipt read `interactions: [], notes: []` -- "boot only; 4
          // control(s) not exercised" on a page that works perfectly when a
          // person types in it.
          const entries = [...document.querySelectorAll("input, textarea")].filter((node) =>
            visible(node) && !node.disabled && !node.readOnly
            && (node.tagName === "TEXTAREA"
              || /^(text|search|number|email|tel|url|)$/i.test(node.getAttribute("type") || node.type || "")));
          const submits = [...document.querySelectorAll("button, [role='button']")]
            .filter((node) => visible(node) && !node.disabled && clean(node.textContent).length > 0)
            .filter((node) => !/(delete|remove|clear|reset|restart|erase|trash|discard|wipe|start over|cancel)/i.test(
              `${clean(node.textContent)} ${node.getAttribute("aria-label") || ""}`
            ));
          if (entries.length === 1 && submits.length >= 1) {
            const field = entries[0];
            const button = document.querySelector("button[type='submit']") && submits.includes(document.querySelector("button[type='submit']"))
              ? document.querySelector("button[type='submit']")
              : submits[0];
            const label = clean(button.textContent).slice(0, 24);
            const sample = /number/i.test(field.type || "") ? "12" : "smoke test";
            const before = observableSignature(document.querySelector("canvas"));
            try {
              // Native setter + input/change so framework-bound fields update too.
              const proto = field.tagName === "TEXTAREA" ? HTMLTextAreaElement : HTMLInputElement;
              const setter = Object.getOwnPropertyDescriptor(proto.prototype, "value");
              if (setter && setter.set) { setter.set.call(field, sample); } else { field.value = sample; }
              field.dispatchEvent(new Event("input", {bubbles: true}));
              field.dispatchEvent(new Event("change", {bubbles: true}));
              button.click();
              if (observableSignature(document.querySelector("canvas")) !== before) {
                state.interactions.push(`typed:${sample}`, `clicked:${label}`);
              } else {
                pushUnique(state.notes, `typed into the only field and pressed ${label}; nothing on the page changed`);
              }
            } catch (_error) {
              pushUnique(state.notes, `typing into the only field and pressing ${label} raised an error`);
            }
          }
        }
        // Press-and-observe, recording ONLY what worked.
        //
        // The comment above records why a press probe was reverted: it fired on
        // 3 of 4 button-carrying apps and was wrong every time, because a
        // Minesweeper reset face, a 10% tip preset and an empty-field "Add task"
        // all correctly do nothing until something else happens first. The
        // objection was precise -- "a note that fires on working apps teaches the
        // reader to skip it" -- and it is about the NOTE, not the press.
        //
        // So this presses and stays silent about anything that did not change.
        // A control that does nothing yet produces no note, no risk and no
        // wolf-crying; a control that DOES change the page produces the one thing
        // boot-only verification could never supply -- evidence the app responds.
        // Nothing here can fail a run.
        //
        // Measured across 14 real deliverables, 11 of which were "boot only"
        // beforehand, including a 9x9 Minesweeper with 82 controls and a habit
        // tracker with 33.
        //
        // `pressed_controls` is published so the coverage line can keep telling
        // the truth about the REST of the page: pressing 6 of 82 must not be
        // allowed to read as though the whole thing was checked.
        const alreadyDriven = state.interactions.length;
        const pressable = [...document.querySelectorAll("button, [role='button']")]
          .filter((node) => visible(node) && !node.disabled)
          .filter((node) => !/(delete|remove|clear|reset|restart|erase|trash|discard|wipe|start over|cancel|sign out|log out|submit order|buy|pay)/i.test(
            `${clean(node.textContent)} ${node.getAttribute("aria-label") || ""}`
          ))
          // Anything that hands a file to the browser HANGS this check.
          // Measured: pressing wordfreq.html's "Download CSV" -- which does the
          // ordinary createObjectURL + anchor click -- left headless Chrome
          // waiting on the transfer until the smoke hit its timeout, and the
          // result was `ok: False, "browser smoke timed out"` on an app that is
          // completely correct. A probe that fails a working deliverable is
          // worse than one that checks nothing, so these are skipped rather than
          // pressed. The download is exercised for real elsewhere; it just
          // cannot be exercised HERE.
          .filter((node) => !/(download|export|print|share|upload|save as|open file)/i.test(
            `${clean(node.textContent)} ${node.getAttribute("aria-label") || ""}`
          ))
          .slice(0, 6);
        let responded = 0;
        pressable.forEach((node) => {
          const pressLabel = (clean(node.textContent) || clean(node.getAttribute("aria-label")) || "control").slice(0, 24);
          const before = observableSignature(document.querySelector("canvas"));
          try { node.click(); } catch (_error) { return; }
          if (observableSignature(document.querySelector("canvas")) !== before) {
            responded += 1;
            pushUnique(state.interactions, `pressed:${pressLabel}`);
          }
        });
        state.pressed_controls = pressable.length;
        state.pressed_responded = responded;
        state.exercised_controls = pressable.length + (alreadyDriven ? 1 : 0);
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
