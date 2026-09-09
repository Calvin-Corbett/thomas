"""Image/design -> code via a render-diff-refine loop (CAP-111).

Turning a *target design* into working code is not a one-shot translation: a
real agent generates a first draft, **renders** it, **diffs** the result against
the target, and **refines** until the two agree. This module implements exactly
that loop as a deterministic, hermetic core.

The pipeline has four explicit stages:

1. **Framework + component-library selection.** Given an analysed design
   target, :func:`select_stack` picks a *framework* (``react`` / ``vue`` /
   ``html``) **and** a concrete *component library* (e.g. ``material-ui``,
   ``vuetify``, ``bootstrap``, or the library-free ``plain`` set) from explicit
   registries. Both choices -- plus the role->component mapping actually used --
   are recorded on :class:`StackSelection`; nothing is left implicit. The
   selected library is *load-bearing*: it decides the concrete component tag
   emitted for each abstract role, so the choice is observable in the generated
   code, not decorative.

2. **Render.** The generated code is rendered to a **structural representation**
   -- an element tree -- by an *injectable renderer*. The real default,
   :class:`DomRenderer`, parses the emitted markup with the standard library's
   :mod:`html.parser`, recovering each element's abstract role, props and text.
   Because it is stdlib-only it runs hermetically; tests may also inject a
   :class:`FakeRenderer`.

3. **Diff.** :func:`diff_trees` performs a structural comparison of the rendered
   tree against the target tree, emitting a list of :class:`Discrepancy` records
   (missing/extra nodes, role/text/prop mismatches), each carrying the tree path
   at which it was found.

4. **Refine.** :func:`apply_fixes` applies the shallowest layer of discrepancies
   back onto the working model, and :func:`render_diff_refine` iterates
   render -> diff -> refine, tracking every :class:`Iteration`, until the diff is
   empty (converged) or an iteration bound is hit (residual reported honestly).

The **vision / target-analysis edge is injectable.** The documented live lane is
:class:`VisionTargetAnalyzer`, which requires a real vision-model client
(credential-gated) and raises :class:`VisionCredentialsError` when none is
supplied -- this module never fabricates a "live" analysis. Tests inject a
:class:`StaticTargetAnalyzer` carrying a fixed target descriptor. Everything in
the core is deterministic (sorted iteration, no clock, no network, no temp state)
so the whole loop is reproducible.
"""

from __future__ import annotations

import copy
import enum
import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Protocol

__all__ = [
    "Node",
    "DesignTarget",
    "Framework",
    "ComponentLibrary",
    "StackSelection",
    "FRAMEWORKS",
    "COMPONENT_LIBRARIES",
    "select_stack",
    "generate_code",
    "Renderer",
    "DomRenderer",
    "FakeRenderer",
    "DiscrepancyKind",
    "Discrepancy",
    "diff_trees",
    "apply_fixes",
    "Iteration",
    "ImageToCodeResult",
    "render_diff_refine",
    "TargetAnalyzer",
    "StaticTargetAnalyzer",
    "VisionTargetAnalyzer",
    "VisionCredentialsError",
    "StackSelectionError",
]


# ---------------------------------------------------------------------------
# Structural model -- one node type for both target and rendered trees.
# ---------------------------------------------------------------------------
@dataclass
class Node:
    """A structural element: an abstract *role*, string props, text, children.

    The same type describes both the *target* structure (what the design should
    render to) and the *rendered* structure (what the generated code actually
    renders to), so a diff compares like with like.
    """

    role: str
    props: dict[str, str] = field(default_factory=dict)
    text: str | None = None
    children: list[Node] = field(default_factory=list)

    def clone(self) -> Node:
        return copy.deepcopy(self)


@dataclass
class DesignTarget:
    """An analysed design: its structural root plus selection hints.

    ``hints`` may carry ``preferred_framework``, ``preferred_component_library``
    and ``interactivity`` ("static" / "interactive"). They steer, but never
    silently override, the explicit :func:`select_stack` rules.
    """

    root: Node
    hints: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Explicit framework + component-library registries.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Framework:
    name: str
    description: str


