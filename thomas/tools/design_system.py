"""Design-system / component awareness for target projects (CAP-115).

A :class:`DesignSystemScanner` inspects a target project directory and builds an
awareness of its *reusable surface*: the components it already defines and the
design tokens (colors, spacing, typography) it standardises on. It then answers
three practical questions an agent faces before writing new UI:

1. **Discovery** -- what components and tokens already exist, and where?
   Component definitions are parsed from React/TSX/JSX/TS sources (exported
   ``function``/``const`` components, with their props) or from a ``components``
   manifest. Design tokens are parsed from CSS custom properties (``--name:
   value``) and/or a ``tokens.json`` file.

2. **Reuse recommendation** -- given a requested UI element, should the agent
   reuse an existing on-system component instead of inventing one? Matching is
   by name, then by semantic role (a small deterministic synonym table maps
   ``btn``/``cta`` -> button, ``dialog`` -> modal, and so on). When a requested
   *style value* is off-system (e.g. a raw hex color), the scanner suggests the
   nearest on-system token by perceptual color distance.

3. **Coverage** -- for a batch of requested pieces, which map onto existing
   system parts and which genuinely need new work.

The scanner is fully deterministic and depends only on the standard library so
it runs hermetically over a fixture project with no network or external tools.
"""

from __future__ import annotations

import colorsys
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Component",
    "DesignToken",
    "DiscoveryResult",
    "Recommendation",
    "TokenSuggestion",
    "CoverageItem",
    "CoverageReport",
    "DesignSystemScanner",
]

# Source extensions we parse for component definitions.
_COMPONENT_EXTS = {".tsx", ".jsx", ".ts", ".js", ".mjs"}

# Directories never worth scanning.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".cache",
    "coverage",
}

# CSS named colors we need for token discovery / nearest matching. A compact
# but useful subset -- extend as needed; unknown names simply fail to resolve
# to RGB and are skipped from distance math (still recorded as tokens).
_CSS_NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "navy": (0, 0, 128),
    "teal": (0, 128, 128),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "maroon": (128, 0, 0),
    "olive": (128, 128, 0),
    "lime": (0, 255, 0),
    "aqua": (0, 255, 255),
    "fuchsia": (255, 0, 255),
    "slategray": (112, 128, 144),
    "slategrey": (112, 128, 144),
}

# Token categories.
TOKEN_COLOR = "color"
TOKEN_SPACING = "spacing"
TOKEN_TYPOGRAPHY = "typography"
TOKEN_OTHER = "other"

# Semantic role synonyms. Maps a canonical role -> the set of tokens that imply
# it. Used both to classify existing component names and to resolve a requested
# element to a role so name spelling need not match exactly.
_ROLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "button": ("button", "btn", "cta"),
    "modal": ("modal", "dialog", "popup", "overlay", "lightbox"),
    "input": ("input", "textfield", "textbox", "field", "textinput"),
    "card": ("card", "tile", "panel"),
    "nav": ("nav", "navbar", "navigation", "menubar"),
    "avatar": ("avatar", "userpic", "profilepic"),
    "badge": ("badge", "chip", "tag", "pill"),
    "tooltip": ("tooltip", "hint"),
    "dropdown": ("dropdown", "select", "combobox", "picker"),
    "checkbox": ("checkbox", "check", "tickbox"),
    "toggle": ("toggle", "switch"),
    "spinner": ("spinner", "loader", "loading"),
    "table": ("table", "grid", "datagrid", "datatable"),
    "tabs": ("tabs", "tab", "tabbar"),
    "accordion": ("accordion", "collapse", "disclosure"),
    "breadcrumb": ("breadcrumb", "breadcrumbs"),
    "alert": ("alert", "banner", "notification", "toast", "snackbar"),
}


