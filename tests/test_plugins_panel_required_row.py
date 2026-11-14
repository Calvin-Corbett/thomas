"""A required row on the Plugins panel: shown on and locked, a press does nothing, and a failed one can only try again.

Run for real: the panel's own script under node, against a server each test scripts.
"""

from __future__ import annotations

from tests.plugins_panel_scenes import run


def test_a_required_row_reads_on_and_locked_and_a_press_does_nothing() -> None:
    run(
        """
        const page = await open([row({ required: true })]);
        const shown = page.row('Companion apps');
        assert.strictEqual(shown.label(), 'On');
        assert.ok(shown.toggle.isShown());
        assert.strictEqual(shown.toggle.getAttribute('aria-disabled'), 'true');
        assert.ok(shown.text().includes('Always on. Thomas needs this to work.'));
        shown.toggle.click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), []);
        assert.strictEqual(shown.label(), 'On');
        """
    )


def test_a_screen_reader_hears_an_on_switch_that_is_disabled() -> None:
    run(
        """
        const page = await open([row({ required: true })]);
        const { toggle } = page.row('Companion apps');
        assert.strictEqual(toggle.getAttribute('role'), 'switch');
        assert.strictEqual(toggle.getAttribute('aria-checked'), 'true');
        assert.strictEqual(toggle.getAttribute('aria-disabled'), 'true');
        """
    )


def test_an_optional_row_beside_it_is_not_locked() -> None:
    run(
        """
        const page = await open([row({ required: true }), row({ id: 'other', title: 'Other apps' })]);
        const other = page.row('Other apps');
        assert.strictEqual(other.toggle.getAttribute('aria-disabled'), 'false');
        assert.ok(!other.text().includes('Always on'));
        """
    )


def test_a_failed_required_row_offers_try_again_and_never_leave_it_off() -> None:
    run(
        """
        const page = await open([row({ ...FAILED, required: true })]);
        const shown = page.row('Companion apps');
        assert.strictEqual(shown.label(), "Didn't start");
        assert.ok(shown.shown('Try again'));
        assert.ok(!shown.shown('Leave it off'));
        page.pressAnswers.push(row({ required: true }));
        shown.button('Try again').click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/on']);
        assert.strictEqual(shown.label(), 'On');
        """
    )


def test_stop_now_never_shows_for_a_required_row() -> None:
    run(
        """
        const [page, shown] = await stoppingPage({ required: true, enabled: true });
        await page.tick(60000);
        assert.ok(!shown.shown('Stop now'));
        """
    )
