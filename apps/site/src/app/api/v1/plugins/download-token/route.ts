import { NextRequest, NextResponse } from "next/server";
import {
  buildDownloadToken,
  getHostedPlugin,
  getStoreApiKey,
  storeApiKeysMatch,
} from "@/lib/marketplace-catalog";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "plugin-download-token",
    limit: 30,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const apiKey = request.headers.get("X-Thomas-API-Key") || "";
  let expectedApiKey: string;
  try {
    expectedApiKey = getStoreApiKey();
  } catch {
    return NextResponse.json({ error: "Plugin downloads are not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  if (!storeApiKeysMatch(apiKey, expectedApiKey)) {
    return NextResponse.json({ error: "Missing or invalid API key" }, { status: 401, headers: { "Cache-Control": "no-store" } });
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
  let token: string;
  try {
    token = buildDownloadToken(pluginId, expires);
  } catch {
    return NextResponse.json({ error: "Plugin downloads are not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  return NextResponse.json({
    plugin_id: pluginId,
    channel,
    download_url: `/api/v1/plugins/download/${token}`,
    sha256: hosted.sha256,
    size_bytes: hosted.bundleSizeBytes,
  }, { headers: { "Cache-Control": "no-store" } });
}
