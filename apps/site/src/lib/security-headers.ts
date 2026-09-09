// Canonical security headers for the Thomas marketing site.
//
// WHY THIS FILE EXISTS
// --------------------
// On Cloudflare (OpenNext) the marketing pages are statically prerendered and
// served by the Worker's cache path, which does NOT apply `next.config.mjs`'s
// `async headers()`. As a result the headers were configured but absent on the
// live site (verified: https://thomas-site.thomasdevhub.workers.dev returned no
// CSP / HSTS / X-Frame-Options, etc.). Security scanners and Cloudflare's
// Security Center flag that as "missing security headers".
//
// `middleware.ts` runs in the Worker for every page/route request (including
// prerendered ones), so setting the headers there guarantees they ship. This
// module is the single source of truth for that set.
//
// Keep in sync with:
//   - next.config.mjs  (applies on `next start` / the Vercel deploy path)
//   - public/_headers   (applies to static assets served by the CF asset binding)

const isProduction = process.env.NODE_ENV === "production";

// `unsafe-inline` is required: Next.js injects inline hydration scripts and the
// Spline hero uses inline/blob scripts. Per-request nonces don't work with full
// static prerendering (the HTML is cached), so this stays for a marketing site.
//
// `unsafe-eval` is required in PRODUCTION too: the Spline 3D hero viewer parses
// its .splinecode scene by evaluating strings as JS (new Function/eval). Without
// it the home-page hero fails to load with a CSP error. Verified against the
// OpenNext/workerd build. (The previous config only allowed eval in dev, but the
// CSP never actually reached the browser before, so that gap went unnoticed.)
const scriptSrc = ["'self'", "'unsafe-inline'", "'unsafe-eval'", "blob:"];

export const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src ${scriptSrc.join(" ")}`,
  "style-src 'self' 'unsafe-inline'",
  // `https:` keeps the Spline 3D hero (prod.spline.design textures) working
  // without enumerating every Spline sub-domain.
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  // `connect-src https:` allows the Spline scene fetch + any HTTPS API call.
  "connect-src 'self' https:",
  "media-src 'self' data: blob: https:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  isProduction ? "upgrade-insecure-requests" : "",
]
  .filter(Boolean)
  .join("; ");

export const securityHeaders: ReadonlyArray<{ key: string; value: string }> = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  // HSTS: 2 years + subdomains + preload-eligible. Browsers ignore it over
  // plain HTTP, so it is always safe to send. This was the one header missing
  // from the config entirely.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
];
