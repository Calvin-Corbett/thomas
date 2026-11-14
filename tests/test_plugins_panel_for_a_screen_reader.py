"""What the Plugins panel tells a screen reader: everything it shows, once, and nothing the page cannot stand behind.

Run for real: the panel's own script under node, against a server each test scripts.
"""

from __future__ import annotations

import pytest

from tests.plugins_panel_scenes import run

# Two ways of having no answer: refused at once, and a read that waits its full ten seconds.
OUT_OF_TOUCH = [
    pytest.param("'down'", 5000, 2000, "Thomas isn't answering", id="refused"),
    pytest.param("'silent'", 15000, 2000, "Thomas is taking a while", id="waiting"),
]


@pytest.mark.parametrize(("answer", "until_out", "until_back", "words"), OUT_OF_TOUCH)
def test_the_way_back_is_announced_and_the_old_words_do_not_stay(
    answer: str, until_out: int, until_back: int, words: str
) -> None:
    run(
        f"""
        const page = await open([row()]);
        page.getAnswer = {answer};
        await page.tick({until_out});
        assert.match(page.status.textContent, /^{words}/);
        page.getAnswer = null;
        await page.tick({until_back});
        assert.strictEqual(page.status.textContent, 'Thomas is answering again.');
        const heard = page.spoken.length;
        await page.tick(20000);
        assert.strictEqual(page.spoken.length, heard, 'said once');
        """
    )


def test_what_changed_while_it_was_away_is_said_with_the_way_back() -> None:
    run(
        """
        const page = await open([row()]);
        page.getAnswer = 'down';
        await page.tick(5000);
        page.getAnswer = null;
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(2000);
        assert.strictEqual(page.status.textContent, 'Thomas is answering again. Companion apps: Off.');
        """
    )


@pytest.mark.parametrize(("answer", "until_out", "until_back", "words"), OUT_OF_TOUCH)
@pytest.mark.parametrize(("fields", "checked"), [("{}", "true"), ("{ state: 'off', enabled: false }", "false")])
def test_with_no_answer_a_row_is_not_exposed_as_on_or_off(
    fields: str, checked: str, answer: str, until_out: int, until_back: int, words: str
) -> None:
    """ARIA has no third position for a switch, so while nothing is known this is a locked button."""
    run(
        f"""
        const page = await open([row({fields})]);
        const {{ toggle }} = page.row('Companion apps');
        assert.strictEqual(toggle.getAttribute('role'), 'switch');
        assert.strictEqual(toggle.getAttribute('aria-checked'), '{checked}');
        page.getAnswer = {answer};
        await page.tick({until_out});
        assert.strictEqual(toggle.tag, 'button');
        assert.strictEqual(toggle.getAttribute('role'), null);
        assert.strictEqual(toggle.getAttribute('aria-checked'), null);
        assert.strictEqual(toggle.getAttribute('aria-disabled'), 'true');
        page.getAnswer = null;
        await page.tick({until_back});
        assert.strictEqual(toggle.getAttribute('role'), 'switch');
        assert.strictEqual(toggle.getAttribute('aria-checked'), '{checked}');
        assert.strictEqual(toggle.getAttribute('aria-disabled'), 'false');
        """
    )


def test_a_screen_reader_hears_a_stop_from_start_to_end() -> None:
    run(
        """
        const page = await open([row()]);
        page.row('Companion apps').toggle.click();
        await page.settle();
        page.report.rows = [row({ ...STOPPING, waiting_for: 2 })];
        await page.tick(1000);
        await page.tick(3000);
        await page.tick(5000);
        page.report.rows = [row({ ...STOPPING, waiting_for: 1 })];
        await page.tick(1000);
        page.report.rows = [row({ state: 'off', enabled: false })];
        await page.tick(1000);
        assert.deepStrictEqual(page.spoken, [
          'Companion apps: Turning off...',
          'Companion apps: Finishing 2 jobs first.',
          'Companion apps: Stop now is available. Anything those apps are waiting on will fail.',
          'Companion apps: Finishing 1 job first.',
          'Companion apps: Off.',
        ]);
        """
    )


def test_a_screen_reader_hears_why_a_row_failed_to_start_and_the_second_time() -> None:
    run(
        """
        const page = await open([row({ state: 'loading' })]);
        const shown = page.row('Companion apps');
        page.report.rows = [row(FAILED)];
        await page.tick(1000);
        assert.deepStrictEqual(page.spoken, [
          "Companion apps: Didn't start. Companion apps didn't start. The rest of Thomas is working normally.",
        ]);
        page.pressAnswers.push(row(FAILED));
        shown.button('Try again').click();
        await page.settle();
        assert.match(page.spoken.at(-1), /It still didn't start\\. The rest of Thomas is working normally\\.$/);
        """
    )


def test_stopped_partway_is_not_said_twice_over() -> None:
    run(
        """
        const [page] = await stoppingPage();
        page.report.rows = [row({ state: 'off', enabled: false, stopped_partway: true })];
        await page.tick(1000);
        assert.strictEqual(page.spoken.at(-1), 'Companion apps: Off. What it was doing was stopped partway.');
        """
    )


def test_every_button_on_a_row_is_named_for_its_row() -> None:
    run(
        """
        const second = { id: 'b', title: 'Second part' };
        const page = await open([row(FAILED), row({ ...second, ...FAILED })]);
        const nameOf = (control) => control.getAttribute('aria-labelledby').split(' ')
          .map((id) => page.host.all((node) => node.id === id)[0].textContent).join(' ');
        for (const words of ['Try again', 'Leave it off', 'Ask Thomas why']) {
          assert.strictEqual(nameOf(page.row('Companion apps').button(words)), `${words} Companion apps`);
          assert.strictEqual(nameOf(page.row('Second part').button(words)), `${words} Second part`);
        }

        const stopping = await open([row({ ...STOPPING, waiting_for: 1 })]);
        const shown = stopping.row('Companion apps');
        const stopName = (words) => shown.button(words).getAttribute('aria-labelledby').split(' ')
          .map((id) => stopping.host.all((node) => node.id === id)[0].textContent).join(' ');
        await stopping.tick(3000);
        assert.strictEqual(stopName('Stop now'), 'Stop now Companion apps');
        shown.button('Stop now').click();
        assert.strictEqual(stopName('Stopping now...'), 'Stopping now... Companion apps');
        """
    )


def test_a_note_that_has_gone_leaves_nothing_on_the_status_line() -> None:
    run(
        """
        const page = new Page();
        page.report = { rows: [row({ state: 'off', enabled: false })], notes: ['raw'], note_codes: ['choices_unreadable'] };
        await page.show();
        assert.match(page.text(), /Changing any switch saves a fresh copy\\./);
        assert.match(page.status.textContent, /Changing any switch saves a fresh copy\\./);
        page.report = { rows: [row({ state: 'off', enabled: false })], notes: [], note_codes: [] };
        await page.tick(5000);
        assert.doesNotMatch(page.text(), /fresh copy/);
        assert.strictEqual(page.status.textContent, '');
        """
    )
