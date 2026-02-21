export type Workspace = {
  workspace_id: string;
  name: string;
  owner_user_id?: string | null;
  created_at: string;
};

export async function fetchWorkspaces(): Promise<Workspace[]> {
  const res = await fetch("/api/workspaces", { credentials: "include" });
  if (!res.ok) throw new Error(`Failed to fetch workspaces: ${res.status}`);
  return res.json();
}
