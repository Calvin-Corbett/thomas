/**
 * Surface host for companion `surface` modules.
 *
 * A surface is an HTML document shipped inside a signed module bundle. It runs
 * in an iframe sandboxed with `allow-scripts` and deliberately WITHOUT
 * `allow-same-origin`, which puts it in an opaque origin: it cannot touch the
 * shell's DOM, storage, or auth token even though it is served from this host.
 * Its CSP also denies connect-src, so it has no network of its own.
 *
 * Everything it needs therefore arrives through this bridge. The shell holds
 * the auth token and makes the real API calls; the surface only ever gets to
 * ask. Because a sandboxed frame reports its origin as "null", we authenticate
 * inbound messages by comparing `event.source` against the frame's own
 * contentWindow rather than by origin string.
 */

const BRIDGE_MARKER = 1;

/**
 * Each route also says how to unwrap its response.
 *
 * A surface asks for a value and should receive that value — `thomas.storage
 * .get("sets")` resolves to the stored array, not to `{ok, key, value}`. Handing
 * back the envelope makes every app write `(await get(k)).value`, and the first
 * app that forgets does `prev.push(...)` on an object and breaks. The transport
 * shape is this layer's business, not the app's.
 */
const METHOD_ROUTES = {
  "storage.get": { path: "storage/get", method: "POST", unwrap: (r) => (r ? r.value : undefined) },
  "storage.set": { path: "storage/set", method: "POST", unwrap: (r) => Boolean(r && r.stored) },
  "storage.delete": { path: "storage/delete", method: "POST", unwrap: (r) => Boolean(r && r.deleted) },
  "storage.keys": { path: "storage/keys", method: "GET", unwrap: (r) => (r && r.keys) || [] },
  ask: { path: "ask", method: "POST", unwrap: (r) => String((r && r.text) || "") },
};

function surfaceBase(moduleId) {
  return `/api/companion/v1/surface/${encodeURIComponent(moduleId)}`;
}

export function createSurfaceHost({ requestJson, requestText, mount, onClose }) {
  let frame = null;
  let activeModule = null;
  let listening = false;

  function isOpen() {
    return Boolean(frame);
  }

  function reply(message, ok, payload) {
    if (!frame || !frame.contentWindow) {
      return;
    }
    // targetOrigin must be "*": an opaque origin cannot be named. Safe here
    // because we only ever reply to a request we matched to this frame.
    frame.contentWindow.postMessage(
      ok
        ? { __thomasBridge: BRIDGE_MARKER, id: message.id, ok: true, result: payload }
        : { __thomasBridge: BRIDGE_MARKER, id: message.id, ok: false, error: String(payload) },
      "*",
    );
  }

  async function dispatch(message) {
    const method = String(message.method || "");

    if (method === "close") {
      close();
      return { closed: true };
    }

    const route = METHOD_ROUTES[method];
    if (!route) {
      throw new Error(`unknown bridge method: ${method}`);
    }

    const base = surfaceBase(activeModule.module_id);
    const payload =
      route.method === "GET"
        ? await requestJson(`${base}/${route.path}`)
        : await requestJson(`${base}/${route.path}`, {
            method: "POST",
            body: JSON.stringify(message.params || {}),
          });
    return route.unwrap ? route.unwrap(payload) : payload;
  }

  async function onMessage(event) {
    if (!frame || event.source !== frame.contentWindow) {
      return;
    }
    const message = event.data;
    if (!message || message.__thomasBridge !== BRIDGE_MARKER || !message.id) {
      return;
    }
    try {
      reply(message, true, await dispatch(message));
    } catch (err) {
      reply(message, false, (err && err.message) || "bridge call failed");
    }
  }

  async function open(module) {
    if (!mount) {
      return;
    }
    close();
    activeModule = module;

    const shell = document.createElement("div");
    shell.className = "companion-surface-shell";

    const bar = document.createElement("div");
    bar.className = "companion-surface-bar";

    const title = document.createElement("span");
    title.className = "companion-surface-title";
    title.textContent = module.display_name || module.module_id;

    const back = document.createElement("button");
    back.type = "button";
    back.className = "companion-surface-back";
    back.textContent = "Done";
    back.addEventListener("click", () => close());

    bar.appendChild(back);
    bar.appendChild(title);

    frame = document.createElement("iframe");
    frame.className = "companion-surface-frame";
    frame.title = title.textContent;
    // No allow-same-origin: this is what keeps the surface in an opaque origin.
    frame.setAttribute("sandbox", "allow-scripts");
    frame.setAttribute("referrerpolicy", "no-referrer");

    shell.appendChild(bar);
    shell.appendChild(frame);

    mount.innerHTML = "";
    mount.appendChild(shell);
    mount.hidden = false;

    if (!listening) {
      window.addEventListener("message", onMessage);
      listening = true;
    }

    // The document is fetched here rather than set as frame.src because an
    // iframe navigation cannot carry the bearer header, and remote mode requires
    // one. Putting the token in the URL instead would hand it to the surface,
    // which can read its own location. The served document carries its CSP in a
    // meta tag, since srcdoc does not inherit response headers.
    const activeFrame = frame;
    try {
      const html = await requestText(`${surfaceBase(module.module_id)}/document`);
      if (frame !== activeFrame) {
        return;
      }
      frame.srcdoc = html;
    } catch (err) {
      if (frame !== activeFrame) {
        return;
      }
      title.textContent = `${title.textContent} — failed to load`;
      frame.srcdoc = "";
      throw err;
    }
  }

  function close() {
    if (listening) {
      window.removeEventListener("message", onMessage);
      listening = false;
    }
    frame = null;
    activeModule = null;
    if (mount) {
      mount.innerHTML = "";
      mount.hidden = true;
    }
    if (typeof onClose === "function") {
      onClose();
    }
  }

  return { open, close, isOpen };
}
