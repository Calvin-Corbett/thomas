"""The webhooks row, off: its twelve routes answer 404, a server started that way never loads them, and nothing is kept.

The word webhook names several things in Thomas, and this row serves one: the messages other services send in, with the
list of who may send them. The receivers answer to a signature, the nine routes that manage them to your token and then
to a webhook admin token of their own. What Thomas sends out is separate: alert webhooks in
``thomas/server/routes/mission_workflows.py``, the Asset Studio's in ``thomas/server/routes/asset_studio_aiohttp.py``, and
the outgoing channels under ``thomas/channels/``. ``thomas/marketplace/webhooks/`` is a third thing, which nothing calls.

The row's words claim receiving and recording, and tests here hold them to that: on the real store a correctly signed
delivery is recorded as failed and answers 500, because ``PersistenceEngine`` has no way to take the goal it asks for, and
every management route answers 503 until ``THOMAS_WEBHOOK_ADMIN_TOKEN`` is set.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, choose
from thomas.core.persistence import PersistenceEngine
from thomas.marketplace.security.mutating_route_policy import evaluate_mutating_route_policy_exceptions
from thomas.marketplace.security.security_audit import run_security_audit
from thomas.server.proof.selection import select
from thomas.server.routes import webhooks

# Written out, because a list worked out from the row would agree with whatever the row did.
GUARDED = {
    "POST /api/webhooks/register": "POST /api/webhooks/register",
    "GET /api/webhooks/stats/all": "GET /api/webhooks/stats/all",
    "GET /api/webhooks/inbox/recent": "GET /api/webhooks/inbox/recent",
    "POST /api/webhooks/inbox/retry/{event_id}": "POST /api/webhooks/inbox/retry/e1",
    "POST /api/webhooks/test/{id}": "POST /api/webhooks/test/w1",
    "PATCH /api/webhooks/{id}": "PATCH /api/webhooks/w1",
    "DELETE /api/webhooks/{id}": "DELETE /api/webhooks/w1",
    "GET /api/webhooks/{id}": "GET /api/webhooks/w1",
    "GET /api/webhooks": "GET /api/webhooks",
}
SIGNED = {
    "POST /webhooks/receive/github": "POST /webhooks/receive/github",
    "POST /webhooks/receive/stripe": "POST /webhooks/receive/stripe",
    "POST /webhooks/receive/{id}": "POST /webhooks/receive/w1",
}
ROUTES = {**GUARDED, **SIGNED}
OWN_CODE = (
    "thomas.server.rows.webhooks",
    "thomas.server.routes.webhooks_aiohttp",
    "thomas.server.routes.webhooks",
    "thomas.server.routes.webhooks_routes",
    "thomas.server.routes.webhooks_delivery",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {
    *ROUTES,
    "HEAD /api/webhooks/stats/all",
    "HEAD /api/webhooks/inbox/recent",
    "HEAD /api/webhooks/{id}",
    "HEAD /api/webhooks",
}
# A setting in the shell that runs these would change what every route below answers.
SETTINGS = (
    "THOMAS_WEBHOOK_ADMIN_TOKEN",
    "THOMAS_WEBHOOK_REQUIRE_SIGNATURES",
    "THOMAS_GITHUB_WEBHOOK_SECRET",
    "THOMAS_GITHUB_WEBHOOK_SECRETS",
    "THOMAS_STRIPE_WEBHOOK_SECRET",
    "THOMAS_STRIPE_WEBHOOK_SECRETS",
    "THOMAS_WEBHOOKS_FILE",
    "THOMAS_WEBHOOK_RECEIPTS_FILE",
    "THOMAS_WEBHOOK_STATS_FILE",
    "THOMAS_WEBHOOK_INBOX_FILE",
    "THOMAS_ENV",
    "ENV",
    "PYTHON_ENV",
)


def _start(helper: Callable[..., tuple[Any, Any]], folder: Path) -> dict[str, Any]:
    with pytest.MonkeyPatch.context() as patch:
        for name in SETTINGS:
            patch.delenv(name, raising=False)
        started, found = helper("webhooks", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("webhooks-off")
    found = _start(start_with_one_row_off, folder)
    assert found["home"] == str(folder / "home")
    inboxes = sorted(folder.rglob("thomas_webhook_inbox.jsonl"))
    assert len(inboxes) == 1, inboxes
    found["inbox"] = [json.loads(line) for line in inboxes[0].read_text(encoding="utf-8").splitlines()]
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    return _start(ask_as_a_remote_caller, tmp_path_factory.mktemp("webhooks-remote"))


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "webhooks"}
    assert seen["rows"]["webhooks"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_twelve_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        **dict.fromkeys(GUARDED.values(), 503),  # no webhook admin token is set
        "POST /api/webhooks/register": 400,  # an empty body is refused before the admin token is asked for
        "POST /webhooks/receive/github": 500,  # no GitHub secret is set
        "POST /webhooks/receive/stripe": 400,  # an empty body names no event
        "POST /webhooks/receive/w1": 404,  # the handler: w1 is not registered. seen["live_on"] shows the route is there
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    Whatever a route file holds at the top level survives off and on the same way: here the rate limits, and whether a
    receiver must refuse an unsigned delivery, which each turn on sets again.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_delivery_sent_while_it_is_off_is_refused_and_not_kept(seen: dict[str, Any]) -> None:
    """The row's words say so, and that what was already recorded stays.

    Each receiver was sent a delivery three times, off, on and off again, and only the one sent while on left a line,
    which is still in the inbox after the row went off.
    """
    assert seen["off"]["POST /webhooks/receive/stripe"] == seen["off_again"]["POST /webhooks/receive/stripe"] == 404
    assert [(row["provider"], row["status"]) for row in seen["inbox"]] == [("stripe", "failed")]


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    """Their sender signs them, so the receivers answer to a signature and not to the token. In remote mode a receiver
    with no secret set answers 503 rather than taking an unsigned delivery, and an id it does not know answers 404."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {
        **dict.fromkeys(GUARDED.values(), 401),
        "POST /webhooks/receive/github": 503,
        "POST /webhooks/receive/stripe": 503,
        "POST /webhooks/receive/w1": 404,
    }
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_no_page_calls_these_routes() -> None:
    """The row's words tell you no page changes and none shows the record. If a page ever calls these, this fails and those
    words have to change. The Webhooks tile on the Integrations panel counts health checks and is not one: nothing in the
    sidebar opens that panel, and its Create Webhook button has no handler of its own.

    A landing runs this only for a change to this row or its routes. A caller added anywhere else is found by the full
    suite.
    """
    wanted = ("api/webhooks", "webhooks/receive/")
    callers = [
        path
        for folder in ("thomas/server/web", "web", "desktop", "extensions")
        for path in (ROOT / folder).rglob("*")
        if path.suffix in {".js", ".ts", ".tsx", ".html", ".py"}
        and "node_modules" not in path.parts
        and any(word in path.read_text(encoding="utf-8", errors="replace") for word in wanted)
    ]
    assert callers == []
    assert (ROOT / "thomas" / "server" / "web" / "js" / "browser_shell.js").is_file()  # an empty walk would pass


