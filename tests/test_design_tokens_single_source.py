"""The design-token single-source contract (2026-08-06/07 unification).

tokens.css is THE design source: the five theme blocks, the accessibility
guards, and values the chat shell DERIVES at runtime. These tests pin the
invariants that two days of unification bought:

1. tokens.css carries the five-theme shell, the reduced-motion guard, and the
   global focus ring - every page linking it inherits all three.
2. chat_themes.js derives its payloads from tokens.css (no hand-mirroring).
3. The light and sandstone themes stay WCAG AA: ratios are RECOMPUTED from
   the live token values, so a color tweak that breaks contrast fails here
   with numbers, not vibes.
4. The retired theme mechanisms stay dead.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
TOKENS = (WEB / "css" / "tokens.css").read_text(encoding="utf-8")
CHAT_THEMES = (WEB / "js" / "chat_themes.js").read_text(encoding="utf-8")


def test_tokens_css_is_the_single_source() -> None:
    for theme in ("dark", "light", "aurora", "sandstone"):
        assert f'html[data-thomas-theme="{theme}"]' in TOKENS
    assert "@media (prefers-reduced-motion: reduce)" in TOKENS
    assert ":focus-visible" in TOKENS
    # the focus ring must beat inline outline suppression
    focus_block = TOKENS[TOKENS.rindex(":focus-visible") :]
    assert "!important" in focus_block.split("}")[0]


def test_chat_shell_derives_from_tokens() -> None:
    assert "deriveThemeVarsFromTokens" in CHAT_THEMES
    assert "window.ThomasChatThemes" in CHAT_THEMES
    assert "/css/tokens.css" in CHAT_THEMES  # it locates the sheet by href


def test_retired_theme_mechanisms_stay_dead() -> None:
    living = []
    for path in list((WEB / "js").rglob("*.js")) + list(WEB.glob("*.html")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ("te-theme-light'", 'te-theme-light"', "te-space-active"):
            if needle in text:
                living.append(f"{path.name}: {needle}")
    assert not living, (
        "a retired theme class came back to life (the unified engine on <html> "
        f"is the only theme authority): {living}"
    )


# ---- WCAG AA, recomputed from the live token values ----

def _theme_block(name: str) -> str:
    if name == "nebula":
        start = TOKENS.index(":root")
    else:
        start = TOKENS.index(f'html[data-thomas-theme="{name}"]')
    return TOKENS[start : TOKENS.index("}", start)]


def _token(block: str, key: str, fallback_block: str = "") -> str:
    for source in (block, fallback_block):
        m = re.search(re.escape(key) + r":\s*([^;]+);", source)
        if m:
            return m.group(1).strip()
    raise AssertionError(f"{key} not found")


def _rgb(value: str, backdrop: tuple[float, float, float]) -> tuple[float, float, float]:
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.match(r"rgba\(([^)]+)\)", value)
    assert m, value
    parts = [float(p) for p in m.group(1).split(",")]
    r, g, b = parts[:3]
    a = parts[3] if len(parts) > 3 else 1.0
    br, bg, bb = backdrop
    return (r * a + br * (1 - a), g * a + bg * (1 - a), b * a + bb * (1 - a))


def _ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    def lum(rgb: tuple[float, float, float]) -> float:
        def f(c: float) -> float:
            c = c / 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = rgb
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    l1, l2 = lum(fg), lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def test_light_themes_stay_wcag_aa() -> None:
    root = _theme_block("nebula")
    failures = []
    for name in ("light", "sandstone"):
        block = _theme_block(name)
        bg = _rgb(_token(block, "--c-bg", root), (255, 255, 255))
        menu = _rgb(_token(block, "--c-menu-bg", root), bg)
        for ink_key, minimum in (("--c-text", 4.5), ("--c-dim", 4.5), ("--c-muted", 4.5), ("--c-accent", 4.5)):
            ink_raw = _token(block, ink_key, root)
            for surface_name, surface in (("bg", bg), ("menu", menu)):
                ink = _rgb(ink_raw, surface)
                r = _ratio(ink, surface)
                if r < minimum:
                    failures.append(f"{name} {ink_key} on {surface_name}: {r:.2f} < {minimum}")
        # buttons: the accent-ink pair must hold in both directions
        accent = _rgb(_token(block, "--c-accent", root), bg)
        accent_ink = _rgb(_token(block, "--c-accent-ink", root), accent)
        r = _ratio(accent_ink, accent)
        if r < 4.5:
            failures.append(f"{name} accent-ink on accent: {r:.2f} < 4.5")
    assert not failures, "WCAG AA regression in the light themes: " + "; ".join(failures)
