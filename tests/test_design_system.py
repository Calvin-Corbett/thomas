"""Hermetic tests for the design-system scanner (CAP-115).

These tests build a small fixture project in a temp dir, then prove the
acceptance line: components + tokens are discovered with their locations; a
requested element that matches an existing component recommends REUSE (not
new); an off-system color value is mapped to the nearest on-system token; a
genuinely-absent component is reported as needs-new; determinism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.design_system import (
    TOKEN_COLOR,
    TOKEN_SPACING,
    TOKEN_TYPOGRAPHY,
    DesignSystemScanner,
    color_distance,
    parse_color,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal on-system fixture project: components + CSS + tokens.json."""
    src = tmp_path / "src" / "components"
    src.mkdir(parents=True)

    (src / "Button.tsx").write_text(
        """
        import React from "react";

        interface ButtonProps {
          label: string;
          onClick?: () => void;
          variant?: "primary" | "secondary";
        }

        export function Button({ label, onClick, variant = "primary" }: ButtonProps) {
          return <button onClick={onClick}>{label}</button>;
        }
        """.strip(),
        encoding="utf-8",
    )

    (src / "Modal.tsx").write_text(
        """
        import React from "react";

        export const Modal = ({ open, title, children }: { open: boolean; title: string; children: any }) => {
          return open ? <div className="modal">{title}{children}</div> : null;
        };
        """.strip(),
        encoding="utf-8",
    )

    (src / "Avatar.jsx").write_text(
        """
        export default function Avatar({ src, alt }) {
          return <img src={src} alt={alt} className="avatar" />;
        }
        """.strip(),
        encoding="utf-8",
    )

    styles = tmp_path / "src" / "styles"
    styles.mkdir(parents=True)
    (styles / "tokens.css").write_text(
        """
        :root {
          --color-primary: #3366ff;
          --color-danger: #ff0000;
          --color-surface: #ffffff;
          --spacing-sm: 8px;
          --spacing-md: 16px;
          --font-body: "Inter", sans-serif;
          --color-alias: var(--color-primary);
        }
        """.strip(),
        encoding="utf-8",
    )

    (tmp_path / "tokens.json").write_text(
        """
        {
          "colors": { "brand-teal": "#008080" },
          "spacing": { "lg": "24px" },
          "typography": { "heading": "700 24px/1.2 Inter" }
        }
        """.strip(),
        encoding="utf-8",
    )

    # Noise that must be ignored.
    ndir = tmp_path / "node_modules" / "junk"
    ndir.mkdir(parents=True)
    (ndir / "Ignored.tsx").write_text("export function IgnoreMe() { return null; }", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Discovery with locations
# ---------------------------------------------------------------------------


def test_discovers_components_with_locations_and_props(project: Path) -> None:
    scanner = DesignSystemScanner(project)
    result = scanner.discover()

    names = result.component_names()
    assert names == ["Avatar", "Button", "Modal"]  # sorted, node_modules excluded

    by_name = {c.name: c for c in result.components}
    assert by_name["Button"].file == "src/components/Button.tsx"
    # Props come from the destructured parameter.
    assert by_name["Button"].props == ("label", "onClick", "variant")
    assert by_name["Modal"].file == "src/components/Modal.tsx"
    assert by_name["Avatar"].file == "src/components/Avatar.jsx"
    assert by_name["Avatar"].props == ("src", "alt")
    # Roles are inferred deterministically.
    assert by_name["Button"].role == "button"
    assert by_name["Modal"].role == "modal"
    assert by_name["Avatar"].role == "avatar"


def test_discovers_tokens_with_locations_and_categories(project: Path) -> None:
    scanner = DesignSystemScanner(project)
    result = scanner.discover()

    colors = {t.name: t for t in result.tokens_by_category(TOKEN_COLOR)}
    assert "color-primary" in colors
    assert colors["color-primary"].value == "#3366ff"
    assert colors["color-primary"].file == "src/styles/tokens.css"
    assert colors["color-primary"].rgb == (0x33, 0x66, 0xFF)
    # tokens.json color is discovered too, with its own location.
    assert "brand-teal" in colors
    assert colors["brand-teal"].file == "tokens.json"

    spacing = {t.name for t in result.tokens_by_category(TOKEN_SPACING)}
    assert {"spacing-sm", "spacing-md", "lg"} <= spacing

    typography = {t.name for t in result.tokens_by_category(TOKEN_TYPOGRAPHY)}
    assert "font-body" in typography
    assert "heading" in typography

    # var() aliases are not recorded as concrete tokens.
    assert all(t.name != "color-alias" for t in result.tokens)


# ---------------------------------------------------------------------------
# Reuse recommendation (the core "don't reinvent" behaviour)
# ---------------------------------------------------------------------------


def test_requested_element_matching_component_recommends_reuse(project: Path) -> None:
    scanner = DesignSystemScanner(project)

    # Exact name.
    rec = scanner.recommend_component("Button")
    assert rec.reuse is True
    assert rec.action == "reuse"
    assert rec.component is not None
    assert rec.component.name == "Button"
    assert rec.match_reason == "name"


def test_reuse_by_semantic_role_not_exact_name(project: Path) -> None:
    scanner = DesignSystemScanner(project)

    # "PrimaryCTA" is not a component name, but role -> button.
    rec = scanner.recommend_component("PrimaryCTA")
    assert rec.reuse is True
    assert rec.component is not None
    assert rec.component.name == "Button"
    assert rec.match_reason == "role"
    assert rec.role == "button"

    # "ConfirmDialog" -> modal role -> Modal component.
    rec2 = scanner.recommend_component("ConfirmDialog")
    assert rec2.reuse is True
    assert rec2.component is not None
    assert rec2.component.name == "Modal"
    assert rec2.match_reason == "role"


def test_absent_component_reports_needs_new(project: Path) -> None:
    scanner = DesignSystemScanner(project)

    rec = scanner.recommend_component("DataTable")
    assert rec.reuse is False
    assert rec.action == "needs_new"
    assert rec.component is None


# ---------------------------------------------------------------------------
# Off-system color -> nearest on-system token
# ---------------------------------------------------------------------------


def test_offsystem_color_maps_to_nearest_token(project: Path) -> None:
    scanner = DesignSystemScanner(project)

    # #3162fa is a hair off the primary #3366ff and far from danger/surface/teal.
    suggestion = scanner.suggest_token("#3162fa")
    assert suggestion is not None
    assert suggestion.token.name == "color-primary"
    assert suggestion.exact is False
    assert suggestion.distance > 0

    # A near-red maps to the danger token, not primary.
    red = scanner.suggest_token("#fe0202")
    assert red is not None
    assert red.token.name == "color-danger"


def test_exact_onsystem_color_flags_exact(project: Path) -> None:
    scanner = DesignSystemScanner(project)
    suggestion = scanner.suggest_token("#3366ff")
    assert suggestion is not None
    assert suggestion.token.name == "color-primary"
    assert suggestion.exact is True
    assert suggestion.distance == 0.0


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


def test_coverage_splits_covered_and_needs_new(project: Path) -> None:
    scanner = DesignSystemScanner(project)
    report = scanner.assess_coverage(
        components=["Button", "PrimaryCTA", "DataTable"],
        colors=["#3366ff", "#123456"],
    )

    covered = {i.requested for i in report.covered}
    needs_new = {i.requested for i in report.needs_new}

    assert "Button" in covered
    assert "PrimaryCTA" in covered  # role reuse
    assert "#3366ff" in covered  # exact token
    assert "DataTable" in needs_new
    assert "#123456" in needs_new  # off-system color -> not covered

    # Off-system color still carries a nearest-token suggestion.
    offsys = next(i for i in report.items if i.requested == "#123456")
    assert offsys.suggestion is not None
    assert offsys.suggestion.token.category == TOKEN_COLOR

    assert 0.0 < report.coverage_ratio < 1.0


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_discovery_is_deterministic(project: Path) -> None:
    a = DesignSystemScanner(project).discover().as_dict()
    b = DesignSystemScanner(project).discover().as_dict()
    assert a == b


def test_recommendation_and_suggestion_deterministic(project: Path) -> None:
    s1 = DesignSystemScanner(project)
    s2 = DesignSystemScanner(project)
    assert s1.recommend_component("PrimaryCTA").as_dict() == s2.recommend_component("PrimaryCTA").as_dict()
    assert s1.suggest_token("#3162fa").as_dict() == s2.suggest_token("#3162fa").as_dict()


# ---------------------------------------------------------------------------
# Color-parse unit coverage (supports the nearest-token math)
# ---------------------------------------------------------------------------


def test_parse_color_formats() -> None:
    assert parse_color("#fff") == (255, 255, 255)
    assert parse_color("#000000") == (0, 0, 0)
    assert parse_color("rgb(255, 0, 0)") == (255, 0, 0)
    assert parse_color("rgba(0, 128, 0, 0.5)") == (0, 128, 0)
    assert parse_color("navy") == (0, 0, 128)
    assert parse_color("not-a-color") is None


def test_color_distance_zero_for_identical() -> None:
    assert color_distance((10, 20, 30), (10, 20, 30)) == 0.0
    assert color_distance((0, 0, 0), (255, 255, 255)) > 0


def test_empty_project_is_safe(tmp_path: Path) -> None:
    scanner = DesignSystemScanner(tmp_path)
    result = scanner.discover()
    assert result.components == []
    assert result.tokens == []
    assert scanner.recommend_component("Button").action == "needs_new"
    assert scanner.suggest_token("#3366ff") is None