def test_nothing_acts_on_a_delivery_on_the_real_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The row's words claim receiving and recording, and say Thomas does not act on them.

    ``FakePersistence`` in ``tests/test_webhooks.py`` has a ``create_goal`` the real engine lacks, so those tests cannot
    see this. If the real store ever takes a goal, this fails and those words have to change.
    """
    engine = PersistenceEngine(state_file=tmp_path / "state.json", report_dir=tmp_path / "reports", auto_save=False)
    monkeypatch.setattr(webhooks, "get_persistence", lambda: engine)

    with pytest.raises(HTTPException) as refused:
        webhooks._queue_goal("Review the push.", "webhook.github", {})

    assert refused.value.status_code == 500
    assert engine.goals == []


def test_the_security_audit_fails_while_the_row_is_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On the source code the words say so: these are the first routes that list has held that you can turn off.

    The audit builds a server from your saved choices, and ``docs/security/mutating_route_policy_exceptions.json`` tells it
    to expect the three receivers, so with the row saved off it reports all three missing, and with it back on it does not.
    This only ever runs on the source code, the one place that file is, so it says nothing about a release: the test after
    next does. If the audit learns that a row turned off is not a route gone missing, this fails and those words have to
    change.
    """
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    choose(data, on=[row.id for row in ROWS if row.id != "webhooks"])

    report = evaluate_mutating_route_policy_exceptions(ROOT)

    assert report["ok"] is False
    assert sorted(error["message"].split()[2] for error in report["errors"]) == [
        "/webhooks/receive/github",
        "/webhooks/receive/stripe",
        "/webhooks/receive/{id}",
    ]
    assert {error["code"] for error in report["errors"]} == {"mutating_route_policy.exception_route_missing"}

    choose(data, on=[row.id for row in ROWS])
    back_on = evaluate_mutating_route_policy_exceptions(ROOT)

    assert "mutating_route_policy.exception_route_missing" not in {error["code"] for error in back_on["errors"]}


def test_the_words_limit_what_they_say_about_the_audit_to_the_source_code() -> None:
    """With no limit they are false on a release, where turning this back on ends nothing: the test below shows it."""
    words = next(row for row in ROWS if row.id == "webhooks").config["words"]["off_means"]

    about_the_audit = [sentence for sentence in words.split(". ") if "audit" in sentence]

    assert len(about_the_audit) == 1, words
    assert "on Thomas's source code" in about_the_audit[0]


def test_on_a_release_the_row_makes_no_difference_to_the_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A release leaves out the file that names the three receivers, so the audit cannot miss them there.

    It fails the same with the row on or off, and the folder audited decides that, whichever copy of Thomas runs it, so
    this audits a real bundle. If a release ever carries that file, this fails and those words have to change.
    """
    built = subprocess.run(
        [sys.executable, "scripts/package_release.py", "--out-dir", str(tmp_path / "out"), "--no-zip", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr[-1500:]
    bundle = Path(json.loads(built.stdout.splitlines()[-1])["output_dir"])
    assert not (bundle / "docs" / "security").exists()
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))

    def failing_with(on: list[str]) -> list[str]:
        choose(data, on=on)
        return run_security_audit(bundle)["summary"]["failing_checks"]

    with_it_on = failing_with([row.id for row in ROWS])
    with_it_off = failing_with([row.id for row in ROWS if row.id != "webhooks"])

    assert "mutating_route_policy" in with_it_on
    assert with_it_on == with_it_off


@pytest.mark.parametrize("changed", ["thomas/server/rows/webhooks.py", "thomas/server/routes/webhooks_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_webhooks_off_touches_only_its_routes.py" in chosen
    assert "tests/test_webhooks.py" in chosen
