"""Fakes shared by the aliveness loop tests: a scripted sensor, an observation, an isolated gate."""

from __future__ import annotations

import time

from thomas.core.aliveness_gate import PushBudget, SpeakGate
from thomas.core.aliveness_permissions import (
    PermissionStore,
)
from thomas.core.aliveness_world import Observation


class FakeSensor:
    """A sensor whose readings the test controls."""

    def __init__(self, readings: list[Observation] | None = None) -> None:
        self.readings = readings or []

    @property
    def name(self) -> str:
        return "fake"

    def sample(self) -> list[Observation]:
        return list(self.readings)


def obs(key: str, value: str, topic: str = "fake.topic") -> Observation:
    return Observation(topic=topic, key=key, value=value, at=time.time())


def isolated_gate(tmp_path, budget: PushBudget | None = None) -> SpeakGate:
    """A gate whose permission store is a throwaway file.

    Tests must never touch the real store: it is the user's standing contract
    about what may interrupt them.
    """
    return SpeakGate(
        permissions=PermissionStore(tmp_path / "permissions.json"),
        budget=budget or PushBudget(),
    )


