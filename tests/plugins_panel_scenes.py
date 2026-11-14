"""Runs a scene of the Plugins panel's own script under node, for the tests of that panel.

tests/plugins_panel_harness.js is a page and a clock and decides nothing, so a scene reads what a person would read.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
START = """
const assert = require('assert');
const { Page, open, row } = require('./tests/plugins_panel_harness.js');
const STOPPING = { state: 'unloading', enabled: false };
const stoppingPage = async (fields = {}) => {
  const page = await open([row({ ...STOPPING, waiting_for: 1, ...fields })]);
  return [page, page.row(fields.title || 'Companion apps')];
};
const FAILED = { state: 'failed', error: 'RuntimeError: the port is taken' };
(async () => {
"""
END = "\n})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });\n"


def run(scenario: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to run the panel's own script")
    script = START + scenario + END
    result = subprocess.run(
        [node, "-"], input=script, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
