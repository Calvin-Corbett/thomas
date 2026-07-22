"""Tests for the CAP-111 render-diff-refine image/design -> code loop.

Proves the exact Level-2 acceptance line:

* framework + component-library are *explicitly* selected and recorded;
* a render-diff detects discrepancies vs the target;
* the refine loop reduces the diff across iterations to convergence (or reports
  the residual at the bound);
* a perfectly-matching first render needs no refinement;
* determinism.

Everything is hermetic: the vision edge is a :class:`StaticTargetAnalyzer` fake,
the renderer is the stdlib-backed real default (with a :class:`FakeRenderer`
injection test), and there is no network, clock, or temp state.
"""

from __future__ import annotations

import pytest

from thomas.tools.image_to_code import (
    COMPONENT_LIBRARIES,
    ComponentLibrary,
    DesignTarget,
    DiscrepancyKind,
    DomRenderer,
    FakeRenderer,
    Node,
    StackSelectionError,
    StaticTargetAnalyzer,
    VisionCredentialsError,
    VisionTargetAnalyzer,
    apply_fixes,
    diff_trees,
    generate_code,
    render_diff_refine,
    select_stack,
)


# ---------------------------------------------------------------------------
# Fixtures -- fake analysed target descriptors.
# ---------------------------------------------------------------------------
def _login_card() -> Node:
    """A small but non-trivial login card: container > card > {text, input, button}."""
    return Node(
        role="container",
        props={"layout": "center"},
        children=[
            Node(
                role="card",
                props={"variant": "elevated"},
                children=[
                    Node(role="text", text="Sign in", props={"size": "lg"}),
                    Node(role="input", props={"placeholder": "email"}),
                    Node(role="button", text="Submit", props={"color": "primary"}),
                ],
            )
        ],
    )


def _react_target() -> DesignTarget:
    return DesignTarget(
        root=_login_card(),
        hints={"interactivity": "interactive"},
    )


# ---------------------------------------------------------------------------
# (1) Explicit framework + component-library selection, recorded in output.
# ---------------------------------------------------------------------------
def test_framework_and_library_explicitly_selected_and_recorded():
    stack = select_stack(_react_target())
    # interactivity=interactive -> react, whose default library is material-ui.
    assert stack.framework == "react"
    assert stack.component_library == "material-ui"
    # The choice is explicitly recorded, not implicit: rationale + role map.
    assert "react" in stack.rationale
    assert "material-ui" in stack.rationale
    assert stack.role_to_component["button"] == "Button"
    assert stack.role_to_component["input"] == "TextField"


def test_static_hint_selects_html_plain():
    target = DesignTarget(root=_login_card(), hints={"interactivity": "static"})
    stack = select_stack(target)
    assert stack.framework == "html"
    assert stack.component_library == "plain"


def test_explicit_framework_and_library_hints_are_honored():
    target = DesignTarget(
        root=_login_card(),
        hints={
            "preferred_framework": "vue",
            "preferred_component_library": "vuetify",
        },
    )
    stack = select_stack(target)
    assert stack.framework == "vue"
    assert stack.component_library == "vuetify"
    assert stack.role_to_component["button"] == "VBtn"


def test_incompatible_library_for_framework_is_rejected():
    # material-ui only supports react; asking for it with html must fail loudly.
    target = DesignTarget(
        root=_login_card(),
        hints={
            "preferred_framework": "html",
            "preferred_component_library": "material-ui",
        },
    )
    with pytest.raises(StackSelectionError):
        select_stack(target)


def test_selected_library_is_load_bearing_in_generated_code():
    # The component library actually drives the concrete tags emitted, so the
    # selection is observable in the output rather than decorative.
    stack_react = select_stack(_react_target())
    code_react = generate_code(_login_card(), stack_react)
    assert "<Button " in code_react  # material-ui component
    assert "<TextField " in code_react

    stack_html = select_stack(DesignTarget(root=_login_card(), hints={"interactivity": "static"}))
    code_html = generate_code(_login_card(), stack_html)
    assert "<button " in code_html  # plain semantic tag
    assert "<Button " not in code_html


