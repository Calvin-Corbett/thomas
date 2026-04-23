from __future__ import annotations

import json
import subprocess
import sys

from order_service.pricing import sample_order, summarize_order


def test_order_summary_uses_quantities_for_totals() -> None:
    summary = summarize_order(sample_order())
    assert summary["item_count"] == 6
    assert summary["subtotal"] == "54.23"
    assert summary["lines"] == [
        {
            "sku": "bench-runner",
            "quantity": 2,
            "unit_price": "19.99",
            "line_total": "39.98",
        },
        {
            "sku": "guardrail-pack",
            "quantity": 1,
            "unit_price": "7.50",
            "line_total": "7.50",
        },
        {
            "sku": "report-export",
            "quantity": 3,
            "unit_price": "2.25",
            "line_total": "6.75",
        },
    ]


def test_cli_json_outputs_summary_payload() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "order_service", "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["item_count"] == 6
    assert payload["subtotal"] == "54.23"


def test_invoice_text_uses_quantity_aware_summary() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "order_service"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "6 items: $54.23"
