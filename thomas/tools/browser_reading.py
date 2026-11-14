"""Finding things on a page and reading them back.

Split out of ``browser.py`` on 2026-09-21: that file was 1001 lines, past the
800-line soft limit, so nothing in it could be changed until some of it moved.
These are the parts that take a Playwright ``Page`` or ``Locator`` and answer a
question about it -- no browser session state, no tool plumbing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from thomas.tools.browser_page import _clean_text, _looks_like_css_or_xpath, _normalize_selector

if TYPE_CHECKING:  # annotations only -- no runtime dependency on playwright
    from playwright.async_api import Locator, Page


# Prefer these containers in order, but we still score candidates for "best" content.
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

# Strip obvious chrome/noise inside the candidate clone (keeps extraction clean).
_STRIP_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    # cookie/consent patterns
    '[id*="cookie" i]',
    '[class*="cookie" i]',
    '[id*="consent" i]',
    '[class*="consent" i]',
    '[aria-label*="cookie" i]',
    '[aria-label*="consent" i]',
    '[role="dialog"]',
    '[class*="modal" i]',
]


async def _resolve_locator_for_click(page: Page, selector: str) -> Locator:
    """
    If selector looks like CSS/XPath/engine, use page.locator.
    Else treat as human label: button/link role -> get_by_text fallback.
    """
    s = (selector or "").strip()
    if _looks_like_css_or_xpath(s):
        return page.locator(_normalize_selector(s)).first

    # Human label path: prefer roles consumers expect.
    # Note: get_by_role matches accessible name; very robust on modern sites.
    try:
        return page.get_by_role("button", name=s).first
    except Exception:
        pass
    try:
        return page.get_by_role("link", name=s).first
    except Exception:
        pass
    # broader fallback: partial text
    return page.get_by_text(s, exact=False).first


async def _resolve_locator_for_type(page: Page, selector: str) -> Locator:
    """
    If selector looks like CSS/XPath/engine, use page.locator.
    Else treat as human label/placeholder.
    """
    s = (selector or "").strip()
    if _looks_like_css_or_xpath(s):
        return page.locator(_normalize_selector(s)).first

    # Human label path: label is the most consumer-friendly.
    try:
        return page.get_by_label(s, exact=False).first
    except Exception:
        pass
    try:
        return page.get_by_placeholder(s, exact=False).first
    except Exception:
        pass
    # fallback: a direct text match (less ideal for inputs, but better than nothing)
    return page.get_by_text(s, exact=False).first


# ----------------------------
# Better text extraction
# ----------------------------


async def _extract_best_text(page: Page) -> str:
    """
    Picks best content container by scoring candidates:
    score = textLen - 0.6 * linkTextLen
    after stripping common chrome/noise from a cloned node.

    Returns innerText-like visible text.
    """
    js = r"""
    (candidates, stripSelectors) => {
      const strip = (root) => {
        try {
          for (const sel of stripSelectors) {
            const nodes = root.querySelectorAll(sel);
            for (const n of nodes) n.remove();
          }
        } catch (e) {}
      };

      const scoreNode = (node) => {
        if (!node) return {score: 0, text: ""};
        const clone = node.cloneNode(true);
        strip(clone);

        const text = (clone.innerText || "").trim();
        if (!text) return {score: 0, text: ""};

        // link density penalty
        let linkTextLen = 0;
        try {
          const links = clone.querySelectorAll("a");
          for (const a of links) linkTextLen += ((a.innerText || "").trim().length);
        } catch (e) {}

        const score = text.length - 0.6 * linkTextLen;
        return {score, text};
      };

      const seen = new Set();
      const nodes = [];
      for (const sel of candidates) {
        const el = document.querySelector(sel);
        if (el && !seen.has(el)) {
          seen.add(el);
          nodes.push(el);
        }
      }
      if (!nodes.length && document.body) nodes.push(document.body);

      let best = {score: 0, text: ""};
      for (const n of nodes) {
        const r = scoreNode(n);
        if (r.score > best.score) best = r;
      }

      // final fallback
      if (!best.text && document.body) best.text = (document.body.innerText || document.body.textContent || "");
      return best.text || "";
    }
    """
    try:
        txt = await page.evaluate(js, _CONTENT_CANDIDATES, _STRIP_SELECTORS)
        return txt if isinstance(txt, str) else ""
    except Exception:
        try:
            txt = await page.evaluate("() => document.body ? document.body.innerText : ''")
            return txt if isinstance(txt, str) else ""
        except Exception:
            try:
                txt = await page.evaluate("() => document.body ? document.body.textContent : ''")
                return txt if isinstance(txt, str) else ""
            except Exception:
                return ""


# ----------------------------
# Tools
# ----------------------------