# ---------------------------------------------------------------------------
# (2) Render-diff detects discrepancies vs the target.
# ---------------------------------------------------------------------------
def test_render_diff_detects_discrepancies():
    target = _login_card()
    stack = select_stack(_react_target())
    renderer = DomRenderer()

    # A skeleton draft (right structure, empty text/props) must diff non-empty.
    skeleton = Node(
        role="container",
        children=[
            Node(
                role="card",
                children=[
                    Node(role="text"),
                    Node(role="input"),
                    Node(role="button"),
                ],
            )
        ],
    )
    rendered = renderer.render(generate_code(skeleton, stack))
    discreps = diff_trees(rendered, target)
    assert discreps, "expected the render to differ from the target"
    kinds = {d.kind for d in discreps}
    assert DiscrepancyKind.TEXT_MISMATCH in kinds
    assert DiscrepancyKind.PROP_MISSING in kinds


def test_render_diff_detects_structural_and_role_discrepancies():
    target = _login_card()
    stack = select_stack(_react_target())
    renderer = DomRenderer()

    # Wrong role on the button + a missing input node.
    wrong = Node(
        role="container",
        props={"layout": "center"},
        children=[
            Node(
                role="card",
                props={"variant": "elevated"},
                children=[
                    Node(role="text", text="Sign in", props={"size": "lg"}),
                    # input node omitted -> button now sits where input should be
                    Node(role="link", text="Submit", props={"color": "primary"}),
                ],
            )
        ],
    )
    discreps = diff_trees(renderer.render(generate_code(wrong, stack)), target)
    kinds = {d.kind for d in discreps}
    assert DiscrepancyKind.ROLE_MISMATCH in kinds
    assert DiscrepancyKind.MISSING_NODE in kinds


def test_real_dom_renderer_recovers_role_props_and_text():
    stack = select_stack(_react_target())
    node = Node(role="button", text="Submit", props={"color": "primary"})
    rendered = DomRenderer().render(generate_code(node, stack))
    assert rendered.role == "button"
    assert rendered.text == "Submit"
    assert rendered.props == {"color": "primary"}
    # No discrepancy against itself.
    assert diff_trees(rendered, node) == []


def test_apply_fixes_only_touches_shallowest_layer():
    target = _login_card()
    # Skeleton: correct structure, empty content -> top layer diff is the root's
    # missing "layout" prop; deeper layers are the card's/leaves' content.
    model = Node(
        role="container",
        children=[Node(role="card", children=[Node(role="text"), Node(role="button")])],
    )
    discreps = diff_trees(model, target)
    fixed = apply_fixes(model, discreps, target)
    # Frontier (depth 0) is applied: the root prop now matches the target.
    assert fixed.props == {"layout": "center"}
    # Deeper content is untouched this pass: the text leaf is still empty.
    assert fixed.children[0].children[0].text is None
    # And a subsequent diff has strictly fewer discrepancies.
    assert len(diff_trees(fixed, target)) < len(discreps)


# ---------------------------------------------------------------------------
# (3) Refine loop reduces the diff across iterations to convergence.
# ---------------------------------------------------------------------------
def test_refine_loop_converges_and_diff_strictly_decreases():
    target = _react_target()
    result = render_diff_refine(target, renderer=DomRenderer(), max_iterations=8)

    assert result.converged is True
    assert result.residual == ()
    # More than one iteration means refinement actually happened.
    assert len(result.iterations) >= 2
    assert result.refinements >= 1

    counts = [it.discrepancy_count for it in result.iterations]
    # Skeleton draft (correct structure, empty content) -> content-only diffs,
    # fixed shallowest-layer-first, so the discrepancy count strictly decreases.
    assert counts[0] > 0
    assert counts[-1] == 0
    assert all(later < earlier for earlier, later in zip(counts, counts[1:]))

    # Progress metric (matched nodes) is monotonically non-decreasing.
    matched = [it.matched_nodes for it in result.iterations]
    assert all(b >= a for a, b in zip(matched, matched[1:]))

    # The converged code renders back to the exact target.
    final_tree = DomRenderer().render(result.final_code)
    assert diff_trees(final_tree, target.root) == []


def test_refine_loop_converges_from_structural_gap():
    # Start from a model missing a whole subtree; the loop must add it and
    # converge (exercises MISSING_NODE fixes across iterations).
    target = _react_target()
    initial = Node(role="container")  # just the root, everything else missing
    result = render_diff_refine(target, renderer=DomRenderer(), initial_model=initial, max_iterations=12)
    assert result.converged is True
    assert result.residual == ()
    assert result.refinements >= 2  # built up layer by layer
    assert diff_trees(DomRenderer().render(result.final_code), target.root) == []


