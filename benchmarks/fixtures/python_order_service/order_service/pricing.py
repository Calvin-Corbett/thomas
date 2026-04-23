from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int
    unit_price: Decimal


def sample_order() -> list[OrderLine]:
    return [
        OrderLine(sku="bench-runner", quantity=2, unit_price=Decimal("19.99")),
        OrderLine(sku="guardrail-pack", quantity=1, unit_price=Decimal("7.50")),
        OrderLine(sku="report-export", quantity=3, unit_price=Decimal("2.25")),
    ]


def summarize_order(lines: list[OrderLine]) -> dict[str, Any]:
    subtotal = sum(line.unit_price for line in lines)
    item_count = len(lines)
    return {
        "item_count": item_count,
        "subtotal": str(subtotal),
        "lines": [
            {
                "sku": line.sku,
                "quantity": line.quantity,
                "unit_price": str(line.unit_price),
                "line_total": str(line.unit_price),
            }
            for line in lines
        ],
    }


def format_invoice(lines: list[OrderLine]) -> str:
    summary = summarize_order(lines)
    return f"{summary['item_count']} items: ${summary['subtotal']}"
