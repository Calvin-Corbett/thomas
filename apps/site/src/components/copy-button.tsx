"use client";

import { useState } from "react";

type CopyButtonProps = {
  text: string;
  label?: string;
};

export function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [status, setStatus] = useState(label);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Copied");
      window.setTimeout(() => setStatus(label), 1200);
    } catch {
      setStatus("Failed");
      window.setTimeout(() => setStatus(label), 1200);
    }
  };

  return (
    <button className="system-copy-button" type="button" onClick={onCopy}>
      {status}
    </button>
  );
}
