(() => {
  "use strict";

  const canvas = document.getElementById("game");
  const ctx = canvas.getContext("2d");
  const WIDTH = canvas.width;
  const HEIGHT = canvas.height;
  const keys = new Set();
  const pressed = new Set();
  const pointer = { x: 0, y: 0 };

  const palette = {
    ink: "#151816",
    grid: "#2d342e",
    lane: "#273329",
    laneEdge: "#566153",
    text: "#f4f0e4",
    muted: "#bab4a7",
    yellow: "#f7c64a",
    orange: "#d76e2c",
    teal: "#67dbc7",
    green: "#8fc96b",
    red: "#e0644f",
    blue: "#5f8fd7",
    violet: "#8c7adb",
    shadow: "rgba(0, 0, 0, 0.35)",
  };

  const basePackets = [
    { id: "north-cache", x: 154, y: 142, r: 13, value: 120 },
    { id: "glass-node", x: 812, y: 124, r: 13, value: 120 },
    { id: "switch-yard", x: 482, y: 222, r: 13, value: 140 },
    { id: "coil-market", x: 252, y: 420, r: 13, value: 140 },
    { id: "relay-five", x: 716, y: 392, r: 13, value: 160 },
    { id: "south-cache", x: 454, y: 520, r: 13, value: 180 },
  ];

  const droneRoutes = [
    { id: "alpha", x: 230, y: 242, r: 19, axis: "x", min: 122, max: 582, speed: 82, phase: 0, color: palette.red },
    { id: "bravo", x: 690, y: 226, r: 18, axis: "y", min: 104, max: 462, speed: 74, phase: 0.35, color: palette.violet },
    { id: "charlie", x: 410, y: 420, r: 20, axis: "x", min: 286, max: 824, speed: 94, phase: 0.62, color: palette.orange },
  ];

  const walls = [
    { x: 0, y: 0, w: WIDTH, h: 44 },
    { x: 0, y: HEIGHT - 44, w: WIDTH, h: 44 },
    { x: 0, y: 0, w: 44, h: HEIGHT },
    { x: WIDTH - 44, y: 0, w: 44, h: HEIGHT },
    { x: 184, y: 184, w: 190, h: 38 },
    { x: 586, y: 164, w: 38, h: 190 },
    { x: 116, y: 348, w: 214, h: 38 },
    { x: 534, y: 478, w: 238, h: 38 },
    { x: 424, y: 312, w: 44, h: 152 },
  ];

  const state = {
    mode: "menu",
    message: "",
    score: 0,
    collected: 0,
    elapsed: 0,
    shields: 3,
    dashCooldown: 0,
    dashTime: 0,
    flashTime: 0,
    cameraShake: 0,
    player: { x: 92, y: HEIGHT - 96, vx: 0, vy: 0, r: 17, facing: 0 },
    packets: [],
    drones: [],
    uplink: { x: WIDTH - 100, y: 92, r: 34, active: false },
  };

  const reset = () => {
    state.mode = "menu";
    state.message = "";
    state.score = 0;
    state.collected = 0;
    state.elapsed = 0;
    state.shields = 3;
    state.dashCooldown = 0;
    state.dashTime = 0;
    state.flashTime = 0;
    state.cameraShake = 0;
    state.player.x = 92;
    state.player.y = HEIGHT - 96;
    state.player.vx = 0;
    state.player.vy = 0;
    state.player.facing = -Math.PI / 4;
    state.packets = basePackets.map((packet) => ({ ...packet, collected: false, pulse: 0 }));
    state.drones = droneRoutes.map((drone) => ({ ...drone, t: drone.phase * Math.PI * 2, vx: 0, vy: 0 }));
    state.uplink.active = false;
  };

  const startGame = () => {
    reset();
    state.mode = "playing";
  };

  const circleRectCollision = (circle, rect) => {
    const nearX = Math.max(rect.x, Math.min(circle.x, rect.x + rect.w));
    const nearY = Math.max(rect.y, Math.min(circle.y, rect.y + rect.h));
    const dx = circle.x - nearX;
    const dy = circle.y - nearY;
    return dx * dx + dy * dy < circle.r * circle.r;
  };

  const resolveWalls = (entity, oldX, oldY) => {
    for (const wall of walls) {
      if (!circleRectCollision(entity, wall)) continue;
      entity.x = oldX;
      if (circleRectCollision(entity, wall)) {
        entity.x = oldX;
        entity.y = oldY;
      }
      if (circleRectCollision(entity, wall)) {
        entity.x = Math.max(44 + entity.r, Math.min(WIDTH - 44 - entity.r, entity.x));
        entity.y = Math.max(44 + entity.r, Math.min(HEIGHT - 44 - entity.r, entity.y));
      }
    }
  };

  const isDown = (...names) => names.some((name) => keys.has(name));

  const consumePressed = (...names) => {
    const hit = names.some((name) => pressed.has(name));
    for (const name of names) pressed.delete(name);
    return hit;
  };

  const updatePlaying = (dt) => {
    state.elapsed += dt;
    state.dashCooldown = Math.max(0, state.dashCooldown - dt);
    state.dashTime = Math.max(0, state.dashTime - dt);
    state.flashTime = Math.max(0, state.flashTime - dt);
    state.cameraShake = Math.max(0, state.cameraShake - dt * 18);

    let ax = 0;
    let ay = 0;
    if (isDown("ArrowLeft", "KeyA")) ax -= 1;
    if (isDown("ArrowRight", "KeyD")) ax += 1;
    if (isDown("ArrowUp", "KeyW")) ay -= 1;
    if (isDown("ArrowDown", "KeyS")) ay += 1;

    const length = Math.hypot(ax, ay);
    if (length > 0) {
      ax /= length;
      ay /= length;
      state.player.facing = Math.atan2(ay, ax);
    }

    if (consumePressed("Space") && state.dashCooldown <= 0 && length > 0) {
      state.dashTime = 0.18;
      state.dashCooldown = 1.15;
    }

    const speed = state.dashTime > 0 ? 330 : 178;
    state.player.vx = ax * speed;
    state.player.vy = ay * speed;

    const oldX = state.player.x;
    const oldY = state.player.y;
    state.player.x += state.player.vx * dt;
    state.player.y += state.player.vy * dt;
    resolveWalls(state.player, oldX, oldY);

    for (const packet of state.packets) {
      if (packet.collected) continue;
      packet.pulse += dt;
      const dx = state.player.x - packet.x;
      const dy = state.player.y - packet.y;
      if (Math.hypot(dx, dy) < state.player.r + packet.r) {
        packet.collected = true;
        state.collected += 1;
        state.score += packet.value;
        state.flashTime = 0.2;
      }
    }

    state.uplink.active = state.collected === state.packets.length;
    if (state.uplink.active) {
      const distance = Math.hypot(state.player.x - state.uplink.x, state.player.y - state.uplink.y);
      if (distance < state.player.r + state.uplink.r) {
        state.score += Math.max(250, Math.round(1200 - state.elapsed * 12));
        state.message = "Delivery complete";
        state.mode = "won";
      }
    }

    for (const drone of state.drones) {
      drone.t += dt * (drone.speed / 62);
      const mid = (drone.min + drone.max) / 2;
      const span = (drone.max - drone.min) / 2;
      const previousX = drone.x;
      const previousY = drone.y;
      const wave = Math.sin(drone.t);
      if (drone.axis === "x") {
        drone.x = mid + wave * span;
      } else {
        drone.y = mid + wave * span;
      }
      drone.vx = (drone.x - previousX) / Math.max(dt, 0.001);
      drone.vy = (drone.y - previousY) / Math.max(dt, 0.001);

      const dx = state.player.x - drone.x;
      const dy = state.player.y - drone.y;
      if (Math.hypot(dx, dy) < state.player.r + drone.r && state.flashTime <= 0.01) {
        state.shields -= 1;
        state.score = Math.max(0, state.score - 90);
        state.flashTime = 0.7;
        state.cameraShake = 1;
        const push = Math.atan2(dy, dx);
        state.player.x += Math.cos(push) * 32;
        state.player.y += Math.sin(push) * 32;
        resolveWalls(state.player, oldX, oldY);
        if (state.shields <= 0) {
          state.mode = "lost";
          state.message = "Courier offline";
        }
      }
    }
  };

  const update = (dt) => {
    if (consumePressed("Enter", "NumpadEnter") && state.mode !== "playing") {
      startGame();
      return;
    }
    if (consumePressed("KeyR")) {
      startGame();
      return;
    }
    if (state.mode === "playing") {
      updatePlaying(dt);
    }
  };

  const roundRect = (x, y, w, h, r) => {
    const radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  };

  const drawPanel = (x, y, w, h, alpha = 0.88) => {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = "#20241f";
    roundRect(x, y, w, h, 8);
    ctx.fill();
    ctx.strokeStyle = "rgba(244, 240, 228, 0.2)";
    ctx.stroke();
    ctx.restore();
  };

  const drawBackground = () => {
    const gradient = ctx.createLinearGradient(0, 0, WIDTH, HEIGHT);
    gradient.addColorStop(0, "#1b201b");
    gradient.addColorStop(0.48, "#222920");
    gradient.addColorStop(1, "#171a17");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    ctx.save();
    ctx.strokeStyle = palette.grid;
    ctx.lineWidth = 1;
    for (let x = 44; x < WIDTH; x += 32) {
      ctx.beginPath();
      ctx.moveTo(x, 44);
      ctx.lineTo(x, HEIGHT - 44);
      ctx.stroke();
    }
    for (let y = 44; y < HEIGHT; y += 32) {
      ctx.beginPath();
      ctx.moveTo(44, y);
      ctx.lineTo(WIDTH - 44, y);
      ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.fillStyle = palette.lane;
    ctx.strokeStyle = palette.laneEdge;
    ctx.lineWidth = 2;
    for (const wall of walls) {
      roundRect(wall.x, wall.y, wall.w, wall.h, 8);
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  };

  const drawPacket = (packet) => {
    if (packet.collected) return;
    const pulse = 1 + Math.sin(state.elapsed * 5 + packet.pulse) * 0.08;
    ctx.save();
    ctx.translate(packet.x, packet.y);
    ctx.scale(pulse, pulse);
    ctx.shadowColor = "rgba(247, 198, 74, 0.45)";
    ctx.shadowBlur = 16;
    ctx.fillStyle = palette.yellow;
    ctx.strokeStyle = "#fff5bd";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, -18);
    ctx.lineTo(17, 0);
    ctx.lineTo(0, 18);
    ctx.lineTo(-17, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#8d531c";
    ctx.fillRect(-4, -4, 8, 8);
    ctx.restore();
  };

  const drawUplink = () => {
    const { x, y, r, active } = state.uplink;
    ctx.save();
    ctx.translate(x, y);
    const pulse = 1 + Math.sin(state.elapsed * 4) * 0.08;
    ctx.strokeStyle = active ? palette.teal : "rgba(186, 180, 167, 0.38)";
    ctx.lineWidth = active ? 5 : 3;
    ctx.beginPath();
    ctx.arc(0, 0, r * pulse, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, r * 0.62, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = active ? "rgba(103, 219, 199, 0.28)" : "rgba(186, 180, 167, 0.12)";
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = active ? palette.teal : palette.muted;
    ctx.font = "700 13px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(active ? "UPLINK" : "LOCKED", 0, 5);
    ctx.restore();
  };

  const drawDrone = (drone) => {
    ctx.save();
    ctx.translate(drone.x, drone.y);
    ctx.shadowColor = "rgba(0, 0, 0, 0.45)";
    ctx.shadowBlur = 14;
    ctx.fillStyle = drone.color;
    ctx.beginPath();
    ctx.arc(0, 0, drone.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "#ffd9cd";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(-drone.r - 8, 0);
    ctx.lineTo(drone.r + 8, 0);
    ctx.moveTo(0, -drone.r - 8);
    ctx.lineTo(0, drone.r + 8);
    ctx.stroke();
    ctx.fillStyle = "#2a1514";
    ctx.beginPath();
    ctx.arc(0, 0, 7, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  };

  const drawPlayer = () => {
    const p = state.player;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.facing);
    if (state.flashTime > 0 && Math.floor(state.flashTime * 16) % 2 === 0) {
      ctx.globalAlpha = 0.58;
    }
    ctx.shadowColor = "rgba(103, 219, 199, 0.35)";
    ctx.shadowBlur = state.dashTime > 0 ? 24 : 10;
    ctx.fillStyle = palette.teal;
    ctx.beginPath();
    ctx.moveTo(22, 0);
    ctx.lineTo(-12, -15);
    ctx.lineTo(-7, 0);
    ctx.lineTo(-12, 15);
    ctx.closePath();
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#143c38";
    ctx.beginPath();
    ctx.arc(2, 0, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = palette.yellow;
    ctx.fillRect(-16, -5, 9, 10);
    ctx.restore();
  };

  const drawHud = () => {
    drawPanel(18, 18, 346, 58, 0.76);
    ctx.fillStyle = palette.text;
    ctx.font = "700 18px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(`Score ${state.score}`, 36, 43);
    ctx.font = "600 13px system-ui, sans-serif";
    ctx.fillStyle = palette.muted;
    ctx.fillText(`Packets ${state.collected}/${state.packets.length}`, 36, 64);
    ctx.fillText(`Shield ${state.shields}`, 158, 64);
    ctx.fillText(`Dash ${state.dashCooldown <= 0 ? "ready" : state.dashCooldown.toFixed(1)}`, 246, 64);

    drawPanel(WIDTH - 222, 18, 204, 58, 0.76);
    ctx.fillStyle = palette.muted;
    ctx.font = "600 13px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("WASD or arrows move", WIDTH - 36, 43);
    ctx.fillText("Space dash, F fullscreen", WIDTH - 36, 64);
  };

  const drawOverlay = () => {
    if (state.mode === "playing") return;
    drawPanel(220, 148, 520, 340, 0.94);
    ctx.textAlign = "center";
    ctx.fillStyle = palette.text;
    ctx.font = "800 44px system-ui, sans-serif";
    ctx.fillText("Circuit Courier", WIDTH / 2, 222);
    ctx.font = "600 18px system-ui, sans-serif";
    ctx.fillStyle = palette.muted;
    const lines =
      state.mode === "menu"
        ? [
            "Collect every data packet, dodge patrol drones,",
            "then reach the uplink in the upper-right corner.",
            "",
            "Enter starts. Arrows or WASD move. Space dashes.",
          ]
        : [
            state.message,
            `Final score: ${state.score}`,
            "",
            "Press Enter or R to run another delivery.",
          ];
    lines.forEach((line, index) => {
      ctx.fillText(line, WIDTH / 2, 272 + index * 30);
    });
    ctx.fillStyle = state.mode === "won" ? palette.teal : state.mode === "lost" ? palette.red : palette.yellow;
    ctx.font = "800 20px system-ui, sans-serif";
    ctx.fillText(state.mode === "menu" ? "Press Enter" : state.mode === "won" ? "Route cleared" : "Try again", WIDTH / 2, 426);
  };

  const render = () => {
    ctx.save();
    if (state.cameraShake > 0) {
      const shake = state.cameraShake * 4;
      ctx.translate(Math.sin(state.elapsed * 80) * shake, Math.cos(state.elapsed * 66) * shake);
    }
    drawBackground();
    drawUplink();
    for (const packet of state.packets) drawPacket(packet);
    for (const drone of state.drones) drawDrone(drone);
    drawPlayer();
    ctx.restore();
    drawHud();
    drawOverlay();
  };

  const normalizeKey = (event) => {
    if (event.code) return event.code;
    const key = event.key.length === 1 ? event.key.toUpperCase() : event.key;
    return key.startsWith("Arrow") ? key : `Key${key}`;
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    } else {
      document.documentElement.requestFullscreen().catch(() => {});
    }
  };

  window.addEventListener("keydown", (event) => {
    const code = normalizeKey(event);
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space"].includes(code)) {
      event.preventDefault();
    }
    if (code === "KeyF" && !pressed.has("KeyF")) {
      toggleFullscreen();
    }
    keys.add(code);
    pressed.add(code);
  });

  window.addEventListener("keyup", (event) => {
    keys.delete(normalizeKey(event));
  });

  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * WIDTH;
    pointer.y = ((event.clientY - rect.top) / rect.height) * HEIGHT;
  });

  canvas.addEventListener("pointerdown", () => {
    if (state.mode !== "playing") startGame();
  });

  const renderGameToText = () => {
    const visiblePackets = state.packets
      .filter((packet) => !packet.collected)
      .map((packet) => ({ id: packet.id, x: Math.round(packet.x), y: Math.round(packet.y), r: packet.r, value: packet.value }));
    const drones = state.drones.map((drone) => ({
      id: drone.id,
      x: Math.round(drone.x),
      y: Math.round(drone.y),
      r: drone.r,
      vx: Math.round(drone.vx),
      vy: Math.round(drone.vy),
    }));
    return JSON.stringify({
      coordinateSystem: "origin top-left, x right, y down, canvas 960x640",
      mode: state.mode,
      score: state.score,
      collected: state.collected,
      packetsRemaining: visiblePackets.length,
      elapsed: Number(state.elapsed.toFixed(2)),
      shields: state.shields,
      dashCooldown: Number(state.dashCooldown.toFixed(2)),
      player: {
        x: Math.round(state.player.x),
        y: Math.round(state.player.y),
        vx: Math.round(state.player.vx),
        vy: Math.round(state.player.vy),
        r: state.player.r,
      },
      packets: visiblePackets,
      drones,
      uplink: { ...state.uplink, active: state.uplink.active },
      pointer: { x: Math.round(pointer.x), y: Math.round(pointer.y) },
    });
  };

  window.render_game_to_text = renderGameToText;
  window.advanceTime = (ms) => {
    const steps = Math.max(1, Math.round(ms / (1000 / 60)));
    for (let i = 0; i < steps; i += 1) update(1 / 60);
    render();
    pressed.clear();
  };

  let last = performance.now();
  const frame = (now) => {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    update(dt);
    render();
    pressed.clear();
    requestAnimationFrame(frame);
  };

  reset();
  render();
  requestAnimationFrame(frame);
})();
