"use client";

import { useMemo } from "react";
import type { DownloadPlatform } from "@/lib/types";

function detectPlatform(): DownloadPlatform {
  if (typeof navigator === "undefined") return "windows";
  const value = navigator.userAgent.toLowerCase();
  if (value.includes("mac")) return "macos";
  if (value.includes("linux")) return "linux";
  return "windows";
}

type DownloadButtonProps = {
  source: string;
  className?: string;
};

export function DownloadButton({ source, className }: DownloadButtonProps) {
  const platform = useMemo(() => detectPlatform(), []);
  const href = `/api/download?platform=${platform}&channel=stable&source=${encodeURIComponent(source)}`;

  return (
    <a href={href} className={className ?? "cta-primary"}>
      Download for {platform === "macos" ? "Mac" : platform === "linux" ? "Linux" : "Windows"}
    </a>
  );
}
