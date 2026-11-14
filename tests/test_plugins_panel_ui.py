"""The Plugins panel in Settings, run for real: its own script under node, against a server each test scripts.

tests/plugins_panel_harness.js is a page and a clock and decides nothing, so these read what a person would read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tests import plugin_view_fixture as views
from tests import runtime_plugin_fixture as fixture
from tests.plugin_page_fixture import FAILS_STARTING, ROUTES
from tests.plugin_view_fixture import runtime_with
from tests.plugins_panel_scenes import ROOT, run
from thomas.server.runtime_plugins import PROFILE_PATH, read_profile

CSS = ROOT / "thomas" / "server" / "web" / "css"
RAW = re.compile(r"\b(row|fork|kernel|mount|seam|hook|profile|entry|unloading|pending|disposed|loopback|force)\b", re.I)


def test_every_state_reads_in_plain_words_and_nothing_raw_reaches_the_page() -> None:
    table = [
        ({"state": "active"}, "On", True),
        ({"state": "off", "enabled": False}, "Off", False),
        ({"state": "disposed", "enabled": False}, "Off", False),
        ({"state": "pending"}, "Waiting", True),
        ({"state": "loading"}, "Turning on...", True),
        ({"state": "unloading", "enabled": False}, "Turning off...", False),
        ({"state": "something-new", "enabled": False}, "Off", False),
    ]
    run(
        f"""
        for (const [fields, label, on] of {json.dumps(table)}) {{
          const page = await open([row({{ id: 'raw-id', ...fields }})]);
          const shown = page.row('Companion apps');
          assert.strictEqual(shown.label(), label, fields.state);
          assert.strictEqual(shown.toggle.getAttribute('aria-checked'), String(on), fields.state);
          assert.strictEqual(shown.toggle.classList.contains('on'), on, fields.state);
          assert.doesNotMatch(page.text(), /raw-id|{RAW.pattern}/i, fields.state);
        }}
        """
    )


def test_pending_says_what_it_is_waiting_for() -> None:
    run(
        """
        const page = await open([row({ state: 'pending' })]);
        assert.match(page.row('Companion apps').text(), /Waiting for another part of Thomas to come on\\./);
        """
    )


def test_a_row_with_no_words_is_a_part_of_thomas_and_a_new_row_needs_no_script() -> None:
    run(
        """
        const wordless = { id: 'raw-id', title: '', about: '', off_means: '', stop_now: '' };
        const page = await open([row(wordless), row({ id: 'next', title: 'Something new', about: 'Does a new thing.' })]);
        assert.match(page.row('A part of Thomas').text(), /^A part of Thomas On$/);
        assert.doesNotMatch(page.text(), /raw-id/);
        assert.match(page.row('Something new').text(), /Does a new thing\\./);
        """
    )


def test_what_stops_while_it_is_off_is_always_on_the_row() -> None:
    run(
        """
        for (const fields of [{}, STOPPING, FAILED, { state: 'off', enabled: false }]) {
          const page = await open([row(fields)]);
          assert.match(page.row('Companion apps').text(), /While this is off, those apps stop working\\./);
        }
        """
    )


def test_the_summary_line_says_how_things_stand() -> None:
    run(
        """
        const off = { state: 'off', enabled: false };
        const second = { id: 'b', title: 'Second' };
        const cases = [
          [[row(), row(second)], 'Everything is on.'],
          [[row(off), row({ ...second, ...off })], 'Everything is off.'],
          [[row(off), row(second)], 'One is off. Everything else is on.'],
          [[row(FAILED), row(second)], 'One needs a look.'],
          [[row(FAILED), row({ ...second, ...FAILED })], 'Two need a look.'],
          [[row(STOPPING), row(second)], 'Working on it.'],
          [[row({ state: 'pending' }), row(second)], 'One is waiting.'],
        ];
        for (const [rows, summary] of cases) {
          assert.strictEqual((await open(rows)).host.byClass('plugins-summary').textContent, summary);
        }
        """
    )


def test_a_switch_is_a_switch_to_a_screen_reader() -> None:
    run(
        """
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        const named = (id) => shown.node.all((node) => node.id === id)[0].textContent;
        assert.strictEqual(shown.toggle.tag, 'button');
        assert.strictEqual(shown.toggle.type, 'button');
        assert.strictEqual(shown.toggle.getAttribute('role'), 'switch');
        assert.strictEqual(named(shown.toggle.getAttribute('aria-labelledby')), 'Companion apps');
        const told = shown.toggle.getAttribute('aria-describedby').split(' ').map(named).join(' ');
        assert.strictEqual(told, 'On Runs the apps. While this is off, those apps stop working.');
        """
    )


def test_a_status_line_speaks_a_change_once_and_never_on_a_poll() -> None:
    run(
        """
        const page = await open([row({ state: 'loading' })]);
        const status = page.host.byClass('sr-only');
        assert.strictEqual(status.getAttribute('aria-live'), 'polite');
        assert.deepStrictEqual(page.spoken, []);
        await page.tick(5000);
        assert.deepStrictEqual(page.spoken, []);
        page.report.rows = [row()];
        await page.tick(1000);
        assert.deepStrictEqual(page.spoken, ['Companion apps: On.']);
        await page.tick(5000);
        assert.deepStrictEqual(page.spoken, ['Companion apps: On.']);
        """
    )


def test_it_reads_when_the_panel_comes_into_view_and_faster_while_something_moves() -> None:
    run(
        """
        const page = new Page();
        page.report.rows = [row()];
        await page.tick(5000);
        assert.strictEqual(page.reads(), 0, 'the panel is not in view yet');
        await page.show();
        assert.strictEqual(page.reads(), 1);
        page.report.rows = [row({ state: 'loading' })];
        await page.show(false);
        await page.show();
        assert.strictEqual(page.reads(), 2, 'it reads once each time it comes back');
        await page.tick(3000);
        assert.strictEqual(page.reads(), 5, 'once a second while something is starting');
        await page.show(false);
        await page.tick(10000);
        assert.strictEqual(page.reads(), 5, 'a hidden panel asks for nothing');
        page.report.rows = [row()];
        await page.show();
        await page.tick(10000);
        assert.strictEqual(page.reads(), 8, 'back to every five seconds once nothing is moving');
        """
    )


def test_a_hidden_tab_stops_asking_too() -> None:
    run(
        """
        const page = await open([row({ state: 'loading' })]);
        page.document.hidden = true;
        page.listeners.visibilitychange();
        const before = page.reads();
        await page.tick(5000);
        assert.strictEqual(page.reads(), before);
        page.document.hidden = false;
        page.listeners.visibilitychange();
        await page.settle();
        assert.strictEqual(page.reads(), before + 1);
        """
    )


def test_notes_use_the_pages_own_sentences_never_the_raw_text() -> None:
    run(
        """
        const page = new Page();
        page.report = {
          rows: [row()],
          notes: ['could not be read: Traceback C:/secret/choices.json', 'other raw words'],
          note_codes: ['choices_unreadable', 'a_new_code'],
        };
        await page.show();
        assert.match(page.text(), /Your saved plugin choices couldn't be read, so everything is back to its default\\./);
        assert.match(page.text(), /Your old choices are kept\\. Changing any switch saves a fresh copy\\./);
        assert.match(page.text(), /Thomas noticed a problem with its plugin list\\./);
        assert.doesNotMatch(page.text(), /Traceback|secret|raw words/);

        const empty = new Page();
        empty.report = { rows: [], notes: ['raw'], note_codes: ['list_unreadable'] };
        await empty.show();
        assert.match(empty.text(), /^Thomas couldn't read its list of plugins, so none of them started\\. The rest of Thomas is working\\./);
        """
    )


def test_it_opens_on_plugins_from_the_deep_link_and_not_otherwise() -> None:
    run(
        """
        assert.deepStrictEqual(new Page({ search: '?embed=1&section=plugins' }).sections, ['plugins']);
        assert.deepStrictEqual(new Page({ search: '?embed=1' }).sections, []);
        """
    )


def test_a_browser_without_the_watcher_still_reads_once() -> None:
    run(
        """
        const page = new Page({ watches: false });
        await page.settle();
        assert.strictEqual(page.reads(), 1);
        assert.match(page.text(), /^Marketplace is where to find new things\\.$/);
        """
    )


def test_the_stylesheet_uses_only_tokens_both_themes_define() -> None:
    sheet = (CSS / "settings_plugins.css").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", sheet, flags=re.S)
    assert re.search(r"#[0-9a-f]{3,8}\b(?!\s*\{)|\brgba?\(|\bhsla?\(", code.replace("#plugins", ""), re.I) is None
    tokens = (CSS / "tokens.css").read_text(encoding="utf-8")
    colours = {name for name in re.findall(r"var\((--[\w-]+)\)", code) if name.startswith("--c-")}
    assert {"--c-text", "--c-dim", "--c-border"} <= colours  # an empty compare would pass
    for theme in ("dark", "light"):
        block = tokens.split(f'html[data-thomas-theme="{theme}"], html[data-theme="{theme}"] {{', 1)[1].split("}", 1)[0]
        for name in colours | {"--c-success", "--c-warn", "--c-danger"}:  # the shared status pill reads these three
            assert f"{name}:" in block, (theme, name)
    assert "prefers-reduced-motion" in code
    assert "#plugins [hidden]" in code  # button.btn sets display, which would otherwise beat the attribute


@pytest.fixture
def real_report(tmp_path: Path) -> dict[str, Any]:
    """What a running server reports for one row of each kind, words included."""
    views.reset()
    fixture.failures_left = 1
    runtime = runtime_with(tmp_path, [("good", ROUTES, True), ("spare", ROUTES, False), ("bad", FAILS_STARTING, True)])
    profile = tmp_path / "profile.toml"
    words = 'title = "Failing part"\nabout = "It fails."\noff_means = "Nothing stops."\nstop_now = ""\n'
    profile.write_text(profile.read_text(encoding="utf-8") + words, encoding="utf-8")
    runtime.load()
    runtime.mark_ready()
    return runtime.report()


def test_the_panel_reads_what_a_real_server_reports(real_report: dict[str, Any]) -> None:
    run(
        f"""
        const page = new Page();
        page.report = {json.dumps(real_report)};
        await page.show();
        assert.strictEqual(page.host.byClass('plugin-rows').children.length, 3);
        assert.strictEqual(page.row('Failing part').label(), "Didn't start");
        assert.match(page.row('Failing part').text(), /The reason recorded was: RuntimeError: the port is taken/);
        assert.deepStrictEqual(page.host.all((node) => node.classList.contains('plugin-name')).slice(0, 2).map((node) => node.textContent), ['A part of Thomas', 'A part of Thomas']);
        """
    )


def test_the_shipped_rows_all_have_the_words_the_panel_reads() -> None:
    rows = [{"id": entry.id, **entry.config["words"]} for entry in read_profile(PROFILE_PATH).entries]
    assert rows  # an empty compare would pass
    run(
        f"""
        const shipped = {json.dumps(rows)};
        const page = await open(shipped.map((words) => row(words)));
        for (const words of shipped) {{
          const text = page.row(words.title).text();
          assert.ok(text.includes(words.about) && text.includes(words.off_means), words.title);
        }}
        """
    )


def test_turning_off_is_not_waited_on_and_the_polled_state_is_the_truth() -> None:
    run(
        """
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        shown.toggle.click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/off']);
        assert.strictEqual(shown.label(), 'Turning off...');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        assert.doesNotMatch(shown.text(), /saved as off/, 'nothing has said it was saved yet');
        shown.toggle.click();
        assert.strictEqual(page.presses().length, 1, 'a locked switch sends nothing');
        await page.tick(1000);
        assert.strictEqual(shown.label(), 'Turning off...', 'the press has not reached the server yet');
        for (const [waiting_for, words] of [[2, /Finishing 2 jobs first\\./], [1, /Finishing 1 job first\\./], [0, /Almost done\\./]]) {
          page.report.rows = [row({ ...STOPPING, waiting_for })];
          await page.tick(1000);
          assert.match(shown.text(), words);
          assert.match(shown.text(), /This is saved as off, so it stays off even if Thomas restarts\\./);
        }
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(1000);
        assert.strictEqual(shown.label(), 'Off');
        assert.strictEqual(shown.toggle.getAttribute('aria-checked'), 'false');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'false');
        const reads = page.reads();
        await page.tick(5000);
        assert.strictEqual(page.reads(), reads + 1, 'the press still held open does not keep it polling fast');
        """
    )


def test_a_good_answer_does_not_mean_it_started() -> None:
    run(
        """
        const page = await open([row({ state: 'off', enabled: false })]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(row(FAILED));
        shown.toggle.click();
        assert.strictEqual(shown.label(), 'Turning on...');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/on']);
        assert.strictEqual(shown.label(), "Didn't start");
        assert.ok(!shown.toggle.isShown(), 'a row that failed has no switch to lie with');
        """
    )


def test_a_row_still_turning_on_can_be_taken_back() -> None:
    run(
        """
        const page = await open([row({ state: 'loading' })]);
        const shown = page.row('Companion apps');
        assert.strictEqual(shown.label(), 'Turning on...');
        shown.toggle.click();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/off']);
        """
    )


def test_an_answer_that_left_before_a_press_is_not_believed() -> None:
    run(
        """
        const off = { state: 'off', enabled: false };
        const page = await open([row(off)]);
        const shown = page.row('Companion apps');
        let release;
        page.getAnswer = new Promise((resolve) => { release = resolve; });
        await page.show(false);
        await page.show();
        page.pressAnswers.push(row());
        shown.toggle.click();
        await page.settle();
        assert.strictEqual(shown.label(), 'On');
        page.getAnswer = null;
        page.report.rows = [row()];
        release({ rows: [row(off)] });
        await page.settle();
        assert.strictEqual(shown.label(), 'On');
        """
    )


def test_a_switch_shows_what_is_true_and_a_press_moves_it_from_there() -> None:
    """Saved and running can differ, as after a save that failed. The switch shows running, and presses from there."""
    run(
        """
        for (const [fields, shows, press] of [[{ state: 'off', enabled: true }, 'false', 'on'], [{ state: 'active', enabled: false }, 'true', 'off']]) {
          const page = await open([row(fields)]);
          const shown = page.row('Companion apps');
          assert.strictEqual(shown.toggle.getAttribute('aria-checked'), shows);
          shown.toggle.click();
          assert.deepStrictEqual(page.presses(), [`POST /api/plugins/thomas/companion/${press}`]);
        }
        """
    )


def test_stop_now_comes_after_a_wait_with_its_cost_beside_it() -> None:
    run(
        """
        const [page, shown] = await stoppingPage();
        await page.tick(2000);
        assert.ok(!shown.shown('Stop now'), 'a quick stop must not flash the button');
        await page.tick(1000);
        assert.ok(shown.shown('Stop now'));
        assert.match(shown.text(), /Stop now Anything those apps are waiting on will fail\\./);
        const cost = shown.node.byClass('plugin-stop-cost');
        assert.strictEqual(shown.button('Stop now').getAttribute('aria-describedby'), cost.id);
        assert.deepStrictEqual(page.presses(), [], 'nothing is pressed for you');
        """
    )


def test_a_quick_stop_never_shows_stop_now() -> None:
    run(
        """
        const [page, shown] = await stoppingPage();
        await page.tick(2000);
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(5000);
        assert.ok(!shown.shown('Stop now'));
        assert.strictEqual(shown.label(), 'Off');
        """
    )


def test_a_row_with_no_cost_to_print_never_shows_stop_now() -> None:
    run(
        """
        const [page, shown] = await stoppingPage({ title: 'Version pile-up check', stop_now: '', waiting_for: 0 });
        await page.tick(10000);
        assert.ok(!shown.shown('Stop now'));
        assert.match(shown.text(), /Almost done\\./);
        """
    )


def test_a_stop_stuck_with_no_jobs_left_can_still_be_ended() -> None:
    """waiting_for is 0 while a stop step hangs, and Stop now ends that, so the row keeps the button."""
    run(
        """
        const [page, shown] = await stoppingPage({ waiting_for: 0 });
        await page.tick(3000);
        assert.ok(shown.shown('Stop now'));
        """
    )


def test_a_wordless_row_with_work_held_still_shows_a_cost_before_stop_now() -> None:
    run(
        """
        const [page, shown] = await stoppingPage({ title: 'Older server row', stop_now: '' });
        await page.tick(3000);
        assert.match(shown.text(), /Stop now Anything it is still doing will be cut off, and may need doing again\\./);
        """
    )


def test_only_stop_now_sends_force_and_the_row_says_what_it_cost() -> None:
    run(
        """
        const [page, shown] = await stoppingPage();
        await page.tick(3000);
        shown.button('Stop now').click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/off?force=1']);
        assert.ok(shown.shown('Stopping now...'));
        shown.button('Stopping now...').click();
        assert.strictEqual(page.presses().length, 1);
        page.report.rows = [row({ state: 'off', enabled: false, stopped_partway: true })];
        await page.tick(1000);
        assert.match(shown.text(), /Off\\. What it was doing was stopped partway\\./);
        assert.ok(!shown.shown('Stop now') && !shown.shown('Stopping now...'));
        page.pressAnswers.push(row());
        shown.toggle.click();
        await page.settle();
        assert.doesNotMatch(shown.text(), /stopped partway/);
        """
    )


def test_stopped_partway_is_said_only_when_the_server_says_so() -> None:
    """Stop now can land just after the work finished by itself, and only the server knows that it did."""
    run(
        """
        const [page, shown] = await stoppingPage();
        await page.tick(3000);
        page.report.rows = [row({ state: 'off', enabled: false, stopped_partway: false })];
        shown.button('Stop now').click();
        await page.tick(1000);
        assert.strictEqual(shown.label(), 'Off');
        assert.doesNotMatch(shown.text(), /partway/);
        await page.tick(5000);
        assert.doesNotMatch(shown.text(), /partway/);

        const elsewhere = await open([row({ state: 'off', enabled: false, stopped_partway: true })]);
        assert.match(elsewhere.row('Companion apps').text(), /stopped partway/, 'it was pressed in another tab');

        const running = await open([row({ stopped_partway: true })]);
        assert.doesNotMatch(running.row('Companion apps').text(), /partway/, 'it is back on');
        """
    )


def test_a_stop_that_outlasts_stop_now_says_so_and_promises_nothing_more() -> None:
    run(
        """
        const held = await stoppingPage();
        await held[0].tick(3000);
        held[1].button('Stop now').click();
        await held[0].tick(3000);
        assert.match(held[1].text(), /This is taking longer than it should\\. It stays off when Thomas next restarts\\./);

        const answered = await stoppingPage();
        await answered[0].tick(3000);
        answered[0].pressAnswers.push(row({ ...STOPPING, waiting_for: 1 }));
        answered[1].button('Stop now').click();
        await answered[0].settle();
        assert.match(answered[1].text(), /This is taking longer than it should\\./);
        """
    )


def test_a_row_starting_afresh_does_not_read_as_turning_off() -> None:
    """Try again on a row that failed after loading waits for its old work first, with on saved."""
    run(
        """
        const [page, shown] = await stoppingPage({ enabled: true });
        assert.strictEqual(shown.label(), 'Restarting...');
        assert.doesNotMatch(shown.text(), /saved as off/);
        await page.tick(3000);
        shown.button('Stop now').click();
        await page.tick(3000);
        assert.match(shown.text(), /taking longer than it should\\./);
        assert.doesNotMatch(shown.text(), /stays off/);
        """
    )


def test_a_poll_never_takes_focus_off_stop_now() -> None:
    run(
        """
        const [page, shown] = await stoppingPage({ waiting_for: 6 });
        await page.tick(3000);
        const stop = shown.button('Stop now');
        stop.focus();
        for (const waiting_for of [5, 4, 3, 2]) {
          page.report.rows = [row({ ...STOPPING, waiting_for })];
          await page.tick(1000);
          assert.strictEqual(page.document.activeElement, stop);
          assert.strictEqual(page.row('Companion apps').node, shown.node, 'rows change in place');
        }
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(1000);
        assert.strictEqual(page.document.activeElement, shown.toggle, 'focus is not lost when the button goes');
        """
    )


def test_focus_an_outage_moved_goes_back_with_its_control() -> None:
    """A read hides what has focus with nothing pressed. Left to the first control, Enter could start what you left off."""
    run(
        """
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        const leave = shown.button('Leave it off');
        leave.focus();
        page.getAnswer = 'down';
        await page.tick(5000);
        assert.strictEqual(shown.label(), 'No answer');
        assert.strictEqual(page.document.activeElement, shown.toggle, 'focus is not lost when the button goes');
        page.getAnswer = null;
        await page.tick(5000);
        assert.strictEqual(shown.label(), "Didn't start");
        assert.strictEqual(page.document.activeElement, leave);
        """
    )


def test_focus_an_outage_moved_stays_put_if_its_control_has_not_come_back() -> None:
    run(
        """
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        shown.button('Leave it off').focus();
        page.getAnswer = 'down';
        await page.tick(5000);
        page.getAnswer = null;
        page.report.rows = [row()];
        await page.tick(5000);
        assert.strictEqual(shown.label(), 'On');
        assert.strictEqual(page.document.activeElement, shown.toggle);
        """
    )


def test_stop_now_coming_back_later_does_not_pull_focus_off_the_switch() -> None:
    """Focus left Stop now because the stop ended, not an outage, so a stop much later has no claim on it."""
    run(
        """
        const [page, shown] = await stoppingPage({ waiting_for: 6 });
        await page.tick(3000);
        shown.button('Stop now').focus();
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(5000);
        assert.strictEqual(page.document.activeElement, shown.toggle);
        page.report.rows = [row({ ...STOPPING, waiting_for: 6 })];
        await page.tick(5000);
        await page.tick(5000);
        assert.ok(shown.shown('Stop now'));
        assert.strictEqual(page.document.activeElement, shown.toggle);
        """
    )


def test_a_failed_row_says_why_and_offers_three_ways_on() -> None:
    run(
        """
        const page = await open([row({ ...FAILED, error: '<img src=x onerror=alert(1)>' })]);
        const shown = page.row('Companion apps');
        assert.strictEqual(shown.label(), "Didn't start");
        assert.match(shown.text(), /Companion apps didn't start\\. The rest of Thomas is working normally\\./);
        assert.ok(shown.text().includes('The reason recorded was: <img src=x onerror=alert(1)>'), 'shown as text');
        assert.ok(!shown.toggle.isShown());
        for (const words of ['Try again', 'Leave it off', 'Ask Thomas why']) assert.ok(shown.shown(words), words);
        """
    )


def test_try_again_presses_on_and_a_second_failure_says_still() -> None:
    run(
        """
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(row(FAILED), row());
        const again = shown.button('Try again');
        again.focus();
        again.click();
        assert.strictEqual(shown.label(), 'Turning on...');
        assert.strictEqual(page.document.activeElement, shown.toggle, 'focus stays on the row');
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/on']);
        assert.match(shown.text(), /It still didn't start\\. The rest of Thomas is working normally\\./);
        assert.ok(shown.toggle.hidden, 'the switch has gone again');
        again.click();
        await page.settle();
        assert.strictEqual(shown.label(), 'On');
        assert.ok(shown.toggle.isShown());
        """
    )


def test_leave_it_off_is_a_plain_off_press() -> None:
    run(
        """
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(row({ state: 'off', enabled: false }));
        shown.button('Leave it off').click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/off']);
        assert.strictEqual(shown.label(), 'Off');
        assert.ok(shown.toggle.isShown() && !shown.shown('Try again'));
        """
    )


def test_ask_thomas_why_fills_a_draft_you_can_read_and_sends_nothing() -> None:
    run(
        """
        const page = await open([row({ id: 'raw-id', ...FAILED })]);
        page.row('Companion apps').button('Ask Thomas why').click();
        assert.deepStrictEqual(page.presses(), []);
        assert.deepStrictEqual(JSON.parse(JSON.stringify(page.posted)), [[{
          type: 'thomas:workspace-chat:open',
          mode: 'settings',
          draft: "Companion apps didn't start. The reason recorded was: RuntimeError: the port is taken. What does that mean, and what should I do?",
        }, 'http://thomas.test']]);
        const alone = await open([row(FAILED)], { embedded: false });
        assert.ok(!alone.row('Companion apps').shown('Ask Thomas why'), 'on its own, Settings has no chat drawer');
        assert.ok(alone.row('Companion apps').shown('Try again'));
        """
    )


def test_when_thomas_stops_answering_the_switches_stop_claiming_anything() -> None:
    run(
        """
        const page = await open([row(), row({ id: 'b', title: 'Second', ...FAILED })]);
        const shown = page.row('Companion apps');
        page.getAnswer = 'down';
        await page.show(false);
        await page.show();
        assert.match(page.text(), /Thomas isn't answering\\. It may be restarting\\. This page will catch up by itself\\./);
        assert.strictEqual(page.host.byClass('plugins-summary').hidden, true);
        assert.ok(page.host.byClass('plugins-panel').classList.contains('is-stale'));
        assert.strictEqual(shown.label(), 'No answer');
        assert.ok(shown.toggle.classList.contains('is-unknown') && !shown.toggle.classList.contains('on'));
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        shown.toggle.click();
        assert.deepStrictEqual(page.presses(), [], 'a locked switch sends nothing');
        assert.ok(!page.row('Second').shown('Try again'), 'and a stale failure offers nothing to press');
        page.getAnswer = null;
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(2000);
        assert.doesNotMatch(page.text(), /isn't answering/);
        assert.strictEqual(shown.label(), 'Off');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'false');
        assert.ok(!page.host.byClass('plugins-panel').classList.contains('is-stale'));
        """
    )


def test_a_server_that_errors_reads_as_not_answering() -> None:
    run(
        """
        const errors = new Page();
        errors.getAnswer = 500;
        await errors.show();
        assert.match(errors.text(), /isn't answering/);
        """
    )


def test_from_another_device_it_says_so_and_stops_asking() -> None:
    run(
        """
        const page = new Page();
        page.report.rows = [row()];
        page.getAnswer = 403;
        await page.show();
        assert.match(page.text(), /You can change these only on the computer Thomas runs on\\./);
        assert.doesNotMatch(page.text(), /Companion apps|403/);
        await page.tick(10000);
        assert.strictEqual(page.reads(), 1);
        """
    )


def test_a_save_that_fails_says_so_and_the_switch_stays_true() -> None:
    run(
        """
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(500);
        shown.toggle.click();
        await page.settle();
        assert.match(page.text(), /Thomas couldn't save that\\. Try again\\./);
        assert.doesNotMatch(page.text(), /500/);
        assert.strictEqual(shown.label(), 'On');
        page.pressAnswers.push(row({ state: 'off', enabled: false }));
        shown.toggle.click();
        await page.settle();
        assert.doesNotMatch(page.text(), /couldn't save/);
        """
    )


def test_on_refused_while_stopping_is_not_a_failure() -> None:
    run(
        """
        const page = await open([row({ state: 'off', enabled: false })]);
        const shown = page.row('Companion apps');
        page.report.rows = [row(STOPPING)];
        page.pressAnswers.push(409);
        shown.toggle.click();
        await page.settle();
        assert.doesNotMatch(page.text(), /couldn't save/);
        assert.strictEqual(shown.label(), 'Turning off...');
        """
    )


def test_a_dropped_press_is_only_a_failure_if_it_never_landed() -> None:
    run(
        """
        const landed = await open([row()]);
        landed.report.rows = [row({ ...STOPPING, waiting_for: 1 })];
        landed.pressAnswers.push('down');
        landed.row('Companion apps').toggle.click();
        await landed.settle();
        assert.doesNotMatch(landed.text(), /couldn't save/);
        assert.match(landed.text(), /Finishing 1 job first\\./);

        const lost = await open([row()]);
        lost.pressAnswers.push('down');
        lost.row('Companion apps').toggle.click();
        await lost.settle();
        assert.match(lost.text(), /Thomas couldn't save that\\. Try again\\./);
        assert.strictEqual(lost.row('Companion apps').label(), 'On');
        """
    )
