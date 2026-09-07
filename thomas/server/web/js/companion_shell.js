/**
 * Shell chrome behaviour: the rail, the home screen, host reachability, and the
 * build-an-app flow.
 *
 * Split out of companion.js, which had grown past the 800-line soft limit in
 * agent_safety.toml. companion_home.js stays pure rendering helpers; this module
 * owns the behaviour that drives them, and takes its collaborators as arguments
 * rather than reaching for module scope.
 */

import { renderHomeGrid, renderRailPins } from "./companion_home.js";

export function createCompanionShell({
  state,
  refs,
  asText,
  requestJson,
  openSurface,
  loadInstalledModules,
}) {
  function setRailExpanded(expanded) {
    state.railExpanded = Boolean(expanded);
    if (refs.rail) {
      refs.rail.classList.toggle("expanded", state.railExpanded);
    }
    if (refs.railToggle) {
      refs.railToggle.setAttribute("aria-expanded", state.railExpanded ? "true" : "false");
    }
    if (refs.railScrim) {
      refs.railScrim.hidden = !state.railExpanded;
    }
  }

  function toggleRail() {
    setRailExpanded(!state.railExpanded);
  }

  function renderHome() {
    const modules = state.apps.installed;
    const openable = renderHomeGrid(refs.homeGrid, modules, { onOpen: openSurface });
    renderRailPins(refs.railPins, modules, { onOpen: openSurface });

    if (!refs.homeMeta) {
      return;
    }
    if (modules.length === 0) {
      refs.homeMeta.textContent =
        "No apps installed yet. Ask above for something you want, and Thomas can build it for this phone.";
    } else if (openable === 0) {
      refs.homeMeta.textContent =
        "These modules are installed but none ships a surface to open yet.";
    } else {
      refs.homeMeta.textContent = "";
    }
  }

  async function refreshHome() {
    await loadInstalledModules();
    renderHome();
  }

  function setHomeStatus(message, { error = false } = {}) {
    if (!refs.homeStatus) {
      return;
    }
    const text = asText(message, "");
    refs.homeStatus.textContent = text;
    refs.homeStatus.hidden = text === "";
    refs.homeStatus.setAttribute("data-tone", error ? "error" : "info");
  }

  function setHomeMode(mode) {
    const next = mode === "build" ? "build" : "ask";
    state.home.mode = next;
    if (refs.homeComposerForm) {
      refs.homeComposerForm.setAttribute("data-mode", next);
    }
    if (refs.homeComposerMode) {
      refs.homeComposerMode.textContent = next === "build" ? "Build" : "Ask";
    }
    if (refs.homeComposerInput) {
      refs.homeComposerInput.placeholder =
        next === "build" ? "Describe an app to build\u2026" : "Ask Thomas anything\u2026";
    }
  }

  function setHomeBuilding(building) {
    state.home.building = Boolean(building);
    if (refs.homeComposerSend) {
      refs.homeComposerSend.disabled = state.home.building;
    }
    if (refs.homeComposerInput) {
      refs.homeComposerInput.disabled = state.home.building;
    }
  }

  /* Describe an app, get an app. Thomas writes the surface, the studio signs it,
     and it goes through the same verification and policy gates as any bundle
     before its icon shows up on this screen. */
  async function buildAppFromDescription(description) {
    if (state.home.building) {
      return;
    }
    setHomeBuilding(true);
    setHomeStatus("Building your app\u2026 this takes a moment.");
    try {
      const payload = await requestJson("/api/companion/v1/surface/generate", {
        method: "POST",
        body: JSON.stringify({ description }),
      });
      const moduleId = asText(payload && payload.module_id, "");
      const displayName = asText(payload && payload.display_name, moduleId);
      await refreshHome();
      setHomeStatus(`${displayName} is installed.`);
      if (moduleId) {
        openSurface(moduleId);
      }
    } catch (error) {
      setHomeStatus(
        `Could not build that: ${asText(error && error.message, "request failed")}`,
        { error: true },
      );
    } finally {
      setHomeBuilding(false);
    }
  }

  /* The computer running Thomas can sleep, and then this phone can do nothing.
     That state has to be visible before you tap something, not after it fails. */
  async function refreshHostStatus() {
    try {
      await requestJson("/api/companion/v1/status");
      state.host.state = "online";
    } catch (_error) {
      state.host.state = "offline";
    }
    state.host.checkedAt = Date.now();
    renderHostStatus();
  }

  function renderHostStatus() {
    if (refs.railStatus) {
      refs.railStatus.setAttribute("data-state", asText(state.host.state, "unknown"));
    }
    if (!refs.railStatusLabel) {
      return;
    }
    const labels = { online: "Thomas online", offline: "Thomas unreachable", unknown: "Checking" };
    refs.railStatusLabel.textContent = labels[state.host.state] || labels.unknown;
  }

  return {
    setRailExpanded,
    toggleRail,
    renderHome,
    refreshHome,
    setHomeStatus,
    setHomeMode,
    setHomeBuilding,
    buildAppFromDescription,
    refreshHostStatus,
    renderHostStatus,
  };
}