@dataclass(frozen=True)
class ComponentLibrary:
    name: str
    frameworks: tuple[str, ...]
    # Maps an abstract role -> the concrete component/tag emitted in code.
    role_to_component: dict[str, str]

    def component_for(self, role: str) -> str:
        return self.role_to_component.get(role, role)


FRAMEWORKS: dict[str, Framework] = {
    "react": Framework("react", "React component tree (JSX)."),
    "vue": Framework("vue", "Vue single-file-component template."),
    "html": Framework("html", "Plain semantic HTML document."),
}

# Component libraries keyed by name. Each declares which frameworks it supports
# and how abstract roles map to concrete components. ``plain`` is the
# library-free fallback that maps roles to semantic HTML tags.
COMPONENT_LIBRARIES: dict[str, ComponentLibrary] = {
    "material-ui": ComponentLibrary(
        "material-ui",
        ("react",),
        {
            "button": "Button",
            "input": "TextField",
            "card": "Card",
            "text": "Typography",
            "container": "Box",
            "link": "Link",
            "image": "CardMedia",
        },
    ),
    "vuetify": ComponentLibrary(
        "vuetify",
        ("vue",),
        {
            "button": "VBtn",
            "input": "VTextField",
            "card": "VCard",
            "text": "VLabel",
            "container": "VContainer",
            "link": "RouterLink",
            "image": "VImg",
        },
    ),
    "bootstrap": ComponentLibrary(
        "bootstrap",
        ("html",),
        {
            "button": "button",
            "input": "input",
            "card": "div",
            "text": "p",
            "container": "div",
            "link": "a",
            "image": "img",
        },
    ),
    "plain": ComponentLibrary(
        "plain",
        ("react", "vue", "html"),
        {
            "button": "button",
            "input": "input",
            "card": "section",
            "text": "p",
            "container": "div",
            "link": "a",
            "image": "img",
        },
    ),
}

# The default component library per framework, used when a target does not
# request one explicitly.
_DEFAULT_LIBRARY: dict[str, str] = {
    "react": "material-ui",
    "vue": "vuetify",
    "html": "plain",
}


class StackSelectionError(ValueError):
    """Raised when framework/component-library selection cannot be satisfied."""


@dataclass(frozen=True)
class StackSelection:
    """The *explicitly recorded* framework + component-library decision."""

    framework: str
    component_library: str
    rationale: str
    role_to_component: dict[str, str]


def select_stack(target: DesignTarget) -> StackSelection:
    """Explicitly select a framework and component library for ``target``.

    Rules (deterministic, evaluated in order):

    1. An explicit ``preferred_framework`` hint wins if it names a known
       framework.
    2. Otherwise ``interactivity == "static"`` -> ``html``; ``interactivity in
       {"interactive", "spa"}`` -> ``react``.
    3. Otherwise default to ``html`` (the simplest target).

    The component library is the ``preferred_component_library`` hint when it is
    compatible with the chosen framework, else that framework's default.
    """
    hints = target.hints
    reasons: list[str] = []

    preferred_fw = hints.get("preferred_framework")
    if preferred_fw:
        if preferred_fw not in FRAMEWORKS:
            raise StackSelectionError(f"unknown preferred_framework: {preferred_fw!r}")
        framework = preferred_fw
        reasons.append(f"framework from explicit hint {preferred_fw!r}")
    else:
        interactivity = hints.get("interactivity", "")
        if interactivity == "static":
            framework = "html"
            reasons.append("framework=html from interactivity=static")
        elif interactivity in ("interactive", "spa"):
            framework = "react"
            reasons.append(f"framework=react from interactivity={interactivity!r}")
        else:
            framework = "html"
            reasons.append("framework=html by default (no hints)")

    preferred_lib = hints.get("preferred_component_library")
    if preferred_lib:
        lib = COMPONENT_LIBRARIES.get(preferred_lib)
        if lib is None:
            raise StackSelectionError(f"unknown preferred_component_library: {preferred_lib!r}")
        if framework not in lib.frameworks:
            raise StackSelectionError(f"component library {preferred_lib!r} does not support framework {framework!r}")
        component_library = preferred_lib
        reasons.append(f"component library from explicit hint {preferred_lib!r}")
    else:
        component_library = _DEFAULT_LIBRARY[framework]
        reasons.append(f"component library={component_library!r} (default for {framework!r})")

    lib = COMPONENT_LIBRARIES[component_library]
    return StackSelection(
        framework=framework,
        component_library=component_library,
        rationale="; ".join(reasons),
        role_to_component=dict(lib.role_to_component),
    )


