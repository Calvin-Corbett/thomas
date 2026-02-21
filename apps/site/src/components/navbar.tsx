import Link from "next/link";
import { siteConfig } from "@/lib/site-config";

export function Navbar() {
  return (
    <header className="nav-shell">
      <div className="nav-inner">
        <Link href="/" className="brand-mark" aria-label="Thomas home">
          <span className="brand-dot" />
          <span>{siteConfig.name}</span>
        </Link>
        <nav aria-label="Primary navigation" className="nav-links">
          {siteConfig.nav.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
