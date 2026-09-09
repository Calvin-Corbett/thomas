"""Testing utilities for webhook functionality."""

from datetime import datetime
from typing import Any

from thomas.marketplace.webhooks._types import (
    Delivery,
    Endpoint,
    Subscription,
    WebhookEvent,
)


class TestPayloadGenerator:
    """Generates realistic test payloads for different event types."""

    SAMPLE_PAYLOADS = {
        "order.created": {
            "id": "order_12345",
            "customer_id": "cust_67890",
            "total": 99.99,
            "status": "pending",
            "items": [{"id": "item_1", "name": "Widget", "qty": 2, "price": 25.00}],
            "created_at": "2024-01-15T10:30:00Z",
        },
        "order.updated": {
            "id": "order_12345",
            "status": "shipped",
            "updated_at": "2024-01-16T14:20:00Z",
            "tracking_number": "TRACK123456",
        },
        "payment.completed": {
            "id": "pay_98765",
            "order_id": "order_12345",
            "amount": 99.99,
            "currency": "USD",
            "method": "credit_card",
            "completed_at": "2024-01-15T10:35:00Z",
        },
        "user.registered": {
            "id": "user_11111",
            "email": "test@example.com",
            "name": "Test User",
            "registered_at": "2024-01-10T08:00:00Z",
        },
    }

    @staticmethod
    def generate(event_type: str, custom_data: dict | None = None) -> dict:
        """Generate a test payload for an event type.

        Args:
            event_type: The event type (e.g., "order.created").
            custom_data: Optional custom data to merge.

        Returns:
            Dictionary with test payload data.
        """
        payload = TestPayloadGenerator.SAMPLE_PAYLOADS.get(event_type, {}).copy()

        if custom_data:
            payload.update(custom_data)

        return payload

    @staticmethod
    def register_sample(event_type: str, payload: dict) -> None:
        """Register a custom sample payload.

        Args:
            event_type: The event type.
            payload: The sample payload.
        """
        TestPayloadGenerator.SAMPLE_PAYLOADS[event_type] = payload

    @staticmethod
    def list_sample_types() -> list[str]:
        """List available sample payload types.

        Returns:
            List of event type strings.
        """
        return list(TestPayloadGenerator.SAMPLE_PAYLOADS.keys())


