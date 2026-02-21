import React, { useEffect, useMemo, useState } from "react";
import { fetchWorkspaces, Workspace } from "../api/workspaces";

const STORAGE_KEY = "thomas.currentWorkspaceId";

export function getCurrentWorkspaceId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setCurrentWorkspaceId(id: string) {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // ignore
  }
}

export function WorkspaceSwitcher() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(getCurrentWorkspaceId());
  const current = useMemo(
    () => workspaces.find((w) => w.workspace_id === currentId) || null,
    [workspaces, currentId]
  );

  useEffect(() => {
    let cancelled = false;
    fetchWorkspaces()
      .then((ws) => {
        if (cancelled) return;
        setWorkspaces(ws);
        const stored = getCurrentWorkspaceId();
        if (!stored && ws.length) {
          setCurrentWorkspaceId(ws[0].workspace_id);
          setCurrentId(ws[0].workspace_id);
        }
      })
      .catch(() => {
        // if API isn't ready yet, hide switcher
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = e.target.value;
    setCurrentId(id);
    setCurrentWorkspaceId(id);
    window.location.reload();
  }

  if (!workspaces.length) return null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span
        style={{
          fontSize: 12,
          padding: "2px 8px",
          borderRadius: 999,
          border: "1px solid rgba(255,255,255,0.2)",
          opacity: 0.9,
        }}
        title="Current workspace"
      >
        {current ? current.name : "Workspace"}
      </span>

      <select
        value={currentId || ""}
        onChange={onChange}
        style={{
          fontSize: 12,
          padding: "6px 8px",
          borderRadius: 8,
          background: "transparent",
          border: "1px solid rgba(255,255,255,0.25)",
          color: "inherit",
        }}
        aria-label="Switch workspace"
      >
        {workspaces.map((w) => (
          <option key={w.workspace_id} value={w.workspace_id}>
            {w.name}
          </option>
        ))}
      </select>
    </div>
  );
}
