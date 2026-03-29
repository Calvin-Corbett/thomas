"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { getSiteLocaleFromPath } from "@/lib/site-locale";

export function LocaleHtmlSync() {
  const pathname = usePathname();

  useEffect(() => {
    const locale = getSiteLocaleFromPath(pathname);
    document.documentElement.lang = locale;
    document.documentElement.dataset.locale = locale;
  }, [pathname]);

  return null;
}
