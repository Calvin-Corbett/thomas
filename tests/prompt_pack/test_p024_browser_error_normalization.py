import json

from typer.testing import CliRunner

from thomas.browser.p024_browser_error_normalization import (
    BrowserErrorNormalizationRequest,
    normalize_browser_error,
)
from thomas.cli.commands.browser.p024_browser_error_normalization import app as cli_app


def test_normalize_control_unreachable() -> None:
    raw = "Can't reach the browser control service (timed out after 20000ms)."
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw))

    assert result.code == "browser_control_unreachable"
    assert result.category == "external"
    assert result.retryable is True


def test_normalize_dependency_missing_playwright() -> None:
    raw = "Playwright is not available in this build"
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw))

    assert result.code == "browser_dependency_missing"
    assert result.category == "config"
    assert result.retryable is False


def test_normalize_launch_failed_from_dict() -> None:
    raw = {"error": 'Error: Failed to start Chrome CDP on port 18800 for profile "work".'}
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw, profile="work"))

    assert result.code == "browser_launch_failed"
    assert result.category == "external"
    assert result.retryable is True
    assert "cdp" in result.raw.lower()


def test_normalize_http_status_mapping_429() -> None:
    raw = {"message": "Too Many Requests", "status": 429}
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw))

    assert result.code == "browser_rate_limited"
    assert result.category == "external"
    assert result.retryable is True


def test_normalize_missing_input_is_deterministic() -> None:
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=None))

    assert result.code == "browser_error_missing"
    assert result.category == "input"
    assert result.retryable is False


def test_redacts_secret_query_params() -> None:
    raw = "cdpUrl=https://example.test?token=SUPERSECRET&other=ok"
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw))

    assert "SUPERSECRET" not in result.raw
    assert "token=<redacted>" in result.raw


def test_to_dict_is_json_serializable() -> None:
    raw = "connection refused to browser control"
    result = normalize_browser_error(BrowserErrorNormalizationRequest(raw=raw))

    payload = result.to_dict()
    dumped = json.dumps(payload, sort_keys=True)
    assert isinstance(dumped, str)


def test_cli_json_output() -> None:
    runner = CliRunner()
    res = runner.invoke(
        cli_app,
        [
            "normalize-error",
            '{"error": "Playwright is not installed"}',
            "--json",
        ],
    )

    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["code"] == "browser_dependency_missing"
    assert payload["category"] == "config"


def test_cli_missing_input_exit_2_with_payload() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["normalize-error", "--json"])

    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    assert payload["code"] == "browser_error_missing"


def test_cli_stdin_dash_reads_input() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["normalize-error", "-", "--json"], input="timeout")

    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["code"] == "browser_timeout"
    assert payload["retryable"] is True


def test_cli_schema_output() -> None:
    runner = CliRunner()
    res = runner.invoke(cli_app, ["normalize-error", "--schema", "--json"])

    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["type"] == "object"
    assert "properties" in payload
