import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SiteDownloadPage } from "@/components/site-download-page";
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

  return buildRouteMetadata("download", locale);
}

export default async function LocalizedDownloadPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { locale } = await params;

  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }

  return <SiteDownloadPage locale={locale} searchParams={searchParams} />;
}
