"""Receipt IDs survive fresh interpreters and concurrent process migration."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.test_action_receipt_shards import _legacy, root  # noqa: F401
from thomas.server.routes import evolve_agent_receipts as receipts


def test_every_migrated_id_survives_a_fresh_process(root: Path) -> None:
    path, history = _legacy(root, 3)
    receipts._save_action_receipt(root, "run", "new", {"state": "running"})
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; "
            "from thomas.server.routes import evolve_agent_receipts as r; "
            "root=Path(sys.argv[1]); "
            "assert all(r._action_receipt(root, 'run', 'old-'+str(i))['state']=='completed' for i in range(3)); "
            "assert len(r._read_receipts(root))==4; print('all old IDs retained')",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=90,
        env=os.environ.copy(),
    )
    assert result.stdout.strip() == "all old IDs retained"
    assert len(path.read_bytes()) < 128
    assert all(receipts._action_receipt(root, "run", f"old-{i}") == value for i, value in enumerate(history.values()))


def test_concurrent_processes_migrate_and_preserve_every_request(root: Path) -> None:
    path, history = _legacy(root, 3)
    program = (
        "import sys, time; from pathlib import Path; "
        "from thomas.server.routes import evolve_agent_receipts as r; "
        "ready = Path(sys.argv[3]); ready.touch(); deadline = time.monotonic() + 30\n"
        "while len(list(ready.parent.glob('process-*.ready'))) < 2:\n"
        "    assert time.monotonic() < deadline, 'workers did not reach barrier'\n"
        "    time.sleep(0.01)\n"
        "r._save_action_receipt(Path(sys.argv[1]), 'run', sys.argv[2], {'state':'completed'}); "
        "assert r._action_receipt(Path(sys.argv[1]), 'run', 'old-0')['state'] == 'completed'"
    )

    def save(index: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", program, str(root), f"process-{index}", str(path.parent / f"process-{index}.ready")],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert all(result.returncode == 0 for result in results), [result.stderr for result in results]
    assert receipts._read_receipts(root) == {
        **history,
        **{receipts._receipt_key("run", f"process-{i}"): {"state": "completed"} for i in range(2)},
    }
