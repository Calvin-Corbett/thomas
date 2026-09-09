#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const siteRequire = createRequire(path.join(repoRoot, "apps", "site", "package.json"));
const { chromium } = siteRequire("playwright");

function parseArgs(argv) {
  const options = {
    url: "http://127.0.0.1:8899/",
    outputDir: path.join(repoRoot, "output", "chat-motion-proof"),
    frames: 12,
    intervalMs: 250,
    warmupMs: 1800,
    viewportWidth: 1600,
    viewportHeight: 1000,
    scenario: "",
    physics: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const raw = String(argv[i] ?? "");
    if (raw === "--url") {
      options.url = String(argv[i + 1] ?? options.url);
      i += 1;
    } else if (raw === "--output-dir") {
      options.outputDir = path.resolve(String(argv[i + 1] ?? options.outputDir));
      i += 1;
    } else if (raw === "--frames") {
      options.frames = Number(argv[i + 1] ?? options.frames);
      i += 1;
    } else if (raw === "--interval-ms") {
      options.intervalMs = Number(argv[i + 1] ?? options.intervalMs);
      i += 1;
    } else if (raw === "--warmup-ms") {
      options.warmupMs = Number(argv[i + 1] ?? options.warmupMs);
      i += 1;
    } else if (raw === "--viewport-width") {
      options.viewportWidth = Number(argv[i + 1] ?? options.viewportWidth);
      i += 1;
    } else if (raw === "--viewport-height") {
      options.viewportHeight = Number(argv[i + 1] ?? options.viewportHeight);
      i += 1;
    } else if (raw === "--scenario") {
      options.scenario = String(argv[i + 1] ?? options.scenario);
      i += 1;
    } else if (raw === "--physics") {
      options.physics = true;
    }
  }
  options.frames = Number.isFinite(options.frames) ? Math.max(4, options.frames) : 12;
  options.intervalMs = Number.isFinite(options.intervalMs) ? Math.max(80, options.intervalMs) : 250;
  options.warmupMs = Number.isFinite(options.warmupMs) ? Math.max(0, options.warmupMs) : 1800;
  return options;
}

function round(value) {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value) : null;
}

function round1(value) {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value * 10) / 10 : null;
}

