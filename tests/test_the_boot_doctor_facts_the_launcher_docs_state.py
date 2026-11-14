"""The Boot Doctor facts in the launcher's public text are still what the code does.

scripts/README.md, the first-run question in scripts/thomas_app.py and the changelog say that
run-ui.ps1 starts Boot Doctor in a hidden window when the server comes up degraded or does not come
up, and name what Boot Doctor can then do. Those are claims about three other files, so they are read
from those files here, and the one part that can simply be run, where the repair agent may write, is run.
A fact that changes there fails here, so the text gets corrected instead of going stale. Only the facts
named below are checked; this is not a scan of everything Boot Doctor can do.
"""

from __future__ import annotations

import re
from pathlib import Path

from thomas.bootdoctor.runtime_helpers import BootDoctorPathPolicy

ROOT = Path(__file__).resolve().parents[1]


def _text(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _function(text: str, name: str) -> str:
    """One PowerShell function, without its quotes, so 'report' and "report" read the same."""
    start = text.index(f"function {name}")
    return re.sub(r"['\"]", "", text[start : text.index("\n}\n", start)]).replace("\\\\", "\\")


def test_run_ui_starts_boot_doctor_hidden_for_a_degraded_start_and_for_no_start() -> None:
    run_ui = _text("scripts", "run-ui.ps1")
    repair = _function(run_ui, "Start-BootDoctorBackgroundRepair")
    rescue = _function(run_ui, "Open-BootDoctorRescue")
    detached = run_ui[run_ui.index("# -NoTray: Run server directly") :]

    for body, mode in ((repair, "report"), (rescue, "rescue")):
        for piece in ("scripts\\bootdoctor.ps1", mode, "--force", "--relaunch", "-WindowStyle Hidden"):
            assert piece in body, (mode, piece)
    assert "Start-BootDoctorBackgroundRepair -Reason $reason -DiagPort $Port" in detached
    assert "Open-BootDoctorRescue -Reason $reason -DiagPort $Port" in detached
    assert "$launch.Healthy" in detached and "'degraded'" in detached, "the two cases the docs name"
    # And the third: no free port near the wanted one, where the report step runs inside run-ui.ps1 itself.
    assert "if ($FreePort -eq 0) {" in run_ui and 'Invoke-BootDoctor -Reason ("No free port found in range' in run_ui
    assert "function Find-FreePort" in run_ui


def test_boot_doctor_does_the_things_the_docs_say_it_can() -> None:
    core = _text("thomas", "core", "boot_doctor.py")
    cli = _text("thomas", "bootdoctor", "__main__.py")

    stop = core[core.index("if auto_repair and port_in_use and not _thomas_http_healthy") :]
    assert stop.index("if _is_thomas_cmdline(cmdline):") < stop.index("_kill_pid(pid)") < stop.index("server_deps")
    assert '[str(py_exe), "-m", "pip", "install", "-e", ".[server]"]' in core
    assert "if auto_repair and not dep_ok:" in core, "pip install runs only when aiohttp or httpx cannot be imported"
    assert "_spawn_thomas_server(" in core
    # A failed test server adds its likely cause and log tail to the report. The doctor no longer patches startup
    # files (e71f0cde dropped that), and the docs must not say it does.
    assert "_record_probe_failure(result, probe_log)" in core
    failure = core[core.index("def _record_probe_failure") : core.index("def _offline_steps")]
    assert '"startup_probe_cause"' in failure and '"startup_probe_log_tail"' in failure
    readme = _text("scripts", "README.md")
    assert "add the likely cause and the last lines of its log to the report" in readme
    assert "thomas/server/tool_extensions.py" not in readme and "thomas/groupchat/__init__.py" not in readme
    assert "best_model_profile(config) if allow_ai else None" in core, "the model summary is on unless switched off"
    assert '"--no-ai"' in cli and '"--no-auto-repair"' in cli
    assert re.search(r'"--max-attempts",\s*type=int,\s*default=3', cli), "up to three rounds"
    assert "autonomy_level=2" in cli
    assert re.search(r"if not config\.models:\s*return None, None, None", cli), "no model, no repair agent"


def test_the_repair_agent_can_write_where_the_docs_say_and_not_elsewhere(tmp_path: Path) -> None:
    policy = BootDoctorPathPolicy(tmp_path)

    for allowed in ("scripts/run-ui.ps1", "thomas/core/config.py", "thomas/server/app.py", "thomas/agent/loop.py"):
        assert policy.is_write_allowed(tmp_path / allowed), allowed
    for refused in ("thomas.toml", "tests/test_x.py", "thomas/memory/store.py", "scripts/setup.ps1", "README.md"):
        assert not policy.is_write_allowed(tmp_path / refused), refused
