"use client";

import { useEffect, useRef, useState } from "react";

type Walker = {
  x: number;
  direction: -1 | 1;
  jumpTimer: number;
  nextJump: number;
};

const THOMAS_PHRASES = [
  "locked in",
  "shipping the next move",
  "eyes on the task",
  "walking the footer beat",
  "Thomas is online",
  "still building",
];

const WALK_MIN_X = 8;
const WALK_MAX_X = 92;
const WALK_SPEED = 12;
const INITIAL_BUBBLE_DELAY_MS = 900;

function randomBetween(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function seedWalker(): Walker {
  return {
    x: 16,
    direction: 1,
    jumpTimer: 0,
    nextJump: randomBetween(2.2, 4.1),
  };
}

export function DinoRiders() {
  const [walker, setWalker] = useState<Walker>(() => seedWalker());
  const walkerRef = useRef<Walker>(walker);
  const [bubbleText, setBubbleText] = useState<string | null>(null);
  const reduceMotionRef = useRef(false);

  useEffect(() => {
    walkerRef.current = walker;
  }, [walker]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => {
      reduceMotionRef.current = media.matches;
      if (media.matches) {
        setBubbleText(null);
        setWalker((current) => ({
          ...current,
          x: 50,
          direction: 1,
          jumpTimer: 0,
        }));
      }
    };
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    let frameId: number | undefined;
    let previous = performance.now();

    const tick = (now: number) => {
      const delta = Math.min(0.05, Math.max(0.001, (now - previous) / 1000));
      previous = now;

      if (!reduceMotionRef.current) {
        setWalker((current) => {
          let x = current.x + current.direction * WALK_SPEED * delta;
          let direction = current.direction;

          if (x >= WALK_MAX_X) {
            x = WALK_MAX_X;
            direction = -1;
          } else if (x <= WALK_MIN_X) {
            x = WALK_MIN_X;
            direction = 1;
          }

          let jumpTimer = Math.max(0, current.jumpTimer - delta);
          let nextJump = current.nextJump - delta;

          if (jumpTimer === 0 && nextJump <= 0) {
            jumpTimer = randomBetween(0.34, 0.52);
            nextJump = randomBetween(2.4, 4.8);
          }

          return {
            x,
            direction,
            jumpTimer,
            nextJump,
          };
        });
      }

      frameId = requestAnimationFrame(tick);
    };

    frameId = requestAnimationFrame(tick);
    return () => {
      if (frameId) cancelAnimationFrame(frameId);
    };
  }, []);

  useEffect(() => {
    if (reduceMotionRef.current) return;

    let showTimer: ReturnType<typeof setTimeout> | undefined;
    let hideTimer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;

    const schedule = (ms: number) => {
      if (showTimer) clearTimeout(showTimer);
      showTimer = setTimeout(showBubble, ms);
    };

    const clearBubble = () => {
      setBubbleText(null);
      schedule(randomBetween(2400, 4200));
    };

    const showBubble = () => {
      if (cancelled || reduceMotionRef.current) return;
      const activeWalker = walkerRef.current;
      if (activeWalker.x < 16 || activeWalker.x > 84) {
        schedule(900);
        return;
      }

      const phrase = THOMAS_PHRASES[Math.floor(Math.random() * THOMAS_PHRASES.length)];
      setBubbleText(phrase);

      if (hideTimer) clearTimeout(hideTimer);
      hideTimer = setTimeout(clearBubble, randomBetween(1500, 2200));
    };

    schedule(INITIAL_BUBBLE_DELAY_MS);

    return () => {
      cancelled = true;
      if (showTimer) clearTimeout(showTimer);
      if (hideTimer) clearTimeout(hideTimer);
    };
  }, []);

  const handleThomasClick = () => {
    setWalker((current) => ({
      ...current,
      jumpTimer: 0.48,
      nextJump: randomBetween(2.7, 4.6),
    }));
    setBubbleText("Thomas");
    window.setTimeout(() => {
      setBubbleText((current) => (current === "Thomas" ? null : current));
    }, 1100);
  };

  const isSpeaking = bubbleText !== null;
  const facingLeft = walker.direction < 0 && !isSpeaking;
  const robotClass = [
    "pixel-agent pixel-agent-blue footer-thomas-robot",
    facingLeft ? "facing-left" : "",
    isSpeaking ? "looking-user" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className="dino-riders-band" aria-label="Thomas walking across the footer">
      <div className="dino-riders-track">
        <div
          className={`footer-thomas-track${walker.jumpTimer > 0 ? " is-jumping" : ""}`}
          style={{ left: `${walker.x}%` }}
        >
          {bubbleText ? <div className="footer-thomas-bubble">{bubbleText}</div> : null}
          <button type="button" className="footer-thomas-hitbox" aria-label="Thomas footer robot" onClick={handleThomasClick}>
            <span className="footer-thomas-shadow" />
            <span className="footer-thomas-robot-frame">
              <span className={robotClass}>
                <span className="agent-head">
                  <span className="agent-eye agent-eye-left" />
                  <span className="agent-eye agent-eye-right" />
                </span>
                <span className="agent-body" />
                <span className="agent-leg agent-leg-left" />
                <span className="agent-leg agent-leg-right" />
              </span>
            </span>
            <span className="footer-thomas-name">Thomas</span>
          </button>
        </div>
      </div>
    </section>
  );
}
