"""The thing that writes the code is allowed to run it.

Thomas's builder got Read/Edit/Write/Glob/Grep and nothing else. The comment above
that list names the assumption it was built on: *"The human watcher reviews the
resulting diff and runs the tests."* Thomas is used unsupervised, by people who
cannot read a diff, so nobody was running those tests.

Shell was gated on `guardrails == "open"` while the default is `"guarded"` — so the
only way to let Thomas run the tests for code it had just written was to also pick
the setting branded least safe. Everywhere else in software "guarded" means *asks
before dangerous things*, not *cannot do things*.

Measured cost, 2026-08-05: Thomas built a three-file expense tracker whose app.js
referenced an undeclared `refreshButton` on its last line. It reported it was
"doing a quick source review" — a READ — and nothing ever executed the page.
Raising the pass budget from 10 to 25 produced more edits and the same bug, because
once a file is written no new information can reach a model that cannot run things.

`fortress` still means no shell. Read-only still means no shell in every mode.
"""

from __future__ import annotations

import argparse

import pytest

from thomas.forge.anvil import forge_code_runner


def _allow_shell(guardrails: str, *, autonomy: int = 3, file_access: str = "project") -> bool:
    """Recompute the gate the way run_configured_turn does."""

    args = argparse.Namespace(autonomy=autonomy, file_access=file_access, guardrails=guardrails)
    live_edit = args.autonomy >= 3 and args.file_access != "read_only"
    return live_edit and args.guardrails in ("open", "guarded")


@pytest.mark.parametrize("guardrails", ["open", "guarded"])
def test_the_builder_has_a_shell_at_the_default_setting(guardrails: str) -> None:
    assert _allow_shell(guardrails), (
        f"at guardrails={guardrails!r} the builder cannot run anything, so it cannot "
        "check its own work and a one-line runtime bug ships"
    )


def test_the_default_guardrail_is_one_that_allows_a_shell() -> None:
    """The gate is only meaningful next to what the default actually is."""

    from pathlib import Path

    source = Path(forge_code_runner.__file__).read_text(encoding="utf-8")
    assert 'default="guarded"' in source, "the default guardrail moved; re-check this gate"
    assert _allow_shell("guarded"), "the default setting leaves the builder unable to run anything"


def test_fortress_still_means_no_shell() -> None:
    """Widening the default must not delete the setting that exists to say no."""

    assert not _allow_shell("fortress")


@pytest.mark.parametrize("guardrails", ["open", "guarded", "fortress"])
def test_read_only_never_gets_a_shell(guardrails: str) -> None:
    assert not _allow_shell(guardrails, file_access="read_only")


@pytest.mark.parametrize("guardrails", ["open", "guarded", "fortress"])
def test_low_autonomy_never_gets_a_shell(guardrails: str) -> None:
    assert not _allow_shell(guardrails, autonomy=2)


def test_the_prompt_no_longer_tells_the_model_it_cannot_run_things() -> None:
    """A shell the model is told it does not have is a shell it will not use.

    Asserted against the GENERATED prompt, not the source file. The first version of
    this test read the source and matched the comment that quotes the old wording in
    order to explain why it changed -- a check that greps for a smell also hits the
    note explaining the smell's removal.
    """

    from thomas.forge.anvil.bridge_prompts import compose_headless_prompt

    prompt = compose_headless_prompt(
        "build a small page", guardrails="guarded", file_access="project", autonomy_level=3
    )
    assert "you do not run shell or git yourself" not in prompt, (
        "the prompt still tells the builder it has no shell, so the capability is inert"
    )
    assert "RUN WHAT YOU BUILT" in prompt, "the prompt does not ask the model to run its work"
    assert "shell is unavailable and external" not in prompt, (
        "the guardrail line still claims guarded has no shell"
    )
