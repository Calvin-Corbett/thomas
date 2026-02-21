// Global fetch shim that injects X-Workspace-Id for all /api requests.
// This avoids refactoring every existing API call site.
//
// The selected workspace is stored in localStorage by WorkspaceSwitcher.

import { getCurrentWorkspaceId } from "../components/WorkspaceSwitcher";

const originalFetch = window.fetch.bind(window);

function shouldAttach(url: string): boolean {
  // Attach only to same-origin /api calls.
  try {
    const u = new URL(url, window.location.origin);
    return u.origin === window.location.origin && u.pathname.startsWith("/api");
  } catch {
    return url.startsWith("/api");
  }
}

window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" ? input : (input instanceof URL ? input.toString() : (input as Request).url);

  if (!shouldAttach(url)) {
    return originalFetch(input as any, init);
  }

  const ws = getCurrentWorkspaceId();
  if (!ws) {
    return originalFetch(input as any, init);
  }

  const headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined));
  if (!headers.has("X-Workspace-Id")) {
    headers.set("X-Workspace-Id", ws);
  }

  const nextInit: RequestInit = { ...(init || {}), headers };

  return originalFetch(input as any, nextInit);
};
