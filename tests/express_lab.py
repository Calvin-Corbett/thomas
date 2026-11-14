"""The Express test lab: the assembled fakes, the repository, and the plain record a fixture hands back.

``ExpressLab`` is what an Express test builds first: a scratch layout, a deterministic git repository on ``dev``
with a base commit, an injected clock, and the fake grant transport, presence and ACL lister. A lab fixture is a
function that builds one trick inside a lab and returns a ``LabCase`` describing what it built. A ``LabCase`` holds
data only: it says what was created and what was measured, never what a referee or writer ought to do with it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tests.express_acl import FakeAclLister
from tests.express_fakes import FakeClock, FakeGrantTransport, FakePresence
from tests.express_repo import BASE_FILES, EOL_RULES, ExpressLayout, TempGitRepo
from tests.express_winfs import create_symlink, is_reparse_point, require_windows


@dataclass
class LabCase:
    """One built trick. ``facts`` holds what the fixture measured about it, so a self-test can check the claim.

    ``claimed`` are the path spellings a hand-in would name, ``patches`` one hand-in patch per spelling or per
    variant, ``inbox_entry`` the hand-in folder or file for an inbox trick, and ``protected`` the folders a test
    should compare before and after. ``arm``, when set, changes the world on disk once and is the trick itself (a
    folder turned into a junction); the code under test decides when to call it.
    """

    name: str
    kind: str  # path | patch | inbox | poison | forged | control
    trick: str
    windows_only: bool
    workdir: Path
    claimed: tuple[str, ...] = ()
    protected: tuple[Path, ...] = ()
    patches: tuple[bytes, ...] = ()
    facts: dict[str, object] = field(default_factory=dict)
    arm: Callable[[], None] | None = None
    inbox_entry: Path | None = None


class ExpressLab:
    """Layout, repository, clock and fakes for one test. ``crlf=True`` adds line-ending rules and autocrlf."""

    def __init__(
        self,
        root: Path,
        files: Mapping[str, bytes | str] | None = None,
        clock: FakeClock | None = None,
        *,
        crlf: bool = False,
    ) -> None:
        self.clock = clock or FakeClock()
        self.layout = ExpressLayout(root).build()
        self.repo = TempGitRepo(self.layout.repo, self.clock, self.layout.hooks)
        self.transport = FakeGrantTransport()
        self.presence = FakePresence(self.clock)
        self.acl = FakeAclLister()
        self.symlink = create_symlink  # a test may swap in a creator that works without the privilege
        self.outside = root / "outside"
        self.outside.mkdir(parents=True, exist_ok=True)
        self._closers: list[tuple[Callable[[], None], Path | None]] = []
        base = dict(BASE_FILES if files is None else files)
        if crlf:
            self.repo.autocrlf = True
            base[".gitattributes"] = EOL_RULES
        self.base_sha = self.repo.commit_files(base, "base")

    def on_close(self, closer: Callable[[], None], gone: Path | None = None) -> None:
        """Register an undo. ``gone`` is a path that must no longer be a reparse point once the undo has run."""
        self._closers.append((closer, gone))

    def close(self) -> None:
        """Undo every junction and link first, so cleanup of the scratch root can never walk through one.

        Every undo runs even if an earlier one fails; afterwards each registered path is checked, and anything
        that went wrong is raised together, so a leftover junction is never silent.
        """
        problems: list[str] = []
        done: list[Path] = []
        while self._closers:
            closer, gone = self._closers.pop()
            try:
                closer()
            except OSError as exc:
                problems.append(f"undo failed: {exc}")
            if gone is not None:
                done.append(gone)
        problems += [f"{p} is still a reparse point" for p in done if is_reparse_point(p)]
        if problems:
            raise RuntimeError("; ".join(problems))


FixtureBuilder = Callable[[ExpressLab], LabCase]
FIXTURES: dict[str, tuple[str, bool, FixtureBuilder]] = {}


def lab_fixture(name: str, kind: str, *, windows_only: bool = False) -> Callable[[FixtureBuilder], FixtureBuilder]:
    """Register a builder under ``name``. A Windows-only builder refuses to run elsewhere, with the reason."""

    def register(build: FixtureBuilder) -> FixtureBuilder:
        def guarded(lab: ExpressLab) -> LabCase:
            if windows_only:
                require_windows(f"the {name} trick")
            return build(lab)

        if name in FIXTURES:
            raise ValueError(f"lab fixture {name} is registered twice")
        FIXTURES[name] = (kind, windows_only, guarded)
        return build

    return register


def build_fixture(name: str, lab: ExpressLab) -> LabCase:
    """Build the named trick in ``lab``.

    An unknown name raises ``KeyError`` (a typo is a test error, never a skip). ``EnvironmentUnavailable`` means
    this machine cannot have the trick; ``FixtureBroken`` means it can and the fixture failed.
    """
    if name not in FIXTURES:
        raise KeyError(f"no lab fixture is named {name}")
    return FIXTURES[name][2](lab)


def fixture_names(kind: str | None = None) -> list[str]:
    return [n for n, (k, _w, _b) in FIXTURES.items() if kind is None or k == kind]
