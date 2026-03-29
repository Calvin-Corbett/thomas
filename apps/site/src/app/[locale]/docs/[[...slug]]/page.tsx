import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocsPage } from "@/components/docs-page";
import { getDocPage, isSupportedDocLocale, type DocLocale } from "@/lib/docs";
import { buildDocMetadata } from "@/lib/site-metadata";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug?: string[] }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;

  if (!isSupportedDocLocale(locale) || locale === "en") {
    return {};
  }

  const page = getDocPage(locale as DocLocale, slug);

  if (!page) {
    return {};
  }

  return buildDocMetadata(locale, page);
}

export default async function LocalizedDocsPage({
  params,
}: {
  params: Promise<{ locale: string; slug?: string[] }>;
}) {
  const { locale, slug } = await params;

  if (!isSupportedDocLocale(locale) || locale === "en") {
    notFound();
  }

  const page = getDocPage(locale, slug);

  if (!page) {
    notFound();
  }

  return <DocsPage locale={locale} page={page} />;
}
