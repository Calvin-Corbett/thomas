import type { ReactNode } from "react";

type Tone = "warning" | "info" | "spec" | "example";

type CalloutProps = {
  tone?: Tone;
  title: string;
  children: ReactNode;
};

const toneNames: Record<Tone, string> = {
  warning: "Warning",
  info: "Information",
  spec: "Specification",
  example: "Example",
};

export function CalloutBlock({ tone = "info", title, children }: CalloutProps) {
  return (
    <aside className={`callout-block callout-${tone}`}>
      <p className="callout-kicker">{toneNames[tone]}</p>
      <p className="callout-title">{title}</p>
      <div className="callout-body">{children}</div>
    </aside>
  );
}
