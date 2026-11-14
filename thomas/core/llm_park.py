"""What a turn refused by the rate-limit park reports, rather than by the provider.

``LLMClient`` parks a profile after a 429 (its cooldown). The park is capped at ten
minutes and the plan limit that set it can run for a day and a half, so from the
second message onward the park's words -- not the provider's -- are all Chat has to
explain the refusal with. Kept out of ``llm_client.py``, which is at the repo's
800-line limit.
"""

from __future__ import annotations

import time

from thomas.core.llm_shared import LLMError
from thomas.core.provider_limits import read_limit


def parked_text(profile: str, remaining: float, refusal: str) -> str:
    """The park's sentence, with the provider's own refusal repeated after it.

    On its own the park names no limit and no reset, which is exactly what you were
    given ("wait a moment"). Chat and Autopilot both read the limit out of the
    repeated refusal (thomas/core/provider_limits.py) and find nothing to read in the
    park.
    """
    said = str(refusal or "").strip()
    parked = f"Rate-limit cooldown active for profile '{profile}' ({int(remaining)}s remaining)."
    return f"{parked} {said}" if said else parked


def parked_error(profile: str, remaining: float, refusal: str) -> LLMError:
    """The park's refusal, carrying the quota facts the provider's refusal carried.

    A park that raises a bare 429 loses what ``LLMError.quota_hint`` is asked for: a
    task turn treats a 429 with no quota hint as a burst to sit out
    (thomas/agent/loop_execution.py) and says "the provider asked Thomas to pause for
    5.0s; work will resume automatically" -- "wait a moment" in another voice, on a
    limit that runs until Saturday. So the code and reset the remembered refusal
    carried are handed back with it, read by the one reader
    (thomas/core/provider_limits.py). A park that remembers nothing carries nothing,
    and a burst is still sat out.
    """
    limit = read_limit(str(refusal or ""), at=time.time())
    return LLMError(
        parked_text(profile, remaining, refusal),
        status=429,
        retryable=True,
        error_code="" if limit is None else limit.quota_code,
        response_headers={} if limit is None else limit.headers,
    )


__all__ = ["parked_error", "parked_text"]
