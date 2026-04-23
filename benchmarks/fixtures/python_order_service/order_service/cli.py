from __future__ import annotations

import json
import sys

from .pricing import format_invoice, sample_order, summarize_order


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    lines = sample_order()
    if "--json" in args:
        sys.stdout.write(json.dumps(summarize_order(lines)) + "\n")
        return 0
    sys.stdout.write(format_invoice(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
