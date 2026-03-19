"use client";

import { useEffect, useRef, useState } from "react";

type Agent = {
  id: string;
  startY: number;
  speed: number; // percent per second
  tint: "blue" | "green" | "orange" | "pink" | "purple" | "yellow";
};

const AGENTS: Agent[] = [
  { id: "pixel-alpha", startY: 18, speed: 7.3, tint: "blue" },
  { id: "pixel-luma", startY: 30, speed: 7.8, tint: "purple" },
  { id: "pixel-echo", startY: 42, speed: 7.5, tint: "green" },
  { id: "pixel-bolt", startY: 56, speed: 6.9, tint: "orange" },
  { id: "pixel-mochi", startY: 70, speed: 8.1, tint: "pink" },
  { id: "pixel-sunny", startY: 82, speed: 6.7, tint: "yellow" },
];

const PHRASES = [
  "dang banana pro is crazy good",
  "agent mode locked in",
  "coffee level: shipping",
  "tiny bot, big backlog",
  "deployed and dramatic",
  "no bugs, just features",
];
const INITIAL_DIALOGUE_DELAY_MS = 420;

const DIALOGUE_PRESETS = {
  classic: [
    ...PHRASES,
    "my sprint goal is snacks and speed",
    "todo list got folded like laundry",
    "that bug packed its bags",
    "ship now, flex later",
    "we are so back",
    "clean commit, chaotic energy",
    "i fixed it by believing harder",
    "thomas just cooked another release",
    "bug count went missing",
    "my branch has main character energy",
  ],
  friends: [
    "Brandon just speed-ran the backlog",
    "Trey asked for one tweak and got seven",
    "Zach found a bug before coffee",
    "Matt said one more test and meant twelve",
    "Taylor turned chaos into a checklist",
    "John shipped fixes like a machine",
    "Brandon and Trey are in build mode again",
    "Zach and Matt are cooking today",
    "Taylor dropped clean commits all morning",
    "John touched one file and fixed five things",
    "Brandon said easy and then rewrote half the stack",
    "Trey dropped a hotfix before breakfast",
    "Zach is debugging with laser eyes again",
    "Matt turned one ticket into a masterpiece",
    "Taylor keeps shipping like it is a sport",
    "John just diffed reality itself",
    "Brandon, Trey, and Zach are on a heater",
    "Matt, Taylor, and John are farming Ws",
  ],
  chaos: [
    "status: locked in and slightly unhinged",
    "ship it before the snack break",
    "that refactor looked at me first",
    "we debug at dawn",
    "panic? never heard of her",
    "full send, safety on",
    "this sprint has lore now",
    "kpi: vibes and velocity",
    "today we conquer tabs and tasks",
    "suspiciously successful",
    "this deploy has plot armor",
    "compiler says yes, heart says maybe",
    "the roadmap is now a speedrun",
    "legend says tests are still passing",
    "we replaced fear with Ctrl+S",
    "all gas, no merge conflicts",
    "if it works we call it architecture",
  ],
  clean: [
    "all systems nominal",
    "workflow is healthy",
    "progress is steady",
    "nice and clean release path",
    "tracking looks good",
    "ready for the next task",
    "stable build, clear next steps",
    "pipeline is green across the board",
    "productivity is quietly elite today",
    "signal high, noise low",
    "smooth handoff, smooth release",
  ],
} as const;

const DIALOGUE_MODES = Object.keys(DIALOGUE_PRESETS) as Array<keyof typeof DIALOGUE_PRESETS>;
const COLLISION_PHRASES = ["sorry oops", "watch out", "oops, my bad", "pardon me", "did not see you there"];

type AgentRuntime = Agent & {
  x: number;
  y: number;
  yTarget: number;
  ySpeed: number;
  avoidThomasBias: number;
  collisionCooldown: number;
  bonkTimer: number;
  collisionPhrase: string | null;
  collisionSpeakTimer: number;
  direction: -1 | 1;
  fleeing: boolean;
  fleeDirection: -1 | 1;
  fleeBoost: number;
  jumping: boolean;
};

