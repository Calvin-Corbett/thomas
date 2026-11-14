"""thomas.core stays the bottom of the dependency tree: BootDoctor is handed what it needs from above.

boot_doctor.py imported the Windows PIN prompt from thomas.tools and the API-key store from thomas.server, which
thomas/_architecture.py lists as debt and the circular-import gate refuses in any staged change to that file. The
two now arrive as arguments from the entry points, and with nothing handed in the answer is no.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import sys
import types
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
from tests._bootdoctor_fakes import isolate_offline_checks
from thomas.bootdoctor import collaborators
from thomas.core import boot_ai_summary, boot_doctor
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig

ROOT = Path(__file__).resolve().parent.parent
CORE_FILES = ("boot_doctor.py", "boot_process.py", "boot_ai_summary.py", "boot_checks.py")


def _thomas_packages_imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("thomas."):
            names.add(".".join(node.module.split(".")[:2]))
        elif isinstance(node, ast.Import):
            names.update(".".join(a.name.split(".")[:2]) for a in node.names if a.name.startswith("thomas."))
    return names


@pytest.mark.parametrize("name", CORE_FILES)
def test_the_core_boot_doctor_files_import_nothing_from_tools_or_server(name: str) -> None:
    imported = _thomas_packages_imported(ROOT / "thomas" / "core" / name)
    assert not imported & {"thomas.tools", "thomas.server", "thomas.agent"}, imported


def test_a_path_outside_the_root_is_refused_when_nothing_can_ask(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    gate = boot_doctor.BootDoctorPathGate(tmp_path / "root")

    assert gate.allow_with_auth(tmp_path / "root" / "runtime" / "x.txt", purpose="inside")  # no question needed
    with pytest.raises(PermissionError):
        gate.allow_with_auth(tmp_path / "elsewhere" / "report.txt", purpose="outside")


def test_a_path_outside_the_root_needs_a_yes_from_the_one_who_is_asked(tmp_path: Path) -> None:
    (tmp_path / "root").mkdir()
    asked: list[str] = []

    def no(action: str, reason: str) -> bool:
        asked.append(action)
        return False

    def yes(action: str, reason: str) -> bool:
        asked.append(action)
        return True

    outside = tmp_path / "elsewhere" / "report.txt"
    with pytest.raises(PermissionError):
        boot_doctor.BootDoctorPathGate(tmp_path / "root", no).allow_with_auth(outside, purpose="outside")
    assert boot_doctor.BootDoctorPathGate(tmp_path / "root", yes).allow_with_auth(outside, purpose="outside")
    assert len(asked) == 2
    assert str(outside.resolve()) in asked[0]


def _config(tmp_path: Path, api_key: str = "") -> AppConfig:
    models = {"m": ModelConfig(name="m", provider="openai_compat", model="gpt-5", api_key=api_key)}
    return AppConfig(memory=MemoryConfig(root=str(tmp_path)), models=models, default_model="m")


def test_the_stored_key_fills_a_profile_that_has_none(tmp_path: Path) -> None:
    config = _config(tmp_path)
    seen: list[tuple[Path, str]] = []

    def lookup(folder: Path, profile: str) -> str:
        seen.append((folder, profile))
        return "stored-key"

    cfg = boot_ai_summary.model_cfg_with_secret(config, "m", lookup)

    assert cfg.api_key == "stored-key"
    assert seen == [(config.memory.root_path / ".thomas", "m")]


def test_a_key_in_the_config_is_kept_and_a_failing_lookup_changes_nothing(tmp_path: Path) -> None:
    def never(folder: Path, profile: str) -> str:
        raise AssertionError("a profile with a key must not be looked up")

    def broken(folder: Path, profile: str) -> str:
        raise OSError("secret store unreadable")

    assert boot_ai_summary.model_cfg_with_secret(_config(tmp_path, "own-key"), "m", never).api_key == "own-key"
    assert boot_ai_summary.model_cfg_with_secret(_config(tmp_path), "m", broken).api_key == ""
    assert boot_ai_summary.model_cfg_with_secret(_config(tmp_path), "m", None).api_key == ""


def test_the_entry_points_hand_the_collaborators_to_run_boot_doctor(tmp_path: Path, monkeypatch) -> None:
    seen: dict = {}

    def fake_run_boot_doctor(**kwargs) -> Path:
        seen.update(kwargs)
        return tmp_path / "report.txt"

    monkeypatch.setattr(bd_main, "run_boot_doctor", fake_run_boot_doctor)

    bd_main._run_report(
        config=AppConfig(), root=tmp_path, port=22058, reason="x", report_path=None, auto_repair=False, allow_ai=False
    )

    assert seen["authorize"] is collaborators.windows_authorize
    assert seen["secret_lookup"] is collaborators.stored_api_key
    direct = (ROOT / "scripts" / "run_boot_doctor_direct.py").read_text(encoding="utf-8")
    assert "authorize=windows_authorize" in direct
    assert "secret_lookup=stored_api_key" in direct


@pytest.mark.parametrize("content", ["[]", "null", '"text"', "42"])
def test_a_secret_file_that_is_not_a_table_leaves_the_key_empty_and_the_report_running(
    tmp_path: Path, content: str
) -> None:
    # SecretStore reads the file with data.get(...) outside its own guard, so any non-object JSON raises
    # AttributeError. The key lookup is best effort and must not be able to stop the tool that runs when state is broken.
    (tmp_path / ".thomas").mkdir()
    (tmp_path / ".thomas" / "secrets.json").write_text(content, encoding="utf-8")

    cfg = boot_ai_summary.model_cfg_with_secret(_config(tmp_path), "m", collaborators.stored_api_key)

    assert cfg.api_key == ""


@pytest.mark.parametrize(
    "error", [ImportError("no module"), SyntaxError("broken module"), AttributeError("half-loaded package")]
)
def test_a_server_package_that_will_not_import_leaves_the_key_empty(tmp_path: Path, monkeypatch, error) -> None:
    _refuse_import(monkeypatch, "thomas.server.secrets", error)

    assert collaborators.stored_api_key(tmp_path, "m") is None


def _refuse_import(monkeypatch, module: str, error: BaseException) -> None:
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == module:
            raise error
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)


class _FakeGate:
    """Stands in for the Windows PIN prompt, which these tests must never open."""

    def __init__(self, answer: object = True, error: BaseException | None = None) -> None:
        self.asked: list[tuple[str, str]] = []
        self.answer, self.error = answer, error

    def request_authorization(self, action_description: str, reason: str = "") -> object:
        self.asked.append((action_description, reason))
        if self.error is not None:
            raise self.error
        return self.answer


def _install_gate(monkeypatch, gate: _FakeGate) -> None:
    fake = types.ModuleType("thomas.tools.windows_auth")
    fake.get_auth_gate = lambda *args, **kwargs: gate
    monkeypatch.setitem(sys.modules, "thomas.tools.windows_auth", fake)


@pytest.mark.parametrize(
    "error", [ImportError("no module"), SyntaxError("broken module"), AttributeError("half-loaded package")]
)
def test_a_tools_package_that_will_not_import_is_a_no_to_the_pin_question(monkeypatch, error) -> None:
    _refuse_import(monkeypatch, "thomas.tools.windows_auth", error)

    assert collaborators.windows_authorize("Boot Doctor path access: D:/x", "why") is False


def test_with_the_tools_package_broken_a_path_outside_the_root_is_refused(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "root").mkdir()
    _refuse_import(monkeypatch, "thomas.tools.windows_auth", ImportError("no module"))
    gate = boot_doctor.BootDoctorPathGate(tmp_path / "root", collaborators.windows_authorize)

    with pytest.raises(PermissionError):
        gate.allow_with_auth(tmp_path / "elsewhere" / "report.txt", purpose="outside")


@pytest.mark.parametrize("answer", [True, False, None])
def test_the_pin_answer_is_the_gates_answer_and_the_question_reaches_it(monkeypatch, answer) -> None:
    gate = _FakeGate(answer)
    _install_gate(monkeypatch, gate)

    assert collaborators.windows_authorize("Boot Doctor path access: D:/x", "why") is bool(answer)

    assert gate.asked == [("Boot Doctor path access: D:/x", "why")]


@pytest.mark.parametrize("error", [OSError("no desktop"), RuntimeError("no dialog"), PermissionError("denied")])
def test_a_prompt_that_cannot_be_shown_is_a_no(monkeypatch, error) -> None:
    _install_gate(monkeypatch, _FakeGate(error=error))

    assert collaborators.windows_authorize("Boot Doctor path access: D:/x", "why") is False


@pytest.mark.parametrize("given", [True, False])
def test_the_direct_runner_hands_the_config_it_loaded_to_the_offline_check(
    tmp_path: Path, monkeypatch, given: bool
) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    other = tmp_path / "other.toml"
    other.write_text("", encoding="utf-8")
    argv = ["run_boot_doctor_direct.py", "--root", str(tmp_path), "--no-ai", "--no-auto-repair"]
    monkeypatch.setattr(sys, "argv", argv + (["--config", str(other)] if given else []))
    spec = importlib.util.spec_from_file_location(
        "run_boot_doctor_direct", ROOT / "scripts" / "run_boot_doctor_direct.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    seen: dict = {}
    monkeypatch.setattr(runner, "run_boot_doctor", lambda **kwargs: seen.update(kwargs) or tmp_path / "report.txt")

    assert runner.main() == 0

    # Otherwise the offline check reads <root>/thomas.toml and can call the wrong file fine.
    assert seen["config_path"] == (other if given else None)
