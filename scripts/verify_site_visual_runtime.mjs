#!/usr/bin/env node
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";
import fs from "node:fs/promises";
import { createRequire } from "node:module";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const siteDir = path.join(repoRoot, "apps", "site");
const siteRequire = createRequire(path.join(siteDir, "package.json"));
const { chromium } = siteRequire("playwright");

function parseArgs(argv) {
  const options = {
    host: "127.0.0.1",
    port: 3108,
    timeoutMs: 180000,
    viewportWidth: 1424,
    viewportHeight: 768,
    skipBuild: false,
    outputDir: path.join(repoRoot, "output", "site-visual-proof"),
    reportPath: path.join(repoRoot, "output", "site-visual-proof", "runtime-report.json"),
  };

  for (let i = 0; i < argv.length; i += 1) {
    const raw = String(argv[i] ?? "");
    if (raw === "--host") {
      options.host = String(argv[i + 1] ?? options.host);
      i += 1;
      continue;
    }
    if (raw === "--port") {
      options.port = Number(argv[i + 1] ?? options.port);
      i += 1;
      continue;
    }
    if (raw === "--timeout-ms") {
      options.timeoutMs = Number(argv[i + 1] ?? options.timeoutMs);
      i += 1;
      continue;
    }
    if (raw === "--output-dir") {
      options.outputDir = path.resolve(String(argv[i + 1] ?? options.outputDir));
      i += 1;
      continue;
    }
    if (raw === "--report") {
      options.reportPath = path.resolve(String(argv[i + 1] ?? options.reportPath));
      i += 1;
      continue;
    }
    if (raw === "--viewport-width") {
      options.viewportWidth = Number(argv[i + 1] ?? options.viewportWidth);
      i += 1;
      continue;
    }
    if (raw === "--viewport-height") {
      options.viewportHeight = Number(argv[i + 1] ?? options.viewportHeight);
      i += 1;
      continue;
    }
    if (raw === "--skip-build") {
      options.skipBuild = true;
      continue;
    }
  }

  if (!Number.isFinite(options.port) || options.port <= 0) {
    throw new Error(`Invalid --port value: ${options.port}`);
  }
  if (!Number.isFinite(options.timeoutMs) || options.timeoutMs < 1000) {
    throw new Error(`Invalid --timeout-ms value: ${options.timeoutMs}`);
  }
  return options;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizePath(p) {
  return String(p).replace(/\\/g, "/");
}

function relRepoPath(absPath) {
  return normalizePath(path.relative(repoRoot, absPath));
}

async function waitForHttpReady(url, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 1200);
      const response = await fetch(url, {
        method: "GET",
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (response.ok) {
        return;
      }
    } catch {
      // Keep polling until timeout.
    }
    await sleep(500);
  }
  throw new Error(`Timed out waiting for site readiness at ${url}`);
}

async function stopServer(child) {
  if (!child || child.exitCode !== null) {
    return;
  }

  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
      killer.on("exit", () => resolve());
      killer.on("error", () => resolve());
    });
    return;
  }

  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", () => resolve())),
    sleep(4000),
  ]);
  if (child.exitCode === null) {
    child.kill("SIGKILL");
  }
}

async function runCommand(cmd, args, { cwd, env, timeoutMs, label }) {
  const logs = [];
  const child = spawn(cmd, args, {
    cwd,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    shell: process.platform === "win32",
  });

  const onData = (chunk) => {
    const text = String(chunk ?? "").trimEnd();
    if (!text) {
      return;
    }
    logs.push(text);
    if (logs.length > 240) {
      logs.shift();
    }
  };

  child.stdout?.on("data", onData);
  child.stderr?.on("data", onData);

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    if (child.exitCode === null) {
      child.kill();
    }
  }, timeoutMs);

  const exitCode = await new Promise((resolve) => {
    child.once("exit", (code) => resolve(code ?? 1));
    child.once("error", () => resolve(1));
  });

  clearTimeout(timer);
  if (exitCode !== 0) {
    const suffix = logs.length > 0 ? `\n${logs.slice(-30).join("\n")}` : "";
    if (timedOut) {
      throw new Error(`${label} timed out after ${timeoutMs}ms.${suffix}`);
    }
    throw new Error(`${label} failed with exit code ${exitCode}.${suffix}`);
  }
}

function parseMetricNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

