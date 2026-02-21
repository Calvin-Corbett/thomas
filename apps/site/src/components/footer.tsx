import Link from "next/link";
import { getRepoUrl } from "@/lib/site-config";

export function Footer() {
  const repoUrl = getRepoUrl();
  return (
    <footer className="footer-shell">
      <div className="footer-inner">
        <div>
          <p className="footer-title">Thomas</p>
          <p className="footer-copy">One assistant for planning, execution, and follow-through.</p>
        </div>
        <div className="footer-links">
          <Link href="/download">Download</Link>
          <Link href="/updates">Updates</Link>
          <Link href="/journey">Journey</Link>
          <a href={repoUrl} target="_blank" rel="noreferrer">
            GitHub (Advanced)
          </a>
        </div>
      </div>
    </footer>
  );
}
