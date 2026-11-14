"""A server the desktop shell starts is as quiet as one run-ui starts.

Four self-improvement engines (code-issue, self-upgrade, UI-workflow, local-agent)
default to on in code and run background checks: a heartbeat script, configuration
and release checks, image-provider searches, local Ollama and git status reads.
``scripts/run-ui.ps1`` sets all six engine flags to 0 for the server it starts, but
the desktop shell spawned its own server with the environment untouched, so the icon
that opens the shell left them running. The shell now hands its server the same
defaults; a flag you set yourself still wins. An empty one is not a setting: every
engine reads an empty value as unset and falls back to its default, which is on.

The environment builder is read out of ``desktop/main.js`` and run in Node, because
main.js needs Electron and cannot be imported on its own.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN_JS = ROOT / "desktop" / "main.js"
RUN_UI = ROOT / "scripts" / "run-ui.ps1"
NODE = shutil.which("node")


def _quiet_names_in_run_ui() -> set[str]:
    text = RUN_UI.read_text(encoding="utf-8")
    block = text[text.index("foreach ($quietVar in @(") :]
    return set(re.findall(r"'(THOMAS_[A-Z_]+)'", block[: block.index("{")]))


def _builder_source() -> str:
    source = MAIN_JS.read_text(encoding="utf-8")
    assert "const QUIET_ENGINE_VARS" in source and "function serverEnv()" in source, (
        "desktop/main.js must build its server's environment in serverEnv()"
    )
    start = source.index("const QUIET_ENGINE_VARS")
    end = source.index("\n}\n", source.index("function serverEnv()")) + 3
    return source[start:end]


def _server_env(**preset: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("THOMAS_")}
    env.update(preset)
    program = _builder_source() + "\nconsole.log(JSON.stringify(serverEnv()));\n"
    done = subprocess.run(  # noqa: S603 - node on a snippet cut from main.js
        [NODE, "-e", program], capture_output=True, check=False, env=env, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_shell_quiets_the_same_six_flags_run_ui_quiets() -> None:
    names = _quiet_names_in_run_ui()
    assert len(names) == 6, names

    source = MAIN_JS.read_text(encoding="utf-8")
    listed = set(re.findall(r'"(THOMAS_[A-Z_]+)"', source[source.index("const QUIET_ENGINE_VARS") :][:600]))

    assert listed == names


def test_the_server_it_spawns_is_handed_that_environment() -> None:
    source = MAIN_JS.read_text(encoding="utf-8")
    spawn = source[source.index("spawnedServer = spawn(") :]
    call = spawn[: spawn.index("});")]

    assert "env: serverEnv()" in call
    assert source.index("env: serverEnv()") > source.index("} else {", source.index("if (CAGED) {"))


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_every_idle_engine_flag_is_off_unless_you_set_it() -> None:
    env = _server_env(THOMAS_UNRELATED_SETTING="kept")

    for name in _quiet_names_in_run_ui():
        assert env[name] == "0", name
    assert env["THOMAS_UNRELATED_SETTING"] == "kept", "the rest of the environment must pass through"


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_a_flag_you_set_yourself_is_left_alone() -> None:
    env = _server_env(THOMAS_CODE_ISSUE_ENGINE_ENABLED="1", THOMAS_SELF_UPGRADE_ENGINE_ENABLED="false")

    assert env["THOMAS_CODE_ISSUE_ENGINE_ENABLED"] == "1"
    assert env["THOMAS_SELF_UPGRADE_ENGINE_ENABLED"] == "false"
    assert env["THOMAS_UI_WORKFLOW_ENGINE_ENABLED"] == "0"


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_an_empty_flag_is_not_a_setting_and_the_engine_stays_off() -> None:
    """Every engine's _env_bool reads an empty value as unset, and four default to on."""
    env = _server_env(THOMAS_LOCAL_AGENT_ENGINE_ENABLED="", THOMAS_CODE_ISSUE_ENGINE_ENABLED="  ")

    assert env["THOMAS_LOCAL_AGENT_ENGINE_ENABLED"] == "0"
    assert env["THOMAS_CODE_ISSUE_ENGINE_ENABLED"] == "0"