function analyzeSamples(samples) {
  const snapshots = samples.map((sample) => sample?.snapshot || {});
  const primaryRows = snapshots
    .map((sample) => sample?.primary || null)
    .filter(Boolean);
  const actorRows = snapshots.flatMap((sample) => Array.isArray(sample?.actors) ? sample.actors : []);
  const worldModes = [...new Set(snapshots.map((sample) => String(sample?.worldMode || "")).filter(Boolean))];
  const directions = [];
  let inBoundsFailures = 0;
  let illegalIdleSurfaceFailures = 0;
  let transitionSurfaceFailures = 0;
  let facingMismatchCount = 0;
  let maxGroundStepPx = 0;
  let groundedStepCount = 0;
  let groundedStepTotal = 0;
  let maxLabelDriftPx = 0;
  let maxVisualCenterOffsetPx = 0;
  primaryRows.forEach((row, index) => {
    const snapshot = samples[index]?.snapshot || {};
    const bounds = snapshot?.bounds || null;
    const x = Number(row?.x || 0);
    const y = Number(row?.y || 0);
    maxLabelDriftPx = Math.max(maxLabelDriftPx, Math.abs(Number(row?.labelCenterOffsetPx || 0)));
    maxVisualCenterOffsetPx = Math.max(maxVisualCenterOffsetPx, Math.abs(Number(row?.visualCenterOffsetPx || 0)));
    if (bounds) {
      const maxX = Number(bounds.width || 0);
      const maxY = Number(bounds.height || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y) || x < -4 || x > (maxX + 4) || y < -4 || y > (maxY + 4)) {
        inBoundsFailures += 1;
      }
    }
    if (row.legalSurfaceLock !== true) {
      if (String(row.transitionKind || "")) {
        transitionSurfaceFailures += 1;
      } else {
        illegalIdleSurfaceFailures += 1;
      }
    }
    if (index === 0) return;
    const prev = primaryRows[index - 1];
    const dx = Number(row?.x || 0) - Number(prev?.x || 0);
    const direction = Math.abs(dx) >= 6 ? Math.sign(dx) : 0;
    directions.push(direction);
    if (!String(row?.transitionKind || "") && !String(prev?.transitionKind || "")) {
      const groundStepPx = Math.abs(dx);
      groundedStepCount += 1;
      groundedStepTotal += groundStepPx;
      maxGroundStepPx = Math.max(maxGroundStepPx, groundStepPx);
    }
    if (direction !== 0) {
      const transitioning = Boolean(String(row?.transitionKind || "") || String(prev?.transitionKind || ""));
      if (transitioning) {
        return;
      }
      const facing = String(row?.facing || "");
      const expectedFacing = direction > 0 ? "right" : "left";
      if (facing !== expectedFacing) {
        facingMismatchCount += 1;
      }
    }
  });
  const directionChanges = directions.reduce((count, direction, index) => {
    if (!direction || index === 0) return count;
    const prev = directions.slice(0, index).reverse().find(Boolean) || 0;
    return prev && prev !== direction ? count + 1 : count;
  }, 0);
  const facingChanges = primaryRows.reduce((count, row, index) => {
    if (index === 0) return count;
    return count + (row.facing !== primaryRows[index - 1].facing ? 1 : 0);
  }, 0);
  const movementPx = primaryRows.reduce((total, row, index) => {
    if (index === 0) return total;
    return total + Math.abs(Number(row.x || 0) - Number(primaryRows[index - 1].x || 0));
  }, 0);
  const legalSurfaceFailures = illegalIdleSurfaceFailures;
  const transitionKinds = [...new Set(primaryRows.map((row) => String(row.transitionKind || "")).filter(Boolean))];
  const platformIds = [...new Set(primaryRows.map((row) => String(row.currentPlatformId || "")).filter(Boolean))];
  const propKinds = [...new Set(actorRows.map((row) => String(row.propKind || "")).filter(Boolean))];
  const helperKinds = [...new Set(actorRows.filter((row) => String(row.kind || "") === "delegation").map((row) => String(row.name || "")).filter(Boolean))];
  return {
    frameCount: samples.length,
    worldModes,
    primarySampleCount: primaryRows.length,
    facingChanges,
    directionChanges,
    facingMismatchCount,
    movementPx: round(movementPx),
    averageGroundStepPx: round1(groundedStepCount ? groundedStepTotal / groundedStepCount : 0),
    maxGroundStepPx: round1(maxGroundStepPx),
    maxLabelDriftPx: round1(maxLabelDriftPx),
    maxVisualCenterOffsetPx: round1(maxVisualCenterOffsetPx),
    legalSurfaceFailures,
    transitionSurfaceSamples: transitionSurfaceFailures,
    inBoundsFailures,
    platformIds,
    transitionKinds,
    propKinds,
    helperActorsSeen: helperKinds,
    passed: primaryRows.length > 0
      && legalSurfaceFailures === 0
      && inBoundsFailures === 0
      && facingMismatchCount === 0
      && maxLabelDriftPx <= 4.5
      && maxVisualCenterOffsetPx <= 4.5,
  };
}

