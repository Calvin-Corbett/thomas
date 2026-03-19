import type { MetadataRoute } from "next";
import { getCanonicalSiteUrl } from "@/lib/site-config";

const routes = ["/", "/download", "/updates", "/journey", "/infinite", "/deep-dive", "/support"];

export default function sitemap(): MetadataRoute.Sitemap {
  const base = getCanonicalSiteUrl();
  const now = new Date();
  return routes.map((route) => ({
    url: `${base}${route}`,
    lastModified: now,
    changeFrequency: route === "/" ? "daily" : "weekly",
    priority: route === "/" || route === "/download" ? 1 : 0.7,
  }));
}
