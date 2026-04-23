import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SiteDeepDivePage } from "@/components/site-deep-dive-page";
import { buildRouteMetadata } from "@/lib/site-metadata";
import { isSupportedSiteLocale } from "@/lib/site-locale";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!isSupportedSiteLocale(locale) || locale === "en") {
    return {};
  }
  return buildRouteMetadata("deep-dive", locale);
}

export default async function LocalizedDeepDivePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }
  return <SiteDeepDivePage locale={locale} />;
}
