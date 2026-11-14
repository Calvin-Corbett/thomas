"""A self-fix reaches the running Thomas only through your approval, and exactly as shown.

Project 3 of docs/superpowers/specs/2026-09-22-trusted-self-change-design.md. A
self-fix made in green arrives in the commit-master inbox; the promoter, which
runs as you, re-derives it without executing any of it, asks you on cards worded
by the pinned catalogue, and only then moves ``dev`` and the running copy.
Every refusal here happens before the Windows prompt is shown.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from scripts.cage import self_change_promoter as sp

from tests.green_support import git
from tests.landing_support import (
    checkout_bytes,
    copy_blue,
    isolated_landing_git,
    landing_blue_template,
    prepare_green_root,
)
from thomas.core.git_launcher import real_git_first
from thomas.server import green_checkout, green_handoff
from thomas.tools import cage_shell, trusted_card

pytestmark = pytest.mark.usefixtures(isolated_landing_git.__name__)


@pytest.fixture
def blue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> Path:
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(prepare_green_root(tmp_path / "green-root")))
    monkeypatch.setenv("PATH", real_git_first(os.environ)["PATH"])
    return copy_blue(landing_blue_template(tmp_path_factory), tmp_path)


@pytest.fixture
def pins(tmp_path: Path) -> Path:
    root = tmp_path / "pins"
    root.mkdir()
    (root / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    return root


class Asker:
    def __init__(self, *answers: bool) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str]] = []

    def __call__(self, action: str, reason: str) -> bool:
        self.asked.append((action, reason))
        return self.answers.pop(0) if self.answers else False


def _promoter(blue: Path, pins: Path, ask, audit=lambda _repo: []) -> sp.Promoter:
    return sp.Promoter(repo=blue, cage_root=cage_shell.cage_root(), ask=ask, pin_root=pins, audit=audit)


def _submit(blue: Path, execution_id: str, files: dict[str, str]) -> Path:
    green = green_checkout.create_green(blue, execution_id)
    for rel, text in files.items():
        (green.work / rel).parent.mkdir(parents=True, exist_ok=True)
        (green.work / rel).write_text(text, encoding="utf-8")
    patch = green_checkout.green_patch(green)
    return green_handoff._write_submission(
        green, patch, green_checkout.changed_paths(green, _staged=True), "Fixed it.", "chat-1", f"self-{execution_id}"
    )


def _outbox(sid: str, kind: str) -> dict:
    return json.loads((cage_shell.cage_root() / "outbox" / f"{sid}.{kind}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_approving_lands_exactly_the_change_on_dev_and_in_the_running_copy(
    blue: Path, pins: Path, autocrlf: str, tmp_path: Path
) -> None:
    git(blue, "config", "core.autocrlf", autocrlf)
    before = git(blue, "rev-parse", "dev")
    new_source = "NEW = 1\n"
    sub = _submit(blue, "exec-yes", {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": new_source})
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert git(blue, "rev-parse", "dev") == outcome.commit_sha != before
    assert git(blue, "rev-parse", f"{outcome.commit_sha}^") == before
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (blue / "thomas" / "new.py").read_text(encoding="utf-8") == new_source
    # The repository setting is shared by the promoter (which strips GIT_ variables)
    # and plain Git in pytest's isolated environment.
    status = subprocess.run(["git", "status", "--porcelain"], cwd=blue, capture_output=True, text=True, check=True)
    assert status.stdout == "", status.stdout
    reference = checkout_bytes(blue, tmp_path / "reference", ["thomas/fix_me.py", "thomas/new.py"], autocrlf)
    for path, content in reference.items():
        assert (blue / path).read_bytes() == content
    action, reason = ask.asked[0]
    assert action.startswith("Put Thomas's changes into the running Thomas")
    assert "Fixed it." not in action + reason, "the model's words never reach the Windows prompt"
    pending = _outbox(sub.name, "pending")
    assert pending["chat"] == "chat-1"
    assert pending["cards"][-1]["pairing_code"] in reason
    assert len(pending["card_prompts"]) == 1
    assert pending["card_prompts"][0]["end"] >= pending["card_prompts"][0]["start"] > 0
    verdict = _outbox(sub.name, "verdict")
    assert verdict["status"] == "landed"
    assert verdict["card_prompts"] == pending["card_prompts"]
    assert not sub.exists()


def test_declining_leaves_dev_and_the_running_copy_unchanged(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-no", {"thomas/fix_me.py": "VALUE = 2\n"})

    outcome = _promoter(blue, pins, Asker(False)).promote(sub)

    assert outcome.status == "declined"
    assert git(blue, "rev-parse", "dev") == before
    assert (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _outbox(sub.name, "verdict")["status"] == "declined"


def test_the_promoter_never_runs_the_code_it_promotes(blue: Path, pins: Path, tmp_path: Path) -> None:
    marker = tmp_path / "ran.txt"
    code = f"open({str(marker)!r}, 'w').write('ran')\n"
    sub = _submit(blue, "exec-inert", {"thomas/side_effect.py": code, "tests/test_side_effect.py": code})

    assert _promoter(blue, pins, Asker(True)).promote(sub).status == "landed"
    assert not marker.exists()


def test_python_that_does_not_compile_is_refused_before_asking(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-broken", {"thomas/fix_me.py": "def broken(:\n"})
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused" and "thomas/fix_me.py" in outcome.detail
    assert ask.asked == []


def test_uncommitted_work_in_the_running_copy_is_never_overwritten(blue: Path, pins: Path) -> None:
    before = git(blue, "rev-parse", "dev")
    sub = _submit(blue, "exec-dirty", {"thomas/fix_me.py": "VALUE = 2\n"})
    (blue / "thomas" / "fix_me.py").write_text("VALUE = 'someone else is editing this'\n", encoding="utf-8")

    outcome = _promoter(blue, pins, Asker(True)).promote(sub)

    assert outcome.status == "refused" and "uncommitted" in outcome.detail
    assert git(blue, "rev-parse", "dev") == before
    assert "someone else" in (blue / "thomas" / "fix_me.py").read_text(encoding="utf-8")


def test_a_dev_that_moved_during_the_prompt_is_asked_again_on_the_new_tree(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-race", {"thomas/fix_me.py": "VALUE = 2\n"})
    asked: list[tuple[str, str]] = []

    def someone_lands_first_then_you_approve(action: str, reason: str) -> bool:
        if not asked:
            (blue / "README.md").write_text("moved on\n", encoding="utf-8")
            git(blue, "commit", "-qam", "someone else landed first")
        asked.append((action, reason))
        return True

    outcome = _promoter(blue, pins, someone_lands_first_then_you_approve).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert len(asked) == 2, "an approval covers one exact tree"
    assert asked[0][1] != asked[1][1], "the new tree carries a new pairing code"
    prompts = _outbox(sub.name, "pending")["card_prompts"]
    assert len(prompts) == 2, "both completed cards survive the second pending write"
    assert all(prompt["end"] >= prompt["start"] > 0 for prompt in prompts)
    assert git(blue, "show", "dev:README.md") == "moved on"
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"


def test_a_dangerous_file_gets_its_own_card_and_can_be_left_out(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-mixed", {"scripts/cage/new_rule.py": "RULE = 1\n", "thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker(False, True)  # decline the cage file, approve the rest

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "landed", outcome.detail
    assert ask.asked[0][0].startswith("Change a file that guards Thomas")
    assert "scripts/cage/new_rule.py" in ask.asked[0][0]
    assert "own approval" in ask.asked[0][1]
    assert git(blue, "show", "dev:thomas/fix_me.py") == "VALUE = 2"
    assert not (blue / "scripts" / "cage" / "new_rule.py").exists()
    assert outcome.files == ["thomas/fix_me.py"]


def test_a_change_that_guts_an_imported_module_is_refused_before_asking(blue: Path, pins: Path) -> None:
    """Measured live 2026-09-22 (exec-8ef69b69fb68): a worker blocked from reading
    the file it had to edit wrote a module holding only its new docstring --
    5 lines added, 102 deleted -- and every name other modules import from it was
    gone. Nothing here runs the code: the check parses both versions."""
    (blue / "thomas" / "lib.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (blue / "thomas" / "user.py").write_text("from thomas.lib import helper\n", encoding="utf-8")
    git(blue, "add", "-A")
    git(blue, "commit", "-qm", "a module and its importer")
    sub = _submit(blue, "exec-gutted", {"thomas/lib.py": '"""Only a docstring now."""\n'})
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask).promote(sub)

    assert outcome.status == "refused"
    assert "helper" in outcome.detail and "thomas/user.py" in outcome.detail
    assert ask.asked == []


def test_the_card_shows_how_big_each_change_is(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-sized", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker(True)

    _promoter(blue, pins, ask).promote(sub)

    assert "thomas/fix_me.py (+1 -1)" in ask.asked[0][0]
    # The Windows prompt stays short; the chat card carries the diff itself.
    card = _outbox(sub.name, "pending")["cards"][-1]
    assert "+VALUE = 2" in card["excerpt"] and "-VALUE = 1" in card["excerpt"]
    assert "+VALUE = 2" not in ask.asked[0][0] + ask.asked[0][1]


def test_a_tampered_catalogue_holds_without_asking_or_refusing(blue: Path, pins: Path) -> None:
    """A catalogue that does not match its pin is the machine's state, not the change's fault (a re-pin refused
    self-thomas-eb0e79c9d549 on 2026-10-08): the hand-in waits, and is asked once the pin matches again."""
    good = (pins / trusted_card.PIN_NAME).read_text()
    (pins / trusted_card.PIN_NAME).write_text("0" * 64)
    sub = _submit(blue, "exec-tamper", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker(True)
    promoter = _promoter(blue, pins, ask)

    outcome = promoter.promote(sub)

    assert outcome.status == "held" and "approval cards" in outcome.detail
    assert ask.asked == []
    assert sub.is_dir() and not (cage_shell.cage_root() / "outbox" / f"{sub.name}.verdict.json").exists()

    (pins / trusted_card.PIN_NAME).write_text(good)
    assert promoter.run_once().status == "landed"  # type: ignore[union-attr]
    assert len(ask.asked) == 1


def test_a_surprise_writer_refuses_without_asking(blue: Path, pins: Path) -> None:
    sub = _submit(blue, "exec-writer", {"thomas/fix_me.py": "VALUE = 2\n"})
    ask = Asker(True)

    outcome = _promoter(blue, pins, ask, audit=lambda _r: ["S-1-5-21-9-9-9-1234"]).promote(sub)

    assert outcome.status == "refused" and "S-1-5-21-9-9-9-1234" in outcome.detail
    assert ask.asked == []
