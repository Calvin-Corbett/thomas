"""The one import every Express test starts from.

    from tests.express_support import ExpressLab, build_fixture

``ExpressLab(tmp_path)`` gives a scratch layout, a deterministic git repository on ``dev``, an injected clock, and
the fake grant transport, presence and ACL lister. ``build_fixture(name, lab)`` builds one named trick for real in
that lab and returns a ``LabCase`` recording what it built. It raises ``KeyError`` for a name nobody registered,
``EnvironmentUnavailable`` when this machine cannot have the trick, and ``FixtureBroken`` when it can and the
fixture failed. Importing this module registers every fixture.

"The plan" in these modules is the Express lane plan (``EXPRESS-LANE-PLAN.md``): its work-package table has entries
such as "A1" (this lab), "B1" (eligibility) and "B2" (the verifying writer). The plan is not part of this
repository. The pieces: ``express_fakes`` (clock, pipe, presence), ``express_acl`` (ACL lister), ``express_repo``
(layout and git), ``express_winfs`` (Windows primitives), ``express_lab`` (the lab and registry),
``express_lab_paths`` / ``express_lab_patches`` / ``express_lab_inbox`` (the fixtures) and ``express_pytest``
(the ``lab`` fixture and skip or strict handling).
"""

from __future__ import annotations

from tests import express_lab_inbox, express_lab_patches, express_lab_paths  # noqa: F401  (registers the fixtures)
from tests.express_acl import Ace, FakeAclLister  # noqa: F401
from tests.express_fakes import FakeClock, FakeGrantTransport, FakePresence, PipeRefused  # noqa: F401
from tests.express_lab import FIXTURES, ExpressLab, LabCase, build_fixture, fixture_names  # noqa: F401
from tests.express_lab_inbox import write_hand_in  # noqa: F401
from tests.express_repo import ExpressLayout, TempGitRepo, TreeEntry, resolved_git  # noqa: F401
from tests.express_winfs import IS_WINDOWS, EnvironmentUnavailable, FixtureBroken, is_reparse_point  # noqa: F401

# Plan row 6: every path-identity trick a landing must end refused with the tree unchanged (the plan's own list).
PATH_IDENTITY_FIXTURES = (
    "junction_after_check",
    "short_name_alias",
    "case_variant",
    "alternate_stream",
    "trailing_dot",
    "dot_git_variant",
    "symlink_to_outside",
    "gitlink",
    "mode_change",
    "rename",
    "binary_blob",
    "pyc_file",
    "nul_byte_path",
    "non_canonical_spelling",
)
