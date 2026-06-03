import { NextRequest, NextResponse } from "next/server";
import { getHostedPlugin, verifyDownloadToken } from "@/lib/marketplace-catalog";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "plugin-download",
    limit: 120,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const { token } = await params;
  let decoded: ReturnType<typeof verifyDownloadToken>;
  try {
    decoded = verifyDownloadToken(token);
  } catch {
    return NextResponse.json({ error: "Plugin downloads are not configured" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
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
