from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.memory.autonomy import AutonomyMemoryEngine


def _cfg(tmp_path) -> AppConfig:  # noqa: ANN001
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )


def test_v2_retrieval_stays_thread_scoped_for_episodes(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.add_event("telegram:1", "user_message", "Project codename alphafox")
        mem.add_event("telegram:2", "user_message", "Secret launch key zeta-99")

        ctx_same = mem.retrieve("codename alphafox", thread="telegram:1", budget=900, mode="auto")
        ctx_other = mem.retrieve("zeta-99", thread="telegram:1", budget=900, mode="auto")

        assert "alphafox" in ctx_same.text.lower()
        assert "secret launch key zeta-99" not in ctx_other.text.lower()
    finally:
        mem.close()


def test_cross_thread_retrieval_can_use_explicit_global_user_facts(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        episode_id = mem.add_event(
            "telegram:1",
            "user_fact",
            "The deployment target is cloudflare workers",
            metadata={"source": "user_remember"},
        )
        promoted = mem.auto_promote_event_memory(
            thread_id="telegram:1",
            etype="user_fact",
            text="The deployment target is cloudflare workers",
            source_episode_id=episode_id,
        )

        ctx_other = mem.retrieve("deployment target", thread="telegram:2", budget=900, mode="auto")

        assert promoted is True
        assert "cloudflare workers" in ctx_other.text.lower()
    finally:
        mem.close()


def test_ordinary_prose_is_not_promoted_as_global_memory(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        episode_id = mem.add_event(
            "telegram:1",
            "user_message",
            "my deployment target is cloudflare workers",
        )
        promoted = mem.auto_promote_event_memory(
            thread_id="telegram:1",
            etype="user_message",
            text="my deployment target is cloudflare workers",
            source_episode_id=episode_id,
        )

        ctx_other = mem.retrieve("deployment target", thread="telegram:2", budget=900, mode="auto")

        assert promoted is False
        assert "cloudflare workers" not in ctx_other.text.lower()
    finally:
        mem.close()


def test_explicit_memory_writes_are_idempotent_and_do_not_conflict(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        for text in (
            "The launch code is 101",
            "The backup phone ends in 202",
            "The launch code is 101",
        ):
            assert mem.auto_promote_event_memory(
                thread_id="telegram:1",
                etype="user_fact",
                text=text,
            )

        stats = mem.stats()
        assert int(stats.get("v2_facts", 0)) == 2
        assert int(stats.get("v2_contradictions_open", 0)) == 0
    finally:
        mem.close()


def test_assistant_events_do_not_promote_profile_hints(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.add_event("telegram:1", "assistant_message", "My name is Mallory")
        stats = mem.stats()
        assert int(stats.get("v2_profile_hints", 0) or 0) == 0
    finally:
        mem.close()


def test_profile_memory_can_be_enabled_or_disabled_per_thread(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.pin("user.name", "the product owner")

        mem.set_thread_memory_policy("telegram:1", include_profile=True)
        with_profile = mem.retrieve("what is my name", thread="telegram:1", budget=900, mode="auto")
        assert "the product owner" in with_profile.text.lower()

        mem.set_thread_memory_policy("telegram:1", include_profile=False)
        without_profile = mem.retrieve("what is my name", thread="telegram:1", budget=900, mode="auto")
        assert "the product owner" not in without_profile.text.lower()
    finally:
        mem.close()


def test_set_thread_memory_policy_accepts_budget_tokens_alias(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.set_thread_memory_policy("telegram:1", budget_tokens=1600, include_profile=True)
        policy = mem.thread_memory_policy("telegram:1")
        assert policy.get("max_pack_tokens") == 1600
        assert policy.get("include_profile") is True
    finally:
        mem.close()


def test_diagnostics_include_v2_health(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.add_event("telegram:1", "user_message", "hello world")
        diag = mem.diagnostics(thread="telegram:1", trace_limit=5)
        assert isinstance(diag, dict)
        assert diag["stats"]["v2_enabled"] is True
        assert "v2_health" in diag
        assert "v2_thread_settings" in diag
    finally:
        mem.close()


def test_contradictions_list_and_resolve(tmp_path) -> None:  # noqa: ANN001
    mem = AutonomyMemoryEngine(_cfg(tmp_path), enable_legacy=False, enable_v2=True)
    mem.start()
    try:
        mem.pin("user.name", "the product owner")
        mem.pin("user.name", "Kevin")

        rows = mem.list_contradictions(only_open=True, limit=20)
        assert len(rows) >= 1
        cid = int(rows[0]["id"])

        ok = mem.resolve_contradiction(cid, resolved=True)
        assert ok is True

        rows_after = mem.list_contradictions(only_open=True, limit=20)
        ids_after = {int(r["id"]) for r in rows_after}
        assert cid not in ids_after
    finally:
        mem.close()
