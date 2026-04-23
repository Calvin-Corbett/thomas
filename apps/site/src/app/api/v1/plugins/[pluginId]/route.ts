import { NextRequest, NextResponse } from "next/server";
import { getMarketplaceInstallablePlugin } from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ pluginId: string }> },
) {
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