def _normalize_name(name: str) -> str:
    """Lowercase and strip non-alphanumeric characters for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _role_of(name: str) -> str | None:
    """Resolve the semantic role of a component/element name, if any.

    The name is normalized then matched against role synonym tokens. A synonym
    matches when it appears as a substring of the normalized name so that
    ``PrimaryButton`` -> ``button`` and ``ConfirmDialog`` -> ``modal``.
    """
    norm = _normalize_name(name)
    if not norm:
        return None
    best: tuple[int, str] | None = None
    for role, synonyms in _ROLE_SYNONYMS.items():
        for syn in synonyms:
            if syn in norm:
                # Prefer the longest synonym match for specificity/determinism.
                cand = (len(syn), role)
                if best is None or cand > best:
                    best = cand
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    """A discovered reusable component."""

    name: str
    file: str
    props: tuple[str, ...] = ()
    role: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "file": self.file,
            "props": list(self.props),
            "role": self.role,
        }


@dataclass(frozen=True)
class DesignToken:
    """A discovered design token (color / spacing / typography / other)."""

    name: str
    value: str
    category: str
    file: str
    rgb: tuple[int, int, int] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "category": self.category,
            "file": self.file,
            "rgb": list(self.rgb) if self.rgb else None,
        }


@dataclass
class DiscoveryResult:
    """Everything the scanner found in a target project."""

    components: list[Component] = field(default_factory=list)
    tokens: list[DesignToken] = field(default_factory=list)

    def component_names(self) -> list[str]:
        return [c.name for c in self.components]

    def tokens_by_category(self, category: str) -> list[DesignToken]:
        return [t for t in self.tokens if t.category == category]

    def as_dict(self) -> dict[str, object]:
        return {
            "components": [c.as_dict() for c in self.components],
            "tokens": [t.as_dict() for t in self.tokens],
        }


@dataclass(frozen=True)
class TokenSuggestion:
    """Nearest on-system token suggested for an off-system value."""

    requested_value: str
    token: DesignToken
    distance: float
    exact: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "requested_value": self.requested_value,
            "token": self.token.as_dict(),
            "distance": round(self.distance, 4),
            "exact": self.exact,
        }


@dataclass(frozen=True)
class Recommendation:
    """Whether a requested UI element should reuse an existing component."""

    requested: str
    action: str  # "reuse" | "needs_new"
    component: Component | None = None
    match_reason: str | None = None  # "name" | "role" | None
    role: str | None = None

    @property
    def reuse(self) -> bool:
        return self.action == "reuse"

    def as_dict(self) -> dict[str, object]:
        return {
            "requested": self.requested,
            "action": self.action,
            "component": self.component.as_dict() if self.component else None,
            "match_reason": self.match_reason,
            "role": self.role,
        }


@dataclass(frozen=True)
class CoverageItem:
    """One requested piece mapped to system coverage."""

    kind: str  # "component" | "color"
    requested: str
    covered: bool
    recommendation: Recommendation | None = None
    suggestion: TokenSuggestion | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "requested": self.requested,
            "covered": self.covered,
            "recommendation": self.recommendation.as_dict() if self.recommendation else None,
            "suggestion": self.suggestion.as_dict() if self.suggestion else None,
        }


@dataclass
class CoverageReport:
    """Coverage across a batch of requested pieces."""

    items: list[CoverageItem] = field(default_factory=list)

    @property
    def covered(self) -> list[CoverageItem]:
        return [i for i in self.items if i.covered]

    @property
    def needs_new(self) -> list[CoverageItem]:
        return [i for i in self.items if not i.covered]

    @property
    def coverage_ratio(self) -> float:
        if not self.items:
            return 0.0
        return len(self.covered) / len(self.items)

    def as_dict(self) -> dict[str, object]:
        return {
            "items": [i.as_dict() for i in self.items],
            "covered_count": len(self.covered),
            "needs_new_count": len(self.needs_new),
            "coverage_ratio": round(self.coverage_ratio, 4),
        }


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB_RE = re.compile(r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)$")
_HSL_RE = re.compile(r"^hsla?\(\s*(\d{1,3})\s*,\s*(\d{1,3})%\s*,\s*(\d{1,3})%\s*(?:,\s*[\d.]+\s*)?\)$")


def parse_color(value: str) -> tuple[int, int, int] | None:
    """Parse a CSS color literal into an ``(r, g, b)`` tuple, or ``None``.

    Supports ``#rgb``, ``#rrggbb``, ``rgb()/rgba()``, ``hsl()/hsla()``, and a
    subset of named colors. Deterministic and stdlib-only.
    """
    v = value.strip().lower()
    m = _HEX_RE.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = _RGB_RE.match(v)
    if m:
        rgb = tuple(min(255, int(m.group(i))) for i in (1, 2, 3))
        return rgb  # type: ignore[return-value]
    m = _HSL_RE.match(v)
    if m:
        h = int(m.group(1)) % 360 / 360.0
        s = min(100, int(m.group(2))) / 100.0
        light = min(100, int(m.group(3))) / 100.0
        r, g, b = colorsys.hls_to_rgb(h, light, s)
        return (round(r * 255), round(g * 255), round(b * 255))
    if v in _CSS_NAMED_COLORS:
        return _CSS_NAMED_COLORS[v]
    return None


def _is_color_value(value: str) -> bool:
    return parse_color(value) is not None


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Perceptual-ish RGB distance using a low-cost weighted Euclidean metric.

    Uses the "redmean" weighting which approximates perceptual difference far
    better than plain Euclidean distance while remaining pure arithmetic.
    """
    rmean = (a[0] + b[0]) / 2.0
    dr = a[0] - b[0]
    dg = a[1] - b[1]
    db = a[2] - b[2]
    weight_r = 2 + rmean / 256.0
    weight_g = 4.0
    weight_b = 2 + (255 - rmean) / 256.0
    return (weight_r * dr * dr + weight_g * dg * dg + weight_b * db * db) ** 0.5


