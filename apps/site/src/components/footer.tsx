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
          <p className="footer-copy">Local-first execution system for verified desktop workflows.</p>
          <p className="footer-copy footer-warning">
            Use this with explicit command approval and AI-safe auditable release metadata.
          </p>
        </div>
        <div className="footer-links">
          <Link href="/download">Download</Link>
          <Link href="/roadmap">Roadmap</Link>
          <Link href="/updates">Updates</Link>
          <Link href="/journey">Journey</Link>
          <Link href="/deep-dive">Deep Dive</Link>
          <Link href="/support">Support</Link>
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
