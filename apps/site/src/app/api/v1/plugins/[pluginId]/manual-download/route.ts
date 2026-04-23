import { NextRequest, NextResponse } from "next/server";
import {
  buildDownloadToken,
  getHostedPlugin,
  getStoreApiKey,
} from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ pluginId: string }> },
) {
  const { pluginId } = await params;
  const hosted = getHostedPlugin(pluginId);
  if (!hosted) {
    return NextResponse.json({ error: "Plugin not found" }, { status: 404 });
  }
  const token = buildDownloadToken(pluginId, getStoreApiKey(), Math.floor(Date.now() / 1000) + 300);
  return NextResponse.redirect(new URL(`/api/v1/plugins/download/${token}`, request.url), { status: 302 });
}
