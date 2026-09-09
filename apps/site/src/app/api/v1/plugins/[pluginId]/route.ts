import { NextRequest, NextResponse } from "next/server";
import { getMarketplaceInstallablePlugin } from "@/lib/marketplace-catalog";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ pluginId: string }> },
) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "plugin-detail",
    limit: 240,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const { pluginId } = await params;
  const channel = request.nextUrl.searchParams.get("channel") === "beta" ? "beta" : "stable";
  const plugin = getMarketplaceInstallablePlugin(pluginId, channel);
  if (!plugin) {
    return NextResponse.json({ error: "Plugin not found" }, { status: 404 });
  }
  return NextResponse.json(plugin, {
    headers: {
      "cache-control": "public, s-maxage=300, stale-while-revalidate=900",
    },
  });
}
