import type { ReleaseChannel } from "@/lib/types";

export const siteConfig = {
  name: "Thomas",
  productLine: "AI Command Center",
  description:
    "Thomas helps everyday users get real work done with one assistant for planning, execution, and follow-through.",
  nav: [
    { href: "/", label: "Home" },
    { href: "/download", label: "Download" },
    { href: "/updates", label: "Updates" },
    { href: "/journey", label: "Journey" },
    { href: "/support", label: "Support" },
  ],
  social: {
    github: "https://github.com",
  },
} as const;

export function getRepoSlug(): string {
  return process.env.THOMAS_GITHUB_REPO ?? "";
}

export function getRepoUrl(): string {
  const slug = getRepoSlug();
  if (!slug.includes("/")) {
    return "";
  }
  return `https://github.com/${slug}`;
}

export function getReleasesUrl(): string {
  const repo = getRepoUrl();
  if (!repo) {
    return "";
  }
  return `${repo}/releases`;
}

export function hasRepoConfigured(): boolean {
  return getRepoUrl().length > 0;
}

export function getDefaultChannel(): ReleaseChannel {
  const raw = process.env.THOMAS_RELEASE_CHANNEL;
  if (raw === "beta") {
    return "beta";
  }
  return "stable";
}

export function getCanonicalSiteUrl(): string {
  return process.env.SITE_URL ?? "https://thomas.dev";
}
