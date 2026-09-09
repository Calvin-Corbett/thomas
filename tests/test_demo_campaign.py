import unittest

from thomas.demo.campaign import build_run_index_rows, render_campaign_report


class TestDemoCampaign(unittest.TestCase):
    def test_build_run_index_rows_flattens_scorecards(self):
        cards = [
            {
                "run_id": "r1",
                "summary": {
                    "competitors": {
                        "thomas": {
                            "weighted_score": 95,
                            "credibility_weighted_score": 90,
                            "success_rate": 1.0,
                            "avg_elapsed_seconds": 200,
                            "avg_follow_up_prompts": 1,
                            "avg_quality_score": 4.5,
                            "evidence_coverage": 1.0,
                        },
                        "reference_cli": {
                            "weighted_score": 60,
                            "credibility_weighted_score": 30,
                            "success_rate": 0.6,
                            "avg_elapsed_seconds": 500,
                            "avg_follow_up_prompts": 3,
                            "avg_quality_score": 3.2,
                            "evidence_coverage": 0.5,
                        },
                    }
                },
            }
        ]
        rows = build_run_index_rows(cards)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["run_id"], "r1")
        self.assertIn(rows[0]["competitor"], {"thomas", "reference_cli"})

    def test_render_campaign_report_includes_rankings(self):
        aggregate = {
            "runs_count": 2,
            "ranking": [
                {"rank": 1, "competitor": "thomas", "weighted_score_mean": 96.0},
                {"rank": 2, "competitor": "reference_cli", "weighted_score_mean": 62.0},
            ],
            "credibility_ranking": [
                {"rank": 1, "competitor": "thomas", "credibility_weighted_score_mean": 94.0},
                {"rank": 2, "competitor": "reference_cli", "credibility_weighted_score_mean": 40.0},
            ],
            "competitors": {
                "thomas": {
                    "runs": 2,
                    "weighted_score_mean": 96.0,
                    "credibility_weighted_score_mean": 94.0,
                    "success_rate_mean": 1.0,
                    "avg_elapsed_seconds_mean": 210.0,
                    "avg_follow_up_prompts_mean": 1.0,
                    "avg_quality_score_mean": 4.6,
                    "evidence_coverage_mean": 1.0,
                }
            },
        }
        report = render_campaign_report(
            campaign_id="campaign-x",
            aggregate=aggregate,
            runs_attempted=2,
            runs_completed=2,
        )
        self.assertIn("campaign-x", report)
        self.assertIn("Aggregate Ranking", report)
        self.assertIn("Credibility", report)
        self.assertIn("thomas", report)


if __name__ == "__main__":
    unittest.main()