function evaluateAssertions(metrics) {
  const footerTop = parseMetricNumber(metrics.footer_top);
  const bandTop = parseMetricNumber(metrics.band_top);
  const bandHeight = parseMetricNumber(metrics.band_height);
  const viewportWidth = parseMetricNumber(metrics.viewport_width);
  const rootScrollWidth = parseMetricNumber(metrics.root_scroll_width);
  const consoleErrorCount = parseMetricNumber(metrics.console_error_count);
  const brokenImageCount = parseMetricNumber(metrics.broken_image_count);
  const hasNav = metrics.has_nav === true;
  const hasMain = metrics.has_main === true;
  const hasFooter = metrics.has_footer === true;
  const riders = Array.isArray(metrics.riders) ? metrics.riders : [];

  const coreLayoutPresent = hasNav && hasMain && hasFooter;
  const noConsoleRuntimeErrors = consoleErrorCount !== null && consoleErrorCount === 0;
  const noBrokenImages = brokenImageCount !== null && brokenImageCount === 0;
  const bandOnFooterBorder =
    footerTop !== null && bandTop !== null && Math.abs(bandTop - footerTop) <= 3;
  const noBandStripHeight = bandHeight !== null && Math.round(bandHeight) === 0;
  const ridersMountedOnBack =
    riders.length > 0 &&
    riders.every((rider) => {
      const saddleTop = parseMetricNumber(rider.saddle_top);
      const saddleBottom = parseMetricNumber(rider.saddle_bottom);
      const robotBodyTop = parseMetricNumber(rider.robot_body_top);
      if (saddleTop === null || saddleBottom === null || robotBodyTop === null) {
        return false;
      }
      // Rider torso should start at or just below saddle height so it reads
      // as seated on the dino back, not floating above it.
      return robotBodyTop >= saddleTop - 2 && robotBodyTop <= saddleBottom + 4;
    });
  const ridersSeatContactStable =
    riders.length > 0 &&
    riders.every((rider) => {
      const saddleTop = parseMetricNumber(rider.saddle_top);
      const robotBodyBottom = parseMetricNumber(rider.robot_body_bottom);
      if (saddleTop === null || robotBodyBottom === null) {
        return false;
      }
      const bottomOffset = robotBodyBottom - saddleTop;
      // Rider body should sit near saddle top, not float high or hang down
      // like it's walking beside the dino.
      return bottomOffset >= -6 && bottomOffset <= 16;
    });
  const ridersCenteredOnSaddle =
    riders.length > 0 &&
    riders.every((rider) => {
      const saddleLeft = parseMetricNumber(rider.saddle_left);
      const saddleRight = parseMetricNumber(rider.saddle_right);
      const robotBodyLeft = parseMetricNumber(rider.robot_body_left);
      const robotBodyRight = parseMetricNumber(rider.robot_body_right);
      const robotBodyCenterX = parseMetricNumber(rider.robot_body_center_x);
      if (
        saddleLeft === null ||
        saddleRight === null ||
        robotBodyLeft === null ||
        robotBodyRight === null ||
        robotBodyCenterX === null
      ) {
        return false;
      }
      const saddleCenterX = saddleLeft + (saddleRight - saddleLeft) / 2;
      const centered = Math.abs(robotBodyCenterX - saddleCenterX) <= 4;
      const overlapsSaddle =
        robotBodyRight >= saddleLeft + 1 && robotBodyLeft <= saddleRight - 1;
      return centered && overlapsSaddle;
    });
  const ridersRobotClearlyVisible =
    riders.length > 0 &&
    riders.every((rider) => {
      const trackTop = parseMetricNumber(rider.track_top);
      const trackBottom = parseMetricNumber(rider.track_bottom);
      const robotTop = parseMetricNumber(rider.robot_top);
      const robotBottom = parseMetricNumber(rider.robot_bottom);
      const robotWidth = parseMetricNumber(rider.robot_width);
      const robotHeight = parseMetricNumber(rider.robot_height);
      if (
        trackTop === null ||
        trackBottom === null ||
        robotTop === null ||
        robotBottom === null ||
        robotWidth === null ||
        robotHeight === null
      ) {
        return false;
      }
      const intersectsTrack = robotBottom > trackTop + 1 && robotTop < trackBottom - 1;
      return robotWidth >= 12 && robotHeight >= 10 && intersectsTrack;
    });
  const noHorizontalDragOverflow =
    viewportWidth !== null &&
    rootScrollWidth !== null &&
    rootScrollWidth <= viewportWidth + 1;

  return {
    core_layout_present: coreLayoutPresent,
    no_console_runtime_errors: noConsoleRuntimeErrors,
    no_broken_images: noBrokenImages,
    band_on_footer_border: bandOnFooterBorder,
    no_band_strip_height: noBandStripHeight,
    riders_mounted_on_back: ridersMountedOnBack,
    riders_seat_contact_stable: ridersSeatContactStable,
    riders_centered_on_saddle: ridersCenteredOnSaddle,
    riders_robot_clearly_visible: ridersRobotClearlyVisible,
    no_horizontal_drag_overflow: noHorizontalDragOverflow,
  };
}

