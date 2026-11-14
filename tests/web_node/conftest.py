"""Let pytest run the Build/Chat browser artifacts by their own paths.

The build verifier passes changed test paths directly to pytest. Pytest does not
collect JavaScript or HTML files by default, and errors on a path it cannot
collect, so every artifact here that a change can touch is named below, by name.
Nothing else in this directory is claimed: the ~100 other .mjs fixtures keep
their usual owning Python test.

Build/Chat Node regressions: the named .mjs harnesses run under Node; the same
scripts are also driven by tests/test_build_chat_preview_races.py.

build_chat_browser_probe.html is the hand-run half of the same work: nothing
headless can click its buttons, but its path is handed to pytest like any other
changed file under tests/, and a page nobody collects rots in silence. So the
probe gets a collector too -- a static one. It cannot open a browser, and does
not pretend to: it checks that the probe still lines up with the shipped code it
loads (the script files exist, the exports it calls are still exported, the ids
it queries are in its own markup) and that its frame table agrees with both the
whole-token sandbox rule and shell_frame_relay.mjs. Those are exactly the ways a
hand-run page goes stale between the days someone opens it.

Build's project chooser: build_project_chooser.html (the visual probe page) and
build_project_chooser_position.mjs (its Node harness) get a static check each.
Each artifact is only useful while it is still what the rest of that fix
assumes: the probe page is evidence only if it loads the SHIPPED module and can
still put the unfixed `left:0` anchor back beside it, and the harness is only
the one test_build_project_chooser_position.py runs if it still names every
Build layout.

The task card's revisit harness (chat_task_card_revisit_restore.mjs) and its
browser fixture (task_card_updates_visual.html) are claimed too. The normal
Python wrapper also runs that harness; this lets the build verifier select it
itself without treating a JavaScript file as Python.

"Improve Thomas" (improve_thomas_panel.mjs) gets a static check, for the same
reason the chooser harness does: test_improve_thomas_is_one_way.py already runs
it under Node with a bounded timeout, so claiming it here is about the verifier
handing this path to pytest -- not a second Node run. What is checked is that
the harness is still evidence about the shipped panel: it loads
self_edit_controls.js, names /api/self/projects -- the route it posts a request
to and reads the project list from -- and pulls only names that file still
exports.

Several self-fix runs add this same file at once, so it lands as an add/add
conflict more often than not. Every collector here is one branch in
``_collector_for`` plus its own ``pytest.File``/``pytest.Item`` pair, so
resolving one keeps both sides: take the union of the branches and the classes
they name. Do not fold two fixtures into one class.

The dispatch is a plain function rather than the hook body so the self-check can
assert the POSITIVE half -- that each fixture is still claimed, by its own class.
A resolution that keeps one side's classes and drops its branch leaves a file
that imports, collects the other side's fixtures, and silently stops running
this one; every assertion about class integrity would still have passed.

This file collects ITSELF as well, which is not decoration. The build verifier
hands every changed path under ``tests/`` straight to pytest
(``thomas/forge/anvil/build_verify.py``), so editing this collector runs
``pytest tests/web_node/conftest.py`` -- and a conftest carries hooks, not
``test_`` functions, so that run collected nothing and exited 5 ("no tests
ran"), failing a change that was fine.

The self-check reaches both of the ways pytest can arrive here, because neither
one covers the other:

* Named on the command line, this file is imported as a module (pytest collects
  a path it was given whatever ``python_files`` says), so
  ``test_the_web_node_collector_is_wired`` runs. That is the verifier's case.
* In an ordinary whole-suite run, a conftest is never collected as a test
  module, so only the ``_SELF`` branch of ``_collector_for`` below reaches it.
  Without that branch the wiring would go unchecked in CI.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
SOURCES = {
    "build_preview_race.mjs": "thomas/server/web/js/unified_code_results.js",
    "chat_edit_resend_failure.mjs": "thomas/server/web/chat.html",
    "shell_frame_relay.mjs": "thomas/server/web/js/workspace_shell.js",
}
PROBE = "build_chat_browser_probe.html"
CHOOSER_ARTIFACTS = {"build_project_chooser.html", "build_project_chooser_position.mjs"}
_HARNESS = "chat_task_card_revisit_restore.mjs"
_VISUAL_FIXTURE = "task_card_updates_visual.html"
_IMPROVE_HARNESS = "improve_thomas_panel.mjs"
_IMPROVE_PANEL = "self_edit_controls.js"
_IMPROVE_WRAPPER = "tests/test_improve_thomas_is_one_way.py"
_SELF = "conftest.py"
# The object a factory hands back, keyed by the local name the probe gives it,
# so `chat.editMessageFrom()` is checked against the file that defines `create`.
FACTORY_RESULTS = {"chat": "ThomasChatMessageView"}
# One row of the probe's relay table: [label, { attributes }, ours].
RELAY_ROW = re.compile(r"^\s*\[(?P<label>.+?),\s*\{(?P<attributes>.*?)\},\s*(?P<ours>true|false)\],?$", re.MULTILINE)


def _collector_for(name: str) -> type[pytest.File] | None:
    """Which ``pytest.File`` claims ``name``, or None. One branch per fixture."""
    if name in BROWSER_MODE_HARNESSES:
        return BrowserModeScript
    if name in SOURCES:
        return NodeHarness
    if name == PROBE:
        return BrowserProbe
    if name in CHOOSER_ARTIFACTS:
        return ChooserArtifact
    if name == _HARNESS:
        return _TaskCardFile
    if name == _VISUAL_FIXTURE:
        return _TaskCardVisualFile
    if name == _IMPROVE_HARNESS:
        return _ImproveThomasFile
    # This directory is flat, so the only conftest at or below it is this one.
    if name == _SELF:
        return _CollectorSelfCheckFile
    return None


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> pytest.File | None:
    if file_path.parent != HERE:
        return None
    claimed = _collector_for(file_path.name)
    return claimed.from_parent(parent, path=file_path) if claimed else None


class NodeHarness(pytest.File):
    def collect(self):
        yield NodeHarnessCase.from_parent(self, name=self.path.stem)


class NodeHarnessCase(pytest.Item):
    def runtest(self) -> None:
        source = ROOT / SOURCES[self.parent.path.name]
        result = subprocess.run(
            ["node", str(self.parent.path), str(source)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "passed" in result.stdout or "preserve the transcript" in result.stdout


# Browser-mode Node harnesses. The Python contract tests also run these; this
# collector keeps a direct pytest invocation from silently reporting "no tests
# ran" for their .mjs paths. Each one is handed the shipped modules it loads,
# in the order the page loads them.
CODE_SIBLINGS = (
    "unified_code_view_state.js",
    "unified_code_artifacts.js",
    "unified_code_results.js",
    "unified_code_projects.js",
    "unified_code_roster.js",
    "unified_code_drawer.js",
    "unified_code_agent_chat.js",
    "unified_code_cards.js",
    "unified_code_live_diff.js",
    "unified_code_composer.js",
    "unified_code_events.js",
    "unified_code_live_view.js",
    "unified_code_surface.js",
    "unified_code_run_stream.js",
    "unified_code_questions.js",
    "unified_code_controls.js",
    "unified_code_continuation.js",
    "unified_code_history_rows.js",
    "unified_code_loading.js",
)
CODE_DEPENDENCIES = ("unified_code_lifecycle.js",) + CODE_SIBLINGS
BROWSER_MODE_HARNESSES = {
    "code_run_terminal_status.mjs": ("unified_code_mode.js",)
    + (
        "unified_code_lifecycle.js",
        "unified_code_artifacts.js",
        "unified_code_results.js",
        "unified_code_projects.js",
        "unified_code_roster.js",
        "unified_code_drawer.js",
        "unified_code_agent_chat.js",
        "unified_code_cards.js",
        "unified_code_live_diff.js",
        "unified_code_composer.js",
        "unified_code_events.js",
        "unified_code_live_view.js",
        "unified_code_surface.js",
        "unified_code_run_stream.js",
        "unified_code_questions.js",
        "unified_code_controls.js",
        "unified_code_view_state.js",
    ),
    "code_stop_refresh_and_scroll.mjs": ("unified_code_mode.js",)
    + (
        "unified_code_lifecycle.js",
        "self_edit_controls.js",
        "unified_code_artifacts.js",
        "unified_code_results.js",
        "unified_code_projects.js",
        "unified_code_roster.js",
        "unified_code_drawer.js",
        "unified_code_agent_chat.js",
        "unified_code_cards.js",
        "unified_code_live_diff.js",
        "unified_code_composer.js",
        "unified_code_events.js",
        "unified_code_live_view.js",
        "unified_code_surface.js",
        "unified_code_run_stream.js",
        "unified_code_questions.js",
        "unified_code_controls.js",
        "unified_code_view_state.js",
    ),
    "unified_code_mode_lifecycle.mjs": ("unified_code_mode.js",) + CODE_DEPENDENCIES,
    "unified_work_support_lifecycle.mjs": (
        "unified_work_support.js",
        "unified_work_mode.js",
        # Shared steer wording, loaded ahead of the adapter in chat.html.
        "steering_language.js",
        # The Work card's live tasks and steer boxes, which the adapter creates.
        "unified_work_mode_steer.js",
    ),
    "chat_steer_box_explains_refusals.mjs": (
        # Same order the page loads them in: wording first, then the two
        # modules that read it.
        "steering_language.js",
        "chat_activity_view.js",
        "chat_activity_actions.js",
    ),
}


class BrowserModeHarness(pytest.Item):
    def runtest(self) -> None:
        script = self.path
        result = subprocess.run(
            ["node", str(script), *(str(JS / sibling) for sibling in BROWSER_MODE_HARNESSES[script.name])],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
        assert result.returncode == 0, f"{script.name} failed:\n{result.stdout}\n{result.stderr}"

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, f"Node lifecycle harness: {self.path.name}"


class BrowserModeScript(pytest.File):
    def collect(self):
        yield BrowserModeHarness.from_parent(self, name="node_lifecycle")


def _loaded_scripts(probe: str) -> list[str]:
    return re.findall(r"loadScript\('([\w.]+)'\)", probe)


def check_the_scripts_it_loads_exist(probe: str) -> None:
    names = _loaded_scripts(probe)
    assert names, "the probe must load the shipped scripts it claims to exercise"
    missing = [name for name in names if not (JS / name).is_file()]
    assert not missing, f"the probe loads {missing}, which are not in thomas/server/web/js"


def check_the_exports_it_calls_are_still_exported(probe: str) -> None:
    """A renamed export leaves the page loading fine and doing nothing, which is
    the one failure someone opening it by hand is least likely to notice."""
    sources = {name: (JS / name).read_text(encoding="utf-8") for name in _loaded_scripts(probe)}
    calls = set(re.findall(r"window\.(Thomas\w+)\.(\w+)\(", probe))
    for alias, exported in re.findall(r"const (\w+) = window\.(Thomas\w+);", probe):
        calls |= {(exported, method) for method in re.findall(rf"\b{alias}\.(\w+)\(", probe)}
    for alias, exported in FACTORY_RESULTS.items():
        calls |= {(exported, method) for method in re.findall(rf"\b{alias}\.(\w+)\(", probe)}
    assert calls, "the probe must call into the shipped scripts, not just load them"
    for exported, method in sorted(calls):
        owners = [name for name, body in sources.items() if f"window.{exported} = " in body]
        assert owners, f"no script the probe loads defines window.{exported}"
        body = sources[owners[0]]
        assert re.search(rf"\b{method}\b", body), f"{exported}.{method}() is gone from {owners[0]}"


def check_the_ids_it_queries_are_in_the_markup(probe: str) -> None:
    queried = set(re.findall(r"\$\('#([\w-]+)'\)", probe))
    assert len(queried) > 5, "the probe queries the controls and readouts of all three sections"
    absent = sorted(ident for ident in queried if f'id="{ident}"' not in probe)
    assert not absent, f"the probe queries #{absent}, which nothing in the page has"


def check_the_frame_table_matches_the_shipped_rule(probe: str) -> None:
    """Both halves of the relay claim must agree: the expectation the page shows
    a reader, and the whole-token `allow-same-origin` rule in workspace_shell.js
    that shell_frame_relay.mjs runs. A sandbox value only this page covers would
    be checked on the days someone remembers to open it, so require the headless
    harness to carry every skipped shape too."""
    harness = (HERE / "shell_frame_relay.mjs").read_text(encoding="utf-8")
    rows = list(RELAY_ROW.finditer(probe))
    assert len(rows) >= 6, "the relay table must keep covering the shipped sandboxed frames"
    for row in rows:
        sandbox = re.search(r"sandbox: '([^']*)'", row.group("attributes"))
        # No sandbox attribute at all means the frame inherits this origin.
        expected = "allow-same-origin" in sandbox.group(1).split() if sandbox else True
        declared = row.group("ours") == "true"
        assert declared == expected, (
            f"{row.group('label')} expects sendTheme={declared}, the whole-token rule says {expected}"
        )
        if sandbox and not expected:
            assert f"sandbox: '{sandbox.group(1)}'" in harness, (
                f"sandbox='{sandbox.group(1)}' is only checked by hand; shell_frame_relay.mjs must cover it as well"
            )


PROBE_CHECKS = {
    "the_scripts_it_loads_exist": check_the_scripts_it_loads_exist,
    "the_exports_it_calls_are_still_exported": check_the_exports_it_calls_are_still_exported,
    "the_ids_it_queries_are_in_the_markup": check_the_ids_it_queries_are_in_the_markup,
    "the_frame_table_matches_the_shipped_rule": check_the_frame_table_matches_the_shipped_rule,
}


class BrowserProbe(pytest.File):
    def collect(self):
        for name in PROBE_CHECKS:
            yield BrowserProbeCase.from_parent(self, name=name)


class BrowserProbeCase(pytest.Item):
    def runtest(self) -> None:
        PROBE_CHECKS[self.name](self.parent.path.read_text(encoding="utf-8"))


class ChooserArtifact(pytest.File):
    def collect(self):
        yield ChooserCheck.from_parent(self, name="build_project_chooser")


class ChooserCheck(pytest.Item):
    def runtest(self) -> None:
        if self.path.suffix == ".html":
            html = self.path.read_text(encoding="utf-8")
            assert 'id="tc-composer-rail"' in html
            assert 'id="tc-code-library-menu"' in html
            assert 'src="../../thomas/server/web/js/chat_composer_panels.js"' in html
            assert "panels.bindLibraryActions()" in html
            assert 'id="unfixed"' in html, "the probe must still be able to show the reported layout"
            return

        # The Python regression runs this harness once with a bounded timeout.
        # When the verifier passes .mjs to pytest directly, check that the
        # artifact is the one exercised there instead of spawning Node twice.
        harness = HERE / "build_project_chooser_position.mjs"
        assert self.path == harness
        text = self.path.read_text(encoding="utf-8")
        assert "Build project selected" in text
        assert "Build reopened wide" in text
        assert "Opening the chooser" in text, "the harness must still cover the open path"
        assert "Clamped at the left edge" in text, "the harness must still make the edge clamps bind"


class _TaskCardHarness(pytest.Item):
    def runtest(self) -> None:
        # This collector adds the harness to every run that reaches this
        # directory, so a machine without node has to SKIP it the way the rest
        # of the suite's JavaScript checks do. Shelling straight out to `node`
        # turned a missing toolchain into a failed run of unrelated Python.
        if shutil.which("node") is None:
            pytest.skip("node is not installed")
        repo = Path(__file__).resolve().parents[2]
        web = repo / "thomas" / "server" / "web"
        result = subprocess.run(
            [
                "node",
                str(self.path),
                str(web / "chat.html"),
                str(web / "js" / "chat_turn_flow.js"),
                str(web / "js" / "chat_activity_view.js"),
                str(web / "js" / "chat_activity_actions.js"),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        checks = json.loads(result.stdout)
        failed = [name for name, passed in checks.items() if not passed]
        assert not failed, f"task-card harness failed: {failed}"

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, "task-card Node harness"


class _TaskCardFile(pytest.File):
    def collect(self):
        yield _TaskCardHarness.from_parent(self, name="task-card updates")


class _TaskCardVisualFile(pytest.File):
    def collect(self):
        # The visual fixture is opened by the browser playtest, not executed as Python.
        # Give explicit pytest file selection a lightweight, verifiable check.
        yield _TaskCardVisualItem.from_parent(self, name="visual fixture loads live renderer")


class _TaskCardVisualItem(pytest.Item):
    def runtest(self) -> None:
        html = self.path.read_text(encoding="utf-8")
        assert 'src="../../thomas/server/web/js/chat_activity_view.js"' in html
        assert "window.advanceTask" in html
        # The point of opening this is to watch the card fill up, overflow four
        # updates, and report a step that stalled. Keep it able to show that.
        assert html.count("summary:") > 4
        assert "blocker:" in html
        # …and to show the card most tasks actually get: a worker with no Build
        # conversation, reading the same recorded history.
        assert 'id="worker-activity"' in html
        assert "worker-exec" in html
        # …and the failed-read state, whose "Try again" is the only retry a
        # settled card gets — nothing polls a task that has finished.
        assert 'id="stranded-activity"' in html
        assert "stranded-exec" in html
        # …and a task you stopped, which is recorded with blocker="cancelled"
        # and must not be painted as a run that failed.
        assert 'id="stopped-activity"' in html
        assert "stopped-exec" in html
        # …and two workers on one card, where the panel tags each merged line
        # with its worker and the header must still show the task's status.
        assert 'id="merged-activity"' in html
        assert "merged-a" in html and "merged-b" in html
        # …and the same card where only ONE of the two workers answers, which
        # leaves the panel holding part of the run rather than none of it.
        assert 'id="partial-activity"' in html
        assert "partial-a" in html and "partial-b" in html
        # …and the condition the keyboard has to survive: the poll rebuilds a
        # running card's innerHTML every few seconds, destroying every control
        # in it. Reproduce that here rather than only describing it.
        assert "window.repaintTicker" in html

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, "task-card browser fixture"


class _ImproveThomasFile(pytest.File):
    def collect(self):
        yield _ImproveThomasItem.from_parent(self, name="improve thomas panel harness")


class _ImproveThomasItem(pytest.Item):
    def runtest(self) -> None:
        # Static, like ChooserCheck: the Python wrapper is what spawns Node for
        # this harness, and spawning it twice is what that precedent avoids.
        harness = self.path.read_text(encoding="utf-8")
        panel = (JS / _IMPROVE_PANEL).read_text(encoding="utf-8")
        assert f"thomas/server/web/js/{_IMPROVE_PANEL}" in harness, "the harness must load the shipped panel"
        assert "/api/self/projects" in harness, "the harness must still hold the panel to the project route"
        assert (ROOT / _IMPROVE_WRAPPER).is_file(), f"{_IMPROVE_WRAPPER} is what runs this harness under Node"
        assert _IMPROVE_HARNESS in (ROOT / _IMPROVE_WRAPPER).read_text(encoding="utf-8")
        # A renamed export would leave the harness destructuring undefined and
        # failing for a reason that says nothing about the panel.
        pulled = re.search(r"const \{([^}]*)\} = context\.window\.ThomasSelfEdit;", harness)
        assert pulled, "the harness must take its entry points off window.ThomasSelfEdit"
        for name in (part.strip() for part in pulled.group(1).split(",")):
            assert name and re.search(rf"\b{name}\b", panel), f"ThomasSelfEdit.{name} is gone from {_IMPROVE_PANEL}"

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, "Improve Thomas panel harness"


def _the_collector_is_wired() -> None:
    """Every named fixture is on disk and claimed, and nothing else here is.

    ``tests/web_node/`` holds sixty-odd ``.mjs`` harnesses that their own Python
    wrappers run. Claiming one of those here would run it twice -- once as its
    wrapper's subprocess and once as a bare item with no wrapper's setup -- so
    the negative case is asserted alongside the positive one.
    """
    here = Path(__file__).parent
    for name in (_HARNESS, _VISUAL_FIXTURE, _IMPROVE_HARNESS):
        assert (here / name).is_file(), f"{name} is missing from {here}"
    assert issubclass(_TaskCardFile, pytest.File)
    assert issubclass(_TaskCardVisualFile, pytest.File)
    assert issubclass(_ImproveThomasFile, pytest.File)
    assert _collector_for(_IMPROVE_HARNESS) is _ImproveThomasFile
    # Each fixture is claimed, and by its own class. ``from_parent`` needs a real
    # collection tree, so the dispatch is asked for the class rather than for a
    # built collector.
    assert _collector_for(_HARNESS) is _TaskCardFile
    assert _collector_for(_VISUAL_FIXTURE) is _TaskCardVisualFile
    assert _collector_for(_SELF) is _CollectorSelfCheckFile
    # The other collectors in this file, each by its own class, the same way.
    for names, owner in (
        (BROWSER_MODE_HARNESSES, BrowserModeScript),
        (SOURCES, NodeHarness),
        ({PROBE}, BrowserProbe),
        (CHOOSER_ARTIFACTS, ChooserArtifact),
    ):
        for name in names:
            assert (here / name).is_file(), f"{name} is missing from {here}"
            assert _collector_for(name) is owner, name
    # The unclaimed branch returns before it touches ``parent``, so the hook
    # itself can be asked directly without building that tree either.
    assert _collector_for("chat_boot.mjs") is None
    assert pytest_collect_file(here / "chat_boot.mjs", parent=None) is None
    assert pytest_collect_file(here / "browser_history.mjs", parent=None) is None


class _CollectorSelfCheck(pytest.Item):
    def runtest(self) -> None:
        _the_collector_is_wired()

    def reportinfo(self) -> tuple[Path, int, str]:
        return self.path, 0, "web_node collector wiring"


class _CollectorSelfCheckFile(pytest.File):
    def collect(self):
        yield _CollectorSelfCheck.from_parent(self, name="collector is wired")


def test_the_web_node_collector_is_wired() -> None:
    """The same check, for the route that imports this file as a test module."""
    _the_collector_is_wired()
