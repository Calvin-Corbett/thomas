import unittest

from thomas.demo.browser_duel import (
    build_execution_plan,
    build_results_from_browser,
    default_adapter,
    load_adapters,
    parse_target_args,
)


class TestDemoBrowserDuel(unittest.TestCase):
    def test_parse_target_args_requires_two(self):
        with self.assertRaises(ValueError):
            parse_target_args(["thomas=http://127.0.0.1:8899"])

    def test_parse_target_args_parses_pairs(self):
        out = parse_target_args(
            [
                "thomas=http://127.0.0.1:8899",
                "openclaw=http://127.0.0.1:3000",
            ]
        )
        self.assertEqual(out["thomas"], "http://127.0.0.1:8899")
        self.assertEqual(out["openclaw"], "http://127.0.0.1:3000")

    def test_build_results_from_browser_uses_min_quality(self):
        browser = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 12.5,
                "transcript_relpath": "browser_transcripts/a.txt",
                "completed_at": "2026-01-01T00:00:00+00:00",
                "error": "",
            }
        ]
        rows = build_results_from_browser(browser_results=browser, quality_min=1)
        self.assertEqual(rows[0]["quality_score"], 1)
        self.assertEqual(rows[0]["evidence"], "browser_transcripts/a.txt")

    def test_load_adapters_defaults_for_missing_file(self):
        adapters = load_adapters(None, ["thomas", "openclaw"])
        base = default_adapter()
        self.assertEqual(adapters["thomas"].composer_selector, base.composer_selector)
        self.assertEqual(adapters["openclaw"].send_selector, base.send_selector)

    def test_build_execution_plan_randomized_seed_stable(self):
        pack = {
            "tasks": [
                {"id": "t1", "title": "A", "prompt": "P"},
                {"id": "t2", "title": "B", "prompt": "Q"},
            ]
        }
        a = build_execution_plan(task_pack=pack, competitors=["thomas", "openclaw"], randomize=True, seed=9)
        b = build_execution_plan(task_pack=pack, competitors=["thomas", "openclaw"], randomize=True, seed=9)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()

