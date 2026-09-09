from scripts.forge.publish.content_check import inspect


def test_populated_workboard_is_not_distributable():
    assert inspect("plans/thomas/WORKBOARD.md", b"- msg_id=msg-20260101010101-builder; summary=example")
    assert not inspect("plans/thomas/WORKBOARD.md", b"# Workboard\n\n## Agent Claims\n\nNone.\n")


def test_raw_results_are_excluded_but_regression_tests_are_kept():
    assert inspect("demo/agentic-runs/session/report.md", b"# Results")
    assert inspect("plans/session/results.jsonl", b"{}")
    assert not inspect("tests/test_failure_recovery.py", b"def test_recovery(): pass\n")


def test_machine_paths_are_rejected_and_fictional_examples_are_allowed():
    assert inspect("docs/setup.md", b"C:/Users/" + b"private-account/project")
    assert not inspect("docs/setup.md", b"C:/Users/example/project")


def test_runtime_javascript_is_not_treated_as_private_runtime_data():
    assert not inspect("thomas/server/web/js/runtime/component.js", b"const ready = true;")
    assert inspect("runtime/session.json", b"{}")


def test_github_zip_wrapper_does_not_hide_internal_paths(tmp_path):
    import zipfile

    from scripts.forge.publish.content_check import archive_members

    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project-main/plans/session/log.jsonl", "{}")
    members = list(archive_members(path))
    assert members[0][0] == "plans/session/log.jsonl"
    assert inspect(*members[0])


# Each test below states the red condition first: the rule must be observed
# firing on real internal content before the passing case means anything.


def test_self_critical_product_claims_are_not_distributable():
    assert inspect("docs/GUIDE.md", b"Known debt: app.py exceeds 1500 lines")
    assert inspect("README.md", b"## Known rough edges\n")
    assert inspect("docs/x.md", b"These modules are debt, not features.")
    assert inspect("docs/x.md", b"The module is burst-generated and has no real caller.")
    # Describing what the software does, including its limits, stays allowed.
    assert not inspect("README.md", b"Thomas is beta software. Review generated code.")
    assert not inspect("docs/x.md", b"A loader reference is migration debt, not a standing exception.")


def test_internal_task_identifiers_are_not_distributable():
    assert inspect("docs/plan.md", b"See HSK-20260905-034626 for the rollout.")
    assert inspect("docs/plan.md", b"Tracked under REPO-TRUTH-COORDINATION-20260902.")
    # Fictional ids are what tests are asked to use, and tests are exempt.
    assert not inspect("tests/test_claims.py", b'agent.claim("HSK-777")')
    assert not inspect("docs/plan.md", b"Release 0.19.36 shipped on 2026-09-07.")


def test_unpublished_design_records_are_not_cited():
    assert inspect("scripts/tool.py", b"# see docs/superpowers/plans/2026-08-27-x.md")
    assert inspect("docs/OVERLAY.md", b"Phase 2 (.superpowers/sdd/2026-08-27-x/progress.md).")
    assert not inspect("docs/OVERLAY.md", b"Phase 2 of the overlay design.")


def test_ops_ledgers_ship_their_schema_but_not_their_history():
    populated = b'{"version": 1, "records": [{"id": "2026-01-01-example-1"}]}'
    assert inspect("docs/ops/graveyard.json", populated)
    assert inspect("docs/ops/branch_claims.json", populated)
    assert not inspect("docs/ops/graveyard.json", b'{"version": 1, "records": []}')


def test_generated_corpora_and_benchmark_adapters_are_excluded():
    assert inspect("tests/browser_workflow_corpus/case_0001.json", b"{}")
    assert inspect("benchmarks/harbor_thomas/agent.py", b"pass\n")
    assert not inspect("tests/test_browser_click.py", b"def test_click(): pass\n")


def test_coordination_records_are_caught_outside_the_workboard_too():
    claim = b"- agent=codex-integrator; role=solo; scope=thomas/server/app.py"
    assert inspect("docs/ops/status.md", claim)
    assert inspect("docs/notes.md", b"- msg_id=msg-20260909023718-root; summary=example")
    # The board tooling and its tests are what produce these lines.
    assert not inspect("scripts/crew/workboard/board_io.py", claim)


def test_known_issues_catalogue_is_not_distributable():
    assert inspect("docs/KNOWN_ISSUES.md", b"# Known Issues\n")
    assert not inspect("docs/TROUBLESHOOTING.md", b"# Troubleshooting\n")


def test_a_citation_that_wraps_across_lines_is_still_caught():
    # A line-based rule sees "docs/superpowers/" on one line and a bare
    # filename on the next, and passes both. This is how twenty real leaks
    # survived an automated sweep.
    wrapped = b"WHY THIS EXISTS (phase 1.5, spec docs/superpowers/\nspecs/2026-08-24-praxis-first-design.md):\n"
    assert inspect("scripts/tool.py", wrapped)
    assert not inspect("scripts/tool.py", b"WHY THIS EXISTS (phase 1.5): the gate refuses that.\n")


def test_a_bare_design_record_filename_is_caught_without_its_directory():
    assert inspect("thomas/server/overlay/__init__.py", b"# phase 2 (2026-09-02-fork-by-overlay.md)")
    assert inspect("docs/GUIDE.md", b"See 2026-08-27-branch-equilibrium.md for the rationale.")
    # A published doc that date-SUFFIXES its name is a different shape.
    assert not inspect("docs/GUIDE.md", b"See AGENT_ADVERSARIAL_AUDIT_2026-03-19.md for the rationale.")
    assert not inspect("docs/GUIDE.md", b"Released 2026-09-07; see CHANGELOG.md.")


def test_the_publisher_strips_everything_the_gate_blocks():
    """The two lists must not drift apart.

    The gate refuses a release that carries an internal path; the publisher's
    strip list is what stops the path being carried in the first place. When
    only the gate knows about a path, the next release FAILS instead of simply
    shipping clean -- and someone under time pressure widens the gate to get a
    green check. Keeping the publisher ahead of the gate is what prevents that.
    """
    import json
    from pathlib import Path

    from scripts.forge.publish.content_check import BLOCKED_PREFIXES

    baseline = json.loads(
        Path("docs/repo_hygiene_baseline.json").read_text(encoding="utf-8")
    )
    stripped = set(baseline.get("publish_strip_prefixes", []))
    stripped |= set(baseline.get("forbidden_tracked_prefixes", []))

    missing = sorted(p for p in BLOCKED_PREFIXES if p.endswith("/") and p not in stripped)
    assert not missing, (
        "content_check.py blocks these prefixes but the publisher does not strip them, "
        "so a release carrying them fails the gate instead of shipping clean. "
        f"Add them to publish_strip_prefixes in docs/repo_hygiene_baseline.json: {missing}"
    )
