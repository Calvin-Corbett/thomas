"""What a row's words say, a sentence at a time, read from the shipped list.

A row's test keeps a dict of its sentences and the tests that show each one. These helpers return data and the test
asserts, because pytest rewrites asserts only in test modules.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from tests.row_proof_fixture import ROOT

LIST = ROOT / "thomas" / "server" / "rows" / "default.toml"


def sentences(row_id: str, *keys: str) -> list[str]:
    """The sentences of the named fields of a row, in the order the page tells them."""
    row = next(row for row in tomllib.loads(LIST.read_text(encoding="utf-8"))["row"] if row["id"] == row_id)
    return [part for key in keys for part in re.split(r"(?<=\.)\s+", row[key]) if part]


def unnamed_tests(words: dict[str, tuple[str, ...]], *proofs: Path) -> list[str]:
    """Tests the words name that none of ``proofs`` defines."""
    text = " ".join(proof.read_text(encoding="utf-8") for proof in proofs)
    return sorted({name for names in words.values() for name in names if f"def {name}(" not in text})
