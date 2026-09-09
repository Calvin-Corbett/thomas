"use client";

import { useEffect } from "react";

export function SplineViewerLoader() {
  useEffect(() => {
    void import("@splinetool/viewer");
  }, []);

  return null;
}
