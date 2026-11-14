/* Decorative theme worlds. Mount the same static markup before the shell boots. */
(function () {
  'use strict';
  const markup = `    <!-- ===================== LIVING WORLDS (behind everything) =====================
         KNOWN, MEASURED, DELIBERATELY NOT CHANGED — and z-index: 0 is correct
         here, so do not "fix" it to -1. See below for what that costs.

         At 900px on the Code empty state, a drifting 30px moon sits under the
         subtitle and "Describe the outcome in the composer below." reads as
         "...the composer belo(sphere) Keep using this same" -- the w and the
         full stop apparently swallowed. Cropped at 3x, it looks like the sprite
         is painted on top.

         It is NOT. \`main\` is \`position: relative; z-index: 1\` and this wrapper is
         \`z-index: 0\`, both children of #tc-shell, so the text genuinely paints
         above the sprite. What actually fails is contrast: the subtitle is
         \`--c-dim\`, rgba(238,240,251,.66), and light grey on a bright sphere has
         almost none. The sprites are animated, so the same line is legible a few
         seconds later -- which is why this reads as intermittent rather than
         broken.

         Two measurements that are worth nothing here, both tried:
           * \`elementFromPoint\` reports the TEXT as topmost, but this layer is
             \`pointer-events: none\` and that API skips it either way.
           * A screenshot alone cannot separate "covered" from "no contrast".
             Hiding this wrapper removes the sphere AND the whole background,
             which proves only that the sprite belongs to it.

         One measurement that DOES separate them, if this comes up again:
         repaint the transcript in a hue absent from both the page and the
         sprite (\`.tc-code-turn * { color:#ff0000 !important }\`), then compare
         the fraction of red pixels inside the sprite's own rect against the
         same-height strip beside it on the same line. Covered would read near
         zero on the sprite; contrast reads comparable. Measured 0.188 on the
         sprite against 0.257 beside it -- the glyphs are there, just washed
         out, confirming the paragraph above.
         Do NOT threshold on "dark" pixels: \`--c-bg\` is #070912, every channel
         under 90, so a brightness test scores the BACKGROUND as text and
         returns a confident wrong answer (it reported the control strip as
         100% "text").

         Setting this wrapper to \`z-index: -1\` was tried and REVERTED: a negative
         z-index puts it behind #tc-shell's own opaque \`--c-bg\`, and every theme
         goes flat black -- verified by screenshot, the entire nebula gone. It
         trades an intermittent contrast dip for losing the design.

         A real fix is a design decision, not a z-index: dim or exclude sprites
         beneath running text, or give the empty-state copy its own backdrop.
         Left alone rather than guessed at. -->

    <div aria-hidden="true" style="position: absolute; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;">

      <!-- NEBULA -->
      <div class="tc-world is-nebula">
        <div style="position: absolute; inset: -12%;">
          <div style="position: absolute; inset: 0; background:
              radial-gradient(42% 46% at 24% 30%, rgba(124,108,255,0.42), transparent 60%),
              radial-gradient(38% 42% at 80% 22%, rgba(64,196,224,0.28), transparent 62%),
              radial-gradient(48% 50% at 64% 82%, rgba(196,86,196,0.24), transparent 60%),
              radial-gradient(64% 64% at 50% 50%, rgba(38,28,86,0.32), transparent 72%);
              animation: tc-neb-drift 160s ease-in-out infinite alternate, tc-neb-hue 110s ease-in-out infinite alternate;"></div>
          <div style="position: absolute; inset: 0; background-image:
              radial-gradient(1.4px 1.4px at 12% 18%, rgba(255,255,255,0.95), transparent),
              radial-gradient(1px 1px at 28% 64%, rgba(255,255,255,0.7), transparent),
              radial-gradient(1.6px 1.6px at 47% 32%, rgba(214,224,255,0.9), transparent),
              radial-gradient(1px 1px at 63% 72%, rgba(255,255,255,0.65), transparent),
              radial-gradient(1.3px 1.3px at 78% 44%, rgba(255,255,255,0.85), transparent),
              radial-gradient(1px 1px at 88% 78%, rgba(255,255,255,0.6), transparent),
              radial-gradient(1px 1px at 38% 88%, rgba(255,255,255,0.7), transparent),
              radial-gradient(1.2px 1.2px at 8% 52%, rgba(255,255,255,0.8), transparent),
              radial-gradient(1px 1px at 55% 12%, rgba(255,255,255,0.7), transparent),
              radial-gradient(1.5px 1.5px at 70% 58%, rgba(230,224,255,0.9), transparent);
              background-size: 360px 360px; animation: tc-stars 150s linear infinite, tc-twinkle 5s ease-in-out infinite;"></div>
        </div>
        <div style="position: absolute; right: 6%; bottom: -90px; width: 240px; height: 240px; animation: tc-planet-drift 90s ease-in-out infinite;">
          <div style="position: absolute; inset: 0; border-radius: 50%; background: radial-gradient(circle at 34% 28%, #8f8cff, #4b3fa6 58%, #221a52 100%); box-shadow: inset -26px -20px 50px rgba(0,0,0,0.55), 0 0 70px rgba(124,108,255,0.22);"></div>
          <div style="position: absolute; top: 44%; left: -22%; width: 144%; height: 36px; border-radius: 50%; border: 3px solid rgba(173,160,255,0.5); transform: rotate(-18deg) scaleY(0.34); animation: tc-spin 80s linear infinite;"></div>
        </div>
        <div style="position: absolute; left: 9%; top: 14%; width: 86px; height: 86px; border-radius: 50%; background: radial-gradient(circle at 36% 30%, #7fe4cf, #2f8f93 60%, #16454f 100%); box-shadow: inset -10px -8px 22px rgba(0,0,0,0.5), 0 0 36px rgba(71,215,172,0.25); animation: tc-planet-drift 70s ease-in-out infinite reverse;"></div>
        <div style="position: absolute; right: 26%; top: 22%; width: 30px; height: 30px; border-radius: 50%; background: radial-gradient(circle at 36% 30%, #e7ecff, #97a0c8 70%, #5b6088); box-shadow: inset -4px -3px 8px rgba(0,0,0,0.4);"></div>
        <div style="position: absolute; top: 17%; left: 0; animation: tc-fly-right 30s linear infinite;">
          <div style="animation: tc-bob 4s ease-in-out infinite;" data-bot data-primary="#bcd8ff" data-secondary="#6f9bff" data-trim="#0a0e1c" data-glow="rgba(120,150,255,0.55)" data-scale="0.62" data-flame="true"></div>
        </div>
        <div style="position: absolute; top: 33%; left: 0; transform: scaleX(-1); animation: tc-fly-left 40s linear infinite;">
          <div style="animation: tc-bob 5s ease-in-out infinite;" data-bot data-primary="#c8b8ff" data-secondary="#8b7bff" data-trim="#0a0e1c" data-glow="rgba(150,120,255,0.5)" data-scale="0.5" data-flame="true"></div>
        </div>
        <div style="position: absolute; top: 64%; left: 0; animation: tc-fly-right 52s linear infinite;">
          <div style="animation: tc-bob 6s ease-in-out infinite;" data-bot data-primary="#a8e8ff" data-secondary="#5ec4e6" data-trim="#0a0e1c" data-glow="rgba(94,196,230,0.45)" data-scale="0.38" data-flame="true"></div>
        </div>
      </div>

      <!-- AURORA -->
      <div class="tc-world is-aurora">
        <div style="position: absolute; top: -34%; left: -20%; width: 140%; height: 95%; background: linear-gradient(115deg, transparent 22%, rgba(52,224,176,0.30) 42%, rgba(70,160,255,0.22) 56%, transparent 76%); filter: blur(44px); animation: tc-aurora 20s ease-in-out infinite;"></div>
        <div style="position: absolute; top: -44%; left: -10%; width: 130%; height: 100%; background: linear-gradient(98deg, transparent 30%, rgba(120,255,214,0.2) 50%, transparent 72%); filter: blur(54px); animation: tc-aurora 30s ease-in-out infinite reverse;"></div>
        <div style="position: absolute; inset: 0; background-image: radial-gradient(1.6px 1.6px at 20% 16%, rgba(255,255,255,0.9), transparent), radial-gradient(1.2px 1.2px at 60% 8%, rgba(255,255,255,0.7), transparent), radial-gradient(1.4px 1.4px at 84% 22%, rgba(255,255,255,0.8), transparent), radial-gradient(1.2px 1.2px at 38% 30%, rgba(255,255,255,0.7), transparent); background-size: 100% 100%;"></div>
        <div style="position: absolute; inset: 0; background-image: radial-gradient(2px 2px at 20% 20%, rgba(255,255,255,0.8), transparent), radial-gradient(2px 2px at 70% 40%, rgba(255,255,255,0.6), transparent), radial-gradient(1.5px 1.5px at 45% 70%, rgba(255,255,255,0.7), transparent); background-size: 260px 260px, 320px 320px, 200px 200px; animation: tc-snow 24s linear infinite; opacity: 0.7;"></div>
        <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 200px; background: linear-gradient(180deg, transparent, rgba(6,30,30,0.6)); clip-path: polygon(0 100%, 0 56%, 12% 38%, 24% 60%, 38% 30%, 52% 58%, 66% 26%, 80% 54%, 92% 36%, 100% 56%, 100% 100%);"></div>
        <div style="position: absolute; top: 38%; left: 0; animation: tc-fly-right 46s linear infinite;">
          <div style="animation: tc-bob 5.5s ease-in-out infinite;" data-bot data-primary="#a8f0da" data-secondary="#34e0b0" data-trim="#06302a" data-glow="rgba(52,224,176,0.5)" data-scale="0.52" data-flame="true"></div>
        </div>
      </div>

      <!-- SANDSTONE -->
      <div class="tc-world is-sandstone">
        <div style="position: absolute; top: 12%; right: 16%; width: 130px; height: 130px; border-radius: 50%; background: radial-gradient(circle at 50% 50%, rgba(255,214,150,0.95), rgba(240,170,90,0.5) 60%, transparent 72%); animation: tc-sun 14s ease-in-out infinite;"></div>
        <div style="position: absolute; inset: 0; background-image: radial-gradient(rgba(120,90,50,0.05) 1px, transparent 1px); background-size: 4px 4px; opacity: 0.7;"></div>
        <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 200px; background: linear-gradient(180deg, transparent, rgba(206,158,104,0.28)); clip-path: ellipse(75% 100% at 30% 130%);"></div>
        <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 150px; background: linear-gradient(180deg, transparent, rgba(176,120,68,0.3)); clip-path: ellipse(70% 100% at 80% 140%);"></div>
        <div style="position: absolute; bottom: 92px; left: 0; animation: tc-sled 56s linear infinite;">
          <div style="position: relative; animation: tc-bob 6s ease-in-out infinite;">
            <div data-bot data-primary="#ffd6a7" data-secondary="#ffad60" data-trim="#3a2a1a" data-glow="rgba(192,96,60,0.45)" data-scale="0.5" data-flame="false"></div>
            <span style="position: absolute; left: -6px; bottom: -6px; width: 52px; height: 7px; border-radius: 6px; background: linear-gradient(90deg, rgba(192,96,60,0.2), #c0603c, rgba(192,96,60,0.2)); box-shadow: 0 6px 14px rgba(192,96,60,0.4);"></span>
          </div>
        </div>
      </div>

      <!-- DARK (blueprint workshop) -->
      <div class="tc-world is-dark">
        <div style="position: absolute; inset: 0; background-image: linear-gradient(rgba(110,155,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(110,155,255,0.06) 1px, transparent 1px); background-size: 44px 44px;"></div>
        <div style="position: absolute; left: 0; right: 0; height: 160px; background: linear-gradient(180deg, transparent, rgba(110,155,255,0.06), transparent); animation: tc-scan 11s linear infinite;"></div>
        <div style="position: absolute; left: 16%; top: 30%; width: 8px; height: 8px; border-radius: 50%; background: rgba(110,155,255,0.5); box-shadow: 0 0 12px rgba(110,155,255,0.6); animation: tc-node 9s ease-in-out infinite;"></div>
        <div style="position: absolute; left: 24%; top: 46%; width: 6px; height: 6px; border-radius: 50%; background: rgba(110,155,255,0.4); animation: tc-node 12s ease-in-out infinite reverse;"></div>
        <div style="position: absolute; right: 20%; top: 60%; width: 7px; height: 7px; border-radius: 50%; background: rgba(110,155,255,0.45); animation: tc-node 10s ease-in-out infinite;"></div>
        <div style="position: absolute; right: 13%; top: 26%; opacity: 0.85; animation: tc-bob 6s ease-in-out infinite;" data-bot data-primary="#9ad8ff" data-secondary="#5aaeff" data-trim="#0a0e16" data-glow="rgba(90,174,255,0.3)" data-scale="0.62" data-flame="false"></div>
      </div>

      <!-- LIGHT (daylight studio) -->
      <div class="tc-world is-light">
        <div style="position: absolute; top: 16%; left: 0; width: 200px; height: 64px; border-radius: 999px; background: radial-gradient(circle at 40% 50%, rgba(255,255,255,0.95), rgba(225,233,245,0.5) 70%, transparent); filter: blur(8px); animation: tc-cloud 70s linear infinite;"></div>
        <div style="position: absolute; top: 40%; left: 0; width: 150px; height: 52px; border-radius: 999px; background: radial-gradient(circle at 40% 50%, rgba(255,255,255,0.9), rgba(225,233,245,0.4) 70%, transparent); filter: blur(8px); animation: tc-cloud 96s linear infinite; animation-delay: -30s;"></div>
        <div style="position: absolute; left: 22%; top: 28%; width: 8px; height: 8px; border-radius: 2px; background: rgba(47,107,255,0.5); transform: rotate(45deg); animation: tc-spark 5s ease-in-out infinite;"></div>
        <div style="position: absolute; left: 70%; top: 34%; width: 6px; height: 6px; border-radius: 2px; background: rgba(47,107,255,0.4); transform: rotate(45deg); animation: tc-spark 6s ease-in-out infinite; animation-delay: -2s;"></div>
        <div style="position: absolute; right: 14%; top: 24%; animation: tc-hover 5s ease-in-out infinite;" data-bot data-primary="#7db0ff" data-secondary="#2f6bff" data-trim="#16233a" data-glow="rgba(47,107,255,0.28)" data-scale="0.6" data-flame="false"></div>
      </div>
    </div>`;

  // The world rests while you are using another window. Its never-ending animations took about 3% of a 16-core PC
  // all day, nearly all in the graphics process (measured 2026-11-09: 5.8% running, 2.5% paused). Only the world is
  // paused, by one CSS rule on .is-resting, so a dot that shows work going on keeps moving. ?motion=1 never rests.
  function restWhenElsewhere(shell) {
    let always = false;
    try { always = new URLSearchParams(window.location.search).get('motion') === '1'; } catch (e) { /* no query */ }
    if (always) return;
    // hasFocus() stays true while focus is inside an embedded workspace, where the window itself reports a blur.
    const set = function () { shell.classList.toggle('is-resting', document.hidden || !document.hasFocus()); };
    const soon = function () { setTimeout(set, 0); };
    window.addEventListener('blur', soon);
    window.addEventListener('focus', soon);
    document.addEventListener('visibilitychange', soon);
    set();
  }

  function mount(shell) {
    if (!shell || shell.querySelector('.tc-world')) return;
    shell.insertAdjacentHTML('afterbegin', markup);
    restWhenElsewhere(shell);
  }

  window.ThomasChatWorlds = { mount };
})();