class EndpointEchoServer:
    """Simulates an endpoint that captures delivered webhooks.

    Useful for testing webhook delivery without external services.
    """

    def __init__(self, endpoint_id: str = "test_endpoint") -> None:
        """Initialize echo server.

        Args:
            endpoint_id: ID for this echo server.
        """
        self.endpoint_id = endpoint_id
        self._captured_requests: list[dict] = []
        self._response_config = {
            "status_code": 200,
            "body": '{"status": "received"}',
            "delay_ms": 0,
        }

    def set_response(
        self,
        status_code: int = 200,
        body: str = '{"status": "received"}',
        delay_ms: int = 0,
    ) -> None:
        """Configure echo server response.

        Args:
            status_code: HTTP status code to return.
            body: Response body.
            delay_ms: Delay in milliseconds.
        """
        self._response_config = {
            "status_code": status_code,
            "body": body,
            "delay_ms": delay_ms,
        }

    def capture_request(self, payload: dict, headers: dict[str, str]) -> tuple:
        """Capture a webhook request.

        Args:
            payload: The webhook payload.
            headers: Request headers.

        Returns:
            Tuple of (status_code, response_body, latency_ms).
        """
        self._captured_requests.append(
            {
                "payload": payload,
                "headers": headers,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        import time

        start = time.time()
        if self._response_config["delay_ms"] > 0:
            time.sleep(self._response_config["delay_ms"] / 1000.0)

        latency_ms = int((time.time() - start) * 1000)

        return (
            self._response_config["status_code"],
            self._response_config["body"],
            latency_ms,
        )

    def get_captured_requests(self) -> list[dict]:
        """Get all captured requests.

        Returns:
            List of captured request dictionaries.
        """
        return list(self._captured_requests)

    def get_last_request(self) -> dict | None:
        """Get the last captured request.

        Returns:
            Last request dict, or None if no requests captured.
        """
        return self._captured_requests[-1] if self._captured_requests else None

    def clear(self) -> None:
        """Clear captured requests."""
        self._captured_requests.clear()


class DeliverySimulator:
    """Simulates delivery scenarios for testing.

    Tests retry behavior, failure scenarios, etc.
    """

    def __init__(self) -> None:
        """Initialize delivery simulator."""
        self._scenarios: dict[str, callable] = {}

    def register_scenario(self, name: str, scenario: callable) -> None:
        """Register a delivery scenario.

        Args:
            name: Scenario name.
            scenario: Callable that returns (status_code, body, latency_ms).
        """
        self._scenarios[name] = scenario

    def simulate_success(self, latency_ms: int = 50) -> tuple:
        """Simulate successful delivery.

        Args:
            latency_ms: Latency to simulate.

        Returns:
            Tuple of (status_code, body, latency_ms).
        """
        return 200, '{"status": "received"}', latency_ms

    def simulate_temporary_failure(self, latency_ms: int = 100) -> tuple:
        """Simulate temporary failure (5xx).

        Args:
            latency_ms: Latency to simulate.

        Returns:
            Tuple of (status_code, body, latency_ms).
        """
        return 503, "Service Unavailable", latency_ms

    def simulate_permanent_failure(self, latency_ms: int = 50) -> tuple:
        """Simulate permanent failure (4xx).

        Args:
            latency_ms: Latency to simulate.

        Returns:
            Tuple of (status_code, body, latency_ms).
        """
        return 400, "Bad Request", latency_ms

    def simulate_timeout(self) -> tuple:
        """Simulate request timeout.

        Returns:
            Tuple of (status_code, body, latency_ms).
        """
        return 0, "Connection Timeout", 30000

    def execute_scenario(self, scenario_name: str) -> tuple:
        """Execute a registered scenario.

        Args:
            scenario_name: Name of the scenario.

        Returns:
            Tuple of (status_code, body, latency_ms).
        """
        scenario = self._scenarios.get(scenario_name)
        if scenario:
            return scenario()

        return 500, "Unknown Scenario", 0


class PayloadDiffer:
    """Compares expected vs actual webhook payloads."""

    @staticmethod
    def diff(expected: dict, actual: dict) -> dict:
        """Generate diff between expected and actual payloads.

        Args:
            expected: Expected payload.
            actual: Actual payload.

        Returns:
            Difference report.
        """
        return {
            "matches": expected == actual,
            "missing_fields": PayloadDiffer._find_missing_fields(expected, actual),
            "extra_fields": PayloadDiffer._find_extra_fields(expected, actual),
            "value_differences": PayloadDiffer._find_value_differences(expected, actual),
        }

    @staticmethod
    def _find_missing_fields(expected: dict, actual: dict) -> list[str]:
        """Find fields in expected but not in actual.

        Args:
            expected: Expected payload.
            actual: Actual payload.

        Returns:
            List of missing field paths.
        """
        missing = []

        for key in expected:
            if key not in actual:
                missing.append(key)
            elif isinstance(expected[key], dict) and isinstance(actual.get(key), dict):
                missing.extend([f"{key}.{m}" for m in PayloadDiffer._find_missing_fields(expected[key], actual[key])])

        return missing

    @staticmethod
    def _find_extra_fields(expected: dict, actual: dict) -> list[str]:
        """Find fields in actual but not in expected.

        Args:
            expected: Expected payload.
            actual: Actual payload.

        Returns:
            List of extra field paths.
        """
        extra = []

        for key in actual:
            if key not in expected:
                extra.append(key)
            elif isinstance(expected.get(key), dict) and isinstance(actual[key], dict):
                extra.extend([f"{key}.{e}" for e in PayloadDiffer._find_extra_fields(expected[key], actual[key])])

        return extra

    @staticmethod
    def _find_value_differences(expected: dict, actual: dict) -> dict[str, tuple]:
        """Find fields with different values.

        Args:
            expected: Expected payload.
            actual: Actual payload.

        Returns:
            Dictionary of field -> (expected_value, actual_value).
        """
        differences = {}

        for key in expected:
            if key in actual:
                if isinstance(expected[key], dict) and isinstance(actual[key], dict):
                    diffs = PayloadDiffer._find_value_differences(expected[key], actual[key])
                    for k, v in diffs.items():
                        differences[f"{key}.{k}"] = v
                elif expected[key] != actual[key]:
                    differences[key] = (expected[key], actual[key])

        return differences


class WebhookIntegrationTester:
    """Integration test framework for webhook flows."""

    def __init__(self) -> None:
        """Initialize integration tester."""
        self._test_results: list[dict] = []

    def test_register_and_deliver(
        self,
        registry: Any,
        endpoint: Endpoint,
        subscription: Subscription,
        event: WebhookEvent,
        echo_server: EndpointEchoServer,
    ) -> dict:
        """Test complete webhook flow: register -> deliver -> verify.

        Args:
            registry: Webhook registry.
            endpoint: Endpoint configuration.
            subscription: Subscription configuration.
            event: Event to deliver.
            echo_server: Echo server to capture requests.

        Returns:
            Test result dictionary.
        """
        test_result = {
            "test_name": "register_and_deliver",
            "passed": False,
            "steps": [],
            "errors": [],
        }

        try:
            payload = event.payload.to_dict()
            status, body, latency = echo_server.capture_request(payload, subscription.custom_headers)

            test_result["steps"].append(
                {
                    "name": "delivery",
                    "status_code": status,
                    "latency_ms": latency,
                }
            )

            if status == 200:
                test_result["passed"] = True

                captured = echo_server.get_last_request()
                if captured:
                    test_result["captured_payload"] = captured["payload"]

        except Exception as e:
            test_result["errors"].append(str(e))

        self._test_results.append(test_result)
        return test_result

    def test_retry_behavior(
        self,
        delivery: Delivery,
        max_attempts: int = 3,
    ) -> dict:
        """Test retry behavior of a delivery.

        Args:
            delivery: Delivery record to test.
            max_attempts: Maximum retry attempts to expect.

        Returns:
            Test result dictionary.
        """
        test_result = {
            "test_name": "retry_behavior",
            "passed": False,
            "attempts": len(delivery.attempts),
            "max_attempts": max_attempts,
            "final_status": delivery.status.value,
        }

        if len(delivery.attempts) <= max_attempts:
            test_result["passed"] = True

        self._test_results.append(test_result)
        return test_result

    def get_results(self) -> list[dict]:
        """Get all test results.

        Returns:
            List of test result dictionaries.
        """
        return list(self._test_results)

    def get_summary(self) -> dict:
        """Get test summary.

        Returns:
            Summary dictionary.
        """
        total = len(self._test_results)
        passed = sum(1 for r in self._test_results if r.get("passed"))

        return {
            "total_tests": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": (passed / total * 100) if total > 0 else 0,
        }
