"""The Plugins panel keeps asking while you can see it, so what it says stays true when nothing is pressed.

Run for real: the panel's own script under node, against a server each test scripts.
"""

from __future__ import annotations

from tests.plugins_panel_scenes import run


def test_it_reads_every_five_seconds_only_while_you_can_see_it() -> None:
    run(
        """
        const page = new Page();
        page.report.rows = [row()];
        await page.tick(20000);
        assert.strictEqual(page.reads(), 0, 'the panel is not in view yet');
        await page.show();
        assert.strictEqual(page.reads(), 1);
        await page.tick(4999);
        assert.strictEqual(page.reads(), 1);
        await page.tick(1);
        assert.strictEqual(page.reads(), 2);
        await page.tick(15000);
        assert.strictEqual(page.reads(), 5);
        await page.show(false);
        await page.tick(20000);
        assert.strictEqual(page.reads(), 5, 'another section is on screen');
        await page.show();
        assert.strictEqual(page.reads(), 6, 'it reads once as it comes back');
        page.document.hidden = true;
        page.listeners.visibilitychange();
        await page.tick(20000);
        assert.strictEqual(page.reads(), 6, 'the tab is hidden');
        page.document.hidden = false;
        page.listeners.visibilitychange();
        await page.settle();
        assert.strictEqual(page.reads(), 7);
        await page.tick(5000);
        assert.strictEqual(page.reads(), 8, 'and it carries on');
        """
    )


def test_from_another_device_it_still_asks_only_once() -> None:
    run(
        """
        const page = new Page();
        page.report.rows = [row()];
        page.getAnswer = 403;
        await page.show();
        await page.tick(20000);
        assert.strictEqual(page.reads(), 1);
        """
    )


def test_an_idle_page_finds_out_by_itself_that_thomas_went_away_and_came_back() -> None:
    run(
        """
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        assert.match(page.text(), /^Everything is on\\./);
        page.getAnswer = 'down';
        await page.tick(5000);
        assert.match(page.text(), /Thomas isn't answering\\. It may be restarting\\. This page will catch up by itself\\./);
        assert.doesNotMatch(page.text(), /Everything is on/);
        assert.strictEqual(shown.label(), 'No answer');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        assert.deepStrictEqual(page.presses(), [], 'nobody pressed anything');
        page.getAnswer = null;
        await page.tick(2000);
        assert.doesNotMatch(page.text(), /isn't answering/);
        assert.match(page.text(), /^Everything is on\\./);
        assert.strictEqual(shown.label(), 'On');
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'false');
        """
    )


def test_a_row_that_failed_during_a_restart_stops_reading_on() -> None:
    run(
        """
        const slow = await open([row()]);
        slow.getAnswer = 'down';
        await slow.tick(5000);
        slow.getAnswer = null;
        slow.report.rows = [row(FAILED)];
        await slow.tick(2000);
        assert.strictEqual(slow.row('Companion apps').label(), "Didn't start");

        const quick = await open([row()]);
        quick.report.rows = [row(FAILED)];
        await quick.tick(5000);
        assert.strictEqual(quick.row('Companion apps').label(), "Didn't start", 'too quick for a read to have failed');
        assert.match(quick.text(), /^One needs a look\\./);
        """
    )


def test_a_read_that_only_waits_never_says_thomas_isnt_answering() -> None:
    """Six open connections are all a browser gives one server, so a read can wait with Thomas perfectly well.

    Measured in real Chromium with a held off press and five streams: the read never left the browser, and it stayed
    queued for as long as those connections were held. Waiting longer would not have helped.
    """
    run(
        """
        const page = await open([row()]);
        const shown = page.row('Companion apps');
        page.getAnswer = 'silent';
        await page.tick(5000 + 9999);
        assert.match(page.text(), /^Everything is on\\./, 'it has not waited long enough to doubt anything');
        await page.tick(1);
        assert.doesNotMatch(page.text(), /isn't answering/);
        assert.match(page.text(), /Thomas is taking a while to answer\\. It may be busy, or too many Thomas tabs may be open\\./);
        assert.match(page.text(), /This page will catch up by itself\\./);
        assert.doesNotMatch(page.text(), /Everything is on/, 'it cannot know that now');
        assert.strictEqual(shown.label(), 'Checking...');
        assert.ok(page.host.byClass('plugins-panel').classList.contains('is-stale'));
        assert.ok(shown.toggle.classList.contains('is-unknown') && !shown.toggle.classList.contains('on'));
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        shown.toggle.click();
        assert.deepStrictEqual(page.presses(), [], 'a locked switch sends nothing');
        page.getAnswer = null;
        await page.tick(2000);
        assert.doesNotMatch(page.text(), /taking a while/);
        assert.strictEqual(shown.label(), 'On');
        assert.ok(!page.host.byClass('plugins-panel').classList.contains('is-stale'));
        """
    )


def test_a_refused_read_is_what_says_thomas_isnt_answering() -> None:
    """Every connection dies with the server, so a read that waited behind them is refused and the page finds out."""
    run(
        """
        const page = await open([row()]);
        page.getAnswer = 'silent';
        await page.tick(5000 + 10000);
        assert.match(page.text(), /taking a while/);
        page.getAnswer = 'down';
        await page.tick(2000);
        assert.match(page.text(), /Thomas isn't answering/);
        assert.doesNotMatch(page.text(), /taking a while/);
        assert.strictEqual(page.row('Companion apps').label(), 'No answer');
        """
    )


def test_a_failed_row_offers_nothing_to_press_while_a_read_waits() -> None:
    run(
        """
        const page = await open([row(FAILED)]);
        page.getAnswer = 'silent';
        await page.tick(5000 + 10000);
        assert.ok(!page.row('Companion apps').shown('Try again'));
        """
    )
