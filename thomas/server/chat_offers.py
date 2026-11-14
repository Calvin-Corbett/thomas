"""What chat offers other plugins by name (thomas.core.kernel.late). The server shell loads this."""

from __future__ import annotations

from thomas.core.kernel import late, seams
from thomas.server import chat_delegation, chat_delegation_session, chat_self_project

late.provide(seams.START_DELEGATION, lambda app, **kwargs: chat_delegation.start_background_delegation(app, **kwargs))
late.provide(seams.STEER_DELEGATION, lambda *args, **kwargs: chat_delegation.apply_task_update(*args, **kwargs))
late.provide(seams.DELEGATION_RECORD, lambda record: chat_delegation_session._normalize_record(record))
late.provide(seams.BUILD_SETTINGS, lambda **kwargs: chat_self_project.build_settings(**kwargs))
late.provide(
    seams.FOLLOW_AFTER_RESTART, lambda *args, **kwargs: chat_self_project.follow_after_restart(*args, **kwargs)
)
