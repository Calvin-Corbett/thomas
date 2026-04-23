from __future__ import annotations

import time
import uuid


def new_run_id(prefix: str = "run") -> str:
    """Generate a stable, locally-unique run id."""
    # include timestamp prefix to make logs easier to sort
    ts = int(time.time())
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:12]}"
