import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { SITE_LOCALES, isSupportedSiteLocale } from "@/lib/site-locale";

export const dynamicParams = false;

export function generateStaticParams() {
  return SITE_LOCALES.filter((locale) => locale !== "en").map((locale) => ({ locale }));
}

export default async function LocalizedLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }

  return children;
}
