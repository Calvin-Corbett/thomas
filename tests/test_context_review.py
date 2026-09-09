"""Tests for the context-aware agentic reviewer (CAP-081).

Every test is hermetic: modules are supplied as in-memory source text; no
filesystem, network, or live model is touched. The reviewer is deterministic,
so assertions pin exact findings and their standards citations.
"""

from __future__ import annotations

from thomas.tools.context_review import (
    ContextAwareReviewer,
    DependencyDirectionInvariant,
    Finding,
    ModuleSource,
    SignatureCallArityInvariant,
    UndefinedImportInvariant,
    default_invariants,
    review_sources,
)

# ---------------------------------------------------------------------------
# Cross-module signature/call arity
# ---------------------------------------------------------------------------


def test_signature_change_breaks_caller_in_other_module_is_flagged():
    """A function grew a required parameter; a caller in ANOTHER module was
    not updated. This must be flagged as a cross-module invariant violation,
    naming BOTH the call site and the definition, and citing the rule."""
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source=(
            "def do_work(a, b, c):\n"  # line 1 — now requires three args
            "    return a + b + c\n"
        ),
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source=(
            "from pkg.core import do_work\n"  # line 1
            "\n"
            "def run():\n"
            "    return do_work(1, 2)\n"  # line 4 — stale two-arg call
        ),
    )

    findings = ContextAwareReviewer().review([core, caller])

    arity = [f for f in findings if f.invariant_id == "XMOD001"]
    assert len(arity) == 1, findings
    f = arity[0]

    # file:line points at the caller that must change.
    assert f.file == "pkg/caller.py"
    assert f.line == 4
    assert f.severity == "error"

    # Cross-module evidence: BOTH locations, in two different modules.
    modules_involved = {loc.module for loc in f.locations}
    assert modules_involved == {"pkg.caller", "pkg.core"}
    assert len(f.locations) >= 2

    call_loc = next(loc for loc in f.locations if loc.role == "call-site")
    def_loc = next(loc for loc in f.locations if loc.role == "definition")
    assert call_loc.path == "pkg/caller.py" and call_loc.line == 4
    assert def_loc.path == "pkg/core.py" and def_loc.line == 1

    # Standards-cited: rule id + human description both present and explanatory.
    assert f.rule_id == "XMOD001"
    assert f.rule_description
    assert "arity" in f.rule_description.lower()
    assert f.citation.startswith("XMOD001: ")


def test_signature_arity_ok_across_modules_is_not_flagged():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def do_work(a, b, c=0):\n    return a + b + c\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="from pkg.core import do_work\n\ndef run():\n    return do_work(1, 2)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    assert [f for f in findings if f.invariant_id == "XMOD001"] == []


def test_too_many_positional_args_across_modules_is_flagged():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def only_two(a, b):\n    return a + b\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="from pkg.core import only_two\n\nx = only_two(1, 2, 3)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    arity = [f for f in findings if f.invariant_id == "XMOD001"]
    assert len(arity) == 1
    assert "at most 2" in arity[0].message


def test_attribute_call_on_imported_module_is_checked():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def do_work(a, b, c):\n    return 0\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="import pkg.core as core\n\nv = core.do_work(1)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    arity = [f for f in findings if f.invariant_id == "XMOD001"]
    assert len(arity) == 1
    assert {loc.module for loc in arity[0].locations} == {"pkg.caller", "pkg.core"}


def test_star_args_call_suppresses_arity_finding():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def do_work(a, b, c):\n    return 0\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="from pkg.core import do_work\nargs = (1, 2, 3)\nv = do_work(*args)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    assert [f for f in findings if f.invariant_id == "XMOD001"] == []


def test_vararg_definition_accepts_any_positional_count():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def variadic(a, *rest):\n    return 0\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="from pkg.core import variadic\nv = variadic(1, 2, 3, 4)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    assert [f for f in findings if f.invariant_id == "XMOD001"] == []


def test_local_call_is_not_treated_as_cross_module():
    """A call to a same-module function must never be reported by the
    cross-module reviewer, even if arity is wrong (that is a single-file
    concern out of scope here)."""
    mod = ModuleSource(
        name="pkg.solo",
        path="pkg/solo.py",
        source="def helper(a, b, c):\n    return 0\n\nx = helper(1)\n",
    )
    findings = ContextAwareReviewer().review([mod])
    assert findings == []


