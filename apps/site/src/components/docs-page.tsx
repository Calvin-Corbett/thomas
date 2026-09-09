import Link from "next/link";
import {
  getDocLocaleLinks,
  getDocNeighbors,
  getDocsLocaleContent,
  getDocSidebar,
  type DocLocale,
  type ResolvedDocPage,
} from "@/lib/docs";

type DocsPageProps = {
  locale: DocLocale;
  page: ResolvedDocPage;
};

function getSectionId(title: string, index: number) {
  const normalized = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || `section-${index + 1}`;
}

export function DocsPage({ locale, page }: DocsPageProps) {
  const localeContent = getDocsLocaleContent(locale);
  const sidebar = getDocSidebar(locale);
  const languageLinks = getDocLocaleLinks(page.key);
  const neighbors = getDocNeighbors(locale, page.key);

  return (
    <div className="docs-shell" lang={locale}>
      <aside className="docs-sidebar">
        <div className="docs-sidebar-card">
          <p className="docs-sidebar-eyebrow">{localeContent.docsLabel}</p>
          <h2 className="docs-sidebar-title">Thomas</h2>
          <p className="docs-sidebar-intro">{localeContent.docsIntro}</p>
        </div>

        <div className="docs-sidebar-card">
          <p className="docs-sidebar-group-title">{localeContent.languageSwitcherLabel}</p>
          <div className="docs-language-switcher">
            {languageLinks.map((item) => (
              <Link
                key={item.locale}
                href={item.href}
                className={`docs-language-pill${item.locale === locale ? " docs-language-pill-active" : ""}`}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>

        <nav className="docs-sidebar-card" aria-label={localeContent.navLabel}>
          {sidebar.map((group) => (
            <div key={group.key} className="docs-sidebar-group">
              <p className="docs-sidebar-group-title">{group.title}</p>
              <div className="docs-link-list">
                {group.pages.map((entry) => (
                  <Link
                    key={entry.href}
                    href={entry.href}
                    className={`docs-link${entry.href === page.href ? " docs-link-active" : ""}`}
                  >
                    {entry.title}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </aside>

      <article className="docs-main">
        <header className="docs-hero">
          <p className="docs-eyebrow">{page.eyebrow}</p>
          <h1>{page.title}</h1>
          <p className="docs-summary">{page.summary}</p>
        </header>

        <div className="docs-section-index">
          <p className="docs-section-index-title">{localeContent.sectionLabel}</p>
          <div className="docs-section-index-links">
            {page.sections.map((section, index) => {
              const sectionId = getSectionId(section.title, index);
              return (
                <a key={sectionId} href={`#${sectionId}`} className="docs-section-chip">
                  {section.title}
                </a>
              );
            })}
          </div>
        </div>

        <div className="docs-content">
          {page.sections.map((section, index) => {
            const sectionId = getSectionId(section.title, index);
            return (
              <section key={sectionId} id={sectionId} className="docs-section">
                <h2>{section.title}</h2>
                {section.paragraphs?.map((paragraph) => (
                  <p key={paragraph} className="docs-paragraph">
                    {paragraph}
                  </p>
                ))}
                {section.bullets?.length ? (
                  <ul className="docs-bullets">
                    {section.bullets.map((bullet) => (
                      <li key={bullet}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
                {section.checklist?.length ? (
                  <ol className="docs-checklist">
                    {section.checklist.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                ) : null}
                {section.callout ? <p className="docs-callout">{section.callout}</p> : null}
              </section>
            );
          })}
        </div>

        <div className="docs-pager">
          {neighbors.previous ? (
            <Link href={neighbors.previous.href} className="docs-pager-link">
              <span>{localeContent.previousLabel}</span>
              <strong>{neighbors.previous.title}</strong>
            </Link>
          ) : (
            <div />
          )}
          {neighbors.next ? (
            <Link href={neighbors.next.href} className="docs-pager-link docs-pager-link-next">
              <span>{localeContent.nextLabel}</span>
              <strong>{neighbors.next.title}</strong>
            </Link>
          ) : null}
        </div>
      </article>
    </div>
  );
}
