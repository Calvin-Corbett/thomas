"""Persistent tabs become ready without waiting for unrelated resources."""

import json
import subprocess
from pathlib import Path


def test_tab_documents_are_ready_without_history_and_reject_stale_boots():
    root = Path(__file__).resolve().parents[1]
    web = root / "thomas/server/web/js"
    result = subprocess.run(
        [
            "node",
            str(root / "tests/web_node/tab_document_readiness.mjs"),
            *(
                str(web / name)
                for name in [
                    "unified_mode_shell.js",
                    "browser_shell_docs.js",
                    "browser_shell_docs_policy.js",
                    "unified_work_mode.js",
                    "unified_code_mode.js",
                ]
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert all(json.loads(result.stdout).values())
