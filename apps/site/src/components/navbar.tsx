"use client";

import { useState } from "react";
import Link from "next/link";
import { siteConfig } from "@/lib/site-config";

export function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="nav-shell">
      <div className="nav-inner">
        <Link href="/" className="brand-mark" aria-label="Thomas home">
          <span className="brand-dot" />
          <span>{siteConfig.name}</span>
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
          {siteConfig.nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="nav-link"
              onClick={() => setMenuOpen(false)}
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