# ---------------------------------------------------------------------------
# Code generation -- model tree -> markup, using the selected library.
# ---------------------------------------------------------------------------
def generate_code(model: Node, stack: StackSelection) -> str:
    """Render ``model`` to deterministic markup for ``stack``.

    Each abstract role is emitted using the *selected component library's*
    concrete component (so the stack choice is observable in the output). The
    abstract role and props are preserved as ``data-role`` / ``data-prop-*``
    attributes so a structural renderer can recover them exactly.
    """
    lib = COMPONENT_LIBRARIES[stack.component_library]
    lines: list[str] = []
    _emit(model, lib, 0, lines)
    return "\n".join(lines)


def _emit(node: Node, lib: ComponentLibrary, depth: int, out: list[str]) -> None:
    tag = lib.component_for(node.role)
    pad = "  " * depth
    attrs = [f'data-role="{html.escape(node.role, quote=True)}"']
    for key in sorted(node.props):
        val = html.escape(node.props[key], quote=True)
        attrs.append(f'data-prop-{key}="{val}"')
    attr_str = " ".join(attrs)
    inner = html.escape(node.text) if node.text else ""
    if node.children:
        out.append(f"{pad}<{tag} {attr_str}>{inner}")
        for child in node.children:
            _emit(child, lib, depth + 1, out)
        out.append(f"{pad}</{tag}>")
    else:
        out.append(f"{pad}<{tag} {attr_str}>{inner}</{tag}>")


# ---------------------------------------------------------------------------
# Render step -- injectable renderer producing a structural element tree.
# ---------------------------------------------------------------------------
class Renderer(Protocol):
    """Renders generated code to a structural :class:`Node` tree."""

    def render(self, code: str) -> Node: ...


