import type { ReactNode } from "react";

type SystemSectionProps = {
  id?: string;
  eyebrow?: string;
  title: string;
  intro?: string;
  defaultOpen?: boolean;
  children: ReactNode;
};

export function SystemSection({ id, eyebrow, title, intro, children }: SystemSectionProps) {
  const sectionId = id || title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

  return (
    <section className="system-section" id={sectionId}>
      <div className="system-section-head">
        {eyebrow ? <p className="system-eyebrow">{eyebrow}</p> : null}
        <h2 className="system-section-title">{title}</h2>
        {intro ? <p className="system-section-intro">{intro}</p> : null}
      </div>
      <div className="system-section-body">{children}</div>
    </section>
  );
}
