"""
Reporting engine for the CRM system.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from thomas.marketplace.crm._types import Activity, Deal


class ReportingEngine:
    """Generates CRM reports and analytics.

    Provides pipeline reports, activity reports, win/loss analysis,
    revenue tracking, leaderboards, funnel analysis, and cohort analysis.
    """

    def __init__(self) -> None:
        """Initialize the reporting engine."""
        pass

    def generate_pipeline_report(
        self,
        deals: list[Deal],
        pipeline_stages: dict[str, str],
    ) -> dict[str, Any]:
        """Generate a comprehensive pipeline report.

        Args:
            deals: List of all deals
            pipeline_stages: Mapping of stage ID to stage name

        Returns:
            Pipeline report dictionary
        """
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_deals": len(deals),
            "total_pipeline_value": Decimal(0),
            "weighted_forecast": Decimal(0),
            "by_stage": {},
            "by_owner": {},
            "by_probability": {},
        }

        # Initialize stage breakdown
        for stage_id, stage_name in pipeline_stages.items():
            report["by_stage"][stage_id] = {
                "name": stage_name,
                "count": 0,
                "value": Decimal(0),
                "weighted_value": Decimal(0),
                "average_probability": 0,
            }

        # Initialize owner breakdown
        owner_stats = defaultdict(
            lambda: {
                "count": 0,
                "value": Decimal(0),
                "weighted_value": Decimal(0),
            }
        )

        # Probability buckets
        probability_buckets = {
            "0-25": {"count": 0, "value": Decimal(0)},
            "25-50": {"count": 0, "value": Decimal(0)},
            "50-75": {"count": 0, "value": Decimal(0)},
            "75-100": {"count": 0, "value": Decimal(0)},
        }

        # Process deals
        for deal in deals:
            report["total_pipeline_value"] += deal.value
            report["weighted_forecast"] += deal.weighted_value

            # By stage
            if deal.stage_id in report["by_stage"]:
                report["by_stage"][deal.stage_id]["count"] += 1
                report["by_stage"][deal.stage_id]["value"] += deal.value
                report["by_stage"][deal.stage_id]["weighted_value"] += deal.weighted_value

            # By owner
            owner_stats[deal.owner]["count"] += 1
            owner_stats[deal.owner]["value"] += deal.value
            owner_stats[deal.owner]["weighted_value"] += deal.weighted_value

            # By probability
            if deal.probability < 25:
                probability_buckets["0-25"]["count"] += 1
                probability_buckets["0-25"]["value"] += deal.value
            elif deal.probability < 50:
                probability_buckets["25-50"]["count"] += 1
                probability_buckets["25-50"]["value"] += deal.value
            elif deal.probability < 75:
                probability_buckets["50-75"]["count"] += 1
                probability_buckets["50-75"]["value"] += deal.value
            else:
                probability_buckets["75-100"]["count"] += 1
                probability_buckets["75-100"]["value"] += deal.value

        # Calculate averages
        for stage_data in report["by_stage"].values():
            if stage_data["count"] > 0:
                stage_deals = [
                    d for d in deals if d.stage_id == next(k for k, v in report["by_stage"].items() if v is stage_data)
                ]
                avg_prob = sum(d.probability for d in stage_deals) / len(stage_deals)
                stage_data["average_probability"] = int(avg_prob)

        report["by_owner"] = dict(owner_stats)
        report["by_probability"] = probability_buckets

        return report

    def generate_activity_report(
        self,
        activities: list[Activity],
        period_days: int = 30,
    ) -> dict[str, Any]:
        """Generate an activity report.

        Args:
            activities: List of all activities
            period_days: Number of days to report on

        Returns:
            Activity report dictionary
        """
        cutoff_date = datetime.utcnow() - timedelta(days=period_days)

        recent_activities = [a for a in activities if a.timestamp >= cutoff_date]

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "period_days": period_days,
            "total_activities": len(recent_activities),
            "by_type": defaultdict(int),
            "by_user": defaultdict(int),
            "by_date": defaultdict(int),
            "total_duration_minutes": 0,
            "average_duration_minutes": 0,
        }

        # Aggregate by type and user
        total_duration = 0
        activities_with_duration = 0

        for activity in recent_activities:
            report["by_type"][activity.type.value] += 1

            if activity.user:
                report["by_user"][activity.user] += 1

            date_key = activity.timestamp.date().isoformat()
            report["by_date"][date_key] += 1

            if activity.duration:
                total_duration += activity.duration
                activities_with_duration += 1

        report["total_duration_minutes"] = total_duration
        if activities_with_duration > 0:
            report["average_duration_minutes"] = total_duration / activities_with_duration

        report["by_type"] = dict(report["by_type"])
        report["by_user"] = dict(report["by_user"])
        report["by_date"] = dict(report["by_date"])

        return report

    def generate_win_loss_report(
        self,
        won_deals: list[Deal],
        lost_deals: list[Deal],
    ) -> dict[str, Any]:
        """Generate a win/loss analysis report.

        Args:
            won_deals: List of won deals
            lost_deals: List of lost deals

        Returns:
            Win/loss report dictionary
        """
        total_deals = len(won_deals) + len(lost_deals)
        win_rate = (len(won_deals) / total_deals * 100) if total_deals > 0 else 0

        avg_won_size = sum(d.value for d in won_deals) / len(won_deals) if won_deals else Decimal(0)

        avg_lost_size = sum(d.value for d in lost_deals) / len(lost_deals) if lost_deals else Decimal(0)

        # By probability range
        won_by_prob = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
        lost_by_prob = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}

        for deal in won_deals:
            if deal.probability < 25:
                won_by_prob["0-25"] += 1
            elif deal.probability < 50:
                won_by_prob["25-50"] += 1
            elif deal.probability < 75:
                won_by_prob["50-75"] += 1
            else:
                won_by_prob["75-100"] += 1

        for deal in lost_deals:
            if deal.probability < 25:
                lost_by_prob["0-25"] += 1
            elif deal.probability < 50:
                lost_by_prob["25-50"] += 1
            elif deal.probability < 75:
                lost_by_prob["50-75"] += 1
            else:
                lost_by_prob["75-100"] += 1

        # By owner
        won_by_owner = defaultdict(int)
        lost_by_owner = defaultdict(int)

        for deal in won_deals:
            won_by_owner[deal.owner] += 1

        for deal in lost_deals:
            lost_by_owner[deal.owner] += 1

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_deals": total_deals,
            "won_deals": len(won_deals),
            "lost_deals": len(lost_deals),
            "win_rate": round(win_rate, 2),
            "loss_rate": round(100 - win_rate, 2),
            "avg_won_size": str(avg_won_size),
            "avg_lost_size": str(avg_lost_size),
            "size_difference": str(avg_won_size - avg_lost_size),
            "won_by_probability": won_by_prob,
            "lost_by_probability": lost_by_prob,
            "won_by_owner": dict(won_by_owner),
            "lost_by_owner": dict(lost_by_owner),
        }

        return report

    def generate_revenue_report(
        self,
        deals: list[Deal],
        period_days: int = 90,
    ) -> dict[str, Any]:
        """Generate a revenue report.

        Args:
            deals: List of deals
            period_days: Number of days to report on

        Returns:
            Revenue report dictionary
        """
        cutoff_date = datetime.utcnow() - timedelta(days=period_days)

        recent_deals = [d for d in deals if d.created_at >= cutoff_date]

        # Group by date
        revenue_by_date = defaultdict(Decimal)
        forecast_by_date = defaultdict(Decimal)

        for deal in recent_deals:
            date_key = deal.created_at.date().isoformat()
            revenue_by_date[date_key] += deal.value
            forecast_by_date[date_key] += deal.weighted_value

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "period_days": period_days,
            "total_deals": len(recent_deals),
            "total_value": str(sum(d.value for d in recent_deals)),
            "total_forecast": str(sum(d.weighted_value for d in recent_deals)),
            "average_deal_size": str(
                sum(d.value for d in recent_deals) / len(recent_deals) if recent_deals else Decimal(0)
            ),
            "revenue_by_date": {k: str(v) for k, v in revenue_by_date.items()},
            "forecast_by_date": {k: str(v) for k, v in forecast_by_date.items()},
        }

        return report

    def generate_leaderboard(
        self,
        deals: list[Deal],
        metric: str = "value",
    ) -> list[dict[str, Any]]:
        """Generate a rep performance leaderboard.

        Args:
            deals: List of deals
            metric: Metric to rank by ('value', 'count', 'forecast')

        Returns:
            List of rankings
        """
        by_owner = defaultdict(
            lambda: {
                "count": 0,
                "value": Decimal(0),
                "forecast": Decimal(0),
            }
        )

        for deal in deals:
            by_owner[deal.owner]["count"] += 1
            by_owner[deal.owner]["value"] += deal.value
            by_owner[deal.owner]["forecast"] += deal.weighted_value

        # Sort by metric
        if metric == "value":
            sorted_owners = sorted(by_owner.items(), key=lambda x: x[1]["value"], reverse=True)
        elif metric == "count":
            sorted_owners = sorted(by_owner.items(), key=lambda x: x[1]["count"], reverse=True)
        else:  # forecast
            sorted_owners = sorted(by_owner.items(), key=lambda x: x[1]["forecast"], reverse=True)

        leaderboard = []
        for rank, (owner, stats) in enumerate(sorted_owners, 1):
            leaderboard.append(
                {
                    "rank": rank,
                    "owner": owner,
                    "deal_count": stats["count"],
                    "total_value": str(stats["value"]),
                    "forecast": str(stats["forecast"]),
                }
            )

        return leaderboard

    def generate_funnel_report(
        self,
        deals: list[Deal],
        stages: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """Generate a sales funnel report.

        Args:
            deals: List of deals
            stages: List of (stage_id, stage_name) tuples

        Returns:
            Funnel report dictionary
        """
        stage_counts = defaultdict(int)
        stage_values = defaultdict(Decimal)

        for deal in deals:
            stage_counts[deal.stage_id] += 1
            stage_values[deal.stage_id] += deal.value

        funnel = []
        cumulative_count = len(deals)
        cumulative_value = sum(d.value for d in deals)

        for stage_id, stage_name in stages:
            count = stage_counts.get(stage_id, 0)
            value = stage_values.get(stage_id, Decimal(0))

            conversion_rate = (count / cumulative_count * 100) if cumulative_count > 0 else 0

            funnel.append(
                {
                    "stage_id": stage_id,
                    "stage_name": stage_name,
                    "deal_count": count,
                    "value": str(value),
                    "conversion_rate": round(conversion_rate, 2),
                }
            )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "total_deals": len(deals),
            "funnel": funnel,
        }

    def generate_cohort_report(
        self,
        deals: list[Deal],
        stages: dict[str, str],
        cohort_days: int = 30,
    ) -> dict[str, Any]:
        """Generate a cohort analysis report.

        Analyzes deals opened in a specific period and tracks their progression.

        Args:
            deals: List of deals
            stages: Stage mapping
            cohort_days: Days to group deals into cohorts

        Returns:
            Cohort analysis report
        """
        cohorts = defaultdict(lambda: defaultdict(int))

        for deal in deals:
            # Group by cohort (week created)
            cohort_week = (deal.created_at - timedelta(days=deal.created_at.weekday())).date()
            cohort_key = cohort_week.isoformat()

            cohorts[cohort_key][deal.stage_id] += 1

        # Sort by cohort
        sorted_cohorts = sorted(cohorts.items())

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "cohort_period_days": cohort_days,
            "cohorts": [],
        }

        for cohort_key, stage_dist in sorted_cohorts:
            cohort_entry = {
                "cohort": cohort_key,
                "total_deals": sum(stage_dist.values()),
                "by_stage": {},
            }

            for stage_id, stage_name in stages.items():
                cohort_entry["by_stage"][stage_id] = {
                    "name": stage_name,
                    "count": stage_dist.get(stage_id, 0),
                }

            report["cohorts"].append(cohort_entry)

        return report
