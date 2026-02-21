import json
import tempfile
import unittest
from pathlib import Path

from thomas.demo.harness import (
    aggregate_scorecards,
    build_blind_pack,
    build_execution_plan,
    build_results_template,
    compute_summary,
    load_scorecards,
    load_records_json,
    load_task_pack,
    validate_records,
    write_blind_pack,
    write_run_artifacts,
)


class TestDemoHarness(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def _write_json(self, rel: str, payload) -> Path:
        path = self.tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_load_task_pack_rejects_duplicate_task_ids(self):
        path = self._write_json(
            "pack.json",
            {
                "tasks": [
                    {"id": "t1", "title": "A", "prompt": "P"},
                    {"id": "t1", "title": "B", "prompt": "Q"},
                ]
            },
        )
        with self.assertRaises(ValueError):
            load_task_pack(path)

    def test_default_task_pack_is_valid(self):
        repo_root = Path(__file__).resolve().parents[1]
        pack = load_task_pack(repo_root / "demo" / "task_pack.default.json")
        self.assertEqual(pack["id"], "thomas-vs-openclaw-v1")
        self.assertEqual(len(pack["tasks"]), 5)

    def test_compute_summary_ranks_expected_winner(self):
        pack = {
            "tasks": [
                {"id": "t1", "title": "A", "prompt": "P"},
                {"id": "t2", "title": "B", "prompt": "Q"},
            ],
            "weights": {"success_rate": 0.4, "speed": 0.2, "follow_up": 0.2, "quality": 0.2},
            "quality_scale": {"min": 1, "max": 5},
        }
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 120,
                "follow_up_prompts": 0,
                "quality_score": 5,
            },
            {
                "task_id": "t2",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 140,
                "follow_up_prompts": 1,
                "quality_score": 4,
            },
            {
                "task_id": "t1",
                "competitor": "openclaw",
                "success": True,
                "elapsed_seconds": 200,
                "follow_up_prompts": 2,
                "quality_score": 3,
            },
            {
                "task_id": "t2",
                "competitor": "openclaw",
                "success": False,
                "elapsed_seconds": 260,
                "follow_up_prompts": 3,
                "quality_score": 2,
            },
        ]
        summary = compute_summary(pack, records)
        self.assertEqual(summary["ranking"][0]["competitor"], "thomas")
        self.assertGreater(
            summary["competitors"]["thomas"]["weighted_score"],
            summary["competitors"]["openclaw"]["weighted_score"],
        )

    def test_build_results_template_creates_full_matrix(self):
        pack = {
            "tasks": [
                {"id": "t1", "title": "A", "prompt": "P"},
                {"id": "t2", "title": "B", "prompt": "Q"},
            ],
            "quality_scale": {"min": 1, "max": 5},
        }
        template = build_results_template(pack, ["thomas", "openclaw"])
        self.assertEqual(len(template), 4)
        pairs = {(row["task_id"], row["competitor"]) for row in template}
        self.assertEqual(pairs, {("t1", "thomas"), ("t1", "openclaw"), ("t2", "thomas"), ("t2", "openclaw")})

    def test_build_execution_plan_is_deterministic_for_seed(self):
        pack = {
            "tasks": [
                {"id": "t1", "title": "A", "prompt": "P"},
                {"id": "t2", "title": "B", "prompt": "Q"},
            ]
        }
        plan_a = build_execution_plan(
            task_pack=pack,
            competitors=["thomas", "openclaw"],
            randomize=True,
            seed=7,
        )
        plan_b = build_execution_plan(
            task_pack=pack,
            competitors=["thomas", "openclaw"],
            randomize=True,
            seed=7,
        )
        self.assertEqual(plan_a, plan_b)
        self.assertEqual(len(plan_a), 4)

    def test_validate_records_rejects_missing_matrix_entry(self):
        pack = {
            "tasks": [
                {"id": "t1", "title": "A", "prompt": "P"},
                {"id": "t2", "title": "B", "prompt": "Q"},
            ],
            "quality_scale": {"min": 1, "max": 5},
        }
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 12,
                "follow_up_prompts": 0,
                "quality_score": 5,
            },
            {
                "task_id": "t1",
                "competitor": "openclaw",
                "success": True,
                "elapsed_seconds": 20,
                "follow_up_prompts": 1,
                "quality_score": 4,
            },
            {
                "task_id": "t2",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 14,
                "follow_up_prompts": 0,
                "quality_score": 4,
            },
        ]
        with self.assertRaises(ValueError):
            validate_records(task_pack=pack, competitors=["thomas", "openclaw"], records=records)

    def test_validate_records_can_require_evidence(self):
        pack = {
            "tasks": [{"id": "t1", "title": "A", "prompt": "P"}],
            "quality_scale": {"min": 1, "max": 5},
        }
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 1,
                "follow_up_prompts": 0,
                "quality_score": 5,
                "evidence": "",
            }
        ]
        with self.assertRaises(ValueError):
            validate_records(
                task_pack=pack,
                competitors=["thomas"],
                records=records,
                require_evidence=True,
            )

    def test_load_records_json_accepts_utf8_bom(self):
        payload = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 12,
                "follow_up_prompts": 0,
                "quality_score": 5,
            }
        ]
        path = self.tmp_path / "records.json"
        path.write_text(json.dumps(payload), encoding="utf-8-sig")
        records = load_records_json(path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["competitor"], "thomas")

    def test_write_run_artifacts_outputs_expected_files(self):
        pack = {
            "id": "pack",
            "version": 1,
            "name": "Pack",
            "description": "",
            "tasks": [{"id": "t1", "title": "A", "prompt": "P", "success_criteria": "", "time_budget_seconds": 60}],
            "weights": {"success_rate": 0.4, "speed": 0.2, "follow_up": 0.2, "quality": 0.2},
            "quality_scale": {"min": 1, "max": 5},
            "protocol": [],
        }
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "success": True,
                "elapsed_seconds": 10,
                "follow_up_prompts": 0,
                "quality_score": 5,
                "evidence": "",
                "notes": "",
            }
        ]
        summary = compute_summary(pack, records)
        execution_plan = build_execution_plan(
            task_pack=pack,
            competitors=["thomas", "openclaw"],
            randomize=False,
            seed=None,
        )
        run_dir = write_run_artifacts(
            runs_dir=self.tmp_path / "runs",
            run_id="demo-run",
            task_pack=pack,
            competitors=["thomas", "openclaw"],
            execution_plan=execution_plan,
            randomized_order=False,
            random_seed=None,
            require_evidence=False,
            records=records,
            summary=summary,
        )
        self.assertTrue((run_dir / "scorecard.json").exists())
        self.assertTrue((run_dir / "manifest.json").exists())
        self.assertTrue((run_dir / "execution_plan.json").exists())
        self.assertTrue((run_dir / "execution_plan.md").exists())
        self.assertTrue((run_dir / "results.raw.json").exists())
        self.assertTrue((run_dir / "task_prompts.md").exists())
        self.assertTrue((run_dir / "report.md").exists())
        self.assertTrue((run_dir / "overlay.csv").exists())

    def test_load_and_aggregate_scorecards(self):
        runs_dir = self.tmp_path / "runs"
        (runs_dir / "run-1").mkdir(parents=True)
        (runs_dir / "run-2").mkdir(parents=True)
        scorecard_1 = {
            "run_id": "run-1",
            "summary": {
                "competitors": {
                    "thomas": {
                        "weighted_score": 90,
                        "credibility_weighted_score": 80,
                        "success_rate": 1.0,
                        "avg_elapsed_seconds": 300,
                        "avg_follow_up_prompts": 1,
                        "avg_quality_score": 4.5,
                        "evidence_coverage": 0.9,
                    },
                    "openclaw": {
                        "weighted_score": 60,
                        "credibility_weighted_score": 30,
                        "success_rate": 0.6,
                        "avg_elapsed_seconds": 600,
                        "avg_follow_up_prompts": 3,
                        "avg_quality_score": 3.2,
                        "evidence_coverage": 0.5,
                    },
                }
            },
        }
        scorecard_2 = {
            "run_id": "run-2",
            "summary": {
                "competitors": {
                    "thomas": {
                        "weighted_score": 95,
                        "credibility_weighted_score": 85,
                        "success_rate": 1.0,
                        "avg_elapsed_seconds": 320,
                        "avg_follow_up_prompts": 1,
                        "avg_quality_score": 4.6,
                        "evidence_coverage": 0.95,
                    },
                    "openclaw": {
                        "weighted_score": 55,
                        "credibility_weighted_score": 20,
                        "success_rate": 0.5,
                        "avg_elapsed_seconds": 700,
                        "avg_follow_up_prompts": 4,
                        "avg_quality_score": 3.0,
                        "evidence_coverage": 0.4,
                    },
                }
            },
        }
        (runs_dir / "run-1" / "scorecard.json").write_text(json.dumps(scorecard_1), encoding="utf-8")
        (runs_dir / "run-2" / "scorecard.json").write_text(json.dumps(scorecard_2), encoding="utf-8")

        cards = load_scorecards(runs_dir)
        summary = aggregate_scorecards(cards)
        self.assertEqual(summary["runs_count"], 2)
        self.assertEqual(summary["ranking"][0]["competitor"], "thomas")
        self.assertGreater(
            summary["competitors"]["thomas"]["weighted_score_mean"],
            summary["competitors"]["openclaw"]["weighted_score_mean"],
        )

    def test_build_blind_pack_hides_competitor(self):
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "elapsed_seconds": 10,
                "follow_up_prompts": 0,
                "evidence": "a.txt",
            },
            {
                "task_id": "t1",
                "competitor": "openclaw",
                "elapsed_seconds": 20,
                "follow_up_prompts": 1,
                "evidence": "b.txt",
            },
        ]
        samples, answer_key = build_blind_pack(records, seed=1)
        self.assertEqual(len(samples), 2)
        self.assertTrue(all("competitor" not in row for row in samples))
        self.assertEqual(set(answer_key.keys()), {"S001", "S002"})

    def test_write_blind_pack_outputs_files(self):
        run_dir = self.tmp_path / "run"
        run_dir.mkdir(parents=True)
        records = [
            {
                "task_id": "t1",
                "competitor": "thomas",
                "elapsed_seconds": 10,
                "follow_up_prompts": 0,
                "evidence": "a.txt",
            }
        ]
        out_dir = write_blind_pack(run_dir=run_dir, records=records, seed=3)
        self.assertTrue((out_dir / "blind_pack.json").exists())
        self.assertTrue((out_dir / "blind_answer_key.json").exists())
        self.assertTrue((out_dir / "blind_judging_sheet.csv").exists())


if __name__ == "__main__":
    unittest.main()
