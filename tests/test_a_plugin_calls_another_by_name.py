"""One plugin can call another by a name the kernel holds, so neither imports the other.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 8. A dependency this way stays
real and checked: a call nothing provides fails naming the seam, never quietly does nothing.
"""

from __future__ import annotations

import pytest

from thomas.core.kernel import late, seams


@pytest.fixture(autouse=True)
def _clean_provider() -> None:
    yield
    late.withdraw("test_seam")


def test_a_call_reaches_what_was_provided_with_its_arguments() -> None:
    late.provide("test_seam", lambda a, b=0: a + b)
    assert late.call("test_seam", 2, b=3) == 5


def test_a_call_nothing_provides_fails_and_names_the_seam() -> None:
    with pytest.raises(late.NotProvided, match="test_seam"):
        late.call("test_seam")


def test_a_late_provider_sees_a_patch_of_the_function_it_stands_for(monkeypatch: pytest.MonkeyPatch) -> None:
    holder = type("Holder", (), {"real": staticmethod(lambda: "real")})
    late.provide("test_seam", lambda: holder.real())
    monkeypatch.setattr(holder, "real", staticmethod(lambda: "patched"))
    assert late.call("test_seam") == "patched"


def test_every_named_call_is_spelled_once_in_the_kernel() -> None:
    assert len(set(seams.CALLS)) == len(seams.CALLS) and all(isinstance(name, str) for name in seams.CALLS)
