from thomas.marketplace.observability.journal import journal_skip_reason, should_create_journal


def test_journal_skip_reason_disabled() -> None:
    assert journal_skip_reason("build this feature", {"path": "coding"}, enabled=False) == "journal_disabled"


def test_journal_skip_reason_short_prompt() -> None:
    assert journal_skip_reason("hi", {"path": "coding"}, enabled=True) == "prompt_too_short"


def test_journal_skip_reason_skipped_route() -> None:
    assert journal_skip_reason("this is long enough", {"path": "casual"}, enabled=True) == "route_skipped:casual"


def test_should_create_journal_for_real_task() -> None:
    assert should_create_journal("implement websocket reconnection", {"path": "coding"}, enabled=True)
