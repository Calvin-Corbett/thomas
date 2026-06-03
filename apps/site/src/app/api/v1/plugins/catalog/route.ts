import { NextRequest, NextResponse } from "next/server";
import { buildMarketplaceCatalog } from "@/lib/marketplace-catalog";
import { checkRateLimit, rateLimitResponse } from "@/lib/rate-limit";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const rateLimit = checkRateLimit(request, {
    keyPrefix: "plugin-catalog",
    limit: 240,
    windowMs: 5 * 60 * 1000,
  });
  if (!rateLimit.allowed) {
    return rateLimitResponse(rateLimit);
  }

  const channel = request.nextUrl.searchParams.get("channel") === "beta" ? "beta" : "stable";
  try {
    return NextResponse.json(buildMarketplaceCatalog(channel), {
      headers: {
        "cache-control": "public, s-maxage=300, stale-while-revalidate=900",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "Unable to build marketplace catalog.",
      },
      { status: 500 },
    );
  }
}