function renderHtmlReport(report) {
  const rows = report.samples
    .map((sample) => {
      const primary = sample?.snapshot?.primary || {};
      return `
        <tr>
          <td>${sample.frame}</td>
          <td><img src="${sample.screenshot}" alt="frame ${sample.frame}" loading="lazy"></td>
          <td>${primary.mode || ""}</td>
          <td>${primary.facing || ""}</td>
          <td>${primary.currentPlatformId || ""}</td>
          <td>${primary.transitionKind || ""}</td>
          <td>${round1(primary.labelCenterOffsetPx) ?? ""}</td>
          <td>${round1(primary.visualCenterOffsetPx) ?? ""}</td>
          <td>${round1(primary.surfaceDeltaPx) ?? ""}</td>
        </tr>
      `;
    })
    .join("");
  const analysis = report.analysis || {};
  const summaryEntries = Object.entries(analysis)
    .map(([key, value]) => `<tr><th>${key}</th><td>${Array.isArray(value) ? value.join(", ") : String(value)}</td></tr>`)
    .join("");
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Thomas Chat Motion Proof</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; background:#07111d; color:#eaf3ff; margin:0; padding:24px; }
    h1,h2 { margin:0 0 12px; }
    p { color:#bdd1ea; }
    table { width:100%; border-collapse:collapse; margin:16px 0 28px; }
    th, td { border:1px solid rgba(135,173,227,0.16); padding:8px; text-align:left; vertical-align:top; }
    th { background:rgba(15,28,44,0.92); }
    td { background:rgba(8,17,29,0.88); }
    img { width:320px; max-width:100%; border-radius:10px; border:1px solid rgba(135,173,227,0.18); }
    .grid { display:grid; grid-template-columns: minmax(220px, 420px) 1fr; gap:24px; }
    .card { background:rgba(8,17,29,0.88); border:1px solid rgba(135,173,227,0.16); border-radius:16px; padding:16px; }
    code { font-family: ui-monospace, SFMono-Regular, monospace; font-size:12px; }
  </style>
</head>
<body>
  <h1>Thomas Chat Motion Proof</h1>
  <p>Captured at ${report.capturedAt} from <code>${report.url}</code>.</p>
  <p>Scenario: <code>${report.options?.scenario || "ambient"}</code></p>
  <div class="grid">
    <section class="card">
      <h2>Analysis</h2>
      <table>${summaryEntries}</table>
    </section>
    <section class="card">
      <h2>Notes</h2>
      <p>This report is the animation review artifact for chat-world Thomas. Use it to inspect label drift, visible traversal props, facing correctness, and legal surface adherence over time.</p>
      <p>JSON telemetry remains available in <code>motion-proof.json</code>.</p>
    </section>
  </div>
  <h2>Frames</h2>
  <table>
    <thead>
      <tr>
        <th>Frame</th>
        <th>Image</th>
        <th>Mode</th>
        <th>Facing</th>
        <th>Platform</th>
        <th>Traversal</th>
        <th>Label Drift</th>
        <th>Visual Center Drift</th>
        <th>Surface Delta</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
</body>
</html>
`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const framesDir = path.join(options.outputDir, "frames");
  await fs.mkdir(framesDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: options.viewportWidth, height: options.viewportHeight },
    deviceScaleFactor: 1,
  });

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });

  try {
    await page.goto(options.url, { waitUntil: "networkidle" });
    if (options.physics) {
      await page.evaluate(async () => {
        await fetch("/api/preferences", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            advanced: {
              interface: {
                animation_fidelity: "high",
                advanced_chat_physics: true,
              },
            },
          }),
        });
      });
      await page.reload({ waitUntil: "networkidle" });
    }
    await page.waitForSelector(".chat-robot-world-actor", { timeout: 15000 });
    await page.waitForTimeout(options.warmupMs);
    await page.evaluate(() => {
      globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.resetSamples?.();
    });
    if (options.scenario) {
      await page.evaluate((scenarioName) => {
        globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.runScenario?.(scenarioName);
      }, options.scenario);
      await page.waitForTimeout(800);
      await page.evaluate(() => {
        globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.resetSamples?.();
      });
    }

    const samples = [];
    for (let i = 0; i < options.frames; i += 1) {
      const snapshot = await page.evaluate(() => {
        return globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.getSnapshot?.() || null;
      });
      const filePath = path.join(framesDir, `frame-${String(i).padStart(3, "0")}.png`);
      await page.screenshot({ path: filePath, fullPage: false });
      samples.push({
        frame: i,
        capturedAt: new Date().toISOString(),
        screenshot: path.relative(options.outputDir, filePath).replace(/\\/g, "/"),
        snapshot,
      });
      if (i < options.frames - 1) {
        await page.waitForTimeout(options.intervalMs);
      }
    }

    const runtimeSamples = await page.evaluate(() => {
      return globalThis.__THOMAS_CHAT_WORLD_DEBUG__?.getSamples?.() || [];
    });
    const analysis = analyzeSamples(samples);
    const report = {
      url: options.url,
      capturedAt: new Date().toISOString(),
      options,
      analysis,
      consoleErrors,
      runtimeSampleCount: Array.isArray(runtimeSamples) ? runtimeSamples.length : 0,
      samples,
      runtimeSamples,
    };
    await fs.writeFile(
      path.join(options.outputDir, "motion-proof.json"),
      `${JSON.stringify(report, null, 2)}\n`,
      "utf8",
    );
    await fs.writeFile(
      path.join(options.outputDir, "motion-proof.html"),
      renderHtmlReport(report),
      "utf8",
    );
    process.stdout.write(`${JSON.stringify(report.analysis, null, 2)}\n`);
    if (!analysis.passed) {
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
