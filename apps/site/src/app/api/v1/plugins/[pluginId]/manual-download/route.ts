import { NextRequest, NextResponse } from "next/server";
import {
  buildDownloadToken,
  getHostedPlugin,
  getStoreApiKey,
} from "@/lib/marketplace-catalog";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ pluginId: string }> },
) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "plugin-manual-download",
    limit: 60,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const { pluginId } = await params;
  const hosted = getHostedPlugin(pluginId);
  if (!hosted) {
    return NextResponse.json({ error: "Plugin not found" }, { status: 404 });
  }
  try {
    getStoreApiKey();
  } catch {
    return NextResponse.json({ error: "Plugin downloads are not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  let token: string;
  try {
    token = buildDownloadToken(pluginId, Math.floor(Date.now() / 1000) + 300);
  } catch {
    return NextResponse.json({ error: "Plugin downloads are not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  const response = NextResponse.redirect(new URL(`/api/v1/plugins/download/${token}`, request.url), { status: 302 });
  response.headers.set("Cache-Control", "no-store");
  return response;
}
