"""Provider failures that deserve a trouble episode, without transport retries."""

from thomas.core.provider_trouble import EpisodeTracker, classify


def test_overload_without_http_status() -> None:
    trouble = classify("Our servers are currently overloaded. Please try again later.")
    assert trouble is not None and trouble.kind == "overloaded"
    assert "overloaded" in trouble.evidence


def test_anthropic_529_overload() -> None:
    assert classify('Anthropic HTTP 529 {"type":"overloaded_error"}').kind == "overloaded"
    assert classify("Anthropic failure", status=529).kind == "overloaded"


def test_server_errors_and_codex_disconnect() -> None:
    assert classify("Upstream unavailable", status=503).kind == "server_error"
    for status in (500, 502, 504):
        assert classify("Server failure", status=status).kind == "server_error"
    assert (
        classify("ChatGPT/Codex stream disconnected before any usable output. Retry this turn.").kind == "server_error"
    )
    assert classify("Codex text stream disconnected before completion").kind == "server_error"
    assert classify("Connection dropped while contacting the model").kind == "server_error"
    assert classify("Connection reset by peer").kind == "server_error"


def test_local_proxy_and_short_burst_are_not_provider_trouble() -> None:
    assert classify("Cannot connect to proxy http://127.0.0.1:8888: connection refused") is None
    assert classify("Connection to localhost proxy failed", status=503) is None
    assert classify("Local proxy connection timed out", status=503) is None
    assert classify("Proxy connection error", status=503) is None
    assert classify("Local proxy connection failure", status=503) is None
    assert classify("Connection refused to http://[::1]:8888", status=503) is None
    assert classify("Anthropic HTTP 429 Too many requests") is None
    assert classify("Too many requests", status=429) is None
    assert classify("Bad request", status=400) is None
    assert classify("Tool execution failed before completion") is None


def test_usage_limit_and_sign_in() -> None:
    assert classify('ChatGPT/Codex HTTP 429 {"type":"usage_limit_reached"}').kind == "plan_limit"
    assert classify('Anthropic HTTP 429 {"type":"insufficient_quota"}').kind == "plan_limit"
    assert classify("Claude HTTP 429 usage limit reached.").kind == "plan_limit"
    assert classify("Invalid credentials", status=401).kind == "signed_out"
    assert classify("Forbidden", status=403).kind == "signed_out"
    assert classify("invalidated oauth token").kind == "signed_out"
    assert classify("Not logged in - Please run /login").kind == "signed_out"
    assert classify("sign-in expired").kind == "signed_out"
    assert classify("session has expired").kind == "signed_out"


def test_chat_needs_two_distinct_requests_in_ten_minutes() -> None:
    now = [1000.0]
    tracker = EpisodeTracker(clock=lambda: now[0])
    failure = classify("Our servers are currently overloaded")
    assert tracker.failure("anthropic", "chat", "one", failure) is None
    now[0] += 30
    assert tracker.failure("anthropic", "chat", "one", failure) is None
    now[0] += 30
    episode = tracker.failure("anthropic", "chat", "two", failure)
    assert episode is not None and episode.provider == "anthropic"
    assert tracker.open_episodes["anthropic"].id == episode.id


def test_chat_strikes_expire_and_success_resets_them() -> None:
    now = [1000.0]
    tracker = EpisodeTracker(clock=lambda: now[0])
    failure = classify("over capacity")
    assert tracker.failure("claude", "chat", "one", failure) is None
    tracker.success("claude")
    assert tracker.failure("claude", "chat", "two", failure) is None
    now[0] += 601
    assert tracker.failure("claude", "chat", "three", failure) is None


def test_build_autopilot_and_immediate_trouble_open_on_one_failure() -> None:
    tracker = EpisodeTracker(clock=lambda: 1000.0)
    failure = classify("high demand")
    assert tracker.failure("build-model", "build", "run-1", failure) is not None
    assert tracker.failure("auto-model", "autopilot", "run-2", classify("Down", status=503)) is not None
    assert tracker.failure("plan-model", "chat", "turn-1", classify('HTTP 429 {"code":"quota_exceeded"}')) is not None
    assert tracker.failure("login-model", "chat", "turn-1", classify("No access", status=401)) is not None


def test_success_closes_and_reopening_within_ten_minutes_keeps_id() -> None:
    now = [1000.0]
    tracker = EpisodeTracker(clock=lambda: now[0])
    trouble = classify("overloaded")
    first = tracker.failure("codex", "build", "one", trouble)
    tracker.success("codex")
    assert "codex" not in tracker.open_episodes
    now[0] += 599
    again = tracker.failure("codex", "build", "two", trouble)
    assert again.id == first.id
    assert again.closed_at is None


def test_inactivity_closes_and_reopen_window_uses_close_time() -> None:
    now = [1000.0]
    tracker = EpisodeTracker(clock=lambda: now[0])
    trouble = classify("overloaded")
    first = tracker.failure("codex", "build", "one", trouble)
    now[0] += 1201
    assert tracker.open_episodes == {}
    now[0] += 599
    assert tracker.failure("codex", "build", "two", trouble).id == first.id
    now[0] += 1801
    assert tracker.failure("codex", "build", "three", trouble).id != first.id


def test_save_load_open_episode(tmp_path) -> None:
    path = tmp_path / "trouble.json"
    now = [1000.0]
    tracker = EpisodeTracker(clock=lambda: now[0], path=path)
    first = tracker.failure("anthropic", "autopilot", "run-1", classify("server_is_overloaded"))
    tracker.save()
    loaded = EpisodeTracker(clock=lambda: now[0], path=path)
    loaded.load()
    assert loaded.open_episodes["anthropic"].id == first.id
    assert loaded.open_episodes["anthropic"].trouble.kind == "overloaded"
    assert loaded.failure("anthropic", "build", "run-2", classify("over capacity")).id == first.id
