"""The seam finder says where an oversized file wants to be cut, and what it shares.

A file of code is a set of definitions that lean on each other. The monolith
guard measures size; this tool reads the leaning and reports the points where
the cross-references between two halves drop to zero, so the split follows the
code's own structure and the helpers both sides need move to one module.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.forge.seam_finder import find_seams


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "test_big.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_two_independent_groups_cut_where_nothing_crosses(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        import os


        def shared_helper():
            return os.getcwd()


        def a_one():
            return shared_helper()


        def a_two():
            return a_one()


        def b_one():
            return shared_helper() + "b"


        def b_two():
            return b_one()
        ''',
    )
    # Four two-line units remain once the helper leaves the sequence. Every
    # part carries the four header lines and one helper import, so a limit of
    # eleven leaves six lines of room: one cut, and the only cut nothing
    # crosses is between the two groups.
    report = find_seams(path, limit_lines=11)

    assert [p.names for p in report.parts] == [["a_one", "a_two"], ["b_one", "b_two"]]
    assert report.shared == ["shared_helper"]
    assert report.crossings == 0


def test_a_fixture_is_shared_when_both_sides_take_it_as_an_argument(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        import pytest


        @pytest.fixture
        def repo(tmp_path):
            return tmp_path


        def test_first(repo):
            assert repo


        def test_second(repo):
            assert repo
        ''',
    )
    # Two two-line tests remain once the fixture leaves the sequence. With the
    # four header lines and the helper import, a limit of eight leaves three
    # lines of room: the cut falls between them, and both sides still take it.
    report = find_seams(path, limit_lines=8)

    assert report.shared == ["repo"]
    assert [p.names for p in report.parts] == [["test_first"], ["test_second"]]


def test_a_file_under_the_limit_is_one_part_with_no_advice(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        def only():
            return 1
        ''',
    )
    report = find_seams(path, limit_lines=800)

    assert len(report.parts) == 1
    assert report.shared == []
    assert report.crossings == 0


def test_a_chain_that_cannot_be_cut_cleanly_reports_its_crossings(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        def one():
            return 1


        def two():
            return one()


        def three():
            return two()


        def four():
            return three()
        ''',
    )
    # One header line and the import leave six lines of room under eight.
    report = find_seams(path, limit_lines=8)

    assert len(report.parts) == 2
    assert report.crossings >= 1
    assert report.parts[1].needs, "the second part names what it pulls from the first"


def test_the_text_report_names_the_cut_and_the_helper_module(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        def shared_helper():
            return 1


        def a_one():
            return shared_helper()


        def b_one():
            return shared_helper()
        ''',
    )
    report = find_seams(path, limit_lines=6)
    text = report.render()

    assert "shared_helper" in text
    assert "a_one" in text and "b_one" in text
    assert "part 1" in text and "part 2" in text


def test_a_helper_only_one_section_uses_stays_home_and_the_cut_moves(tmp_path: Path) -> None:
    # Written after the aliveness file showed the greedy cut landing inside a
    # section and dragging its local helper into the shared module.
    path = _write(
        tmp_path,
        '''
        def a_one():
            return 1


        def a_two():
            return 2


        def local_helper():
            return 3


        def b_one():
            return local_helper()


        def b_two():
            return local_helper()
        ''',
    )
    # One header line and the import leave eight lines of room under ten: the
    # cheapest cut that fills half a part is before local_helper, not after
    # it, so the helper stays with the only section that uses it.
    report = find_seams(path, limit_lines=10)

    assert report.shared == []
    assert [p.names for p in report.parts] == [["a_one", "a_two"], ["local_helper", "b_one", "b_two"]]
    assert report.crossings == 0


def test_what_a_shared_helper_uses_travels_with_it(tmp_path: Path) -> None:
    # Written after the CLI evolve file showed _seed_repo going shared while
    # the _seed_locked_corpus it calls stayed behind in part one.
    path = _write(
        tmp_path,
        '''
        def seed_corpus():
            return 1


        def seed_repo():
            return seed_corpus()


        def a_one():
            repo = seed_repo()
            return repo


        def b_one():
            repo = seed_repo()
            return repo
        ''',
    )
    # One header line and the import leave four lines of room under six, so
    # the two three-line users cannot share a part and seed_repo goes shared.
    report = find_seams(path, limit_lines=6)

    assert report.shared == ["seed_corpus", "seed_repo"]
    assert [p.names for p in report.parts] == [["a_one"], ["b_one"]]
    assert report.crossings == 0


def test_a_single_unit_over_the_budget_is_named_not_hidden(tmp_path: Path) -> None:
    # Four of the nine oversized production files are one giant function or
    # class; a cut between definitions cannot help, and the report must say so.
    body = "def giant():\n" + "".join(f"    x{i} = {i}\n" for i in range(12)) + "    return x0\n\n\ndef small():\n    return 1\n"
    path = tmp_path / "test_big.py"
    path.write_text(body, encoding="utf-8")

    report = find_seams(path, limit_lines=10)
    text = report.render()

    assert report.oversized == ["giant"]
    assert "giant" in text and "by itself" in text


def test_a_file_over_the_limit_with_no_seam_says_so(tmp_path: Path) -> None:
    # precommit_skip_policy.py was 802 lines against a limit of 800: one part,
    # but "nothing to cut" would be a lie about a file the guard refuses.
    body = "import os\n\n\n" + "".join(f"def f{i}():\n    return os.sep\n\n\n" for i in range(3))
    path = tmp_path / "test_big.py"
    path.write_text(body, encoding="utf-8")

    report = find_seams(path, limit_lines=8)
    text = report.render()

    assert report.total_lines > report.limit
    assert "over the limit" in text
    assert "nothing to cut" not in text


def test_a_javascript_file_gets_the_same_advice(tmp_path: Path) -> None:
    # Six of the twelve remaining monolith violations are web files; top-level
    # function declarations and const bindings are the units there.
    path = tmp_path / "big.js"
    path.write_text(
        textwrap.dedent(
            """
            const SHARED = { limit: 3 };

            function helper(x) {
              return x + SHARED.limit;
            }

            function aOne() {
              return helper(1);
            }

            function aTwo() {
              return aOne() + 1;
            }

            const bOne = () => {
              return helper(2);
            };

            function bTwo() {
              return bOne() + 2;
            }
            """
        ),
        encoding="utf-8",
    )
    # One header line and the import leave eight lines of room under ten.
    report = find_seams(path, limit_lines=12)

    assert report.shared == ["SHARED", "helper"]
    assert [p.names for p in report.parts] == [["aOne", "aTwo"], ["bOne", "bTwo"]]
    assert report.crossings == 0


def test_a_file_wrapped_in_one_closure_is_read_one_level_down(tmp_path: Path) -> None:
    # Both real JavaScript violations are an IIFE: everything sits one brace deep.
    path = tmp_path / "wrapped.js"
    path.write_text(
        textwrap.dedent(
            """
            (function () {
              function helper(x) {
                return x;
              }

              function aOne() {
                return helper(1);
              }

              function aTwo() {
                return aOne();
              }

              function bOne() {
                return helper(2);
              }

              function bTwo() {
                return bOne();
              }
            })();
            """
        ),
        encoding="utf-8",
    )
    report = find_seams(path, limit_lines=12)

    assert report.shared == ["helper"]
    assert [p.names for p in report.parts] == [["aOne", "aTwo"], ["bOne", "bTwo"]]
    assert "one closure" in report.render()


def test_a_giant_class_is_read_by_its_methods(tmp_path: Path) -> None:
    # Four remaining violations are one class each (a 1,680-line test class,
    # the REPL); methods are the units there and self.<name> is the edge.
    path = _write(
        tmp_path,
        '''
        class Big:
            def setUp(self):
                self.ready = True

            def helper(self):
                return 1

            def a_one(self):
                return self.helper()

            def a_two(self):
                return self.a_one()

            def b_one(self):
                return self.helper()

            def b_two(self):
                return self.b_one()
        ''',
    )
    # The class header is one line; a limit of nine leaves seven, so the four
    # two-line methods cannot share a part once the helper leaves the sequence.
    report = find_seams(path, limit_lines=9)

    assert report.oversized == ["Big"]
    inner = report.inner["Big"]
    # unittest calls setUp for every method; no test names it, so it must travel with every part
    assert inner.shared == ["helper", "setUp"]
    assert [p.names for p in inner.parts] == [["a_one", "a_two"], ["b_one", "b_two"]]
    assert "inside Big" in report.render()


def test_an_html_page_is_read_by_its_script_blocks(tmp_path: Path) -> None:
    # Three remaining violations are pages: the inline scripts are the code
    # and everything else is template the tool has no business cutting.
    path = tmp_path / "page.html"
    path.write_text(
        textwrap.dedent(
            """
            <html><body>
            <div id="app"></div>
            <script>
              function helper() { return 1; }
              function aOne() { return helper(); }
              function aTwo() { return aOne(); }
            </script>
            <p>markup between</p>
            <script>
              function bOne() { return helper(); }
              function bTwo() { return bOne(); }
            </script>
            </body></html>
            """
        ),
        encoding="utf-8",
    )
    # A page carries no header into its parts; a limit of three leaves two
    # lines of room, so the four one-line functions cut in the middle.
    report = find_seams(path, limit_lines=3)

    assert report.shared == ["helper"]
    assert [p.names for p in report.parts] == [["aOne", "aTwo"], ["bOne", "bTwo"]]
    assert report.template_lines > 0
    assert "template" in report.render()


def test_a_regex_full_of_quotes_does_not_swallow_the_file(tmp_path: Path) -> None:
    # chat.html's esc() escapes HTML with /[&<>"']/g; the quote characters in
    # that regex read as string openers and the closing brace vanished, so one
    # unit ran 2,710 lines to the end of the page.
    path = tmp_path / "esc.js"
    path.write_text(
        textwrap.dedent(
            """
            function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;" })[c]); }

            function aOne() { return esc("x"); }

            function bOne() { return esc("y"); }

            function bTwo() { return bOne(); }
            """
        ),
        encoding="utf-8",
    )
    # One header line and the import leave two lines of room under four, so
    # the three one-line users cannot share a part once esc leaves the sequence.
    report = find_seams(path, limit_lines=4)

    assert report.oversized == []
    assert report.shared == ["esc"]
    assert [p.names for p in report.parts] == [["aOne"], ["bOne", "bTwo"]]
