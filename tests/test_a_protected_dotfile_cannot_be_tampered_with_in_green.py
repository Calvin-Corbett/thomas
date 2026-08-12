"""A protected file whose name starts with a dot must be guarded like the rest.

``_normalize_relpath`` in ``doppelganger.py`` (and its twin in
``evolve_charter.py``) ended in ``.lstrip("./")``. ``str.lstrip`` takes a SET of
characters, not a prefix, so it ate every leading ``.`` and ``/``. Every consumer
turns the result back into a real filesystem path, so ``.gitignore`` -- listed
under ``[protected] policy_files`` in ``agent_safety.toml`` -- became
``gitignore``, a name that exists in neither the blue nor the green tree.

That is a check with only one possible answer. ``_promotion_protected_diffs``
compared ``blue/gitignore`` with ``green/gitignore``, found both absent, and took
its ``continue`` -- so "this protected file changed" could never be reported for
it, however the file was rewritten. Measured on two trees whose only difference
was one protected file, before the fix::

    AGENTS.md  tampered -> diffs=['AGENTS.md']  promotion BLOCKED
    .gitignore tampered -> diffs=[]             promotion ALLOWED

Same gate, same call, same kind of edit. Only the leading dot decided it.

The revert half was worse, because it reported success. ``evolve``'s
``_restore_green_path_from_blue`` copies ``blue/<norm>`` over ``green/<norm>``,
so a tampered ``.gitignore`` was named as a violation, listed as reverted, and
left exactly as green had written it::

    AGENTS.md  violations=['AGENTS.md']  reverted=['AGENTS.md']  -> RESTORED
    .gitignore violations=['.gitignore'] reverted=['.gitignore'] -> STILL TAMPERED

Two more consequences of the same line, also pinned below:

* ``_normalize_delta_relpath`` guards with
  ``path.is_absolute() or ".." in path.parts``. A leading ``../`` was deleted
  before the test ran, so ``../thomas/agriculture/x.py`` arrived as the in-tree
  ``thomas/agriculture/x.py`` and was promoted as though the caller had named
  it. An interior ``thomas/../x.py`` still raised, which is why the guard looked
  alive.
* ``_is_promotable_scope(".gitignore")`` was ``False`` even though ``.gitignore``
  is in ``_INCLUDE_FILES`` and is copied by ``sync_blue_to_green`` -- so a real
  ``.gitignore`` change was refused with a message naming ``gitignore``.

After the fix every line above flips, and the controls (``AGENTS.md``, an
untampered pair, an ordinary in-tree path) are unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.forge.anvil import doppelganger, evolve

_SAFETY = """
[protected]
policy_files = ["AGENTS.md", ".gitignore"]
"""


def _pair(tmp_path: Path, blue: dict[str, str], green: dict[str, str]) -> doppelganger.DoppelgangerPaths:
    blue_root, green_root = tmp_path / "blue", tmp_path / "dg" / "green"
    for root, files in ((blue_root, blue), (green_root, green)):
        for rel, body in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    return doppelganger.DoppelgangerPaths(
        blue_root=blue_root,
        dg_root=tmp_path / "dg",
        green_root=green_root,
        green_runtime=tmp_path / "dg" / "green-runtime",
        green_venv=tmp_path / "dg" / "venvs" / "green",
        backups_root=tmp_path / "dg" / "backups",
    )


@pytest.mark.parametrize("protected_file", [".gitignore", "AGENTS.md"])
def test_a_tampered_protected_file_blocks_promotion_dot_or_not(tmp_path: Path, protected_file: str) -> None:
    paths = _pair(
        tmp_path,
        {"agent_safety.toml": _SAFETY, protected_file: "ORIGINAL"},
        {"agent_safety.toml": _SAFETY, protected_file: "TAMPERED"},
    )

    assert doppelganger._promotion_protected_diffs(paths) == [protected_file]
    with pytest.raises(RuntimeError, match="protected/supervisor-owned diff"):
        doppelganger._validate_green_to_blue_promotion(paths)


def test_an_untampered_pair_still_reports_no_protected_diff(tmp_path: Path) -> None:
    paths = _pair(
        tmp_path,
        {"agent_safety.toml": _SAFETY, ".gitignore": "runtime/", "AGENTS.md": "rules"},
        {"agent_safety.toml": _SAFETY, ".gitignore": "runtime/", "AGENTS.md": "rules"},
    )

    assert doppelganger._promotion_protected_diffs(paths) == []
    doppelganger._validate_green_to_blue_promotion(paths)


@pytest.mark.parametrize("protected_file", [".gitignore", "AGENTS.md"])
def test_reverting_a_protected_file_really_restores_it(tmp_path: Path, protected_file: str) -> None:
    paths = _pair(
        tmp_path,
        {"agent_safety.toml": _SAFETY, protected_file: "ORIGINAL"},
        {"agent_safety.toml": _SAFETY, protected_file: "TAMPERED"},
    )
    protected_paths = evolve._load_evolve_protected_paths(paths.green_root)

    _delta, violations, reverted = evolve._revert_protected_changes(
        paths, {"changed_files": [protected_file], "changed_count": 1}, protected_paths
    )

    assert violations == [protected_file]
    assert reverted == [protected_file]
    # The claim and the disk have to agree: "reverted" used to be printed over a
    # file nothing had written to.
    assert (paths.green_root / protected_file).read_text(encoding="utf-8") == "ORIGINAL"


def test_a_delta_path_that_climbs_out_of_the_tree_is_refused() -> None:
    with pytest.raises(RuntimeError, match="unsafe delta path"):
        doppelganger._normalize_delta_relpath("../thomas/agriculture/x.py")
    # Control: the interior form always worked, and an ordinary path still passes.
    with pytest.raises(RuntimeError, match="unsafe delta path"):
        doppelganger._normalize_delta_relpath("thomas/../x.py")
    assert doppelganger._normalize_delta_relpath("thomas/agriculture/x.py") == "thomas/agriculture/x.py"
    assert doppelganger._normalize_delta_relpath("./thomas/agriculture/x.py") == "thomas/agriculture/x.py"


def test_a_dotfile_the_sync_ships_is_still_promotable() -> None:
    assert ".gitignore" in doppelganger._INCLUDE_FILES
    assert doppelganger._is_promotable_scope(".gitignore") is True
    # Control: scope decisions for ordinary paths are unchanged.
    assert doppelganger._is_promotable_scope("thomas/agriculture/x.py") is True
    assert doppelganger._is_promotable_scope("etc/passwd") is False