# ---------------------------------------------------------------------------
# Component parsing
# ---------------------------------------------------------------------------

# export function Foo(...)   |   export default function Foo(...)
_FUNC_COMP_RE = re.compile(r"\bexport\s+(?:default\s+)?function\s+([A-Z][A-Za-z0-9_]*)\s*\(([^)]*)\)")
# export const Foo = (...) =>   |   export const Foo: React.FC = (...) =>
_CONST_COMP_RE = re.compile(
    r"\bexport\s+const\s+([A-Z][A-Za-z0-9_]*)\s*(?::[^=]+?)?=\s*"
    r"(?:React\.)?(?:memo\(|forwardRef\()?\s*(?:function\s*)?\(([^)]*)\)\s*(?::[^=]+?)?=>",
)
# TypeScript props interface/type:  interface FooProps { a: string; b?: number }
_PROPS_TYPE_RE = re.compile(
    r"\b(?:interface|type)\s+([A-Za-z0-9_]*Props)\s*(?:=\s*)?\{([^}]*)\}",
    re.DOTALL,
)


def _extract_destructured_props(param_src: str) -> tuple[str, ...]:
    """Pull prop names from a destructured component parameter.

    ``{ label, onClick, variant = "primary" }`` -> ``("label", "onClick",
    "variant")``. Non-destructured params yield no props here (they are resolved
    from a Props type instead).
    """
    brace = re.search(r"\{(.*)\}", param_src, re.DOTALL)
    if not brace:
        return ()
    inner = brace.group(1)
    props: list[str] = []
    for raw in inner.split(","):
        token = raw.strip()
        if not token or token.startswith("..."):
            continue
        # Strip default values and renames: `variant = 'x'`, `label: l`.
        token = token.split("=", 1)[0].split(":", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            props.append(token)
    return tuple(dict.fromkeys(props))


def _extract_type_props(body: str) -> tuple[str, ...]:
    """Pull prop names from a TS interface/type body."""
    props: list[str] = []
    for raw in re.split(r"[;\n]", body):
        token = raw.strip()
        if not token:
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\??\s*:", token)
        if m:
            props.append(m.group(1))
    return tuple(dict.fromkeys(props))


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class DesignSystemScanner:
    """Discover and reason about a target project's design system.

    Parameters
    ----------
    root:
        The target project directory to scan.
    max_files:
        Safety cap on the number of source files parsed (deterministic ordering
        by sorted path, so the cap is stable).
    """

    def __init__(self, root: str | Path, *, max_files: int = 5000) -> None:
        self.root = Path(root)
        self.max_files = max_files
        self._discovery: DiscoveryResult | None = None

    # -- discovery ------------------------------------------------------------

    def discover(self, *, refresh: bool = False) -> DiscoveryResult:
        """Discover components and tokens. Result is cached (pass refresh)."""
        if self._discovery is not None and not refresh:
            return self._discovery
        components: list[Component] = []
        tokens: list[DesignToken] = []
        seen_components: set[tuple[str, str]] = set()
        seen_tokens: set[tuple[str, str]] = set()

        for path in self._iter_files():
            rel = self._relpath(path)
            suffix = path.suffix.lower()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeError):
                # File vanished / unreadable mid-scan: skip it, keep scanning.
                continue
            if suffix in _COMPONENT_EXTS:
                for comp in self._parse_components(text, rel):
                    key = (comp.name, comp.file)
                    if key not in seen_components:
                        seen_components.add(key)
                        components.append(comp)
            elif suffix == ".css":
                for tok in self._parse_css_tokens(text, rel):
                    key = (tok.name, tok.file)
                    if key not in seen_tokens:
                        seen_tokens.add(key)
                        tokens.append(tok)
            elif path.name in ("tokens.json", "design-tokens.json"):
                for tok in self._parse_tokens_json(text, rel):
                    key = (tok.name, tok.file)
                    if key not in seen_tokens:
                        seen_tokens.add(key)
                        tokens.append(tok)
            elif path.name in ("components.json", "components.manifest.json"):
                for comp in self._parse_components_manifest(text, rel):
                    key = (comp.name, comp.file)
                    if key not in seen_components:
                        seen_components.add(key)
                        components.append(comp)

        components.sort(key=lambda c: (c.name, c.file))
        tokens.sort(key=lambda t: (t.category, t.name, t.file))
        self._discovery = DiscoveryResult(components=components, tokens=tokens)
        return self._discovery

    def _iter_files(self):
        if not self.root.is_dir():
            return
        all_paths = [p for p in self.root.rglob("*") if p.is_file() and not any(part in _SKIP_DIRS for part in p.parts)]
        all_paths.sort(key=lambda p: str(p).replace("\\", "/"))
        yield from all_paths[: self.max_files]

    def _relpath(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    # -- component parsing ----------------------------------------------------

    def _parse_components(self, text: str, rel: str) -> list[Component]:
        # Resolve Props types first so component params can reference them.
        type_props: dict[str, tuple[str, ...]] = {}
        for m in _PROPS_TYPE_RE.finditer(text):
            type_props[m.group(1)] = _extract_type_props(m.group(2))

        found: dict[str, Component] = {}

        def _record(name: str, param_src: str, full_match: str) -> None:
            props = _extract_destructured_props(param_src)
            if not props:
                # Try a `: FooProps` annotation on the parameter.
                ann = re.search(r":\s*([A-Za-z0-9_]*Props)\b", param_src) or re.search(
                    r":\s*([A-Za-z0-9_]*Props)\b", full_match
                )
                if ann and ann.group(1) in type_props:
                    props = type_props[ann.group(1)]
                elif f"{name}Props" in type_props:
                    props = type_props[f"{name}Props"]
            if name not in found:
                found[name] = Component(name=name, file=rel, props=props, role=_role_of(name))

        for m in _FUNC_COMP_RE.finditer(text):
            _record(m.group(1), m.group(2), m.group(0))
        for m in _CONST_COMP_RE.finditer(text):
            _record(m.group(1), m.group(2), m.group(0))
        return list(found.values())

    def _parse_components_manifest(self, text: str, rel: str) -> list[Component]:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        entries = data.get("components") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []
        out: list[Component] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            props_raw = entry.get("props", [])
            props = tuple(str(p) for p in props_raw if isinstance(p, (str, int)))
            file_ref = entry.get("file")
            out.append(
                Component(
                    name=name,
                    file=str(file_ref) if file_ref else rel,
                    props=props,
                    role=_role_of(name),
                )
            )
        return out

    # -- token parsing --------------------------------------------------------

    _CSS_VAR_RE = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;{}]+);")

    def _classify_token(self, name: str, value: str) -> str:
        low = name.lower()
        if _is_color_value(value) or any(
            k in low for k in ("color", "colour", "bg", "background", "fg", "border", "shadow")
        ):
            if _is_color_value(value):
                return TOKEN_COLOR
        if any(k in low for k in ("space", "spacing", "gap", "margin", "padding", "size", "radius")):
            return TOKEN_SPACING
        if any(k in low for k in ("font", "text", "line", "weight", "letter", "leading", "tracking")):
            return TOKEN_TYPOGRAPHY
        if _is_color_value(value):
            return TOKEN_COLOR
        return TOKEN_OTHER

    def _parse_css_tokens(self, text: str, rel: str) -> list[DesignToken]:
        out: list[DesignToken] = []
        for m in self._CSS_VAR_RE.finditer(text):
            name = m.group(1).strip()
            value = m.group(2).strip()
            if not value or value.startswith("var("):
                # Skip aliases to other vars -- record the concrete ones only.
                continue
            category = self._classify_token(name, value)
            out.append(
                DesignToken(
                    name=name,
                    value=value,
                    category=category,
                    file=rel,
                    rgb=parse_color(value) if category == TOKEN_COLOR else None,
                )
            )
        return out

    def _parse_tokens_json(self, text: str, rel: str) -> list[DesignToken]:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        out: list[DesignToken] = []
        category_map = {
            "colors": TOKEN_COLOR,
            "color": TOKEN_COLOR,
            "spacing": TOKEN_SPACING,
            "space": TOKEN_SPACING,
            "typography": TOKEN_TYPOGRAPHY,
            "fonts": TOKEN_TYPOGRAPHY,
        }
        for group_key, group_val in data.items():
            if not isinstance(group_val, dict):
                continue
            category = category_map.get(str(group_key).lower(), TOKEN_OTHER)
            for name, value in group_val.items():
                if not isinstance(value, (str, int, float)):
                    continue
                sval = str(value)
                out.append(
                    DesignToken(
                        name=str(name),
                        value=sval,
                        category=category,
                        file=rel,
                        rgb=parse_color(sval) if category == TOKEN_COLOR else None,
                    )
                )
        return out

    # -- reuse recommendation -------------------------------------------------

    def recommend_component(self, requested: str) -> Recommendation:
        """Recommend reusing an existing component for a requested element.

        Matching precedence (deterministic):
          1. exact normalized-name match,
          2. normalized-name substring containment (either direction),
          3. semantic role match via the synonym table.
        Falls back to ``needs_new`` when nothing matches.
        """
        discovery = self.discover()
        components = discovery.components
        req_norm = _normalize_name(requested)

        # 1. exact name.
        exact = [c for c in components if _normalize_name(c.name) == req_norm]
        if exact:
            best = sorted(exact, key=lambda c: (c.name, c.file))[0]
            return Recommendation(
                requested=requested,
                action="reuse",
                component=best,
                match_reason="name",
                role=best.role,
            )

        # 2. substring containment.
        contains = [
            c
            for c in components
            if req_norm and (req_norm in _normalize_name(c.name) or _normalize_name(c.name) in req_norm)
        ]
        if contains:
            best = sorted(contains, key=lambda c: (len(c.name), c.name, c.file))[0]
            return Recommendation(
                requested=requested,
                action="reuse",
                component=best,
                match_reason="name",
                role=best.role,
            )

        # 3. semantic role.
        req_role = _role_of(requested)
        if req_role:
            role_matches = [c for c in components if (c.role or _role_of(c.name)) == req_role]
            if role_matches:
                best = sorted(role_matches, key=lambda c: (c.name, c.file))[0]
                return Recommendation(
                    requested=requested,
                    action="reuse",
                    component=best,
                    match_reason="role",
                    role=req_role,
                )

        return Recommendation(
            requested=requested,
            action="needs_new",
            component=None,
            match_reason=None,
            role=req_role,
        )

    # -- token suggestion -----------------------------------------------------

    def suggest_token(self, value: str, *, category: str = TOKEN_COLOR) -> TokenSuggestion | None:
        """Suggest the nearest on-system token for an off-system value.

        For colors, the nearest token is chosen by :func:`color_distance`. An
        exact match (distance 0) is flagged via ``exact=True`` -- i.e. the value
        is already on-system. Returns ``None`` when there are no comparable
        tokens.
        """
        discovery = self.discover()
        if category != TOKEN_COLOR:
            # Non-color categories: exact value match only (deterministic).
            candidates = [t for t in discovery.tokens if t.category == category]
            for tok in sorted(candidates, key=lambda t: (t.name, t.file)):
                if tok.value.strip().lower() == value.strip().lower():
                    return TokenSuggestion(requested_value=value, token=tok, distance=0.0, exact=True)
            return None

        target = parse_color(value)
        if target is None:
            return None
        color_tokens = [t for t in discovery.tokens if t.category == TOKEN_COLOR and t.rgb is not None]
        if not color_tokens:
            return None
        best: tuple[float, DesignToken] | None = None
        for tok in color_tokens:
            assert tok.rgb is not None
            dist = color_distance(target, tok.rgb)
            cand = (dist, tok)
            # Tie-break deterministically by (name, file) via sorted scan below.
            if best is None or dist < best[0]:
                best = cand
            elif dist == best[0]:
                if (tok.name, tok.file) < (best[1].name, best[1].file):
                    best = cand
        assert best is not None
        return TokenSuggestion(
            requested_value=value,
            token=best[1],
            distance=best[0],
            exact=best[0] == 0.0,
        )

    # -- coverage -------------------------------------------------------------

    def assess_coverage(
        self,
        *,
        components: list[str] | None = None,
        colors: list[str] | None = None,
    ) -> CoverageReport:
        """Report coverage for a batch of requested components and colors.

        A component request is *covered* when it can reuse an existing
        component; a color request is *covered* when it exactly matches an
        on-system token (distance 0). Off-system colors are still reported with
        the nearest-token suggestion so the caller can align to the system.
        """
        items: list[CoverageItem] = []
        for name in components or []:
            rec = self.recommend_component(name)
            items.append(
                CoverageItem(
                    kind="component",
                    requested=name,
                    covered=rec.reuse,
                    recommendation=rec,
                )
            )
        for value in colors or []:
            suggestion = self.suggest_token(value, category=TOKEN_COLOR)
            covered = bool(suggestion and suggestion.exact)
            items.append(
                CoverageItem(
                    kind="color",
                    requested=value,
                    covered=covered,
                    suggestion=suggestion,
                )
            )
        return CoverageReport(items=items)
