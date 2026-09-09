"""Tests for the in-flow PR review model (CAP-149 Level 2).

Hermetic and deterministic: no network, no wall clock, no temp files. Every
assertion proves an exact acceptance-line mechanic against fixed diff text.
"""

from __future__ import annotations

import pytest

from thomas.tools.pr_review import (
    ApprovalBlockedError,
    DiffParseError,
    FixTask,
    PrReview,
    PrReviewError,
    RiskWeights,
    UnknownCommentError,
    UnknownHunkError,
    compute_risk,
)

# ---------------------------------------------------------------------------
# Fixtures: fixed diffs
# ---------------------------------------------------------------------------

# A multi-file diff: a trivial README tweak, a security-sensitive auth change,
# and a test-file change. Each is one hunk.
MULTI_DIFF = """\
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
-hello
+hello world
 second line
diff --git a/app/auth/login.py b/app/auth/login.py
--- a/app/auth/login.py
+++ b/app/auth/login.py
@@ -10,3 +10,4 @@ def login(user):
     validate(user)
+    token = issue_session_token(user)
     return ok
diff --git a/tests/test_flow.py b/tests/test_flow.py
--- a/tests/test_flow.py
+++ b/tests/test_flow.py
@@ -1,3 +1,4 @@
 import pytest
+def test_new_case():
     assert True
"""

TRIVIAL_VS_SECURITY = """\
diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1 +1,2 @@
 note
+one more line
diff --git a/core/secret_store.py b/core/secret_store.py
--- a/core/secret_store.py
+++ b/core/secret_store.py
@@ -5,4 +5,6 @@ class Store:
-    old_secret = None
-    legacy_password = None
+    self.api_key = load_api_key()
+    self.password = decrypt(pw)
+    self.token = mint()
     return self
"""


def _by_file(review: PrReview, path: str):
    for hunk in review.ranked_hunks:
        if hunk.file_path == path:
            return hunk
    raise AssertionError(f"no hunk for {path}")


# ---------------------------------------------------------------------------
# 1. Ingest -> split into hunks, each with a risk score
# ---------------------------------------------------------------------------


def test_diff_splits_into_hunks_each_with_a_risk_score() -> None:
    review = PrReview(MULTI_DIFF)
    hunks = review.ranked_hunks
    assert len(hunks) == 3
    files = {h.file_path for h in hunks}
    assert files == {"README.md", "app/auth/login.py", "tests/test_flow.py"}
    # Every hunk carries an integer score and a band.
    for hunk in hunks:
        assert isinstance(hunk.risk_score, int)
        assert hunk.risk_band in {"low", "medium", "high"}
        assert hunk.header.startswith("@@")


def test_hunk_line_counts_are_parsed() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    assert auth.added == 1
    assert auth.removed == 0
    assert auth.old_start == 10
    assert auth.new_start == 10


def test_empty_diff_raises() -> None:
    with pytest.raises(DiffParseError):
        PrReview("not a diff, no hunks here\n")


# ---------------------------------------------------------------------------
# 2. Risk ranking: highest-first; security/test-touching outranks trivial
# ---------------------------------------------------------------------------


def test_hunks_ordered_highest_risk_first() -> None:
    review = PrReview(MULTI_DIFF)
    scores = [h.risk_score for h in review.ranked_hunks]
    assert scores == sorted(scores, reverse=True)


def test_security_hunk_outranks_trivial_hunk() -> None:
    review = PrReview(TRIVIAL_VS_SECURITY)
    ordered = review.ranked_hunks
    # The security file must come first, ahead of the trivial docs tweak.
    assert ordered[0].file_path == "core/secret_store.py"
    assert ordered[0].is_high_risk
    trivial = _by_file(review, "docs/notes.md")
    secure = _by_file(review, "core/secret_store.py")
    assert secure.risk_score > trivial.risk_score
    assert secure.signals.touches_security is True
    assert trivial.signals.touches_security is False


def test_security_and_test_hunks_outrank_trivial() -> None:
    review = PrReview(MULTI_DIFF)
    readme = _by_file(review, "README.md")
    auth = _by_file(review, "app/auth/login.py")
    tests = _by_file(review, "tests/test_flow.py")
    assert auth.signals.touches_security is True
    assert tests.signals.touches_tests is True
    assert auth.risk_score > readme.risk_score
    assert tests.risk_score > readme.risk_score
    # Ranking puts both non-trivial hunks ahead of the trivial README hunk.
    order = [h.file_path for h in review.ranked_hunks]
    assert order.index("README.md") == len(order) - 1


def test_deletion_ratio_signal_contributes() -> None:
    review = PrReview(TRIVIAL_VS_SECURITY)
    secure = _by_file(review, "core/secret_store.py")
    assert secure.removed == 2
    assert secure.added == 3
    assert 0.0 < secure.signals.deletion_ratio < 1.0


def test_compute_risk_is_pure_and_monotone_in_size() -> None:
    from thomas.tools.pr_review import RiskSignals

    weights = RiskWeights()
    small = RiskSignals(2, 1, 1, False, False, 0.5)
    big = RiskSignals(20, 10, 10, False, False, 0.5)
    assert compute_risk(big, weights) >= compute_risk(small, weights)
    # Security bonus dominates a trivial change.
    sec = RiskSignals(1, 1, 0, False, True, 0.0)
    assert compute_risk(sec, weights) >= weights.high_threshold


