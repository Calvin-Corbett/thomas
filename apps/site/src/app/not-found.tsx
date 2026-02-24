import Link from "next/link";

export default function NotFound() {
  return (
    <section className="section-shell">
      <p className="eyebrow">Not Found</p>
      <h1 className="page-title">That page does not exist.</h1>
      <p className="page-intro">
        The route may have moved or was removed. Use one of the main pages below.
      </p>
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
    </section>
  );
}
