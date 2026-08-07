"""Satellite surfaces converge on the Chat token language (satellite-restyle).

Pins, per the 2026-08 audit:
- the LIVE marketplace shell (runtime renderer + marketplace-workspace.css) has
  no hardcoded rgba(88,166,255) blue left and no marketing-hero headline;
- composer.css runs on tokens (more var() references than raw hex colors);
- evolution.css forge tokens point at the canonical --c-* semantics and use
  var(--font-mono) instead of literal monospace stacks;
- token_economy_widget.css reserves mono for numeric cells only;
- the three injected-palette panels (mention context, PR review, source
  annotation) define their palettes from --c-* tokens, not #-hex literals.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"

MARKETPLACE_CSS = WEB / "css" / "component_styles" / "marketplace-workspace.css"
MARKETPLACE_RENDERER = WEB / "js" / "runtime" / "036_workbench_editors_08.js"
COMPOSER_CSS = WEB / "css" / "composer.css"
EVOLUTION_CSS = WEB / "css" / "evolution.css"
TOKEN_WIDGET_CSS = WEB / "css" / "token_economy_widget.css"
PANELS = (
    WEB / "js" / "mention_context_panel.js",
    WEB / "js" / "pr_review_panel.js",
    WEB / "js" / "source_annotation_panel.js",
)

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_marketplace_styles_carry_no_hardcoded_signal_blue() -> None:
    css = _read(MARKETPLACE_CSS)
    assert "rgba(88, 166, 255" not in css
    assert "rgba(88,166,255" not in css


def test_marketplace_feature_copy_is_a_workspace_header_not_a_marketing_hero() -> None:
    renderer = _read(MARKETPLACE_RENDERER)
    for marketing_line in (
        "Extend what Thomas can do.",
        "Build your own workflow.",
        "Ideas waiting for real wiring.",
        "Explore, then verify.",
    ):
        assert marketing_line not in renderer
    # The quarantine eyebrow is a behavioural contract pinned elsewhere -- keep it.
    assert "Potential · local review only" in renderer
    css = _read(MARKETPLACE_CSS)
    modern = css.split("/* Marketplace modernization:", maxsplit=1)[1]
    # Eyebrow group is caps, like every sibling workspace header.
    assert "text-transform:uppercase" in modern


def test_marketplace_primary_cta_uses_the_token_accent_button_profile() -> None:
    css = _read(MARKETPLACE_CSS)
    modern = css.split("/* Marketplace modernization:", maxsplit=1)[1]
    assert "background:var(--c-accent)!important" in modern
    assert "color:var(--c-accent-ink)!important" in modern
    # Still no raw colors in the modern section.
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", modern)


def test_composer_css_is_token_driven_not_a_hex_ramp() -> None:
    css = _read(COMPOSER_CSS)
    hex_count = len(HEX_RE.findall(css))
    var_count = css.count("var(--")
    assert var_count > hex_count, (
        f"composer.css should lean on tokens: var()={var_count} hex={hex_count}"
    )
    for token in ("--c-composer-bg", "--c-text", "--c-dim", "--c-accent"):
        assert f"var({token}" in css


def test_evolution_forge_tokens_point_at_canonical_semantics() -> None:
    css = _read(EVOLUTION_CSS)
    assert "--fc-accent: var(--c-accent)" in css
    assert "--fc-warn: var(--c-warn)" in css
    assert "--fc-danger: var(--c-danger)" in css
    assert "ui-monospace, \"SFMono-Regular\", Menlo, Consolas, monospace" not in css


def test_token_economy_widget_reserves_mono_for_numeric_cells() -> None:
    css = _read(TOKEN_WIDGET_CSS)
    # Labels (mode pill, live badge) read in the label face, not mono.
    for selector, rules in _rule_map(css).items():
        if ".te-mode-pill" in selector or ".te-topbar-live" in selector:
            assert "ui-monospace" not in rules
            if "font:" in rules or "font-family:" in rules:
                assert "var(--font-label" in rules
    # Numeric cells stay tabular/mono via the token, not a literal stack.
    assert "ui-monospace, SFMono-Regular" not in css
    assert "var(--font-mono" in css


def _rule_map(css: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        out[match.group(1).strip()] = match.group(2)
    return out


def test_injected_panel_palettes_are_token_based() -> None:
    for path in PANELS:
        body = _read(path)
        hexes = HEX_RE.findall(body)
        assert not hexes, f"{path.name} still injects hex colors: {sorted(set(hexes))}"
        assert "var(--c-" in body, f"{path.name} should consume --c-* tokens"
