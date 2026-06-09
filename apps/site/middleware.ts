import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { securityHeaders } from "@/lib/security-headers";

// Sets security headers on every page/route response.
//
// This runs inside the Cloudflare Worker for each request, including the
// statically-prerendered marketing pages. That matters because OpenNext does
// NOT apply `next.config.mjs`'s `headers()` to prerendered responses, so the
// Worker is the only place that reliably gets the headers onto the wire.
// (It also still emits middleware-manifest.json, which OpenNext needs during
// Cloudflare packaging — the original reason this file existed.)
export function middleware(_request: NextRequest) {
  const response = NextResponse.next();
  for (const header of securityHeaders) {
    response.headers.set(header.key, header.value);
  }
  return response;
}

export const config = {
  // Run on everything except Next's internal static assets and the favicon,
  // which are served by the Cloudflare asset binding and covered by
  // public/_headers instead.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