def test_bound_reached_reports_residual_honestly():
    target = _react_target()
    # One refine pass is not enough to fix a deep content diff -> residual.
    result = render_diff_refine(target, renderer=DomRenderer(), max_iterations=1)
    assert result.converged is False
    assert result.residual, "residual discrepancies must be reported at the bound"
    # iterations == max_iterations + 1 (render, refine, render).
    assert len(result.iterations) == 2
    assert result.iterations[-1].discrepancy_count == len(result.residual)


def test_injected_fake_renderer_that_never_matches_hits_bound():
    target = _react_target()
    # A buggy renderer that always returns the wrong tree -> never converges.
    fake = FakeRenderer(Node(role="container", text="WRONG"))
    result = render_diff_refine(target, renderer=fake, max_iterations=3)
    assert result.converged is False
    assert len(result.iterations) == 4
    assert result.residual


# ---------------------------------------------------------------------------
# (4) A perfectly-matching first render needs no refinement.
# ---------------------------------------------------------------------------
def test_perfect_first_render_needs_no_refinement():
    target = _react_target()
    # Seed the loop with the exact target: first render already matches.
    result = render_diff_refine(
        target,
        renderer=DomRenderer(),
        initial_model=target.root,
        max_iterations=8,
    )
    assert result.converged is True
    assert len(result.iterations) == 1
    assert result.refinements == 0
    assert result.iterations[0].discrepancy_count == 0
    assert result.residual == ()


# ---------------------------------------------------------------------------
# (5) Determinism.
# ---------------------------------------------------------------------------
def test_determinism_of_full_loop():
    target = _react_target()
    r1 = render_diff_refine(target, renderer=DomRenderer(), max_iterations=8)
    r2 = render_diff_refine(target, renderer=DomRenderer(), max_iterations=8)

    assert r1.stack == r2.stack
    assert r1.converged == r2.converged
    assert r1.final_code == r2.final_code
    assert [it.discrepancy_count for it in r1.iterations] == [it.discrepancy_count for it in r2.iterations]
    assert [it.discrepancies for it in r1.iterations] == [it.discrepancies for it in r2.iterations]


def test_diff_output_is_sorted_and_stable():
    target = _login_card()
    skeleton = Node(
        role="container",
        children=[Node(role="card", children=[Node(role="text")])],
    )
    stack = select_stack(_react_target())
    rendered = DomRenderer().render(generate_code(skeleton, stack))
    d1 = diff_trees(rendered, target)
    d2 = diff_trees(rendered, target)
    assert d1 == d2
    # Sorted by (depth, path, kind, prop).
    keys = [(d.depth, d.path, d.kind.value, d.prop or "") for d in d1]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Vision edge -- injectable; live lane is credential-gated.
# ---------------------------------------------------------------------------
def test_static_analyzer_is_hermetic_fake():
    target = _react_target()
    analyzer = StaticTargetAnalyzer(target)
    got = analyzer.analyze(source=b"ignored-image-bytes")
    assert got.hints == target.hints
    assert diff_trees(got.root, target.root) == []
    # Returns an independent copy (mutating it must not touch the fixture).
    got.root.role = "mutated"
    assert target.root.role == "container"


def test_vision_analyzer_requires_credentials():
    analyzer = VisionTargetAnalyzer(model_client=None)
    with pytest.raises(VisionCredentialsError):
        analyzer.analyze(source=b"image")


def test_vision_analyzer_uses_injected_client_when_present():
    target = _react_target()

    class _Client:
        def describe_design(self, source):  # noqa: ARG002
            return target

    got = VisionTargetAnalyzer(model_client=_Client()).analyze(source=b"img")
    assert diff_trees(got.root, target.root) == []


def test_end_to_end_from_analyzer_through_convergence():
    # Full path: fake vision analysis -> stack selection -> render/diff/refine.
    analyzer = StaticTargetAnalyzer(_react_target())
    target = analyzer.analyze(source=b"design.png")
    result = render_diff_refine(target, renderer=DomRenderer(), max_iterations=8)
    assert result.stack.framework == "react"
    assert result.stack.component_library == "material-ui"
    assert result.converged is True


# ---------------------------------------------------------------------------
# Registry sanity.
# ---------------------------------------------------------------------------
def test_component_libraries_declare_supported_frameworks():
    for lib in COMPONENT_LIBRARIES.values():
        assert isinstance(lib, ComponentLibrary)
        assert lib.frameworks
        assert "button" in lib.role_to_component
