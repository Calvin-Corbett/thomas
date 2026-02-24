import Link from "next/link";
import { DinoRiders } from "@/components/dino-riders";
import { getRepoUrl } from "@/lib/site-config";

export function Footer() {
  const repoUrl = getRepoUrl();
  return (
    <footer className="footer-shell">
      <DinoRiders />
      <div className="footer-inner">
        <div>
          <p className="footer-title">Thomas</p>
          <p className="footer-copy">One assistant to help you do anything on your computer.</p>
        </div>
        <div className="footer-links">
          <Link href="/download">Download</Link>
          <Link href="/updates">Updates</Link>
          <Link href="/journey">Journey</Link>
          {repoUrl ? (
            <a href={repoUrl} target="_blank" rel="noreferrer">
              GitHub (Advanced)
            </a>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