function failingAssertions(assertions) {
  return Object.entries(assertions)
    .filter(([, value]) => value !== true)
    .map(([key]) => key);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const serverUrl = `http://${opts.host}:${opts.port}`;
  const npmExec = "npm";
  const serverLogs = [];

  await fs.mkdir(opts.outputDir, { recursive: true });
  await fs.mkdir(path.dirname(opts.reportPath), { recursive: true });
  const commandEnv = {
    ...process.env,
    NEXT_TELEMETRY_DISABLED: "1",
    CI: "1",
  };
  if (!opts.skipBuild) {
    await runCommand(npmExec, ["run", "build"], {
      cwd: siteDir,
      env: commandEnv,
      timeoutMs: Math.max(opts.timeoutMs, 300000),
      label: "Site build",
    });
  }

  const devServer = spawn(
    npmExec,
    ["run", "start", "--", "--hostname", opts.host, "--port", String(opts.port)],
    {
      cwd: siteDir,
      env: commandEnv,
      stdio: ["ignore", "pipe", "pipe"],
      shell: process.platform === "win32",
    },
  );

  const pushLog = (chunk) => {
    const line = String(chunk ?? "").trimEnd();
    if (!line) {
      return;
    }
    serverLogs.push(line);
    if (serverLogs.length > 120) {
      serverLogs.shift();
    }
  };

  devServer.stdout?.on("data", pushLog);
  devServer.stderr?.on("data", pushLog);

  let browser;
  try {
    await waitForHttpReady(serverUrl, opts.timeoutMs);

    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: opts.viewportWidth, height: opts.viewportHeight },
      reducedMotion: "reduce",
      colorScheme: "dark",
    });

    // Deterministic Math.random for stable rider positions and screenshots.
    await context.addInitScript(() => {
      let seed = 246813579;
      Math.random = () => {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        return seed / 4294967296;
      };
    });

    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });
    page.on("pageerror", (err) => {
      pageErrors.push(String(err));
    });
    await page.goto(serverUrl, { waitUntil: "networkidle", timeout: opts.timeoutMs });
    await page.waitForSelector(".footer-shell", { timeout: opts.timeoutMs });
    await page.waitForSelector(".dino-riders-band", {
      state: "attached",
      timeout: opts.timeoutMs,
    });

    const fullPageShot = path.join(opts.outputDir, "full-page.png");
    const footerShot = path.join(opts.outputDir, "footer-focus.png");

    await page.screenshot({
      path: fullPageShot,
      fullPage: true,
      type: "png",
    });

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(300);

    await page.screenshot({
      path: footerShot,
      type: "png",
    });

    const metrics = await page.evaluate(() => {
      const footer = document.querySelector(".footer-shell");
      const band = document.querySelector(".dino-riders-band");
      const allTracks = Array.from(document.querySelectorAll(".dino-rider-track"));
      const visibleTracks = allTracks.filter((track) => {
        const rect = track.getBoundingClientRect();
        return rect.right > 10 && rect.left < window.innerWidth - 10;
      });
      const tracks = (visibleTracks.length > 0 ? visibleTracks : allTracks).slice(0, 4);
      const riders = tracks.map((track) => {
        const saddle = track.querySelector(".trex-saddle");
        // Measure the actual robot sprite, not just the wrapper container.
        const robot =
          track.querySelector(".dino-rider-robot") ?? track.querySelector(".dino-rider-robot-wrap");
        const robotBody = track.querySelector(".dino-rider-robot .agent-body");
        const trackRect = track.getBoundingClientRect();
        const saddleRect = saddle?.getBoundingClientRect();
        const robotRect = robot?.getBoundingClientRect();
        const robotBodyRect = robotBody?.getBoundingClientRect();
        const robotCenterX = robotRect ? robotRect.left + robotRect.width / 2 : null;
        const robotBodyCenterX = robotBodyRect ? robotBodyRect.left + robotBodyRect.width / 2 : null;
        return {
          track_top: Math.round(trackRect.top),
          track_bottom: Math.round(trackRect.bottom),
          saddle_top: saddleRect ? Math.round(saddleRect.top) : null,
          saddle_bottom: saddleRect ? Math.round(saddleRect.bottom) : null,
          saddle_left: saddleRect ? Math.round(saddleRect.left) : null,
          saddle_right: saddleRect ? Math.round(saddleRect.right) : null,
          robot_top: robotRect ? Math.round(robotRect.top) : null,
          robot_bottom: robotRect ? Math.round(robotRect.bottom) : null,
          robot_left: robotRect ? Math.round(robotRect.left) : null,
          robot_right: robotRect ? Math.round(robotRect.right) : null,
          robot_center_x: robotCenterX !== null ? Math.round(robotCenterX) : null,
          robot_width: robotRect ? Math.round(robotRect.width) : null,
          robot_height: robotRect ? Math.round(robotRect.height) : null,
          robot_body_top: robotBodyRect ? Math.round(robotBodyRect.top) : null,
          robot_body_bottom: robotBodyRect ? Math.round(robotBodyRect.bottom) : null,
          robot_body_left: robotBodyRect ? Math.round(robotBodyRect.left) : null,
          robot_body_right: robotBodyRect ? Math.round(robotBodyRect.right) : null,
          robot_body_center_x: robotBodyCenterX !== null ? Math.round(robotBodyCenterX) : null,
          robot_body_width: robotBodyRect ? Math.round(robotBodyRect.width) : null,
          robot_body_height: robotBodyRect ? Math.round(robotBodyRect.height) : null,
        };
      });

      const footerRect = footer?.getBoundingClientRect();
      const bandRect = band?.getBoundingClientRect();
      return {
        has_nav: Boolean(document.querySelector(".nav-shell")),
        has_main: Boolean(document.querySelector("main.page-shell")),
        has_footer: Boolean(document.querySelector(".footer-shell")),
        broken_image_count: Array.from(document.images).filter(
          (img) => img.complete && img.naturalWidth === 0,
        ).length,
        viewport_width: Math.round(window.innerWidth),
        root_scroll_width: Math.round(
          Math.max(
            document.documentElement?.scrollWidth ?? 0,
            document.body?.scrollWidth ?? 0,
          ),
        ),
        footer_top: footerRect ? Math.round(footerRect.top) : null,
        band_top: bandRect ? Math.round(bandRect.top) : null,
        band_height: bandRect ? Math.round(bandRect.height) : null,
        riders,
      };
    });
    metrics.console_error_count = consoleErrors.length + pageErrors.length;
    metrics.console_error_samples = [...consoleErrors, ...pageErrors].slice(0, 10);

    const assertions = evaluateAssertions(metrics);
    const failures = failingAssertions(assertions);
    const report = {
      captured_at_utc: new Date().toISOString(),
      target_url: serverUrl,
      viewport: {
        width: opts.viewportWidth,
        height: opts.viewportHeight,
      },
      screenshots: {
        full_page: relRepoPath(fullPageShot),
        footer_focus: relRepoPath(footerShot),
      },
      metrics,
      assertions,
    };

    await fs.writeFile(opts.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf-8");

    if (failures.length > 0) {
      throw new Error(`Visual runtime assertions failed: ${failures.join(", ")}`);
    }

    console.log("Site runtime visual verification: PASS");
    console.log(`- URL: ${serverUrl}`);
    console.log(`- report: ${relRepoPath(opts.reportPath)}`);
    console.log(`- screenshot full: ${relRepoPath(fullPageShot)}`);
    console.log(`- screenshot footer: ${relRepoPath(footerShot)}`);
    console.log(`- assertions: ${JSON.stringify(assertions)}`);
  } catch (error) {
    console.error("Site runtime visual verification: FAIL");
    console.error(`- reason: ${error instanceof Error ? error.message : String(error)}`);
    if (serverLogs.length > 0) {
      console.error("- recent server logs:");
      for (const line of serverLogs.slice(-20)) {
        console.error(`  ${line}`);
      }
    }
    throw error;
  } finally {
    if (browser) {
      await browser.close();
    }
    await stopServer(devServer);
  }
}

main().catch((error) => {
  process.exit(1);
});
