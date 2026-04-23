from __future__ import annotations

import re
from contextlib import suppress
from typing import Any

_MAX_TEXT_CHARS = 8000

_CONTENT_CANDIDATES = [
    "main",
    "article",
    "[role=main]",
    "#content",
    "#main",
    ".content",
    ".main",
    ".article",
    ".post",
    ".entry-content",
    "body",
]

_STRIP_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    '[id*="cookie" i]',
    '[class*="cookie" i]',
    '[id*="consent" i]',
    '[class*="consent" i]',
    '[aria-label*="cookie" i]',
    '[aria-label*="consent" i]',
    '[role="dialog"]',
    '[class*="modal" i]',
]


def _clean_text(text: str) -> str:
    t = re.sub(r"[ \t]+", " ", text or "")
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = "\n".join(line.strip() for line in t.splitlines())
    t = t.strip()
    if len(t) > _MAX_TEXT_CHARS:
        t = t[:_MAX_TEXT_CHARS].rstrip() + "\n...[truncated]"
    return t


def _clean_inline_text(text: str | None) -> str:
    if not text:
        return ""
    value = re.sub(r"\s+", " ", str(text)).strip()
    if len(value) > 400:
        value = value[:400].rstrip() + "..."
    return value


def _same_target_url(left: str, right: str) -> bool:
    def _norm(value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        return text.rstrip("/").lower()

    return bool(_norm(left)) and _norm(left) == _norm(right)


async def _read_page_headline(page: Any, title: str = "") -> str:
    with suppress(Exception):
        headline = _clean_inline_text(await page.locator("h1").first.text_content())
        if headline:
            return headline

    with suppress(Exception):
        meta = await page.evaluate(
            """() => {
                const selectors = [
                  'meta[property="og:title"]',
                  'meta[name="twitter:title"]',
                  'meta[name="title"]'
                ];
                for (const selector of selectors) {
                  const el = document.querySelector(selector);
                  const content = (el && el.getAttribute('content')) || '';
                  if (content && content.trim()) return content.trim();
                }
                return '';
            }"""
        )
        headline = _clean_inline_text(meta if isinstance(meta, str) else "")
        if headline:
            return headline

    return _clean_inline_text(title)


async def _extract_best_text(page: Any) -> str:
    js = """
    ({ candidates, stripSelectors, maxItems }) => {
      function clean(s) { return (s || '').replace(/\\s+/g, ' ').trim(); }
      function linkDensity(el) {
        const text = clean(el.innerText || el.textContent || '');
        if (!text) return 1;
        let linkText = '';
        for (const a of el.querySelectorAll('a')) linkText += ' ' + clean(a.innerText || a.textContent || '');
        return Math.min(1, linkText.length / Math.max(1, text.length));
      }
      function cloneClean(el) {
        const c = el.cloneNode(true);
        for (const sel of stripSelectors) {
          for (const n of c.querySelectorAll(sel)) n.remove();
        }
        return c;
      }
      const scored = [];
      for (const sel of candidates) {
        for (const el of Array.from(document.querySelectorAll(sel)).slice(0, maxItems)) {
          const c = cloneClean(el);
          const text = clean(c.innerText || c.textContent || '');
          if (text.length < 80) continue;
          const density = linkDensity(c);
          scored.push({ text, score: text.length * (1 - density) });
        }
      }
      scored.sort((a, b) => b.score - a.score);
      if (scored.length) return scored[0].text;
      return clean(document.body ? (document.body.innerText || document.body.textContent || '') : '');
    }
    """
    with suppress(Exception):
        text = await page.evaluate(
            js,
            {
                "candidates": _CONTENT_CANDIDATES,
                "stripSelectors": _STRIP_SELECTORS,
                "maxItems": 2000,
            },
        )
        return str(text or "")
    with suppress(Exception):
        return str(await page.locator("body").inner_text(timeout=2000))
    return ""
