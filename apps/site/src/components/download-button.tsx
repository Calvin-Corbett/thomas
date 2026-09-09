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
  labelPrefix?: string;
  platformLabels?: {
    windows: string;
    macos: string;
    linux: string;
  };
};

export function DownloadButton({
  source,
  className,
  labelPrefix = "Download for",
  platformLabels = { windows: "Windows", macos: "Mac", linux: "Linux" },
}: DownloadButtonProps) {
  const platform = useMemo(() => detectPlatform(), []);
  const href = `/api/download?platform=${platform}&channel=stable&source=${encodeURIComponent(source)}`;
  const platformLabel =
    platform === "macos" ? platformLabels.macos : platform === "linux" ? platformLabels.linux : platformLabels.windows;

  return (
    <a href={href} className={className ?? "cta-primary"}>
      {labelPrefix} {platformLabel}
    </a>
  );
}
