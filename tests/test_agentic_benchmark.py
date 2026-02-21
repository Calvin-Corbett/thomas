import json
import tempfile
import unittest
from pathlib import Path

from thomas.demo.agentic_benchmark import (
    apply_template_context,
    compute_before_after_delta,
    evaluate_task_success,
    load_agentic_task_pack,
)


class TestAgenticBenchmark(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def test_apply_template_context_nested(self):
        payload = {
            "prompt": "write {{artifact_dir}}/out.txt",
            "success": {
                "required_files": ["{{artifact_dir}}/out.txt"],
                "required_file_contains": {"{{artifact_dir}}/out.txt": "ok"},
            },
        }
        out = apply_template_context(payload, {"artifact_dir": "runtime/bench/a"})
        self.assertEqual(out["prompt"], "write runtime/bench/a/out.txt")
        self.assertEqual(out["success"]["required_files"][0], "runtime/bench/a/out.txt")
        self.assertIn("runtime/bench/a/out.txt", out["success"]["required_file_contains"])
        self.assertEqual(out["success"]["required_file_contains"]["runtime/bench/a/out.txt"], "ok")

    def test_evaluate_task_success_checks_files_and_regex(self):
        artifact = self.tmp_path / "runtime" / "bench"
        artifact.mkdir(parents=True, exist_ok=True)
        target = artifact / "head.txt"
        target.write_text("abc1234\n", encoding="utf-8")

        task = {
            "success": {
                "response_contains": ["head.txt"],
                "required_files": ["runtime/bench/head.txt"],
                "required_file_regex": {"runtime/bench/head.txt": r"[0-9a-f]{7,40}"},
            }
        }
        result = evaluate_task_success(
            task,
            response_text="Done: head.txt abc1234",
            workspace_root=self.tmp_path,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["reasons"], [])

    def test_load_agentic_task_pack_rejects_unknown_success_key(self):
        pack_path = self.tmp_path / "pack.json"
        pack_path.write_text(
            json.dumps(
                {
                    "id": "x",
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "T",
                            "prompt": "P",
                            "success": {"made_up_check": "x"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_agentic_task_pack(pack_path)

    def test_compute_before_after_delta(self):
        summary = {
            "competitors": {
                "baseline_raw": {
                    "weighted_score": 20.0,
                    "success_rate": 0.25,
                    "avg_elapsed_seconds": 40.0,
                    "evidence_coverage": 0.25,
                },
                "thomas_os": {
                    "weighted_score": 80.0,
                    "success_rate": 1.0,
                    "avg_elapsed_seconds": 55.0,
                    "evidence_coverage": 1.0,
                },
            }
        }
        delta = compute_before_after_delta(
            summary,
            baseline_name="baseline_raw",
            thomas_name="thomas_os",
        )
        self.assertAlmostEqual(delta["metrics"]["weighted_score_delta"], 60.0)
        self.assertAlmostEqual(delta["metrics"]["success_rate_delta"], 0.75)
        self.assertAlmostEqual(delta["metrics"]["avg_elapsed_seconds_delta"], 15.0)


if __name__ == "__main__":
    unittest.main()
