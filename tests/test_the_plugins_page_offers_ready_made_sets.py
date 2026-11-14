"""The Plugins page offers ready-made sets first and folds the long list away, run for real under node.

The page is ``thomas/server/web/settings.plugins-panel.js`` with ``thomas/server/web/settings.plugins-sets.js``, and the
server routes it calls are ``thomas.server.rows.plugin_sets_routes``, which the row ``thomas.server.rows.plugin_sets``
serves. The pause routes it reads are built beside it and are stood in for here. A real browser reads the same page in
``tests/test_the_plugins_page_in_a_browser_with_sets.py``.
"""

from __future__ import annotations

from tests.plugins_panel_scenes import ROOT, run

SCENE = """
const GROUPS = [
  { title: 'Chat and sessions', about: 'Talking to Thomas.', rows: ['chat'] },
  { title: 'Connections', about: 'Other programs.', rows: ['companion', 'other'] },
];
const SETS = {
  sets: [
    { id: 'everyday', title: 'Everyday', about: 'What you use most days.', rows: ['chat', 'companion', 'plugin_sets'] },
    { id: 'just_chat', title: 'Just chat', about: 'The smallest set.', rows: ['chat', 'plugin_sets'] },
    { id: 'everything', title: 'Everything', about: 'All on.', rows: ['chat', 'companion', 'other', 'plugin_sets'] },
  ],
  groups: GROUPS,
};
const ROWS = () => [
  row({ id: 'chat', title: 'Chat', required: true }),
  row({ id: 'companion', title: 'Companion apps' }),
  row({ id: 'other', title: 'Other thing' }),
  row({ id: 'plugin_sets', title: 'Ready-made plugin sets' }),
];
const withSets = async (rows = ROWS(), pause = 404) => {
  const page = new Page();
  page.report.rows = rows;
  page.sets = SETS;
  page.pauseAnswer = pause;
  await page.show();
  return page;
};
const press = async (page, words) => {
  const found = page.host.all((node) => node.tag === 'button' && node.textContent === words && node.isShown());
  assert.strictEqual(found.length, 1, `${words}: ${found.length} shown in ${page.text()}`);
  found[0].click();
  await page.settle();
};
const shown = (page, words) => page.host.all((node) => node.tag === 'button' && node.textContent === words && node.isShown()).length;
const ADVANCED = 'Advanced: choose each plugin yourself';
"""


def test_the_default_view_is_the_sets_and_shows_no_list_of_plugins() -> None:
    run(
        SCENE
        + """
        const page = await withSets();
        const text = page.text();
        assert.match(text, /Pick a ready-made set/);
        for (const name of ['Everyday', 'Just chat', 'Everything']) assert.match(text, new RegExp(name));
        assert.strictEqual(shown(page, 'Apply'), 3);
        assert.strictEqual(shown(page, ADVANCED), 1);
        assert.doesNotMatch(text, /Companion apps|Other thing|While this is off/);
        assert.doesNotMatch(text, /\\b(row|fork|kernel|mount|seam|hook|profile|entry|unloading|pending|disposed|loopback|force)\\b/i);
        """
    )


def test_advanced_opens_the_list_under_its_headings_and_closes_it_again() -> None:
    run(
        SCENE
        + """
        const page = await withSets();
        await press(page, ADVANCED);
        const text = page.text();
        assert.match(text, /Chat and sessions.*Talking to Thomas\\..*Chat/s);
        assert.match(text, /Connections.*Other programs\\..*Companion apps.*Other thing/s);
        assert.match(text, /Ready-made plugin sets/);
        assert.match(text, /Always on\\. Thomas needs this to work\\./);
        assert.strictEqual(page.row('Companion apps').toggle.getAttribute('aria-checked'), 'true');
        await press(page, ADVANCED);
        assert.doesNotMatch(page.text(), /Companion apps/);
        """
    )


def test_a_plugin_the_headings_do_not_name_is_still_listed() -> None:
    run(
        SCENE
        + """
        const page = await withSets([...ROWS(), row({ id: 'brand-new', title: 'Brand new thing' })]);
        await press(page, ADVANCED);
        assert.match(page.text(), /More.*Brand new thing/s);
        """
    )


def test_an_advanced_row_keeps_its_switch_its_failed_state_and_its_try_again() -> None:
    run(
        SCENE
        + """
        const page = await withSets([
          row({ id: 'chat', title: 'Chat', required: true }),
          row({ id: 'companion', title: 'Companion apps', state: 'failed', error: 'RuntimeError: the port is taken' }),
          row({ id: 'plugin_sets', title: 'Ready-made plugin sets' }),
        ]);
        await press(page, ADVANCED);
        const shownRow = page.row('Companion apps');
        assert.match(shownRow.text(), /Companion apps didn't start\\./);
        assert.ok(shownRow.shown('Try again'));
        page.pressAnswers.push(row({ id: 'companion', title: 'Companion apps' }));
        shownRow.button('Try again').click();
        await page.settle();
        assert.deepStrictEqual(page.presses(), ['POST /api/plugins/thomas/companion/on']);
        """
    )


