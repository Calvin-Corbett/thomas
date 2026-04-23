"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getSiteCopy } from "@/lib/site-copy";
import { getLocalizedRoute, getSiteLocaleFromPath, SITE_LOCALES } from "@/lib/site-locale";

export function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();
  const locale = getSiteLocaleFromPath(pathname);
  const copy = getSiteCopy(locale);
  const navItems = [
    { href: "/", label: copy.shell.nav.home },
    { href: "/download", label: copy.shell.nav.download },
    { href: "/docs", label: copy.shell.nav.docs },
    { href: "/marketplace", label: copy.shell.nav.marketplace },
    { href: "/roadmap", label: copy.shell.nav.roadmap },
    { href: "/updates", label: copy.shell.nav.updates },
    { href: "/journey", label: copy.shell.nav.journey },
    { href: "/deep-dive", label: copy.shell.nav["deep-dive"] },
    { href: "/support", label: copy.shell.nav.support },
  ];

  return (
    <header className="nav-shell">
      <div className="nav-inner">
        <Link href={getLocalizedRoute(locale, "/")} className="brand-mark" aria-label="Thomas">
          <span className="brand-dot" />
          <span>Thomas</span>
        </Link>
        <button
          className="nav-hamburger"
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(!menuOpen)}
        >
          <span className="nav-hamburger-bar" />
          <span className="nav-hamburger-bar" />
          <span className="nav-hamburger-bar" />
        </button>
        <nav
          aria-label="Primary navigation"
          className={`nav-links${menuOpen ? " nav-links-open" : ""}`}
        >
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={getLocalizedRoute(locale, item.href)}
              className="nav-link"
              onClick={() => setMenuOpen(false)}
            >
              {item.label}
            </Link>
          ))}
          <div className="nav-language-group" aria-label={copy.shell.languageLabel}>
            {SITE_LOCALES.map((nextLocale) => (
              <Link
                key={nextLocale}
                href={getLocalizedRoute(nextLocale, pathname)}
                className={`nav-language-pill${nextLocale === locale ? " nav-language-pill-active" : ""}`}
                onClick={() => setMenuOpen(false)}
              >
                {nextLocale === "en" ? "EN" : nextLocale === "ja-JP" ? "JA" : "ZH"}
              </Link>
            ))}
          </div>
        </nav>
      </div>
    </header>
  );
}