# ---------------------------------------------------------------------------
# Cross-module undefined import
# ---------------------------------------------------------------------------


def test_import_of_undefined_symbol_across_modules_is_flagged():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def present():\n    return 1\n",
    )
    importer = ModuleSource(
        name="pkg.user",
        path="pkg/user.py",
        source="from pkg.core import missing_symbol\n",  # line 1
    )
    findings = ContextAwareReviewer().review([core, importer])
    undef = [f for f in findings if f.invariant_id == "XMOD002"]
    assert len(undef) == 1
    f = undef[0]
    assert f.file == "pkg/user.py"
    assert f.line == 1
    assert "missing_symbol" in f.message
    # Cross-module evidence names both the import site and the target module.
    roles = {loc.role for loc in f.locations}
    assert roles == {"import", "target-module"}
    assert {loc.module for loc in f.locations} == {"pkg.user", "pkg.core"}
    # Standards-cited.
    assert f.rule_id == "XMOD002"
    assert f.rule_description
    assert f.citation.startswith("XMOD002: ")


def test_import_of_defined_symbol_is_clean():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def present():\n    return 1\n",
    )
    importer = ModuleSource(
        name="pkg.user",
        path="pkg/user.py",
        source="from pkg.core import present\n",
    )
    findings = ContextAwareReviewer().review([core, importer])
    assert [f for f in findings if f.invariant_id == "XMOD002"] == []


def test_reexported_symbol_is_considered_defined():
    base = ModuleSource(
        name="pkg.base",
        path="pkg/base.py",
        source="def gadget():\n    return 1\n",
    )
    facade = ModuleSource(
        name="pkg.facade",
        path="pkg/facade.py",
        source="from pkg.base import gadget\n",  # re-export
    )
    user = ModuleSource(
        name="pkg.user",
        path="pkg/user.py",
        source="from pkg.facade import gadget\n",
    )
    findings = ContextAwareReviewer().review([base, facade, user])
    assert [f for f in findings if f.invariant_id == "XMOD002"] == []


def test_import_from_unreviewed_module_is_ignored():
    """We only flag undefined imports when we actually have the target
    module's source; third-party imports are left alone (no false positives)."""
    importer = ModuleSource(
        name="pkg.user",
        path="pkg/user.py",
        source="from os.path import join\nimport json\n",
    )
    findings = ContextAwareReviewer().review([importer])
    assert findings == []


# ---------------------------------------------------------------------------
# Cross-module dependency direction (injected rule set)
# ---------------------------------------------------------------------------


def test_forbidden_dependency_edge_is_flagged_with_injected_rule():
    core = ModuleSource(
        name="pkg.core.config",
        path="pkg/core/config.py",
        source="VALUE = 1\n",
    )
    ui = ModuleSource(
        name="pkg.ui.widget",
        path="pkg/ui/widget.py",
        # core importing ui violates a declared "core must not depend on ui" rule
        source="from pkg.core.config import VALUE\n",
    )
    core_importer = ModuleSource(
        name="pkg.core.loader",
        path="pkg/core/loader.py",
        source="from pkg.ui.widget import VALUE\n",  # line 1 — forbidden edge
    )
    # Injected, project-specific rule: `pkg.core` may not import `pkg.ui`.
    reviewer = ContextAwareReviewer(invariants=[DependencyDirectionInvariant([("pkg.core", "pkg.ui")])])
    findings = reviewer.review([core, ui, core_importer])
    dep = [f for f in findings if f.invariant_id == "XMOD003"]
    assert len(dep) == 1, findings
    f = dep[0]
    assert f.file == "pkg/core/loader.py"
    assert f.line == 1
    roles = {loc.role for loc in f.locations}
    assert roles == {"importer", "imported"}
    assert f.rule_id == "XMOD003"
    assert f.rule_description
    assert f.citation.startswith("XMOD003: ")


def test_dependency_direction_inert_without_injected_edges():
    a = ModuleSource(name="pkg.a", path="pkg/a.py", source="X = 1\n")
    b = ModuleSource(name="pkg.b", path="pkg/b.py", source="from pkg.a import X\n")
    # Default invariants include a dependency-direction check seeded with NO
    # forbidden edges, so it must stay silent.
    findings = ContextAwareReviewer().review([a, b])
    assert [f for f in findings if f.invariant_id == "XMOD003"] == []


