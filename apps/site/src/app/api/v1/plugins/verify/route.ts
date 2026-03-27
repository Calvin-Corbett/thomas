import { NextRequest, NextResponse } from "next/server";
import { getHostedPlugin } from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const pluginId = typeof body.plugin_id === "string" ? body.plugin_id.trim() : "";
  if (!pluginId) {
    return NextResponse.json({ valid: false, error: "plugin_id is required" }, { status: 400 });
  }

  const hosted = getHostedPlugin(pluginId);
  if (!hosted) {
    return NextResponse.json({ valid: false, error: "Plugin not found" }, { status: 404 });
  }

  return NextResponse.json({
    valid: true,
    plugin_id: pluginId,
    sha256: hosted.sha256,
    size_bytes: hosted.bundleSizeBytes,
  });
}
