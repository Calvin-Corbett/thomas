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
