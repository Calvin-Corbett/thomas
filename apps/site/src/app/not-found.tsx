import Link from "next/link";
import { SystemPageShell } from "@/components/system-page";
import { SystemSection } from "@/components/system-section";

export default function NotFound() {
  return (
    <section className="section-shell">
      <SystemPageShell
        eyebrow="Not Found"
        title="This route does not exist"
        intro="The route may have moved, been renamed, or not yet been published."
      >
        <SystemSection title="Next steps" intro="Use these pages to navigate back quickly.">
          <div className="hero-cta">
            <Link className="cta-secondary" href="/">
              Home
            </Link>
            <Link className="cta-secondary" href="/download">
              Download
            </Link>
            <Link className="cta-secondary" href="/updates">
              Updates
            </Link>
          </div>
        </SystemSection>
      </SystemPageShell>
    </section>
  );
}
