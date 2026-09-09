import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SiteHomePage } from "@/components/site-home-page";
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

  return buildRouteMetadata("home", locale);
}

export default async function LocalizedHomePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }

  return <SiteHomePage locale={locale} />;
}
