/**
 * Home screen: the grid of app icons, and the icons themselves.
 *
 * Apps here are generated, so nobody draws an icon for them. Without one every
 * tile is an identical grey square and the grid stops being scannable — you
 * would be reading labels, not recognising shapes. So each app gets a colour
 * derived from a stable hash of its module_id and a letter from its name. Same
 * app, same colour, every launch and every device.
 */

/** FNV-1a. Small, stable, and the same on every device — which is the point. */
function hashCode(text) {
  let hash = 2166136261;
  const value = String(text || "");
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function appHue(moduleId) {
  return hashCode(moduleId) % 360;
}

export function appTileStyle(moduleId) {
  const hue = appHue(moduleId);
  // Two stops so tiles read as objects rather than flat swatches, and a fixed
  // lightness range so the dark glyph stays legible on every hue.
  return `linear-gradient(150deg, hsl(${hue} 76% 70%), hsl(${(hue + 36) % 360} 68% 56%))`;
}

export function appInitial(displayName, moduleId) {
  const source = String(displayName || moduleId || "?").trim();
  const letter = source.replace(/[^a-zA-Z0-9]/g, "").charAt(0);
  return (letter || "?").toUpperCase();
}

/**
 * Render installed modules as a home grid.
 *
 * `modules` are registry rows. A module whose surface_type is not "surface" has
 * nothing to open yet; it is shown dimmed rather than hidden, so the grid
 * reflects what is actually installed.
 */
export function renderHomeGrid(grid, modules, { onOpen }) {
  if (!grid) {
    return 0;
  }
  grid.innerHTML = "";
  let openable = 0;

  modules.forEach((module) => {
    const moduleId = String((module && module.module_id) || "");
    if (!moduleId) {
      return;
    }
    const displayName = String((module && module.display_name) || moduleId);
    const isSurface = String((module && module.surface_type) || "declarative") === "surface";
    if (isSurface) {
      openable += 1;
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "home-app";
    button.dataset.moduleId = moduleId;
    button.dataset.openable = isSurface ? "true" : "false";
    button.title = isSurface ? displayName : `${displayName} (no surface to open)`;

    const tile = document.createElement("span");
    tile.className = "home-app-tile";
    tile.setAttribute("aria-hidden", "true");
    tile.style.backgroundImage = appTileStyle(moduleId);
    tile.textContent = appInitial(displayName, moduleId);

    const name = document.createElement("span");
    name.className = "home-app-name";
    name.textContent = displayName;

    button.appendChild(tile);
    button.appendChild(name);
    button.addEventListener("click", () => onOpen(moduleId));
    grid.appendChild(button);
  });

  return openable;
}

/** Recently-installed surface apps, as small tiles in the rail. */
export function renderRailPins(container, modules, { onOpen, limit = 4 }) {
  if (!container) {
    return;
  }
  container.innerHTML = "";
  modules
    .filter((module) => String((module && module.surface_type) || "") === "surface")
    .slice(0, limit)
    .forEach((module) => {
      const moduleId = String(module.module_id || "");
      const displayName = String(module.display_name || moduleId);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "rail-pin";
      button.dataset.moduleId = moduleId;
      button.title = displayName;

      const tile = document.createElement("span");
      tile.className = "home-app-tile";
      tile.setAttribute("aria-hidden", "true");
      tile.style.cssText = "width:26px;height:26px;border-radius:8px;font-size:0.8rem;box-shadow:none;";
      tile.style.backgroundImage = appTileStyle(moduleId);
      tile.textContent = appInitial(displayName, moduleId);

      const label = document.createElement("span");
      label.className = "rail-label";
      label.textContent = displayName;

      button.appendChild(tile);
      button.appendChild(label);
      button.addEventListener("click", () => onOpen(moduleId));
      container.appendChild(button);
    });
}
