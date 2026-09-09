import {
  DOCS_COPY,
  DOC_LOCALES,
  DOC_PAGE_ORDER,
  type DocGroupKey,
  type DocLocale,
  type DocPageKey,
  type DocSection,
  type LocaleContent,
} from "@/lib/docs-data";

export { DOC_LOCALES };
export type { DocLocale } from "@/lib/docs-data";

export type ResolvedDocPage = {
  key: DocPageKey;
  slug: string[];
  group: DocGroupKey;
  href: string;
  title: string;
  description: string;
  summary: string;
  eyebrow: string;
  sections: DocSection[];
};

export function isSupportedDocLocale(value: string): value is DocLocale {
  return DOC_LOCALES.includes(value as DocLocale);
}

export function getDocHref(locale: DocLocale, slug: string[]): string {
  const suffix = slug.length ? `/${slug.join("/")}` : "";
  return locale === "en" ? `/docs${suffix}` : `/${locale}/docs${suffix}`;
}

export function getDocsLocaleContent(locale: DocLocale): LocaleContent {
  return DOCS_COPY[locale];
}

export function listDocPages(locale: DocLocale): ResolvedDocPage[] {
  const content = DOCS_COPY[locale];
  return DOC_PAGE_ORDER.map((meta) => {
    const page = content.pages[meta.key];
    return {
      key: meta.key,
      slug: meta.slug,
      group: meta.group,
      href: getDocHref(locale, meta.slug),
      title: page.title,
      description: page.description,
      summary: page.summary,
      eyebrow: page.eyebrow,
      sections: page.sections,
    };
  });
}

export function getDocPage(locale: DocLocale, slug?: string[]): ResolvedDocPage | null {
  const normalized = (slug ?? []).join("/");
  return listDocPages(locale).find((page) => page.slug.join("/") === normalized) ?? null;
}

export function getDocSidebar(locale: DocLocale) {
  const content = DOCS_COPY[locale];
  const pages = listDocPages(locale);
  return (Object.keys(content.groups) as DocGroupKey[]).map((groupKey) => ({
    key: groupKey,
    title: content.groups[groupKey],
    pages: pages.filter((page) => page.group === groupKey),
  }));
}

export function getDocNeighbors(locale: DocLocale, key: DocPageKey) {
  const pages = listDocPages(locale);
  const index = pages.findIndex((page) => page.key === key);
  return {
    previous: index > 0 ? pages[index - 1] : null,
    next: index >= 0 && index < pages.length - 1 ? pages[index + 1] : null,
  };
}

export function getDocLocaleLinks(key: DocPageKey) {
  return DOC_LOCALES.map((locale) => {
    const page = listDocPages(locale).find((entry) => entry.key === key);
    return { locale, label: DOCS_COPY[locale].localeLabel, href: page ? page.href : getDocHref(locale, []) };
  });
}

export function getAllDocHrefs(): string[] {
  return DOC_LOCALES.flatMap((locale) => listDocPages(locale).map((page) => page.href));
}

export function getDocStaticParams() {
  return DOC_PAGE_ORDER.map((page) => ({ slug: page.slug }));
}
