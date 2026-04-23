from __future__ import annotations

import csv
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.demo.harness_artifacts import _write_json


def build_blind_pack(
    records: Sequence[Mapping[str, Any]],
    *,
    seed: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    rows = list(records)
    rng = random.Random(int(seed))
    rng.shuffle(rows)
    samples: list[dict[str, Any]] = []
    answer_key: dict[str, dict[str, str]] = {}
    for idx, row in enumerate(rows, start=1):
        sample_id = f"S{idx:03d}"
        task_id = str(row.get("task_id") or "")
        competitor = str(row.get("competitor") or "")
        samples.append(
            {
                "sample_id": sample_id,
                "task_id": task_id,
                "elapsed_seconds": float(row.get("elapsed_seconds") or 0.0),
                "follow_up_prompts": int(row.get("follow_up_prompts") or 0),
                "evidence": str(row.get("evidence") or ""),
                "notes": str(row.get("notes") or ""),
                "judge_quality_score": "",
                "judge_success_override": "",
                "judge_comments": "",
            }
        )
        answer_key[sample_id] = {"task_id": task_id, "competitor": competitor}
    return samples, answer_key


def write_blind_pack(
    *,
    run_dir: Path,
    records: Sequence[Mapping[str, Any]],
    seed: int = 0,
    out_dir: Path | None = None,
) -> Path:
    target = out_dir if out_dir is not None else (run_dir / "blind_pack")
    target.mkdir(parents=True, exist_ok=True)
    samples, answer_key = build_blind_pack(records, seed=seed)
    _write_json(target / "blind_pack.json", {"seed": int(seed), "samples": samples})
    _write_json(target / "blind_answer_key.json", {"seed": int(seed), "answers": answer_key})

    sheet_path = target / "blind_judging_sheet.csv"
    with sheet_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "task_id",
                "elapsed_seconds",
                "follow_up_prompts",
                "evidence",
                "notes",
                "judge_quality_score",
                "judge_success_override",
                "judge_comments",
            ],
        )
        writer.writeheader()
        for row in samples:
            writer.writerow(row)
    return target