# ---------------------------------------------------------------------------
# Clean change, standards citation, determinism
# ---------------------------------------------------------------------------


def test_clean_change_produces_no_findings():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def add(a, b):\n    return a + b\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source="from pkg.core import add\n\ndef run():\n    return add(1, 2)\n",
    )
    findings = ContextAwareReviewer().review([core, caller])
    assert findings == []


def test_every_finding_is_standards_cited():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def do_work(a, b, c):\n    return 0\n",
    )
    caller = ModuleSource(
        name="pkg.caller",
        path="pkg/caller.py",
        source=("from pkg.core import do_work, gone\n\nx = do_work(1)\n"),
    )
    findings = ContextAwareReviewer().review([core, caller])
    assert findings, "expected at least one finding"
    for f in findings:
        assert isinstance(f, Finding)
        # rule id + human description == the standards citation.
        assert f.rule_id
        assert f.rule_description and len(f.rule_description) > 20
        assert f.citation == f"{f.rule_id}: {f.rule_description}"
        # invariant id is carried and equals the cited rule.
        assert f.invariant_id == f.rule_id
        # file:line + severity + >= 2 cross-module evidence locations.
        assert f.file and f.line >= 1
        assert f.severity in {"error", "warning", "info"}
        assert len(f.locations) >= 2
        assert len({loc.module for loc in f.locations}) >= 2


def test_review_is_deterministic():
    core = ModuleSource(
        name="pkg.core",
        path="pkg/core.py",
        source="def do_work(a, b, c):\n    return 0\n",
    )
    caller_one = ModuleSource(
        name="pkg.one",
        path="pkg/one.py",
        source="from pkg.core import do_work, absent\nx = do_work(1)\n",
    )
    caller_two = ModuleSource(
        name="pkg.two",
        path="pkg/two.py",
        source="from pkg.core import do_work\ny = do_work(9)\n",
    )
    reviewer = ContextAwareReviewer()

    first = reviewer.review([core, caller_one, caller_two])
    # Reordered input must yield identical output (order-independent, sorted).
    second = reviewer.review([caller_two, core, caller_one])
    third = review_sources(
        {
            "pkg.core": core.source,
        }
    )

    assert [f.to_dict() for f in first] == [f.to_dict() for f in second]
    # A different subset yields its own stable result.
    assert isinstance(third, list)

    # Re-running the exact same call repeatedly is byte-identical.
    for _ in range(3):
        again = reviewer.review([core, caller_one, caller_two])
        assert [f.to_dict() for f in again] == [f.to_dict() for f in first]


def test_default_invariants_are_the_three_builtins():
    ids = {inv.rule_id for inv in default_invariants()}
    assert ids == {"XMOD001", "XMOD002", "XMOD003"}
    kinds = {type(inv) for inv in default_invariants()}
    assert kinds == {
        SignatureCallArityInvariant,
        UndefinedImportInvariant,
        DependencyDirectionInvariant,
    }


def test_custom_injected_invariant_is_honored():
    """The rule set is fully injectable/extensible."""

    class NoOpInvariant:
        rule_id = "CUSTOM9"
        rule_description = "a custom cross-module rule for extensibility testing"
        severity = "warning"

        def evaluate(self, index):
            return []

    reviewer = ContextAwareReviewer(invariants=[NoOpInvariant()])
    assert reviewer.invariants[0].rule_id == "CUSTOM9"
    mod = ModuleSource(name="pkg.x", path="pkg/x.py", source="X = 1\n")
    assert reviewer.review([mod]) == []


def test_review_sources_mapping_entrypoint_with_forbidden_edges():
    findings = review_sources(
        {
            "pkg.core.loader": "from pkg.ui.widget import VALUE\n",
            "pkg.ui.widget": "VALUE = 1\n",
        },
        forbidden_edges=[("pkg.core", "pkg.ui")],
    )
    dep = [f for f in findings if f.invariant_id == "XMOD003"]
    assert len(dep) == 1
    assert dep[0].citation.startswith("XMOD003: ")