def test_applying_a_set_asks_how_many_it_turns_on_and_off_and_changes_nothing_until_you_say_go() -> None:
    run(
        SCENE
        + """
        const page = await withSets([
          row({ id: 'chat', title: 'Chat', required: true }),
          row({ id: 'companion', title: 'Companion apps', enabled: false, state: 'off' }),
          row({ id: 'other', title: 'Other thing' }),
          row({ id: 'plugin_sets', title: 'Ready-made plugin sets' }),
        ]);
        const applyOf = (title) => page.host.all((node) => node.classList.contains('plugin-set-card'))
          .find((card) => card.byClass('plugin-set-title').textContent === title);
        applyOf('Everyday').all((node) => node.tag === 'button' && node.textContent === 'Apply')[0].click();
        await page.settle();
        assert.match(page.text(), /This turns on 1 plugin and turns off 1\\. Go\\?/);
        assert.deepStrictEqual(page.others.filter((call) => call.startsWith('POST')), []);
        await press(page, 'Cancel');
        assert.doesNotMatch(page.text(), /Go\\?/);
        assert.deepStrictEqual(page.others.filter((call) => call.startsWith('POST')), []);
        """
    )


def test_going_applies_the_set_shows_the_result_and_reads_the_plugins_again() -> None:
    run(
        SCENE
        + """
        const page = await withSets();
        const reads = page.reads();
        page.applied = {
          set: 'just_chat', title: 'Just chat', turned_on: [], turned_off: ['companion', 'other'],
          left_alone: [
            { id: 'chat', why: 'It is part of how Thomas works, so it cannot be turned off.' },
            { id: 'plugin_sets', why: 'This is the page you are using, so it stays on.' },
          ],
          failed: [],
        };
        page.report.rows = page.report.rows.map((item) => (
          ['companion', 'other'].includes(item.id) ? { ...item, enabled: false, state: 'off' } : item));
        const card = page.host.all((node) => node.classList.contains('plugin-set-card'))[1];
        card.all((node) => node.tag === 'button' && node.textContent === 'Apply')[0].click();
        await page.settle();
        assert.match(page.text(), /This turns on 0 plugins and turns off 2\\. Go\\?/);
        await press(page, 'Go');
        assert.ok(page.others.includes('POST /api/plugins/sets/just_chat/apply'), page.others.join());
        const text = page.text();
        assert.match(text, /Done\\. Turned on 0, turned off 2\\./);
        assert.match(text, /Left alone: Chat \\(It is part of how Thomas works, so it cannot be turned off\\.\\)/);
        assert.doesNotMatch(text, /This is the page you are using/);
        assert.ok(page.reads() > reads, 'the page read the plugins again');
        await press(page, ADVANCED);
        assert.strictEqual(page.row('Companion apps').toggle.getAttribute('aria-checked'), 'false');
        """
    )


def test_a_set_that_cannot_be_applied_says_so_in_plain_words() -> None:
    run(
        SCENE
        + """
        for (const [answer, words] of [
          [403, /only on the computer Thomas runs on/],
          [404, /isn't available any more/],
          [500, /Thomas couldn't do that\\. Try again\\./],
          ['down', /Thomas couldn't do that\\. Try again\\./],
        ]) {
          const page = await withSets();
          page.applied = answer;
          const card = page.host.all((node) => node.classList.contains('plugin-set-card'))[1];
          card.all((node) => node.tag === 'button' && node.textContent === 'Apply')[0].click();
          await page.settle();
          await press(page, 'Go');
          assert.match(page.text(), words, String(answer));
          assert.strictEqual(shown(page, 'Apply'), 3, 'it can be tried again');
        }
        """
    )


def test_with_the_sets_off_the_list_is_the_page_as_it_was_and_nothing_says_sets_are_missing() -> None:
    run(
        SCENE
        + """
        const page = new Page();
        page.report.rows = [row({ id: 'chat', title: 'Chat', required: true }), row()];
        await page.show();
        const text = page.text();
        assert.match(text, /Companion apps/);
        assert.strictEqual(shown(page, ADVANCED), 0);
        assert.doesNotMatch(text, /ready-made|Apply|Advanced/i);
        assert.deepStrictEqual(page.others.filter((call) => call.includes('sets')), []);
        """
    )


def test_turning_the_sets_plugin_off_from_the_list_brings_the_plain_list_back() -> None:
    run(
        SCENE
        + """
        const page = await withSets();
        assert.strictEqual(shown(page, 'Apply'), 3);
        page.report.rows = page.report.rows.map((item) => (
          item.id === 'plugin_sets' ? { ...item, enabled: false, state: 'off' } : item));
        await page.tick(5000);
        assert.strictEqual(shown(page, 'Apply'), 0);
        assert.strictEqual(shown(page, ADVANCED), 0);
        assert.match(page.text(), /Companion apps/);
        """
    )


def test_the_sets_script_loads_before_the_panel_that_asks_for_it() -> None:
    page = (ROOT / "thomas" / "server" / "web" / "settings.html").read_text(encoding="utf-8")
    assert page.index("/static/settings.plugins-sets.js") < page.index("/static/settings.plugins-panel.js")
    assert (ROOT / "thomas" / "server" / "web" / "settings.plugins-sets.js").is_file()
