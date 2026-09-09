from __future__ import annotations

import pytest
import scripts.clean_dev_artifacts as mod


def test_known_dev_artifacts_are_not_tracked() -> None:
    try:
        offenders = mod.tracked_dev_artifacts()
    except RuntimeError as exc:
        pytest.skip(f"git unavailable for tracked artifact guard: {exc}")
    assert offenders == [], f"tracked dev artifacts must be removed: {offenders}"
