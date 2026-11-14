"""run-repl.ps1 could not read thomas.toml, so it never started Ollama or warned about a missing key.

Its patterns were written with doubled backslashes inside single-quoted strings, so
``\\s`` matched a literal backslash followed by ``s`` and ``\\.`` a backslash and any
character. ``Get-DefaultModelName`` returned an empty string for a file that names
a model on its first line. run-ui.ps1 has the same three functions written
correctly; these tests run both scripts' copies against the same files and expect
the same answers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.launcher_powershell_support import RUN_REPL, RUN_UI, needs_windows_powershell, ps_path, run_functions

pytestmark = needs_windows_powershell

FUNCTIONS = ["Uses-OllamaLocal", "Get-DefaultModelName", "Get-ProfileApiKeyFromToml"]

LOCAL = """\
default_model = "local"

[models.local]
provider = "openai_compat"
base_url = "http://localhost:11434/v1"
"""

CLOUD = """\
  default_model = "OpenAI"

[models.local]
base_url = "http://localhost:11434/v1"
api_key = "not-this-one"

[models.openai]
provider = "openai"
  api_key = "not-a-real-key"

[models.anthropic]
api_key = ""
"""

_BODY = """
$Root = {root}
'local: ' + (Uses-OllamaLocal) + '|' + (Get-DefaultModelName)
Set-Content -Path (Join-Path $Root 'thomas.toml') -Value @'
{cloud}'@
'cloud: ' + (Uses-OllamaLocal) + '|' + (Get-DefaultModelName) + '|' + (Get-ProfileApiKeyFromToml -Profile 'openai') + '|' + (Get-ProfileApiKeyFromToml -Profile 'anthropic') + '|' + (Get-ProfileApiKeyFromToml -Profile 'missing')
"""


def _answers(script: Path, tmp_path: Path) -> list[str]:
    root = tmp_path / script.stem
    root.mkdir()
    (root / "thomas.toml").write_text(LOCAL, encoding="utf-8")
    out = run_functions(script, FUNCTIONS, _BODY.format(root=ps_path(root), cloud=CLOUD), root)
    return [line for line in out.splitlines() if line.startswith(("local: ", "cloud: "))] or [out]


@pytest.fixture(scope="module")
def answers(tmp_path_factory: pytest.TempPathFactory) -> dict[str, list[str]]:
    work = tmp_path_factory.mktemp("repl_config")
    return {"run-ui": _answers(RUN_UI, work), "run-repl": _answers(RUN_REPL, work)}


def test_run_repl_finds_an_ollama_profile_and_its_default_model(answers: dict[str, list[str]]) -> None:
    assert answers["run-repl"][0] == "local: True|local", answers["run-repl"]


def test_run_repl_reads_the_key_and_the_model_the_cloud_profiles_name(answers: dict[str, list[str]]) -> None:
    # The model name is lower-cased, a key is trimmed, an empty key and an unknown profile are "".
    assert answers["run-repl"][1] == "cloud: False|openai|not-a-real-key||", answers["run-repl"]


def test_both_launchers_give_the_same_answers(answers: dict[str, list[str]]) -> None:
    assert answers["run-repl"] == answers["run-ui"]