const MIN_X = 2;
const MAX_X = 98;
const ROAM_MIN_X = -12;
const ROAM_MAX_X = 112;
const FLEE_MIN_X = -20;
const FLEE_MAX_X = 120;
const FLEE_SPEED = 86;
const MIN_Y = 14;
const MAX_Y = 90;
const MOBILE_MIN_Y = 64;
const MOBILE_MAX_Y = 90;
const TALK_SAFE_X_MIN = 14;
const TALK_SAFE_X_MAX = 86;
const TALK_SAFE_Y_MIN = 12;
const TALK_SAFE_Y_MAX = 92;
const THOMAS_ZONE_X_MIN = 30;
const THOMAS_ZONE_X_MAX = 70;
const THOMAS_ZONE_Y_MIN = 34;
const THOMAS_ZONE_Y_MAX = 62;
const THOMAS_ZONE_CENTER_X = (THOMAS_ZONE_X_MIN + THOMAS_ZONE_X_MAX) / 2;
const THOMAS_ZONE_CENTER_Y = (THOMAS_ZONE_Y_MIN + THOMAS_ZONE_Y_MAX) / 2;

function randomBetween(min: number, max: number) {
  return min + Math.random() * (max - min);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function isInsideThomasZone(x: number, y: number) {
  return x >= THOMAS_ZONE_X_MIN && x <= THOMAS_ZONE_X_MAX && y >= THOMAS_ZONE_Y_MIN && y <= THOMAS_ZONE_Y_MAX;
}

function canSpeakAtPosition(x: number, y: number) {
  return x >= TALK_SAFE_X_MIN && x <= TALK_SAFE_X_MAX && y >= TALK_SAFE_Y_MIN && y <= TALK_SAFE_Y_MAX;
}

function pickYTargetWithAvoidance(x: number, minY: number, maxY: number, avoidThomasBias: number) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const candidate = randomBetween(minY, maxY);
    if (!isInsideThomasZone(x, candidate)) return candidate;
    if (Math.random() > avoidThomasBias) return candidate;
  }
  return randomBetween(minY, maxY);
}

function seedRuntime(): AgentRuntime[] {
  const step = AGENTS.length > 1 ? (MAX_X - MIN_X) / (AGENTS.length - 1) : 0;
  return AGENTS.map((agent, index) => ({
    ...agent,
    x: MIN_X + index * step,
    y: agent.startY,
    yTarget: pickYTargetWithAvoidance(MIN_X + index * step, MIN_Y, MAX_Y, 0.82),
    ySpeed: 6.2 + Math.random() * 3.1,
    avoidThomasBias: randomBetween(0.62, 0.9),
    collisionCooldown: 0,
    bonkTimer: 0,
    collisionPhrase: null,
    collisionSpeakTimer: 0,
    direction: index % 2 === 0 ? 1 : -1,
    fleeing: false,
    fleeDirection: 1,
    fleeBoost: 1,
    jumping: false,
  }));
}

