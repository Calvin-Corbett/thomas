"""The cage window shows what a run did and what a self-fix changed, and never lets a caller out of the folder it asked about."""

import json
import subprocess
from pathlib import Path

from thomas.core import cage_inspector as inspector


def _green(tmp_path: Path, green_id: str = "thomas-abc123") -> tuple[Path, Path]:
    root = tmp_path / "green"
    work = root / "work" / green_id
    work.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(work), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (work / "a.py").write_text("one\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    (work / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    (work / "new.txt").write_text("hello", encoding="utf-8")
    return root, work


def test_a_green_shows_what_it_changed(tmp_path):
    root, _ = _green(tmp_path)
    assert inspector.greens(root)["greens"][0]["id"] == "thomas-abc123"
    status = inspector.green_status(root, "thomas-abc123")
    assert status["ok"] and status["changed"] == 2
    assert any("a.py" in line for line in status["files"])
    diff = inspector.green_diff(root, "thomas-abc123", "a.py")
    assert "+two" in diff["diff"]
    assert inspector.green_file(root, "thomas-abc123", "new.txt")["text"] == "hello"


def test_a_caller_cannot_leave_the_green(tmp_path):
    root, _ = _green(tmp_path)
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    for bad in ("../../../outside.txt", "..\\..\\..\\outside.txt", str(tmp_path / "outside.txt"), ".git/config", ""):
        assert inspector.green_file(root, "thomas-abc123", bad)["ok"] is False, bad
    assert inspector.green_status(root, "../x")["ok"] is False
    assert inspector.green_status(root, "no-such")["ok"] is False


def test_secret_named_and_binary_files_are_refused(tmp_path):
    root, work = _green(tmp_path)
    (work / ".env").write_text("KEY=1", encoding="utf-8")
    (work / "api_token.txt").write_text("x", encoding="utf-8")
    (work / "blob.bin").write_bytes(b"\x00\x01\x02")
    for name in (".env", "api_token.txt"):
        assert "secret" in inspector.green_file(root, "thomas-abc123", name)["error"]
    assert "binary" in inspector.green_file(root, "thomas-abc123", "blob.bin")["error"]


def test_a_file_over_the_cap_is_cut_and_says_so(tmp_path, monkeypatch):
    root, work = _green(tmp_path)
    monkeypatch.setattr(inspector, "FILE_CAP", 10)
    (work / "big.txt").write_text("x" * 50, encoding="utf-8")
    got = inspector.green_file(root, "thomas-abc123", "big.txt")
    assert got["truncated"] is True and len(got["text"]) == 10 and got["bytes"] == 50


def test_credentials_are_hidden_in_text_and_command_lines():
    assert "abc123secret" not in inspector.redact("run --token abc123secret now")
    assert "hunter2" not in inspector.redact("password=hunter2")
    assert "sk-" not in inspector.redact("key sk-abcdefghijklmnopqrstuvwx here")
    assert "[redacted]" in inspector.redact("Authorization: Bearer eyJabc.def")


def _line(**kw):
    return json.dumps(kw)


def test_runs_report_loops_and_last_moves(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    lines = [_line(fc="tool_started", name="fs.read_file", text="path: same.py", ts=i) for i in range(6)]
    lines += [_line(fc="tool_result", name="check.run", text="pytest failed", is_error=True, ts=9) for _ in range(3)]
    lines += [_line(fc="say", text="thinking about it", ts=10)]
    (agent / "transcript-aaaa1111.txt").write_text("\n".join(lines), encoding="utf-8")
    got = inspector.runs(agent, hours=1)["runs"][0]
    assert got["run"] == "aaaa1111" and got["tool_calls"] == 6 and got["errors"] == 3
    assert any("same call 6 times" in f for f in got["flags"])
    assert any("same error 3 times" in f for f in got["flags"])
    assert got["last_moves"][-1]["text"] == "thinking about it"
    assert inspector.run_tail(agent, "aaaa1111", 2)["moves"][-1]["kind"] == "say"
    assert inspector.run_tail(agent, "../etc", 2)["ok"] is False


def test_processes_lists_this_one():
    got = inspector.processes()
    assert got["ok"] and got["count"] >= 1
    assert any(p["pid"] == got["server_pid"] for p in got["processes"])


def test_a_busy_process_shows_the_processor_it_is_using():
    """The first version asked each process for its load the moment it met it, which always answers 0. Load is the
    processor time used between two readings, as a share of the whole PC."""
    import subprocess
    import sys

    busy = subprocess.Popen(
        [sys.executable, "-c", "import time\nend = time.time() + 20\nwhile time.time() < end: pass"]
    )
    try:
        import time

        import psutil

        ends = time.time() + 10  # the work must be running before the first reading is taken
        while (
            time.time() < ends
            and psutil.Process(busy.pid).cpu_times().user < 0.2
            and not psutil.Process(busy.pid).children()
        ):
            time.sleep(0.05)
        time.sleep(0.3)
        got = inspector.processes(sample_s=0.6)
    finally:
        for child in psutil.Process(busy.pid).children(recursive=True):
            child.kill()
        busy.kill()
        busy.wait()
    # Started from the project's environment, the process this test holds is the launcher half: the work is its child.
    pair = [p for p in got["processes"] if busy.pid in (p["pid"], p["ppid"])]
    assert pair, "the busy process is listed"
    used = max(p["cpu_percent"] or 0.0 for p in pair)
    assert got["sample_s"] == 0.6 and got["cores"] >= 1
    assert used > 0.5, pair  # one busy core of 16 is about 6 percent of the PC
    assert got["cpu_percent"] >= used  # the total for everything listed


def test_each_process_says_what_it_is():
    rows = [
        {"pid": 1, "ppid": 0, "name": "python.exe", "cmd": "python -m thomas.server --port 8898", "age_s": 900},
        {
            "pid": 2,
            "ppid": 1,
            "name": "python.exe",
            "cmd": "venv/python.exe -m thomas.forge.anvil.forge_code_runner x",
            "age_s": 600,
        },
        {
            "pid": 3,
            "ppid": 2,
            "name": "python.exe",
            "cmd": "py/python.exe -m thomas.forge.anvil.forge_code_runner x",
            "age_s": 600,
        },
        {"pid": 4, "ppid": 3, "name": "python.exe", "cmd": "python -m pytest tests/test_a.py -q", "age_s": 12},
        {"pid": 5, "ppid": 4, "name": "chrome-headless-shell.exe", "cmd": "chrome-headless-shell --remote", "age_s": 3},
        {"pid": 6, "ppid": 3, "name": "conhost.exe", "cmd": "", "age_s": 600},
        {"pid": 7, "ppid": 3, "name": "git.exe", "cmd": "git status", "age_s": 1},
        {"pid": 8, "ppid": 3, "name": "node.exe", "cmd": "node tool.js", "age_s": 5},
    ]
    kinds = {row["pid"]: row["kind"] for row in inspector.label(rows, server_pid=1)}
    assert kinds == {
        1: "the server",
        2: "launcher half of a Build agent",  # the environment's python.exe only starts the real one, its child
        3: "Build agent",
        4: "test run",
        5: "browser a test or playtest opened",
        6: "console host",
        7: "git",
        8: "other",
    }


def test_the_answer_counts_each_kind_and_its_load():
    got = inspector.processes(sample_s=0.2)
    assert got["ok"] and isinstance(got["kinds"], dict) and got["kinds"]
    assert all(set(entry) == {"count", "cpu_percent"} for entry in got["kinds"].values())
    assert sum(entry["count"] for entry in got["kinds"].values()) == got["count"]
    assert all("kind" in row for row in got["processes"])
