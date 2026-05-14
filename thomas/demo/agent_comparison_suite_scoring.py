from __future__ import annotations

from typing import Any

from collections.abc import Mapping, Sequence

from thomas.demo.agent_comparison_suite_shared import MetricSpec, _is_number, _safe_float


def _build_metric_rows(
    *,
    metric_specs: Mapping[str, MetricSpec],
    agents: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    agent_ids = [str(agent.get("id") or "").strip() for agent in agents if str(agent.get("id") or "").strip()]
    rows: list[dict[str, Any]] = []
    for metric in sorted(metric_specs.keys()):
        spec = metric_specs[metric]
        values = {}
        for agent in agents:
            aid = str(agent.get("id") or "").strip()
            values[aid] = dict(agent.get("metrics") or {}).get(metric)

        participants = {aid: float(values[aid]) for aid in agent_ids if _is_number(values.get(aid))}
        missing = [aid for aid in agent_ids if aid not in participants]

        status = "no_data"
        winners: list[str] = []
        spread = None
        if len(participants) == 1:
            status = "single_agent"
            winners = list(participants.keys())
            spread = 0.0
        elif len(participants) >= 2:
            status = "ok"
            vals = list(participants.values())
            lo = min(vals)
            hi = max(vals)
            spread = round(hi - lo, 6)
            if spec.preference == "higher_is_better":
                best = hi
                winners = [aid for aid, value in participants.items() if abs(value - best) <= 1e-9]
            elif spec.preference == "lower_is_better":
                best = lo
                winners = [aid for aid, value in participants.items() if abs(value - best) <= 1e-9]
            else:
                raise ValueError(f"unsupported preference: {spec.preference}")

        normalized: dict[str, float] = {aid: 0.0 for aid in agent_ids}
        if participants:
            vals = list(participants.values())
            lo = min(vals)
            hi = max(vals)
            if abs(hi - lo) <= 1e-9:
                for aid in participants:
                    normalized[aid] = 1.0
            else:
                for aid, value in participants.items():
                    if spec.preference == "higher_is_better":
                        normalized[aid] = (value - lo) / (hi - lo)
                    else:
                        normalized[aid] = (hi - value) / (hi - lo)
        normalized = {aid: round(val, 6) for aid, val in normalized.items()}

        gap_to_best: dict[str, float | None] = {}
        if participants and winners:
            if spec.preference == "higher_is_better":
                best = max(participants.values())
                for aid in agent_ids:
                    gap_to_best[aid] = round(best - participants[aid], 6) if aid in participants else None
            else:
                best = min(participants.values())
                for aid in agent_ids:
                    gap_to_best[aid] = round(participants[aid] - best, 6) if aid in participants else None
        else:
            for aid in agent_ids:
                gap_to_best[aid] = None

        rows.append(
            {
                "metric": metric,
                "category": spec.category,
                "preference": spec.preference,
                "weight": round(float(spec.weight), 6),
                "rationale": spec.rationale,
                "test_mode": str(spec.test_mode or "quick"),
                "values": values,
                "participants": sorted(participants.keys()),
                "missing": missing,
                "status": status,
                "winners": sorted(winners),
                "spread": spread,
                "normalized": normalized,
                "gap_to_best": gap_to_best,
            }
        )
    return rows


def _build_scoreboard(rows: Sequence[Mapping[str, Any]], *, agents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    agent_ids = [str(agent.get("id") or "").strip() for agent in agents if str(agent.get("id") or "").strip()]
    wins = {aid: 0 for aid in agent_ids}
    tie_metrics = 0
    measured_metrics = 0

    weighted_points = {aid: 0.0 for aid in agent_ids}
    measured_count = {aid: 0 for aid in agent_ids}
    comparable_measured_count = {aid: 0 for aid in agent_ids}
    max_weight = 0.0

    category_totals: dict[str, float] = {}
    category_points: dict[str, dict[str, float]] = {aid: {} for aid in agent_ids}
    category_measured_counts: dict[str, dict[str, int]] = {aid: {} for aid in agent_ids}
    category_comparable_measured_counts: dict[str, dict[str, int]] = {aid: {} for aid in agent_ids}

    for row in rows:
        participants = list(row.get("participants") or [])
        winners = list(row.get("winners") or [])
        weight = float(row.get("weight") or 0.0)
        category = str(row.get("category") or "uncategorized")
        normalized = dict(row.get("normalized") or {})
        values = dict(row.get("values") or {})

        comparable = len(participants) >= 2
        if comparable:
            measured_metrics += 1
            if len(winners) == 1:
                wins[winners[0]] += 1
            elif len(winners) > 1:
                tie_metrics += 1

        if comparable:
            max_weight += weight
            category_totals[category] = category_totals.get(category, 0.0) + weight
            for aid in agent_ids:
                weighted_points[aid] += float(normalized.get(aid) or 0.0) * weight
                category_points[aid][category] = (
                    float(category_points[aid].get(category) or 0.0) + float(normalized.get(aid) or 0.0) * weight
                )

        for aid in agent_ids:
            if _is_number(values.get(aid)):
                measured_count[aid] += 1
                category_measured_counts[aid][category] = int(category_measured_counts[aid].get(category) or 0) + 1
                if comparable:
                    comparable_measured_count[aid] += 1
                    category_comparable_measured_counts[aid][category] = (
                        int(category_comparable_measured_counts[aid].get(category) or 0) + 1
                    )

    total_metrics = len(rows)
    ranking: list[dict[str, Any]] = []
    for aid in agent_ids:
        composite = round((weighted_points[aid] / max_weight) * 100.0, 3) if max_weight > 0 else 0.0
        coverage = round((measured_count[aid] / total_metrics), 6) if total_metrics > 0 else 0.0
        comparable_coverage = (
            round((comparable_measured_count[aid] / measured_metrics), 6) if measured_metrics > 0 else 0.0
        )
        ranking.append(
            {
                "agent": aid,
                "weighted_points": round(weighted_points[aid], 6),
                "composite_score": composite,
                "coverage": coverage,
                "comparable_coverage": comparable_coverage,
                "wins": int(wins[aid]),
                "metrics_with_data": int(measured_count[aid]),
                "comparable_metrics_with_data": int(comparable_measured_count[aid]),
                "metrics_total": int(total_metrics),
                "comparable_metrics_total": int(measured_metrics),
            }
        )
    ranking.sort(key=lambda item: float(item["composite_score"]), reverse=True)
    for idx, row in enumerate(ranking, start=1):
        row["rank"] = idx

    category_scores: dict[str, dict[str, Any]] = {}
    for aid in agent_ids:
        category_scores[aid] = {}
        for category, category_weight_total in category_totals.items():
            points = float(category_points[aid].get(category) or 0.0)
            score = round((points / category_weight_total) * 100.0, 3) if category_weight_total > 0 else 0.0
            category_scores[aid][category] = {
                "score": score,
                "weighted_points": round(points, 6),
                "max_weight": round(float(category_weight_total), 6),
                "metrics_with_data": int(category_measured_counts[aid].get(category) or 0),
                "comparable_metrics_with_data": int(category_comparable_measured_counts[aid].get(category) or 0),
            }

    return {
        "total_metrics": total_metrics,
        "measured_metrics": measured_metrics,
        "tie_metrics": tie_metrics,
        "wins_by_agent": wins,
        "ranking": ranking,
        "max_weight_total": round(max_weight, 6),
        "category_scores": category_scores,
    }


def _focus_gaps(rows: Sequence[Mapping[str, Any]], *, focus_agent: str, top_n: int) -> list[dict[str, Any]]:
    focus = str(focus_agent or "").strip()
    gaps: list[dict[str, Any]] = []
    for row in rows:
        participants = set(row.get("participants") or [])
        if focus not in participants:
            continue
        if len(participants) < 2:
            continue
        winners = set(row.get("winners") or [])
        if focus in winners:
            continue
        gaps.append(
            {
                "metric": row.get("metric"),
                "category": row.get("category"),
                "weight": row.get("weight"),
                "preference": row.get("preference"),
                "values": row.get("values"),
                "winners": row.get("winners"),
                "gap_to_best": (row.get("gap_to_best") or {}).get(focus),
            }
        )
    gaps.sort(key=lambda item: (float(item.get("weight") or 0.0), float(item.get("gap_to_best") or 0.0)), reverse=True)
    return gaps[: max(0, int(top_n))]


def _build_competitor_pressure(
    *,
    rows: Sequence[Mapping[str, Any]],
    scoreboard: Mapping[str, Any],
    focus_agent: str,
) -> dict[str, Any]:
    focus = str(focus_agent or "").strip()
    ranking = [dict(item) for item in (scoreboard.get("ranking") or []) if isinstance(item, dict)]
    by_agent = {str(item.get("agent") or "").strip(): item for item in ranking if str(item.get("agent") or "").strip()}
    focus_score = _safe_float(dict(by_agent.get(focus) or {}).get("composite_score")) or 0.0
    pressure_rows: list[dict[str, Any]] = []
    for competitor, score_row in by_agent.items():
        if not competitor or competitor == focus:
            continue
        competitor_score = _safe_float(score_row.get("composite_score")) or 0.0
        competitor_wins = 0
        focus_wins = 0
        ties = 0
        comparable_metrics = 0
        for row in rows:
            participants = set(row.get("participants") or [])
            if focus not in participants or competitor not in participants:
                continue
            if len(participants) < 2:
                continue
            comparable_metrics += 1
            winners = set(row.get("winners") or [])
            if competitor in winners and focus not in winners:
                competitor_wins += 1
            elif focus in winners and competitor not in winners:
                focus_wins += 1
            else:
                ties += 1
        pressure_rows.append(
            {
                "competitor": competitor,
                "composite_score": round(competitor_score, 3),
                "composite_delta_vs_focus": round(competitor_score - focus_score, 3),
                "metrics_beating_focus": int(competitor_wins),
                "metrics_focus_beats": int(focus_wins),
                "metrics_tied": int(ties),
                "comparable_metrics": int(comparable_metrics),
                "threat_level": (
                    "high"
                    if (competitor_score > focus_score or competitor_wins > focus_wins)
                    else ("medium" if competitor_wins > 0 else "low")
                ),
            }
        )
    pressure_rows.sort(
        key=lambda item: (
            int(item.get("metrics_beating_focus") or 0),
            float(item.get("composite_delta_vs_focus") or 0.0),
        ),
        reverse=True,
    )
    threats = [row for row in pressure_rows if str(row.get("threat_level") or "") in {"high", "medium"}]
    return {
        "focus_agent": focus,
        "ranked_competitors": pressure_rows,
        "top_threats": threats,
    }