export function PixelAgents() {
  const [agents, setAgents] = useState<AgentRuntime[]>(() => seedRuntime());
  const [speakerId, setSpeakerId] = useState<string | null>(null);
  const [typedPhrase, setTypedPhrase] = useState("");
  const [dialogueEnabled, setDialogueEnabled] = useState(true);
  const speakerIdRef = useRef<string | null>(null);
  const agentsRef = useRef<AgentRuntime[]>(agents);
  const jumpTimeouts = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const yBoundsRef = useRef({ min: MIN_Y, max: MAX_Y });

  useEffect(() => {
    agentsRef.current = agents;
  }, [agents]);

  useEffect(() => {
    speakerIdRef.current = speakerId;
  }, [speakerId]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 760px)");
    const onChange = () => {
      const nextBounds = media.matches ? { min: MOBILE_MIN_Y, max: MOBILE_MAX_Y } : { min: MIN_Y, max: MAX_Y };
      yBoundsRef.current = nextBounds;
      setAgents((current) =>
        current.map((agent) => ({
          ...agent,
          y: clamp(agent.y, nextBounds.min, nextBounds.max),
          yTarget: clamp(agent.yTarget, nextBounds.min, nextBounds.max),
        })),
      );
    };

    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => {
      const enabled = !media.matches;
      setDialogueEnabled(enabled);
      if (!enabled) {
        setSpeakerId(null);
        setTypedPhrase("");
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

      const { min: minY, max: maxY } = yBoundsRef.current;
      let shouldInterruptRegularSpeech = false;

      setAgents((current) => {
        const next = current.map((agent) => {
          let x = agent.x;
          let y = agent.y;
          let yTarget = agent.yTarget;
          let direction = agent.direction;
          let fleeing = agent.fleeing;
          let fleeBoost = agent.fleeBoost;
          let collisionCooldown = Math.max(0, agent.collisionCooldown - delta);
          let bonkTimer = Math.max(0, agent.bonkTimer - delta);
          let collisionSpeakTimer = Math.max(0, agent.collisionSpeakTimer - delta);
          let collisionPhrase = collisionSpeakTimer > 0 ? agent.collisionPhrase : null;

          if (collisionSpeakTimer > 0 && !canSpeakAtPosition(x, y)) {
            collisionSpeakTimer = 0;
            collisionPhrase = null;
          }

          if (Math.abs(yTarget - y) < 0.7) {
            yTarget = pickYTargetWithAvoidance(x, minY, maxY, agent.avoidThomasBias);
          }

          const verticalDirection = Math.sign(yTarget - y);
          if (verticalDirection !== 0) {
            y += verticalDirection * agent.ySpeed * delta;
            if ((verticalDirection > 0 && y > yTarget) || (verticalDirection < 0 && y < yTarget)) {
              y = yTarget;
            }
          }

          y = clamp(y, minY, maxY);

          if (fleeing) {
            x += agent.fleeDirection * FLEE_SPEED * fleeBoost * delta;
            if (x < FLEE_MIN_X || x > FLEE_MAX_X) {
              x = agent.fleeDirection > 0 ? MIN_X + Math.random() * 7 : MAX_X - Math.random() * 7;
              y = pickYTargetWithAvoidance(x, minY, maxY, agent.avoidThomasBias);
              yTarget = pickYTargetWithAvoidance(x, minY, maxY, agent.avoidThomasBias);
              direction = agent.fleeDirection > 0 ? 1 : -1;
              fleeing = false;
              fleeBoost = 1;
            }
            return {
              ...agent,
              x,
              y,
              yTarget,
              collisionCooldown,
              bonkTimer,
              collisionPhrase,
              collisionSpeakTimer,
              direction,
              fleeing,
              fleeBoost,
              jumping: fleeing ? agent.jumping : false,
            };
          }

          if (speakerIdRef.current === agent.id && collisionSpeakTimer <= 0) {
            return agent;
          }

          if (collisionSpeakTimer > 0) {
            return {
              ...agent,
              x,
              y,
              yTarget,
              collisionCooldown,
              bonkTimer,
              collisionPhrase,
              collisionSpeakTimer,
              direction,
            };
          }

          if (isInsideThomasZone(x, y) && Math.random() < agent.avoidThomasBias) {
            const escapeDirection: -1 | 1 = x >= THOMAS_ZONE_CENTER_X ? 1 : -1;
            direction = escapeDirection;
            x += escapeDirection * agent.speed * 0.95 * delta;
            if (Math.random() < 0.36) {
              const yEscape =
                y < THOMAS_ZONE_CENTER_Y
                  ? THOMAS_ZONE_Y_MIN - randomBetween(2.5, 8)
                  : THOMAS_ZONE_Y_MAX + randomBetween(2.5, 8);
              yTarget = clamp(yEscape, minY, maxY);
            }
          }

          const speedScale = bonkTimer > 0 ? 0.38 : 1;
          x += direction * agent.speed * speedScale * delta;
          if (x > ROAM_MAX_X) {
            x = ROAM_MAX_X;
            direction = -1;
          } else if (x < ROAM_MIN_X) {
            x = ROAM_MIN_X;
            direction = 1;
          }

          return {
            ...agent,
            x,
            y,
            yTarget,
            collisionCooldown,
            bonkTimer,
            collisionPhrase,
            collisionSpeakTimer,
            direction,
          };
        });

        for (let i = 0; i < next.length; i += 1) {
          for (let j = i + 1; j < next.length; j += 1) {
            const a = next[i];
            const b = next[j];
            if (a.fleeing || b.fleeing) continue;
            if (a.collisionCooldown > 0 || b.collisionCooldown > 0) continue;
            const dx = Math.abs(a.x - b.x);
            const dy = Math.abs(a.y - b.y);
            if (dx > 4.9 || dy > 7.5) continue;

            const leftIndex = a.x <= b.x ? i : j;
            const rightIndex = leftIndex === i ? j : i;
            const left = next[leftIndex];
            const right = next[rightIndex];

            left.direction = -1;
            right.direction = 1;
            const center = (left.x + right.x) / 2;
            left.x = center - 2.35;
            right.x = center + 2.35;
            left.yTarget = clamp(left.y - 7, minY, maxY);
            right.yTarget = clamp(right.y + 7, minY, maxY);
            left.bonkTimer = 0.58;
            right.bonkTimer = 0.58;
            left.collisionCooldown = 1.3;
            right.collisionCooldown = 1.3;

            const speaker = Math.abs(left.x - 50) <= Math.abs(right.x - 50) ? left : right;
            if (canSpeakAtPosition(speaker.x, speaker.y)) {
              speaker.collisionPhrase = COLLISION_PHRASES[Math.floor(Math.random() * COLLISION_PHRASES.length)];
              speaker.collisionSpeakTimer = 1.35;
            } else {
              speaker.collisionPhrase = null;
              speaker.collisionSpeakTimer = 0;
            }

            if (speakerIdRef.current === speaker.id) {
              shouldInterruptRegularSpeech = true;
            }
          }
        }

        return next;
      });

      if (shouldInterruptRegularSpeech) {
        setSpeakerId(null);
        setTypedPhrase("");
      }

      frameId = requestAnimationFrame(tick);
    };

    frameId = requestAnimationFrame(tick);
    return () => {
      if (frameId) cancelAnimationFrame(frameId);
    };
  }, []);

  useEffect(() => {
    let speakTimer: ReturnType<typeof setTimeout> | undefined;
    let typeTimer: ReturnType<typeof setInterval> | undefined;
    let cancelled = false;

    const schedule = (ms: number) => {
      if (speakTimer) clearTimeout(speakTimer);
      speakTimer = setTimeout(startSpeaking, ms);
    };

    const stopSpeaking = () => {
      if (typeTimer) clearInterval(typeTimer);
      setSpeakerId(null);
      setTypedPhrase("");
    };

    const startSpeaking = () => {
      if (cancelled || !dialogueEnabled) return;
      const activeAgents = agentsRef.current.filter((agent) => !agent.fleeing && agent.collisionSpeakTimer <= 0);
      if (activeAgents.length === 0) {
        schedule(1800);
        return;
      }

      const speakableAgents = activeAgents.filter((agent) => canSpeakAtPosition(agent.x, agent.y));
      if (speakableAgents.length === 0) {
        schedule(1800);
        return;
      }

      const centeredAgents = speakableAgents.filter((agent) => agent.x > 22 && agent.x < 78);
      const speakerPool = centeredAgents.length > 0 ? centeredAgents : speakableAgents;
      const chosen = speakerPool[Math.floor(Math.random() * speakerPool.length)];
      const mode = DIALOGUE_MODES[Math.floor(Math.random() * DIALOGUE_MODES.length)];
      const preset = DIALOGUE_PRESETS[mode];
      const phrase = preset[Math.floor(Math.random() * preset.length)];
      setSpeakerId(chosen.id);
      setTypedPhrase("");

      let index = 0;
      if (typeTimer) clearInterval(typeTimer);
      typeTimer = setInterval(() => {
        index += 1;
        setTypedPhrase(phrase.slice(0, index));
        if (index >= phrase.length) {
          if (typeTimer) clearInterval(typeTimer);
          speakTimer = setTimeout(() => {
            stopSpeaking();
            schedule(3200 + Math.floor(Math.random() * 2300));
          }, 1300);
        }
      }, 40);
    };

    if (dialogueEnabled) {
      schedule(INITIAL_DIALOGUE_DELAY_MS);
    } else {
      stopSpeaking();
    }

    return () => {
      cancelled = true;
      if (speakTimer) clearTimeout(speakTimer);
      if (typeTimer) clearInterval(typeTimer);
    };
  }, [dialogueEnabled]);

  useEffect(() => {
    return () => {
      jumpTimeouts.current.forEach((timerId) => clearTimeout(timerId));
      jumpTimeouts.current.clear();
    };
  }, []);

  const handleAgentClick = (agentId: string) => {
    setAgents((current) =>
      current.map((agent) => {
        if (agent.id !== agentId) return agent;
        const fleeDirection = agent.fleeing ? agent.fleeDirection : agent.x >= 50 ? 1 : -1;
        return {
          ...agent,
          fleeing: true,
          jumping: true,
          fleeDirection,
          direction: fleeDirection,
          fleeBoost: 1.85,
          collisionPhrase: null,
          collisionSpeakTimer: 0,
        };
      }),
    );

    if (speakerIdRef.current === agentId) {
      setSpeakerId(null);
      setTypedPhrase("");
    }

    const existing = jumpTimeouts.current.get(agentId);
    if (existing) clearTimeout(existing);
    const timeoutId = setTimeout(() => {
      setAgents((current) =>
        current.map((agent) => (agent.id === agentId ? { ...agent, jumping: false } : agent)),
      );
      jumpTimeouts.current.delete(agentId);
    }, 650);
    jumpTimeouts.current.set(agentId, timeoutId);
  };

  return (
    <div className="pixel-agents">
      {agents.map((agent) => {
        const talkSafe = canSpeakAtPosition(agent.x, agent.y);
        const collisionText = talkSafe && agent.collisionSpeakTimer > 0 && agent.collisionPhrase ? agent.collisionPhrase : null;
        const isSpeaking = dialogueEnabled && talkSafe ? (collisionText ? true : speakerId === agent.id) : false;
        const facingLeft = agent.direction < 0 && !isSpeaking;
        const trackClass = `pixel-agent-track${agent.fleeing ? " is-fleeing" : ""}`;
        const hitboxClass = `pixel-agent-hitbox${agent.jumping ? " is-jumping" : ""}${agent.bonkTimer > 0 ? " is-bonking" : ""}`;
        const bubbleHorizontal = agent.x < 40 ? "bubble-right" : agent.x > 60 ? "bubble-left" : "bubble-center";
        const bubbleVertical = agent.y < 28 ? "bubble-below" : "bubble-above";
        const agentClass = [
          `pixel-agent pixel-agent-${agent.tint}`,
          facingLeft ? "facing-left" : "",
          isSpeaking ? "looking-user" : "",
          agent.bonkTimer > 0 ? "is-bonking" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <div
            key={agent.id}
            className={trackClass}
            style={{
              top: `${agent.y}%`,
              left: `${agent.x}%`,
            }}
          >
            {isSpeaking ? (
              <div className={`pixel-agent-bubble ${bubbleHorizontal} ${bubbleVertical}`}>
                {collisionText ? <span>{collisionText}</span> : <span className="typewriter">{typedPhrase}</span>}
              </div>
            ) : null}
            <button
              type="button"
              className={hitboxClass}
              aria-label={`${agent.id} pixel agent`}
              onClick={() => handleAgentClick(agent.id)}
            >
              <span className={agentClass}>
                <span className="agent-head">
                  <span className="agent-eye agent-eye-left" />
                  <span className="agent-eye agent-eye-right" />
                </span>
                <span className="agent-body" />
                <span className="agent-leg agent-leg-left" />
                <span className="agent-leg agent-leg-right" />
              </span>
            </button>
          </div>
        );
      })}
    </div>
  );
}
