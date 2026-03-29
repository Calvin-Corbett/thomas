"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DinoRiders } from "@/components/dino-riders";
import { getSiteCopy } from "@/lib/site-copy";
import { getLocalizedRoute, getSiteLocaleFromPath } from "@/lib/site-locale";

export function Footer({ repoUrl }: { repoUrl: string }) {
  const pathname = usePathname();
  const locale = getSiteLocaleFromPath(pathname);
  const copy = getSiteCopy(locale);

  return (
    <footer className="footer-shell">
      <DinoRiders />
      <div className="footer-inner">
        <div>
          <p className="footer-title">{copy.shell.footerTitle}</p>
          <p className="footer-copy">{copy.shell.footerCopy}</p>
          <p className="footer-copy footer-warning">
            {copy.shell.footerWarning}
          </p>
        </div>
        <div className="footer-links">
          <Link href={getLocalizedRoute(locale, "/download")}>{copy.shell.footerLinks.download}</Link>
          <Link href={getLocalizedRoute(locale, "/roadmap")}>{copy.shell.footerLinks.roadmap}</Link>
          <Link href={getLocalizedRoute(locale, "/updates")}>{copy.shell.footerLinks.updates}</Link>
          <Link href={getLocalizedRoute(locale, "/journey")}>{copy.shell.footerLinks.journey}</Link>
          <Link href={getLocalizedRoute(locale, "/deep-dive")}>{copy.shell.footerLinks.deepDive}</Link>
          <Link href={getLocalizedRoute(locale, "/support")}>{copy.shell.footerLinks.support}</Link>
          {repoUrl ? (
            <a href={repoUrl} target="_blank" rel="noreferrer">
              {copy.shell.footerLinks.github}
            </a>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
