"""The System page: seven plain pages about what Thomas is doing and how he is (2026-11-09).

You said the Agents page "looks like it was made in 2008" and showed "all these random agents": "just name it system
... a user can see their stuff and see how the progress of things are going and have multiple pages ... Don't make it
information crowded dense or a bunch of wordy stuff ... be able to turn to different pages about different things.
Different graphics and ways to display the information, interact with it, maybe change things while you're in there."

It is a page of its own at ``/system`` with its own sidebar entry. The old Agents page is gone, and its address
``/agents`` shows this page, so saved links still land somewhere. The page script is run here in node against made-up answers shaped like the routes
it asks, turned to each page in turn.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
PAGES = ["overview", "tasks", "pc", "plugins", "spend", "builds", "about"]
SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const HOSTILE = '<img src=x onerror=alert(1)>';
const answers = {
  '/api/health': { version: '0.0.0', build: { commit: 'abc12345', latest_commit: 'def67890', stale: true }, uptime_s: 7260,
    restart: { restarting: false }, model_auth: { ok: true } },
  '/api/agents/vitals': { cpu: [10, 40, 95], memory: [50, 52, 51], latest: { cpu: 95, memory: 51 } },
  '/api/machine/capacity': { cpus: 16, total_ram_bytes: 64 * 2 ** 30, max_concurrent_runs: 4, load: { limit_percent: 90 } },
  '/api/mission/control': { approvals: { pending_total: 1 }, agents: [
    { id: 'job:1', name: 'Nightly ' + HOSTILE, status: 'running', summary: 'Sorting mail', idle_s: 30 },
    { id: 'run:2', name: 'Stuck one', status: 'running', summary: '', stalled: true, idle_s: 1900 }] },
  '/api/plugins/thomas': { rows: [
    { id: 'agents', title: 'Agents page', about: 'Shows tasks.', state: 'active', required: false },
    { id: 'chat', title: 'Chat', about: 'Talks.', state: 'active', required: true },
    { id: 'voice', title: 'Voice', about: 'Speaks.', state: 'failed', error: 'no microphone ' + HOSTILE, required: false }] },
  '/api/spend/today': { total_usd: 1.5, call_count: 12, tokens: { total: 34000 }, by_model: { 'model-a': 1.25, 'model-b': { usd: 0.25 } } },
  '/api/self/projects': { projects: [
    { title: 'A build', state: 'landed', detail: 'Done.', updated_at: '2026-11-09T10:00:00', timings_seconds: { building: 600 } },
    { title: 'Another', state: 'repair round 2', detail: 'Fixing.', updated_at: '2026-11-09T11:00:00', timings_seconds: {} }] },
};
const sent = [];
const element = () => ({ innerHTML: '', textContent: '', dataset: {}, contains: () => false, querySelector: () => null });
const main = element(), tabs = element(), updated = element(), handlers = {};
global.window = { confirm: () => true };
global.location = { hash: '' };
global.history = { replaceState() {} };
global.setInterval = () => 0;
global.document = { hidden: false, activeElement: null, getElementById: id => ({ 'sy-page': main, 'sy-pages': tabs, 'sy-updated': updated }[id]),
  addEventListener: (type, handler) => { handlers[type] = handler; }, createElement: element };
global.fetch = async (url, options) => { if (options && options.method === 'POST') sent.push(url);
  const body = answers[url]; return { ok: body !== undefined, status: body === undefined ? 404 : 200, json: async () => (body === undefined ? {} : body) }; };
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const settle = () => new Promise(resolve => setTimeout(resolve, 20));
const press = attrs => handlers.click({ target: { closest: () => ({ dataset: attrs.dataset, disabled: false, getAttribute: name => attrs[name] }) } });
(async () => {
  await settle();
  const out = { nav: tabs.innerHTML, pages: {} };
  for (const id of JSON.parse(process.argv[2])) { press({ dataset: { go: id } }); await settle(); out.pages[id] = main.innerHTML; }
  press({ dataset: { go: 'plugins' } }); await settle();
  press({ dataset: { plugin: 'agents' }, 'aria-checked': 'true' }); await settle();
  press({ dataset: { go: 'tasks' } }); await settle();
  press({ dataset: { job: 'job:1', verb: 'cancel' } }); await settle();
  delete answers['/api/mission/control'];
  press({ dataset: { go: 'tasks' } }); await settle();
  out.sent = sent; out.unreadable = main.innerHTML;
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def drawn() -> dict:
    out = subprocess.run(
        ["node", "-e", SCRIPT, str(WEB / "js" / "system_page.js"), json.dumps(PAGES)],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=60,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_there_are_seven_pages_and_each_has_one_heading(drawn: dict) -> None:
    names = ["Overview", "Tasks", "This PC", "Plugins", "Spend", "Builds", "About"]
    assert [name for name in names if f">{name}" in drawn["nav"]] == names
    for page, name in zip(PAGES, names, strict=True):
        assert drawn["pages"][page].count("<h2>") == 1 and f"<h2>{name}</h2>" in drawn["pages"][page], page


def test_the_overview_counts_what_needs_you_and_points_to_where(drawn: dict) -> None:
    overview = drawn["pages"]["overview"]
    assert "3 things need you." in overview, "an approval, a stalled task and a plugin that failed"
    assert (
        "1 approval is waiting for you" in overview
        and "has stalled" in overview
        and "Voice failed to start" in overview
    )
    assert overview.count('data-go="tasks">Look</button>') == 2 and 'data-go="plugins">Look</button>' in overview
    assert "<b>95%</b><span>CPU in use</span>" in overview and "<b>2 of 3</b><span>plugins on</span>" in overview


def test_each_page_shows_its_readings_in_its_own_shape(drawn: dict) -> None:
    pages = drawn["pages"]
    assert pages["pc"].count('class="sy-ring"') == 2 and pages["pc"].count('class="sy-spark"') == 2, "rings and lines"
    assert "is-over" in pages["pc"], "at the limit, the ring says so by its weight, not a warning colour"
    assert "Thomas holds new work when CPU or memory reaches 90%." in pages["pc"] and "<b>64 GB</b>" in pages["pc"]
    assert pages["spend"].count('class="sy-bar"') == 2 and "<b>$1.50</b><span>today</span>" in pages["spend"], "bars"
    assert "<b>$1.25</b>" in pages["spend"] and "<b>$0.25</b>" in pages["spend"]
    assert (
        "<b>1</b><span>landed</span>" in pages["builds"]
        and "<b>10 min</b><span>average build</span>" in pages["builds"]
    )
    assert "<dt>Newest on disk</dt><dd>def67890 (newer than what is running)</dd>" in pages["about"]
    assert "<dt>Up for</dt><dd>2 h 1 min</dd>" in pages["about"]


def test_some_things_can_be_changed_where_you_read_them(drawn: dict) -> None:
    pages = drawn["pages"]
    assert 'role="switch" aria-checked="true" aria-label="Agents page" data-plugin="agents"' in pages["plugins"]
    assert 'data-plugin="chat" disabled' in pages["plugins"] and "always on" in pages["plugins"], (
        "a required one is locked"
    )
    assert 'data-job="job:1" data-verb="cancel">Stop</button>' in pages["tasks"]
    assert 'data-job="run:2"' not in pages["tasks"], "only a queued job can be stopped, retried or run from here"
    assert "data-restart" in pages["about"]
    assert drawn["sent"] == ["/api/plugins/thomas/agents/off", "/api/mission/jobs/job%3A1/cancel"]


def test_nothing_the_server_says_reaches_the_page_as_markup(drawn: dict) -> None:
    everything = json.dumps(drawn["pages"])
    assert "<img src=x" not in everything
    assert "&lt;img src=x onerror=alert(1)&gt;" in drawn["pages"]["tasks"]
    assert "no microphone &lt;img" in drawn["pages"]["plugins"]


def test_a_route_that_cannot_be_read_says_so_in_plain_words(drawn: dict) -> None:
    assert "The task list could not be read just now. Its plugin may be turned off." in drawn["unreadable"]


def test_it_has_its_own_address_and_sidebar_entry_and_the_old_page_is_gone() -> None:
    routes = (ROOT / "thomas" / "server" / "agents_routes.py").read_text("utf-8")
    assert 'app.router.add_get("/system", system_page)' in routes and '(web_dir / "system.html")' in routes
    assert 'app.router.add_get("/agents", system_page)' in routes, "the old address shows System"
    assert "agents.html" not in routes
    gone = ("agents.html", "js/agents_page.js", "js/agents_board.js", "js/agents_vitals.js", "css/agents.css")
    assert [name for name in gone if (WEB / name).exists()] == []
    nav = (WEB / "js" / "chat_workspace_navigation.js").read_text("utf-8")
    shell = (WEB / "js" / "browser_shell.js").read_text("utf-8")
    assert "label: 'System',          mode: 'system'" in nav and "system: '/system?embed=1'," in nav
    assert '"System": { mode: "system", icon: "mission" },' in shell and 'system: "/system?embed=1",' in shell
    assert "label: 'Agents'" not in nav and '"Agents": {' not in shell, "one entry, not two"


def test_the_page_is_plain() -> None:
    page = (WEB / "system.html").read_text("utf-8")
    assert "<title>System" in page and "/static/css/system_page.css" in page and "/static/js/system_page.js" in page
    css = (WEB / "css" / "system_page.css").read_text("utf-8")
    assert "border-left: 3px" not in css and "box-shadow" not in css.replace("box-shadow: 0 1px 3px", ""), (
        "no boxes inside boxes"
    )
    assert "prefers-reduced-motion: reduce" in css and ":focus-visible" in css