class _DomTreeBuilder(HTMLParser):
    """Builds a :class:`Node` tree from markup emitted by :func:`generate_code`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[Node] = []
        self.root: Node | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        role = tag
        props: dict[str, str] = {}
        for name, value in attrs:
            value = value or ""
            if name == "data-role":
                role = value
            elif name.startswith("data-prop-"):
                props[name[len("data-prop-") :]] = value
        node = Node(role=role, props=props)
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self.root = node
        self._stack.append(node)

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and self._stack:
            top = self._stack[-1]
            top.text = (top.text or "") + text

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()


class DomRenderer:
    """Real default renderer: parses markup into an element tree via stdlib.

    Uses :class:`html.parser.HTMLParser`, so it is hermetic (no browser, no
    network). This is the production render step for the render-diff-refine loop.
    """

    def render(self, code: str) -> Node:
        builder = _DomTreeBuilder()
        builder.feed(code)
        builder.close()
        if builder.root is None:
            raise ValueError("renderer produced an empty tree")
        return builder.root


class FakeRenderer:
    """Hermetic test double: returns a preset tree regardless of input.

    Injectable in place of :class:`DomRenderer` to exercise the loop against a
    renderer whose output is controlled by the test (e.g. a deliberately buggy
    render that never fully matches the target).
    """

    def __init__(self, tree: Node) -> None:
        self._tree = tree

    def render(self, code: str) -> Node:  # noqa: ARG002 - preset output
        return self._tree.clone()


# ---------------------------------------------------------------------------
# Diff step -- structural comparison producing a discrepancy list.
# ---------------------------------------------------------------------------
class DiscrepancyKind(enum.Enum):
    MISSING_NODE = "missing_node"
    EXTRA_NODE = "extra_node"
    ROLE_MISMATCH = "role_mismatch"
    TEXT_MISMATCH = "text_mismatch"
    PROP_MISMATCH = "prop_mismatch"
    PROP_MISSING = "prop_missing"
    PROP_EXTRA = "prop_extra"


@dataclass(frozen=True)
class Discrepancy:
    """A single structural difference between rendered and target trees."""

    kind: DiscrepancyKind
    path: tuple[int, ...]
    detail: str = ""
    prop: str | None = None

    @property
    def depth(self) -> int:
        return len(self.path)


def diff_trees(rendered: Node | None, target: Node | None) -> list[Discrepancy]:
    """Structurally diff ``rendered`` against ``target``.

    Returns a deterministic, path-sorted list of discrepancies. An empty list
    means the rendered tree matches the target exactly.
    """
    discreps: list[Discrepancy] = []
    _diff_node(rendered, target, (), discreps)
    discreps.sort(key=lambda d: (d.depth, d.path, d.kind.value, d.prop or ""))
    return discreps


def _diff_node(
    rendered: Node | None,
    target: Node | None,
    path: tuple[int, ...],
    out: list[Discrepancy],
) -> None:
    if rendered is None and target is not None:
        out.append(Discrepancy(DiscrepancyKind.MISSING_NODE, path, detail=target.role))
        return
    if rendered is not None and target is None:
        out.append(Discrepancy(DiscrepancyKind.EXTRA_NODE, path, detail=rendered.role))
        return
    assert rendered is not None and target is not None  # for type-checkers

    if rendered.role != target.role:
        out.append(
            Discrepancy(
                DiscrepancyKind.ROLE_MISMATCH,
                path,
                detail=f"{rendered.role!r}!={target.role!r}",
            )
        )
    if (rendered.text or None) != (target.text or None):
        out.append(
            Discrepancy(
                DiscrepancyKind.TEXT_MISMATCH,
                path,
                detail=f"{rendered.text!r}!={target.text!r}",
            )
        )

    for key in sorted(set(rendered.props) | set(target.props)):
        in_r = key in rendered.props
        in_t = key in target.props
        if in_r and not in_t:
            out.append(Discrepancy(DiscrepancyKind.PROP_EXTRA, path, prop=key))
        elif in_t and not in_r:
            out.append(Discrepancy(DiscrepancyKind.PROP_MISSING, path, prop=key))
        elif rendered.props[key] != target.props[key]:
            out.append(
                Discrepancy(
                    DiscrepancyKind.PROP_MISMATCH,
                    path,
                    prop=key,
                    detail=f"{rendered.props[key]!r}!={target.props[key]!r}",
                )
            )

    n = max(len(rendered.children), len(target.children))
    for i in range(n):
        r_child = rendered.children[i] if i < len(rendered.children) else None
        t_child = target.children[i] if i < len(target.children) else None
        _diff_node(r_child, t_child, path + (i,), out)


# ---------------------------------------------------------------------------
# Refine step -- apply the shallowest layer of fixes toward the target.
# ---------------------------------------------------------------------------
def apply_fixes(model: Node, discreps: Sequence[Discrepancy], target: Node) -> Node:
    """Return a new model with the *shallowest* discrepancy layer fixed.

    Only discrepancies at the minimum depth present are applied per call, so the
    loop advances one structural layer at a time and each iteration is a
    well-defined, observable refinement step. ``target`` is the source of truth
    for the corrected values.
    """
    if not discreps:
        return model.clone()

    frontier_depth = min(d.depth for d in discreps)
    frontier = [d for d in discreps if d.depth == frontier_depth]

    new_model = model.clone()

    # Group fixes by parent path so child-list edits (insert/remove) can be
    # applied in a stable, index-safe order.
    by_parent: dict[tuple[int, ...], list[Discrepancy]] = {}
    for d in frontier:
        parent = d.path[:-1] if d.path else ()
        by_parent.setdefault(parent, []).append(d)

    for parent_path, group in by_parent.items():
        # Structural edits first (descending child index to keep indices valid),
        # then in-place content edits.
        structural = sorted(
            (d for d in group if d.kind in (DiscrepancyKind.MISSING_NODE, DiscrepancyKind.EXTRA_NODE)),
            key=lambda d: d.path[-1] if d.path else 0,
            reverse=True,
        )
        content = [d for d in group if d.kind not in (DiscrepancyKind.MISSING_NODE, DiscrepancyKind.EXTRA_NODE)]
        for d in structural:
            _apply_structural(new_model, d, target)
        for d in content:
            _apply_content(new_model, d, target)

    return new_model


def _node_at(root: Node, path: tuple[int, ...]) -> Node:
    node = root
    for idx in path:
        node = node.children[idx]
    return node


def _shell_of(node: Node) -> Node:
    """A structural placeholder: correct role only, no text/props/children.

    Refining a missing node inserts a shell; its content and descendants surface
    as fresh discrepancies on the next render, so the tree is built up layer by
    layer rather than teleported to the answer in one step.
    """
    return Node(role=node.role)


def _apply_structural(model: Node, d: Discrepancy, target: Node) -> None:
    parent_path = d.path[:-1]
    idx = d.path[-1]
    parent = _node_at(model, parent_path)
    if d.kind is DiscrepancyKind.MISSING_NODE:
        target_node = _node_at(target, d.path)
        insert_at = min(idx, len(parent.children))
        parent.children.insert(insert_at, _shell_of(target_node))
    elif d.kind is DiscrepancyKind.EXTRA_NODE:
        if idx < len(parent.children):
            del parent.children[idx]


def _apply_content(model: Node, d: Discrepancy, target: Node) -> None:
    node = _node_at(model, d.path)
    target_node = _node_at(target, d.path)
    if d.kind is DiscrepancyKind.ROLE_MISMATCH:
        node.role = target_node.role
    elif d.kind is DiscrepancyKind.TEXT_MISMATCH:
        node.text = target_node.text
    elif d.kind in (DiscrepancyKind.PROP_MISMATCH, DiscrepancyKind.PROP_MISSING) and d.prop is not None:
        node.props[d.prop] = target_node.props[d.prop]
    elif d.kind is DiscrepancyKind.PROP_EXTRA and d.prop is not None:
        node.props.pop(d.prop, None)


# ---------------------------------------------------------------------------
# The render-diff-refine loop.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Iteration:
    """One pass of the loop: what was rendered and what still differed."""

    index: int
    code: str
    discrepancy_count: int
    discrepancies: tuple[Discrepancy, ...]
    matched_nodes: int


@dataclass(frozen=True)
class ImageToCodeResult:
    stack: StackSelection
    iterations: tuple[Iteration, ...]
    converged: bool
    final_code: str
    residual: tuple[Discrepancy, ...]

    @property
    def refinements(self) -> int:
        """Number of refine passes applied (0 == first render already matched)."""
        return max(len(self.iterations) - 1, 0)


def _count_nodes(node: Node) -> int:
    return 1 + sum(_count_nodes(c) for c in node.children)


def _matched_nodes(discreps: Sequence[Discrepancy], target: Node) -> int:
    """Target nodes with no discrepancy anywhere in their subtree path."""
    total = _count_nodes(target)
    # A node is "unmatched" if a discrepancy sits at its path or shallower on
    # its lineage; approximate progress as (total - distinct discrepancy paths).
    touched = {d.path for d in discreps}
    return max(total - len(touched), 0)


def render_diff_refine(
    target: DesignTarget,
    *,
    renderer: Renderer | None = None,
    initial_model: Node | None = None,
    max_iterations: int = 8,
) -> ImageToCodeResult:
    """Run the full render-diff-refine loop against ``target``.

    1. Select the framework + component library explicitly.
    2. Start from ``initial_model`` (default: a skeleton with the target's
       structure but empty text/props, so refinement has real work to do).
    3. Repeatedly generate code, render it, diff against the target, and refine,
       tracking each iteration, until the diff is empty (converged) or
       ``max_iterations`` refine passes have run (residual reported).
    """
    if max_iterations < 0:
        raise ValueError("max_iterations must be >= 0")
    renderer = renderer or DomRenderer()
    stack = select_stack(target)

    model = initial_model.clone() if initial_model is not None else _skeleton(target.root)

    iterations: list[Iteration] = []
    converged = False
    last_code = ""
    residual: list[Discrepancy] = []

    for i in range(max_iterations + 1):
        code = generate_code(model, stack)
        last_code = code
        rendered = renderer.render(code)
        discreps = diff_trees(rendered, target.root)
        iterations.append(
            Iteration(
                index=i,
                code=code,
                discrepancy_count=len(discreps),
                discrepancies=tuple(discreps),
                matched_nodes=_matched_nodes(discreps, target.root),
            )
        )
        if not discreps:
            converged = True
            residual = []
            break
        residual = list(discreps)
        if i == max_iterations:
            break
        model = apply_fixes(model, discreps, target.root)

    return ImageToCodeResult(
        stack=stack,
        iterations=tuple(iterations),
        converged=converged,
        final_code=last_code,
        residual=tuple(residual),
    )


def _skeleton(target_root: Node) -> Node:
    """A same-structure draft with correct roles but empty text/props.

    This models a plausible first-pass code generation: the layout is roughly
    right, but the content and styling still need to be refined into place.
    """
    return Node(
        role=target_root.role,
        children=[_skeleton(c) for c in target_root.children],
    )


# ---------------------------------------------------------------------------
# Vision / target-analysis edge -- injectable.
# ---------------------------------------------------------------------------
class TargetAnalyzer(Protocol):
    """Analyses a design source (image bytes/path) into a :class:`DesignTarget`."""

    def analyze(self, source: object) -> DesignTarget: ...


class VisionCredentialsError(RuntimeError):
    """Raised when the live vision lane is used without a model client."""


class StaticTargetAnalyzer:
    """Hermetic fake: returns a fixed, pre-analysed target descriptor.

    Used by tests in place of a real vision model. Ignores ``source`` entirely.
    """

    def __init__(self, target: DesignTarget) -> None:
        self._target = target

    def analyze(self, source: object) -> DesignTarget:  # noqa: ARG002 - fixed
        return DesignTarget(root=self._target.root.clone(), hints=dict(self._target.hints))


class VisionTargetAnalyzer:
    """Documented live lane: analyse a design image with a real vision model.

    This is the *credential-gated* production path. A ``model_client`` capable of
    turning an image into a structural descriptor must be injected; without one,
    :meth:`analyze` raises :class:`VisionCredentialsError` rather than pretending
    a live analysis occurred. The core loop never depends on this path -- tests
    inject :class:`StaticTargetAnalyzer` instead.
    """

    def __init__(self, model_client: object | None = None) -> None:
        self._client = model_client

    def analyze(self, source: object) -> DesignTarget:
        if self._client is None:
            raise VisionCredentialsError(
                "VisionTargetAnalyzer requires a vision-model client "
                "(credential-gated live lane); inject StaticTargetAnalyzer for "
                "hermetic runs."
            )
        # Live lane: delegate to the injected client. The client contract is
        # `describe_design(source) -> DesignTarget`. This branch is exercised
        # only with real credentials and is intentionally thin.
        descriptor = self._client.describe_design(source)  # type: ignore[attr-defined]
        if not isinstance(descriptor, DesignTarget):
            raise VisionCredentialsError("vision client did not return a DesignTarget")
        return descriptor
