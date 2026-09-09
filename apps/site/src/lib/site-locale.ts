import { DOC_LOCALES, type DocLocale } from "@/lib/docs";

export type SiteLocale = DocLocale;

export const SITE_LOCALES = DOC_LOCALES;

const TRANSLATED_ROUTE_PREFIXES = [
  "/",
  "/docs",
  "/download",
  "/updates",
  "/support",
  "/marketplace",
  "/roadmap",
  "/journey",
  "/infinite",
  "/deep-dive",
] as const;

export function isSupportedSiteLocale(value: string): value is SiteLocale {
  return SITE_LOCALES.includes(value as SiteLocale);
}

export function getSiteLocaleFromPath(pathname: string): SiteLocale {
  for (const locale of SITE_LOCALES) {
    if (locale === "en") {
      continue;
    }
    if (pathname === `/${locale}` || pathname.startsWith(`/${locale}/`)) {
      return locale;
    }
  }
  return "en";
}

export function stripSiteLocalePrefix(pathname: string): string {
  const locale = getSiteLocaleFromPath(pathname);
  if (locale === "en") {
    return pathname || "/";
  }

  const stripped = pathname.slice(locale.length + 1);
  return stripped.length ? stripped : "/";
}

export function withSiteLocale(locale: SiteLocale, pathname: string): string {
  const normalized = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const unprefixed = stripSiteLocalePrefix(normalized);
  if (locale === "en") {
    return unprefixed;
  }
  return unprefixed === "/" ? `/${locale}` : `/${locale}${unprefixed}`;
}

export function hasLocalizedRoute(pathname: string): boolean {
  const basePath = stripSiteLocalePrefix(pathname);
  return TRANSLATED_ROUTE_PREFIXES.some((prefix) => basePath === prefix || basePath.startsWith(`${prefix}/`));
}

export function getLocalizedRoute(locale: SiteLocale, pathname: string): string {
  const basePath = stripSiteLocalePrefix(pathname);
  if (!hasLocalizedRoute(pathname)) {
    return locale === "en" ? "/" : `/${locale}`;
  }
  return withSiteLocale(locale, basePath);
}
