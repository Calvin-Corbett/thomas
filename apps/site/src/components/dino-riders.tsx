"use client";

import { useEffect, useRef, useState } from "react";

type Tint = "blue" | "green" | "orange" | "pink" | "purple" | "yellow";

type Rider = {
  id: string;
  tint: Tint;
  lane: 0 | 1 | 2;
  x: number;
  speed: number;
  direction: -1 | 1;
  jumpTimer: number;
  nextJump: number;
};

const RIDER_SPECS: Array<{ id: string; tint: Tint; lane: 0 | 1 | 2; speed: number; direction: -1 | 1 }> = [
  { id: "rider-echo", tint: "blue", lane: 2, speed: 2.7, direction: 1 },
  { id: "rider-sage", tint: "green", lane: 1, speed: 2.3, direction: -1 },
  { id: "rider-bolt", tint: "orange", lane: 2, speed: 2.9, direction: 1 },
  { id: "rider-puff", tint: "pink", lane: 1, speed: 2.1, direction: 1 },
  { id: "rider-void", tint: "purple", lane: 1, speed: 2.4, direction: -1 },
  { id: "rider-spark", tint: "yellow", lane: 2, speed: 2.8, direction: 1 },
];

const PHRASES = [
  "rawr mode engaged",
  "trex torque online",
  "patrolling the release notes",
  "branch is clean, claws are sharp",
  "jumping over blockers",
  "tiny rider, giant velocity",
  "thomas build train rolling",
  "sprint dinosaur approved",
  "ship it then stomp it",
];
const INITIAL_BUBBLE_DELAY_MS = 420;

const MIN_X = -8;
const MAX_X = 108;

function randomBetween(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function seedRiders() {
  const step = (MAX_X - MIN_X) / RIDER_SPECS.length;
  return RIDER_SPECS.map((spec, index) => ({
    ...spec,
    x: MIN_X + step * index,
    jumpTimer: 0,
    nextJump: randomBetween(2.2, 5.8),
  }));
}

export function DinoRiders() {
  const [riders, setRiders] = useState<Rider[]>(() => seedRiders());
  const ridersRef = useRef<Rider[]>(riders);
  const [bubble, setBubble] = useState<{ id: string; text: string } | null>(null);
  const reduceMotionRef = useRef(false);

  useEffect(() => {
    ridersRef.current = riders;
  }, [riders]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => {
      reduceMotionRef.current = media.matches;
      if (media.matches) setBubble(null);
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
        setRiders((current) =>
          current.map((rider) => {
            let x = rider.x + rider.direction * rider.speed * delta;
            if (rider.direction > 0 && x > MAX_X) x = MIN_X;
            if (rider.direction < 0 && x < MIN_X) x = MAX_X;

            let jumpTimer = Math.max(0, rider.jumpTimer - delta);
            let nextJump = rider.nextJump - delta;

            if (jumpTimer === 0 && nextJump <= 0) {
              jumpTimer = randomBetween(0.52, 0.7);
              nextJump = randomBetween(3.2, 6.4);
            }

            return {
              ...rider,
              x,
              jumpTimer,
              nextJump,
            };
          }),
        );
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
      setBubble(null);
      schedule(randomBetween(1800, 4300));
    };

    const showBubble = () => {
      if (cancelled || reduceMotionRef.current) return;
      const active = ridersRef.current.filter((rider) => rider.x > 18 && rider.x < 82);
      const pool = active.length > 0 ? active : ridersRef.current;
      const picked = pool[Math.floor(Math.random() * pool.length)];
      const text = PHRASES[Math.floor(Math.random() * PHRASES.length)];
      setBubble({ id: picked.id, text });

      if (hideTimer) clearTimeout(hideTimer);
      hideTimer = setTimeout(clearBubble, randomBetween(1500, 2400));
    };

    schedule(INITIAL_BUBBLE_DELAY_MS);

    return () => {
      cancelled = true;
      if (showTimer) clearTimeout(showTimer);
      if (hideTimer) clearTimeout(hideTimer);
    };
  }, []);

  return (
    <section className="dino-riders-band" aria-label="Robot riders on T-Rex patrol">
      <div className="dino-riders-grid" />
      <div className="dino-riders-track">
        {riders.map((rider) => {
          const isJumping = rider.jumpTimer > 0;
          const isSpeaking = bubble?.id === rider.id;
          return (
            <div
              key={rider.id}
              className={`dino-rider-track lane-${rider.lane}${isJumping ? " is-jumping" : ""}`}
              style={{ left: `${rider.x}%` }}
            >
              {isSpeaking ? <div className="dino-rider-bubble">{bubble?.text}</div> : null}
              <span className={`dino-rider-sprite${rider.direction < 0 ? " facing-left" : ""}`}>
                <span className="trex-tail" />
                <span className="trex-body" />
                <span className="trex-belly" />
                <span className="trex-neck" />
                <span className="trex-head" />
                <span className="trex-jaw" />
                <span className="trex-eye" />
                <span className="trex-arm" />
                <span className="trex-leg trex-leg-back" />
                <span className="trex-leg trex-leg-front" />
                <span className="trex-saddle" />
                <span className="trex-saddle-strap" />
                <span className="dino-rider-robot-wrap">
                  <span className={`pixel-agent pixel-agent-${rider.tint} dino-rider-robot`}>
                    <span className="agent-head">
                      <span className="agent-eye agent-eye-left" />
                      <span className="agent-eye agent-eye-right" />
                    </span>
                    <span className="agent-body" />
                    <span className="agent-leg agent-leg-left" />
                    <span className="agent-leg agent-leg-right" />
                  </span>
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
