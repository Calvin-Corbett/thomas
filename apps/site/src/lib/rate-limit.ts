import { NextRequest, NextResponse } from "next/server";

type RateLimitOptions = {
  keyPrefix: string;
  limit: number;
  windowMs: number;
};

type RateLimitBucket = {
  count: number;
  resetAt: number;
};

type RateLimitResult = {
  allowed: boolean;
  headers: Record<string, string>;
};

const buckets = new Map<string, RateLimitBucket>();
const MAX_BUCKETS = 2048;

function clientAddress(request: NextRequest): string {
  const directHeaders = [
    request.headers.get("cf-connecting-ip"),
    request.headers.get("x-real-ip"),
    request.headers.get("x-forwarded-for")?.split(",")[0],
  ];
  const candidate = directHeaders.map((value) => value?.trim()).find(Boolean);
  return candidate || "unknown";
}

function pruneExpiredBuckets(now: number): void {
  if (buckets.size <= MAX_BUCKETS) return;
  for (const [key, bucket] of buckets.entries()) {
    if (bucket.resetAt <= now) {
      buckets.delete(key);
    }
  }
  while (buckets.size > MAX_BUCKETS) {
    const oldestKey = buckets.keys().next().value as string | undefined;
    if (!oldestKey) break;
    buckets.delete(oldestKey);
  }
}

export function checkRateLimit(request: NextRequest, options: RateLimitOptions): RateLimitResult {
  const now = Date.now();
  pruneExpiredBuckets(now);

  const key = `${options.keyPrefix}:${clientAddress(request)}`;
  let bucket = buckets.get(key);
  if (!bucket || bucket.resetAt <= now) {
    bucket = { count: 0, resetAt: now + options.windowMs };
    buckets.set(key, bucket);
  }

  bucket.count += 1;
  const retryAfterSeconds = Math.max(1, Math.ceil((bucket.resetAt - now) / 1000));
  const remaining = Math.max(0, options.limit - bucket.count);
  const headers = {
    "X-RateLimit-Limit": String(options.limit),
    "X-RateLimit-Remaining": String(remaining),
    "X-RateLimit-Reset": String(Math.ceil(bucket.resetAt / 1000)),
  };

  if (bucket.count > options.limit) {
    return {
      allowed: false,
      headers: {
        ...headers,
        "Retry-After": String(retryAfterSeconds),
      },
    };
  }

  return { allowed: true, headers };
}

export function rateLimitResponse(result: RateLimitResult): NextResponse {
  return NextResponse.json(
    { error: "Too many requests" },
    {
      status: 429,
      headers: {
        ...result.headers,
        "Cache-Control": "no-store",
      },
    },
  );
}
