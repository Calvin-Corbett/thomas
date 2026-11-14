"""The Thomas shortcut can open the caged Thomas, and never starts a server as you there.

You chose (2026-09-23) to make the caged server your everyday Thomas once your
chats, settings and keys are moved. `python scripts/thomas_app.py --caged` points
the shortcut at it: the desktop shell attaches to port 8898 and, if the server is
down, starts only its scheduled task, which runs it as the cage account. The plain
install stays the rollback.
"""

from __future__ import annotations

from pathlib import Path

from scripts import thomas_app

MAIN_JS = Path(__file__).resolve().parents[1] / "desktop" / "main.js"


def test_the_caged_launcher_opens_the_caged_port_and_starts_only_its_task() -> None:
    text = thomas_app.render_launcher(thomas_app.CAGED_PORT, caged=True)

    assert '"http://127.0.0.1:8898/"' in text
    assert "--server-port 8898 --caged" in text
    assert "schtasks /Run /TN ThomasCagedServer" in text


def test_the_ordinary_launcher_is_unchanged_but_names_its_port() -> None:
    text = thomas_app.render_launcher(thomas_app.DEFAULT_PORT)

    assert '"http://127.0.0.1:8899/"' in text
    assert "--server-port 8899" in text
    assert "--caged" not in text and "schtasks" not in text


def test_the_desktop_shell_never_spawns_a_server_of_its_own_when_caged() -> None:
    source = MAIN_JS.read_text(encoding="utf-8")
    start = source.index("if (CAGED) {")
    caged_branch = source[start : source.index("} else {", start)]

    assert "schtasks" in caged_branch and "windowsHide: true" in caged_branch
    assert "spawnedServer =" not in caged_branch, "a caged launch must not own (and later stop) a server"
    assert "python" not in caged_branch.lower()
