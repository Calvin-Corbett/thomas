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
  const viewportWidth = parseMetricNumber(metrics.viewport_width);
  const rootScrollWidth = parseMetricNumber(metrics.root_scroll_width);
  const consoleErrorCount = parseMetricNumber(metrics.console_error_count);
  const brokenImageCount = parseMetricNumber(metrics.broken_image_count);
  const footerLinkCount = parseMetricNumber(metrics.footer_link_count);
  const routeMatrix = Array.isArray(metrics.route_matrix) ? metrics.route_matrix : [];
  const hasNav = metrics.has_nav === true;
  const hasMain = metrics.has_main === true;
  const hasFooter = metrics.has_footer === true;
  const footerWarningTextPresent = metrics.footer_warning_text_present === true;
  const heroPrimaryCtaPresent = metrics.hero_primary_cta_present === true;

  const coreLayoutPresent =
    routeMatrix.length > 0
      ? routeMatrix.every(
          (route) =>
            route &&
            route.has_nav === true &&
            route.has_main === true &&
            route.has_footer === true,
        )
      : hasNav && hasMain && hasFooter;
  const noConsoleRuntimeErrors = consoleErrorCount !== null && consoleErrorCount === 0;
  const noBrokenImages =
    routeMatrix.length > 0
      ? routeMatrix.every((route) => parseMetricNumber(route.broken_image_count) === 0)
      : brokenImageCount !== null && brokenImageCount === 0;
  const footerNavigationPresent = footerLinkCount !== null && footerLinkCount >= 4;
  const noHorizontalDragOverflow =
    routeMatrix.length > 0
      ? routeMatrix.every((route) => {
          const width = parseMetricNumber(route.viewport_width);
          const scrollWidth = parseMetricNumber(route.root_scroll_width);
          return width !== null && scrollWidth !== null && scrollWidth <= width + 1;
        })
      : viewportWidth !== null &&
          rootScrollWidth !== null &&
          rootScrollWidth <= viewportWidth + 1;
  const navPersistentAllRoutes =
    routeMatrix.length > 0 &&
    routeMatrix.every((route) => {
      const navPosition = String(route.nav_position ?? "").toLowerCase();
      const navTop = parseMetricNumber(route.nav_top);
      const navTopAfterScroll = parseMetricNumber(route.nav_top_after_scroll);
      const validPosition = navPosition === "fixed" || navPosition === "sticky";
      return (
        validPosition &&
        navTop !== null &&
        navTopAfterScroll !== null &&
        Math.abs(navTop) <= 2 &&
        Math.abs(navTopAfterScroll) <= 2
      );
    });
  const unknownRouteThemeIntegrity = (() => {
    const probe = routeMatrix.find((route) => route && route.route === "/__ui-route-smoke__");
    if (!probe) return false;
    const sectionShellCount = parseMetricNumber(probe.section_shell_count);
    const bgLuminance = parseMetricNumber(probe.body_bg_luminance);
    return (
      sectionShellCount !== null &&
      sectionShellCount >= 1 &&
      bgLuminance !== null &&
      bgLuminance < 245
    );
  })();

  return {
    core_layout_present: coreLayoutPresent,
    no_console_runtime_errors: noConsoleRuntimeErrors,
    no_broken_images: noBrokenImages,
    nav_persistent_all_routes: navPersistentAllRoutes,
    unknown_route_theme_integrity: unknownRouteThemeIntegrity,
    footer_warning_text_present: footerWarningTextPresent,
    footer_navigation_present: footerNavigationPresent,
    hero_primary_cta_present: heroPrimaryCtaPresent,
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
    let activeRoute = "/";
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const text = msg.text();
        if (
          activeRoute === "/__ui-route-smoke__" &&
          text.includes("the server responded with a status of 404 (Not Found)")
        ) {
          return;
        }
        consoleErrors.push(text);
      }
    });
    page.on("pageerror", (err) => {
      pageErrors.push(String(err));
    });
    const fullPageShot = path.join(opts.outputDir, "full-page.png");
    const footerShot = path.join(opts.outputDir, "footer-focus.png");
    const routesDir = path.join(opts.outputDir, "routes");
    await fs.mkdir(routesDir, { recursive: true });

    const routesToCheck = [
      "/",
      "/docs",
      "/ja-JP",
      "/ja-JP/docs",
      "/ja-JP/deep-dive",
      "/ja-JP/journey",
      "/ja-JP/roadmap",
      "/zh-CN",
      "/zh-CN/docs",
      "/zh-CN/deep-dive",
      "/zh-CN/marketplace",
      "/download",
      "/updates",
      "/journey",
      "/infinite",
      "/deep-dive",
      "/support",
      "/__ui-route-smoke__",
    ];

    const routeMatrix = [];
    let homeMetrics = null;

    for (const route of routesToCheck) {
      const routeUrl = new URL(route, `${serverUrl}/`).toString();
      activeRoute = route;
      await page.goto(routeUrl, { waitUntil: "load", timeout: opts.timeoutMs });
      await page.waitForSelector(".nav-shell", { timeout: opts.timeoutMs });
      await page.waitForSelector(".footer-shell", { timeout: opts.timeoutMs });
      await page.waitForTimeout(280);

      const routeKey = route === "/" ? "home" : route.replace(/^\//, "").replace(/[^a-z0-9-]/gi, "-");
      const topShotPath = path.join(routesDir, `${routeKey}-top.png`);
      const bottomShotPath = path.join(routesDir, `${routeKey}-bottom.png`);

      await page.screenshot({
        path: topShotPath,
        type: "png",
      });

      if (route === "/") {
        await page.screenshot({
          path: fullPageShot,
          fullPage: true,
          type: "png",
        });
      }

      const topMetrics = await page.evaluate((routePath) => {
        const nav = document.querySelector(".nav-shell");
        const navRect = nav?.getBoundingClientRect();
        const main = document.querySelector("main.page-shell");
        const bodyBg = getComputedStyle(document.body).backgroundColor || "";
        const rgbMatch = bodyBg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
        let bodyBgLuminance = null;
        if (rgbMatch) {
          const r = Number(rgbMatch[1]);
          const g = Number(rgbMatch[2]);
          const b = Number(rgbMatch[3]);
          if (Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b)) {
            bodyBgLuminance = Math.round(0.2126 * r + 0.7152 * g + 0.0722 * b);
          }
        }
        return {
          route: routePath,
          has_nav: Boolean(nav),
          has_main: Boolean(main),
          has_footer: Boolean(document.querySelector(".footer-shell")),
          section_shell_count: document.querySelectorAll(".section-shell").length,
          nav_position: nav ? getComputedStyle(nav).position : null,
          nav_top: navRect ? Math.round(navRect.top) : null,
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
          body_bg_color: bodyBg,
          body_bg_luminance: bodyBgLuminance,
        };
      }, route);

      await page.evaluate(() => window.scrollTo(0, Math.max(window.innerHeight + 420, 920)));
      await page.waitForTimeout(220);
      const navTopAfterScroll = await page.evaluate(() => {
        const nav = document.querySelector(".nav-shell");
        const navRect = nav?.getBoundingClientRect();
        return navRect ? Math.round(navRect.top) : null;
      });

      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(300);

      await page.screenshot({
        path: bottomShotPath,
        type: "png",
      });

      if (route === "/") {
        await page.screenshot({
          path: footerShot,
          type: "png",
        });
        homeMetrics = await page.evaluate(() => {
          const footer = document.querySelector(".footer-shell");
          const warningText = Array.from(document.querySelectorAll(".footer-warning"))
            .map((el) => (el.textContent || "").toLowerCase())
            .join(" ");
          const footerLinks = Array.from(document.querySelectorAll(".footer-links a"));
          const heroPrimaryCta = document.querySelector(".home-hero .cta-primary");

          const footerRect = footer?.getBoundingClientRect();
          return {
            viewport_width: Math.round(window.innerWidth),
            root_scroll_width: Math.round(
              Math.max(
                document.documentElement?.scrollWidth ?? 0,
                document.body?.scrollWidth ?? 0,
              ),
            ),
            footer_top: footerRect ? Math.round(footerRect.top) : null,
            footer_warning_text_present: warningText.includes("ai"),
            footer_link_count: footerLinks.length,
            hero_primary_cta_present: Boolean(heroPrimaryCta),
          };
        });
      }

      routeMatrix.push({
        ...topMetrics,
        nav_top_after_scroll: navTopAfterScroll,
        screenshot_top: relRepoPath(topShotPath),
        screenshot_bottom: relRepoPath(bottomShotPath),
      });
    }

    if (!homeMetrics) {
      throw new Error("Failed to capture home metrics");
    }

    const metrics = {
      has_nav: routeMatrix.every((route) => route.has_nav === true),
      has_main: routeMatrix.every((route) => route.has_main === true),
      has_footer: routeMatrix.every((route) => route.has_footer === true),
      broken_image_count: routeMatrix.reduce(
        (sum, route) => sum + (parseMetricNumber(route.broken_image_count) ?? 0),
        0,
      ),
      viewport_width:
        parseMetricNumber(homeMetrics.viewport_width) ?? parseMetricNumber(routeMatrix[0]?.viewport_width),
      root_scroll_width: routeMatrix.reduce(
        (maxWidth, route) => Math.max(maxWidth, parseMetricNumber(route.root_scroll_width) ?? 0),
        parseMetricNumber(homeMetrics.root_scroll_width) ?? 0,
      ),
      footer_top: homeMetrics.footer_top,
      footer_warning_text_present: homeMetrics.footer_warning_text_present,
      footer_link_count: homeMetrics.footer_link_count,
      hero_primary_cta_present: homeMetrics.hero_primary_cta_present,
      route_matrix: routeMatrix,
    };
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
