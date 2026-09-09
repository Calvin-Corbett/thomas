"use client";

import { CopyButton } from "@/components/copy-button";

type CodeBlockProps = {
  title?: string;
  language?: string;
  children: string;
  copyText?: string;
};

export function CodeBlock({ title, language = "text", children, copyText }: CodeBlockProps) {
  const content = children.trim();
  const payload = copyText ?? content;

  return (
    <figure className="code-block">
      <div className="code-block-head">
        {title ? <figcaption>{title}</figcaption> : null}
        <CopyButton text={payload} />
      </div>
      <pre>
        <code className={`language-${language}`}>{content}</code>
      </pre>
    </figure>
  );
}
