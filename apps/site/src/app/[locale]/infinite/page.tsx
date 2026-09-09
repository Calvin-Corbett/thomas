import { notFound, redirect } from "next/navigation";
import { isSupportedSiteLocale } from "@/lib/site-locale";

export const dynamic = "force-dynamic";

export default async function LocalizedInfinitePage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isSupportedSiteLocale(locale) || locale === "en") {
    notFound();
  }
  redirect(`/${locale}/journey#infinite`);
}
