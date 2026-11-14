"""A press that did not work says so, says it only while that is true, and is never taken for one that did.

Run for real: the panel's own script under node, against a server each test scripts.
"""

from __future__ import annotations

from tests.plugins_panel_scenes import run

NOT_SAVED = r"Thomas couldn't save that\. Try again\."


def test_a_try_again_that_never_arrived_says_so_and_never_says_still() -> None:
    run(
        f"""
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push('down');
        shown.button('Try again').click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/on']);
        assert.match(page.text(), /{NOT_SAVED}/);
        assert.match(shown.text(), /Companion apps didn't start\\. The rest of Thomas is working normally\\./);
        assert.doesNotMatch(shown.text(), /still/);
        assert.ok(shown.shown('Try again'));
        """
    )


def test_a_try_again_answered_with_an_error_never_says_still() -> None:
    run(
        f"""
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(500);
        shown.button('Try again').click();
        await page.settle();
        assert.match(page.text(), /{NOT_SAVED}/);
        assert.doesNotMatch(shown.text(), /still/);
        """
    )


def test_a_try_again_refused_while_the_row_stops_never_says_still() -> None:
    """The server refused it, so no retry ran. Nothing failed either, so there is nothing to apologise for."""
    run(
        f"""
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(409);
        shown.button('Try again').click();
        await page.settle();
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        assert.doesNotMatch(shown.text(), /still/);
        """
    )


def test_a_try_again_whose_answer_dropped_is_not_lost_if_the_row_moved() -> None:
    run(
        f"""
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        page.report.rows = [row({{ state: 'loading' }})];
        page.pressAnswers.push('down');
        shown.button('Try again').click();
        await page.settle();
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        assert.strictEqual(shown.label(), 'Turning on...');
        """
    )


def test_a_try_again_seen_arriving_is_not_lost_when_its_answer_drops() -> None:
    """The row has gone back to failed by the time the page reads it, but it was seen moving on the way."""
    run(
        f"""
        const page = await open([row(FAILED)]);
        const shown = page.row('Companion apps');
        let drop;
        page.pressAnswers.push(new Promise((_resolve, reject) => {{ drop = reject; }}));
        shown.button('Try again').click();
        page.report.rows = [row({{ state: 'loading' }})];
        await page.tick(1000);
        page.report.rows = [row(FAILED)];
        drop(new TypeError('Failed to fetch'));
        await page.settle();
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        assert.strictEqual(shown.label(), "Didn't start");
        """
    )


def test_a_failed_save_stays_while_the_row_stands_as_it_did() -> None:
    run(
        f"""
        const page = await open([row()]);
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        for (let poll = 0; poll < 3; poll += 1) {{
          await page.tick(5000);
          assert.match(page.text(), /{NOT_SAVED}/);
        }}
        """
    )


def test_a_failed_save_that_changed_the_row_on_its_way_stays_too() -> None:
    """An off whose save fails leaves the row running with off in memory, so the read after it looks like a change."""
    run(
        f"""
        const page = await open([row()]);
        page.report.rows = [row({{ enabled: false }})];
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        await page.tick(5000);
        assert.match(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_failed_save_stays_while_the_row_finishes_starting() -> None:
    """The first read can find the row on its way, and its arrival changes nothing: the save is still missing."""
    run(
        f"""
        const page = await open([row({{ state: 'off', enabled: false }})]);
        page.report.rows = [row({{ state: 'loading' }})];
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        await page.tick(5000);
        assert.match(page.text(), /{NOT_SAVED}/);
        page.report.rows = [row()];
        await page.tick(5000);
        assert.strictEqual(page.row('Companion apps').label(), 'On');
        assert.match(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_failed_save_goes_when_you_leave_the_section() -> None:
    run(
        f"""
        const page = await open([row()]);
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        await page.show(false);
        await page.show();
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_failed_save_goes_when_the_row_changes_in_another_tab() -> None:
    run(
        f"""
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push(500);
        shown.toggle.click();
        await page.settle();
        await page.tick(5000);
        page.report.rows = [row({{ state: 'off', enabled: false }})];
        await page.tick(5000);
        assert.strictEqual(shown.label(), 'Off');
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_press_that_never_landed_goes_the_same_way() -> None:
    run(
        f"""
        const page = await open([row()]);
        page.pressAnswers.push('down');
        page.row('Companion apps').toggle.click();
        await page.settle();
        assert.match(page.text(), /{NOT_SAVED}/);
        page.report.rows = [row({{ state: 'off', enabled: false }})];
        await page.tick(5000);
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_failed_save_goes_with_its_row() -> None:
    run(
        f"""
        const second = {{ id: 'b', title: 'Second' }};
        const page = await open([row(), row(second)]);
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        page.report.rows = [row(second)];
        await page.tick(5000);
        assert.doesNotMatch(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_failed_save_stays_when_another_row_changes() -> None:
    run(
        f"""
        const second = {{ id: 'b', title: 'Second' }};
        const page = await open([row(), row(second)]);
        page.pressAnswers.push(500);
        page.row('Companion apps').toggle.click();
        await page.settle();
        await page.tick(5000);
        page.report.rows = [row(), row({{ ...second, state: 'off', enabled: false }})];
        await page.tick(5000);
        assert.match(page.text(), /{NOT_SAVED}/);
        """
    )


def test_a_press_made_while_thomas_is_away_says_so_when_it_is_back() -> None:
    run(
        f"""
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        page.pressAnswers.push('down');
        page.getAnswer = 'down';
        shown.toggle.click();
        await page.settle();
        assert.strictEqual(shown.label(), 'No answer');
        page.getAnswer = null;
        await page.tick(2000);
        assert.match(page.text(), /{NOT_SAVED}/);
        assert.strictEqual(shown.label(), 'On');
        """
    )
