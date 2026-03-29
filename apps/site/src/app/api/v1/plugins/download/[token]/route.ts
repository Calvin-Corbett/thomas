import { NextRequest, NextResponse } from "next/server";
import { getHostedPlugin, verifyDownloadToken } from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  const decoded = verifyDownloadToken(token);
  if (!decoded) {
    return NextResponse.json({ error: "Invalid or expired download token" }, { status: 404 });
  }

  const hosted = getHostedPlugin(decoded.pluginId);
  if (!hosted) {
    return NextResponse.json({ error: "Plugin not found" }, { status: 404 });
  }

  const payload = Buffer.from(hosted.bundleBase64, "base64");
  return new NextResponse(payload, {
    status: 200,
    headers: {
      "Content-Type": "application/zip",
      "Content-Length": String(payload.byteLength),
      "Content-Disposition": `attachment; filename="${hosted.id}-${String(hosted.manifest.version ?? "0.0.0")}.zip"`,
      "X-Plugin-SHA256": hosted.sha256,
      "Cache-Control": "no-store",
    },
  });
}