# ---------------------------------------------------------------------------
# 3. Threaded comments: add / reply / resolve
# ---------------------------------------------------------------------------


def test_comments_thread_and_resolve() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    root = review.add_comment(auth.hunk_id, "alice", "is this token scoped?")
    reply = review.reply(root.comment_id, "bob", "yes, per-session")
    assert reply.parent_id == root.comment_id
    assert reply.hunk_id == auth.hunk_id

    thread = review.thread(root.comment_id)
    assert [c.comment_id for c in thread] == [root.comment_id, reply.comment_id]
    assert all(not c.resolved for c in thread)

    resolved = review.resolve_comment(reply.comment_id)
    assert {c.comment_id for c in resolved} == {root.comment_id, reply.comment_id}
    assert all(c.resolved for c in review.thread(root.comment_id))


def test_comments_for_hunk_and_unknown_ids() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    review.add_comment(auth.hunk_id, "alice", "note")
    assert len(review.comments_for(auth.hunk_id)) == 1

    with pytest.raises(UnknownHunkError):
        review.add_comment("h999", "alice", "x")
    with pytest.raises(UnknownCommentError):
        review.reply("c999", "bob", "y")


# ---------------------------------------------------------------------------
# 4. Approval gate
# ---------------------------------------------------------------------------


def test_approval_blocked_by_unresolved_blocking_high_risk_comment() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    assert auth.is_high_risk

    review.add_comment(auth.hunk_id, "alice", "must scope this token", blocking=True)
    assert review.can_approve() is False
    assert review.blocking_reasons()
    with pytest.raises(ApprovalBlockedError):
        review.approve("carol")
    assert review.approved is False


def test_approval_permitted_once_blocking_comment_resolved() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    blocker = review.add_comment(auth.hunk_id, "alice", "scope it", blocking=True)
    assert review.can_approve() is False

    review.resolve_comment(blocker.comment_id)
    assert review.can_approve() is True
    review.approve("carol")
    assert review.approved is True
    assert review.approved_by == "carol"


def test_non_blocking_comment_does_not_gate_approval() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    review.add_comment(auth.hunk_id, "alice", "nit: naming", blocking=False)
    assert review.can_approve() is True
    review.approve("carol")
    assert review.approved is True


def test_blocking_comment_on_low_risk_hunk_does_not_gate() -> None:
    review = PrReview(MULTI_DIFF)
    readme = _by_file(review, "README.md")
    assert not readme.is_high_risk
    review.add_comment(readme.hunk_id, "alice", "typo", blocking=True)
    # Blocking, but the hunk is not high-risk -> approval still allowed.
    assert review.can_approve() is True


# ---------------------------------------------------------------------------
# 5. Fix handoff
# ---------------------------------------------------------------------------


def test_fix_handoff_emits_structured_task_bound_to_hunk() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    comment = review.add_comment(auth.hunk_id, "alice", "scope the session token to the user", blocking=True)
    task = review.create_fix_task(comment.comment_id)
    assert isinstance(task, FixTask)
    assert task.hunk_id == auth.hunk_id
    assert task.file_path == "app/auth/login.py"
    assert task.hunk_header == auth.header
    assert task.instruction == "scope the session token to the user"
    assert task.comment_id == comment.comment_id
    assert task.risk_band == auth.risk_band
    assert task.blocking is True
    # Serializable for the route/UI layer.
    d = task.as_dict()
    assert d["hunk_id"] == auth.hunk_id
    assert d["file_path"] == "app/auth/login.py"


def test_fix_handoff_accepts_instruction_override_and_rejects_resolved() -> None:
    review = PrReview(MULTI_DIFF)
    auth = _by_file(review, "app/auth/login.py")
    comment = review.add_comment(auth.hunk_id, "alice", "raw note")
    task = review.create_fix_task(comment.comment_id, instruction="Do X precisely")
    assert task.instruction == "Do X precisely"

    review.resolve_comment(comment.comment_id)
    with pytest.raises(PrReviewError):
        review.create_fix_task(comment.comment_id)


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


def test_ingest_is_deterministic() -> None:
    a = PrReview(MULTI_DIFF)
    b = PrReview(MULTI_DIFF)
    assert [h.hunk_id for h in a.ranked_hunks] == [h.hunk_id for h in b.ranked_hunks]
    assert [h.risk_score for h in a.ranked_hunks] == [h.risk_score for h in b.ranked_hunks]
    assert [h.file_path for h in a.ranked_hunks] == [h.file_path for h in b.ranked_hunks]


def test_full_flow_snapshot_is_deterministic() -> None:
    def run() -> dict:
        review = PrReview(MULTI_DIFF)
        auth = _by_file(review, "app/auth/login.py")
        c = review.add_comment(auth.hunk_id, "alice", "scope token", blocking=True)
        review.reply(c.comment_id, "bob", "ok")
        review.create_fix_task(c.comment_id)
        review.resolve_comment(c.comment_id)
        review.approve("carol")
        return review.snapshot()

    assert run() == run()


def test_snapshot_shape() -> None:
    review = PrReview(MULTI_DIFF)
    snap = review.snapshot()
    assert set(snap) == {
        "approved",
        "approved_by",
        "can_approve",
        "blocking_reasons",
        "hunks",
        "comments",
        "fix_tasks",
    }
    assert len(snap["hunks"]) == 3
