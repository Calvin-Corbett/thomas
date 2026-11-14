"""The Pause control on the Plugins page, and that the page does not loop asking for it or for the sets, under node.

The page is ``thomas/server/web/settings.plugins-sets.js`` beside ``thomas/server/web/settings.plugins-panel.js``. The
routes it reads, ``GET /api/thomas/pause`` and ``POST /api/thomas/pause`` and ``/resume``, are built beside it, so every
answer here is a stand-in with the shape they will give. The sets are the ones ``thomas.server.rows.plugin_sets`` serves.
"""

from __future__ import annotations

from tests.plugins_panel_scenes import run
from tests.test_the_plugins_page_offers_ready_made_sets import SCENE


def test_pause_shows_when_the_route_answers_and_says_what_is_true() -> None:
    run(
        SCENE
        + """
        const working = await withSets(ROWS(), { paused: false, since: null, reason: '', still_running: 0 });
        assert.match(working.text(), /Thomas is working/);
        assert.strictEqual(shown(working, 'Pause'), 1);
        const paused = await withSets(ROWS(), { paused: true, since: 5, reason: '', still_running: 2 });
        assert.match(paused.text(), /Thomas is paused \\(2 runs still finishing\\)/);
        assert.strictEqual(shown(paused, 'Resume'), 1);
        const one = await withSets(ROWS(), { paused: true, since: 5, reason: '', still_running: 1 });
        assert.match(one.text(), /Thomas is paused \\(1 run still finishing\\)/);
        const done = await withSets(ROWS(), { paused: true, since: 5, reason: '', still_running: 0 });
        assert.match(done.text(), /Thomas is paused(?! \\()/);
        """
    )


def test_pause_and_resume_press_the_routes_and_show_the_answer() -> None:
    run(
        SCENE
        + """
        const page = await withSets(ROWS(), { paused: false, since: null, reason: '', still_running: 0 });
        page.stillRunning = 3;
        await press(page, 'Pause');
        assert.ok(page.others.includes('POST /api/thomas/pause'));
        assert.match(page.text(), /Thomas is paused \\(3 runs still finishing\\)/);
        await press(page, 'Resume');
        assert.ok(page.others.includes('POST /api/thomas/resume'));
        assert.match(page.text(), /Thomas is working/);
        """
    )


def test_pause_is_hidden_and_never_asked_for_again_when_the_route_is_missing() -> None:
    run(
        SCENE
        + """
        const page = await withSets(ROWS(), 404);
        assert.doesNotMatch(page.text(), /Thomas is (working|paused)|Pause|Resume/);
        await page.tick(60000);
        assert.deepStrictEqual(page.others.filter((call) => call === 'GET /api/thomas/pause'), ['GET /api/thomas/pause']);
        """
    )


def test_an_answer_that_is_not_a_pause_answer_hides_the_control_too() -> None:
    run(
        SCENE
        + """
        const page = await withSets(ROWS(), { rows: [] });
        assert.doesNotMatch(page.text(), /Thomas is (working|paused)/);
        """
    )


def test_the_page_does_not_loop_asking_for_sets_or_pause() -> None:
    run(
        SCENE
        + """
        for (const [sets, pause] of [[SETS, 404], [404, 404], [SETS, { paused: false, since: null, reason: '', still_running: 0 }], ['down', 'down']]) {
          const page = new Page();
          page.report.rows = ROWS();
          page.sets = sets;
          page.pauseAnswer = pause;
          await page.show();
          await page.tick(10000);
          const sent = page.others.filter((call) => call === 'GET /api/plugins/sets').length;
          const paused = page.others.filter((call) => call === 'GET /api/thomas/pause').length;
          assert.ok(sent <= 6, `sets asked ${sent} times in ten seconds`);
          assert.ok(paused <= 4, `pause asked ${paused} times in ten seconds`);
          assert.ok(page.reads() <= 4, `plugins read ${page.reads()} times in ten seconds`);
        }
        """
    )
