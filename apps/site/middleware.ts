import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Pass-through middleware to ensure Next emits middleware-manifest.json,
// which OpenNext expects during Cloudflare packaging.
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}

