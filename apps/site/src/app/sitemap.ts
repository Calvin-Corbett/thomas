import type { MetadataRoute } from "next";
import { getDocLocaleLinks, listDocPages } from "@/lib/docs";
import { getCanonicalSiteUrl } from "@/lib/site-config";
import { getSitemapLanguageAlternates } from "@/lib/site-metadata";

const routes = ["/", "/download", "/docs", "/updates", "/journey", "/deep-dive", "/support", "/roadmap", "/marketplace"] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const base = getCanonicalSiteUrl();
  const now = new Date();
  const routeEntries: MetadataRoute.Sitemap = routes.map((route) => ({
    url: `${base}${route}`,
    lastModified: now,
    changeFrequency: route === "/" || route === "/docs" ? ("daily" as const) : ("weekly" as const),
    priority: route === "/" || route === "/download" || route === "/docs" ? 1 : 0.7,
    alternates: {
      languages: getSitemapLanguageAlternates(route),
    },
  }));
  const docEntries: MetadataRoute.Sitemap = listDocPages("en").map((page) => ({
    url: `${base}${page.href}`,
    lastModified: now,
    changeFrequency: page.key === "home" ? ("daily" as const) : ("weekly" as const),
    priority: page.key === "home" ? 1 : 0.8,
    alternates: {
      languages: Object.fromEntries(
        getDocLocaleLinks(page.key).map((item) => [item.locale, `${base}${item.href}`]),
      ),
    },
  }));

  return [...routeEntries, ...docEntries];
}
