import { NextRequest, NextResponse } from "next/server";
import { buildMarketplaceCatalog } from "@/lib/marketplace-catalog";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
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
