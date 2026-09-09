"use client";

import { ReactNode, useEffect, useMemo, useRef } from "react";

type SystemPageShellClientProps = {
  eyebrow?: string;
  title: string;
  intro?: string;
  versionLabel?: string;
  meta?: ReactNode;
  persistDetails?: boolean;
  children: ReactNode;
};

type DetailStateMap = Record<string, boolean>;

const DETAIL_SELECTOR = "details[data-system-detail-id]";

export function SystemPageShellClient({
  eyebrow,
  title,
  intro,
  versionLabel,
  meta,
  persistDetails = true,
  children,
}: SystemPageShellClientProps) {
  const contentRef = useRef<HTMLDivElement>(null);

  const detailsStorageKey = useMemo(() => {
    if (typeof window === "undefined") {
      return "thomas-system-details-unknown";
    }
    return `thomas-system-details-${window.location.pathname}`;
  }, []);

  const readDetailState = () => {
    if (typeof window === "undefined") {
      return {};
    }
    try {
      const saved = window.localStorage.getItem(detailsStorageKey);
      if (!saved) {
        return {};
      }
      const parsed = JSON.parse(saved) as DetailStateMap;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  };

  const persistDetailState = (root: HTMLElement) => {
    if (typeof window === "undefined") {
      return;
    }
    const state: DetailStateMap = {};
    const details = root.querySelectorAll<HTMLDetailsElement>(DETAIL_SELECTOR);
    for (const detail of details) {
      const detailId = detail.dataset.systemDetailId;
      if (!detailId) {
        continue;
      }
      state[detailId] = detail.open;
    }
    window.localStorage.setItem(detailsStorageKey, JSON.stringify(state));
  };

  const restoreSectionState = (root: HTMLElement) => {
    const persisted = readDetailState();
    const detailNodes = Array.from(root.querySelectorAll<HTMLDetailsElement>(DETAIL_SELECTOR));
    const hasPersisted = Object.keys(persisted).length > 0;

    detailNodes.forEach((detail) => {
      const detailId = detail.dataset.systemDetailId;
      if (!detailId || !(detailId in persisted)) {
        return;
      }
      detail.open = Boolean(persisted[detailId]);
    });

    if (!hasPersisted) {
      detailNodes.forEach((detail) => {
        if (detail.dataset.defaultOpen === "1") {
          detail.open = true;
        }
      });
    }

    persistDetailState(root);
  };

  useEffect(() => {
    if (!persistDetails) {
      return;
    }

    const root = contentRef.current;
    if (!root) {
      return;
    }
    restoreSectionState(root);

    const details = root.querySelectorAll<HTMLDetailsElement>(DETAIL_SELECTOR);
    const onToggle = () => persistDetailState(root);
    details.forEach((detail) => detail.addEventListener("toggle", onToggle));

    return () => {
      details.forEach((detail) => detail.removeEventListener("toggle", onToggle));
    };
  }, [detailsStorageKey, persistDetails]);

  return (
    <div className="system-page-shell">
      <header className="system-page-header">
        <div className="system-page-header-copy">
          {eyebrow ? <p className="system-eyebrow">{eyebrow}</p> : null}
          <h1 className="system-page-title">{title}</h1>
          {intro ? <p className="system-page-intro">{intro}</p> : null}
        </div>
        {(versionLabel || meta) ? (
          <aside className="system-page-header-meta">
            {versionLabel ? <span className="system-inline-badge">{versionLabel}</span> : null}
            {meta}
          </aside>
        ) : null}
      </header>
      <div className="system-page-layout">
        <div ref={contentRef} className="system-page-content">
          {children}
        </div>
      </div>
    </div>
  );
}
