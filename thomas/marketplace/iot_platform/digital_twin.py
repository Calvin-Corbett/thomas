"""
Digital twin management for virtual device representations.

Provides virtual device state synchronization, prediction,
simulation, historical replay, and anomaly detection.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import UUID

from thomas.marketplace.iot_platform._exceptions import IoTException


class DigitalTwinManager:
    """
    Manages virtual representations of physical devices.

    Provides state synchronization, prediction, simulation,
    historical replay, and anomaly detection.
    """

    def __init__(self) -> None:
        """Initialize the digital twin manager."""
        self._twins: dict[UUID, dict[str, Any]] = {}
        self._state_history: dict[UUID, list[tuple[datetime, dict[str, Any]]]] = {}
        self._simulation_mode: dict[UUID, bool] = {}
        self._lock = threading.RLock()

    def create_twin(self, device_id: UUID, initial_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Create a digital twin for a device.

        Args:
            device_id: Physical device ID.
            initial_state: Initial state dictionary.

        Returns:
            Digital twin data dictionary.
        """
        with self._lock:
            twin = {
                "device_id": device_id,
                "state": initial_state or {},
                "created_at": datetime.utcnow(),
                "last_sync": None,
                "expected_state": initial_state or {},
                "anomalies": [],
            }

            self._twins[device_id] = twin
            self._state_history[device_id] = []
            self._simulation_mode[device_id] = False

            return twin

    def get_twin(self, device_id: UUID) -> dict[str, Any] | None:
        """
        Get digital twin for a device.

        Args:
            device_id: Device ID.

        Returns:
            Twin data or None if not exists.
        """
        with self._lock:
            return self._twins.get(device_id)

    def update_twin_state(
        self,
        device_id: UUID,
        state_update: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update digital twin state from telemetry.

        Args:
            device_id: Device ID.
            state_update: State update dictionary.

        Returns:
            Updated twin state.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            twin = self._twins[device_id]

            # Save previous state to history
            self._state_history[device_id].append((datetime.utcnow(), dict(twin["state"])))

            # Update state
            twin["state"].update(state_update)
            twin["last_sync"] = datetime.utcnow()

            # Limit history size
            if len(self._state_history[device_id]) > 1000:
                self._state_history[device_id] = self._state_history[device_id][-1000:]

            return twin

    def set_expected_state(
        self,
        device_id: UUID,
        expected_state: dict[str, Any],
    ) -> None:
        """
        Set expected state for comparison.

        Args:
            device_id: Device ID.
            expected_state: Expected state dictionary.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            self._twins[device_id]["expected_state"] = expected_state

    def compare_states(self, device_id: UUID) -> dict[str, Any]:
        """
        Compare actual vs expected state.

        Args:
            device_id: Device ID.

        Returns:
            Comparison dictionary with differences.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            twin = self._twins[device_id]
            actual = twin["state"]
            expected = twin["expected_state"]

            differences = []

            for key in set(list(actual.keys()) + list(expected.keys())):
                actual_val = actual.get(key)
                expected_val = expected.get(key)

                if actual_val != expected_val:
                    differences.append(
                        {
                            "key": key,
                            "actual": actual_val,
                            "expected": expected_val,
                        }
                    )

            return {
                "device_id": device_id,
                "is_synchronized": len(differences) == 0,
                "differences": differences,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def predict_state(
        self,
        device_id: UUID,
        minutes_ahead: int = 5,
    ) -> dict[str, Any]:
        """
        Predict device state when offline.

        Uses linear trend extrapolation from recent history.

        Args:
            device_id: Device ID.
            minutes_ahead: Minutes to predict ahead.

        Returns:
            Predicted state dictionary.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            if device_id not in self._state_history:
                return {"prediction": "insufficient_data"}

            history = self._state_history[device_id]

            if len(history) < 2:
                return {"prediction": "insufficient_data"}

            # Get last few states
            recent_states = history[-10:]
            [t for t, _ in recent_states]
            states = [s for _, s in recent_states]

            predicted = {}

            # Simple linear extrapolation for numeric values
            for key in states[-1].keys():
                try:
                    values = []
                    for state in states:
                        if key in state and isinstance(state[key], (int, float)):
                            values.append(state[key])

                    if len(values) >= 2:
                        # Calculate trend
                        trend = (values[-1] - values[0]) / max(1, len(values) - 1)
                        predicted[key] = values[-1] + trend * minutes_ahead
                    elif len(values) == 1:
                        predicted[key] = values[0]
                except (TypeError, ValueError):
                    pass

            return {
                "predicted_state": predicted,
                "minutes_ahead": minutes_ahead,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def enable_simulation(self, device_id: UUID) -> None:
        """
        Enable simulation mode for testing.

        Args:
            device_id: Device ID.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            self._simulation_mode[device_id] = True

    def disable_simulation(self, device_id: UUID) -> None:
        """
        Disable simulation mode.

        Args:
            device_id: Device ID.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            self._simulation_mode[device_id] = False

    def is_simulation_mode(self, device_id: UUID) -> bool:
        """Check if device is in simulation mode."""
        with self._lock:
            return self._simulation_mode.get(device_id, False)

    def simulate_command(
        self,
        device_id: UUID,
        action: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Simulate command execution without real device.

        Args:
            device_id: Device ID.
            action: Command action.
            parameters: Command parameters.

        Returns:
            Simulated result.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._twins:
                raise IoTException(f"Twin not found for device {device_id}")

            twin = self._twins[device_id]

            # Simulate state changes based on action
            simulated_state = dict(twin["state"])

            if action == "set_parameter":
                for key, value in parameters.items():
                    simulated_state[key] = value

            elif action == "reset":
                simulated_state = {}

            elif action == "query":
                return {"result": twin["state"]}

            return {
                "action": action,
                "simulated_state": simulated_state,
                "success": True,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def replay_history(
        self,
        device_id: UUID,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        """
        Replay historical state changes.

        Args:
            device_id: Device ID.
            start_time: Optional start time.
            end_time: Optional end time.

        Returns:
            List of (timestamp, state) tuples.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._state_history:
                raise IoTException(f"No history for device {device_id}")

            history = self._state_history[device_id]

            if start_time:
                history = [(t, s) for t, s in history if t >= start_time]

            if end_time:
                history = [(t, s) for t, s in history if t <= end_time]

            return history

    def detect_anomalies(
        self,
        device_id: UUID,
        threshold: float = 2.0,
    ) -> list[dict[str, Any]]:
        """
        Detect state anomalies using statistical analysis.

        Args:
            device_id: Device ID.
            threshold: Standard deviation threshold.

        Returns:
            List of detected anomalies.

        Raises:
            IoTException: If twin not found.
        """
        with self._lock:
            if device_id not in self._state_history:
                raise IoTException(f"No history for device {device_id}")

            history = self._state_history[device_id]

            if len(history) < 10:
                return []

            anomalies = []

            # Analyze numeric values
            recent_states = history[-30:]

            for key in recent_states[-1][1].keys():
                values = []
                times = []

                for timestamp, state in recent_states:
                    if key in state and isinstance(state[key], (int, float)):
                        values.append(float(state[key]))
                        times.append(timestamp)

                if len(values) < 3:
                    continue

                # Calculate statistics
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / len(values)
                std_dev = variance**0.5

                # Detect anomalies
                for i, (timestamp, value) in enumerate(zip(times, values)):
                    if std_dev > 0:
                        z_score = abs((value - mean) / std_dev)

                        if z_score > threshold:
                            anomalies.append(
                                {
                                    "timestamp": timestamp.isoformat(),
                                    "key": key,
                                    "value": value,
                                    "z_score": z_score,
                                    "mean": mean,
                                    "std_dev": std_dev,
                                }
                            )

            self._twins[device_id]["anomalies"] = anomalies
            return anomalies

    def get_state_history(
        self,
        device_id: UUID,
        limit: int = 100,
    ) -> list[tuple[datetime, dict[str, Any]]]:
        """
        Get recent state history.

        Args:
            device_id: Device ID.
            limit: Maximum entries to return.

        Returns:
            List of (timestamp, state) tuples.
        """
        with self._lock:
            if device_id not in self._state_history:
                return []

            return self._state_history[device_id][-limit:]

    def delete_twin(self, device_id: UUID) -> bool:
        """
        Delete a digital twin.

        Args:
            device_id: Device ID.

        Returns:
            True if deleted successfully.
        """
        with self._lock:
            if device_id in self._twins:
                del self._twins[device_id]

            if device_id in self._state_history:
                del self._state_history[device_id]

            if device_id in self._simulation_mode:
                del self._simulation_mode[device_id]

            return True

        return False

    def get_twin_count(self) -> int:
        """Get number of active digital twins."""
        with self._lock:
            return len(self._twins)
