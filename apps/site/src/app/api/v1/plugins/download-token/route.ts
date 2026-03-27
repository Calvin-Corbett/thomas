import { NextRequest, NextResponse } from "next/server";
import {
  buildDownloadToken,
  getHostedPlugin,
  getStoreApiKey,
} from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const apiKey = request.headers.get("X-Thomas-API-Key") || "";
  if (apiKey !== getStoreApiKey()) {
    return NextResponse.json({ error: "Missing or invalid API key" }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const pluginId = typeof body.plugin_id === "string" ? body.plugin_id.trim() : "";
  const channel = body.channel === "beta" ? "beta" : "stable";
  if (!pluginId) {
    return NextResponse.json({ error: "plugin_id is required" }, { status: 400 });
  }

  const hosted = getHostedPlugin(pluginId);
  if (!hosted) {
    return NextResponse.json({ error: "Plugin not found" }, { status: 404 });
  }

  const expires = Math.floor(Date.now() / 1000) + 300;
  const token = buildDownloadToken(pluginId, apiKey, expires);
  return NextResponse.json({
    plugin_id: pluginId,
    channel,
    download_url: `/api/v1/plugins/download/${token}`,
    sha256: hosted.sha256,
    size_bytes: hosted.bundleSizeBytes,
  });
}
