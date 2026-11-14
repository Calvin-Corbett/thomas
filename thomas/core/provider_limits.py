"""What a refused model call actually said: which limit, whose it is, and when it resets.

One reader for every surface that has to explain a 429 to you. The provider
transports word a refusal as ``<provider> HTTP 429 ...`` followed by the
provider's own error body (``thomas/core/llm_streaming.py``,
``llm_streaming_anthropic.py``, and the Claude CLI's plan limit through
``thomas/core/claude_plan.py``), and that one string is all any of these
surfaces ever gets:

* Autopilot's pause (``thomas/server/autopilot_park.py``) read a plan name, a
  quota code and a reset time out of it and said "Paused: your ChatGPT Pro
  usage limit is reached. It resets Saturday 26 September at 08:02".
* Chat's failure text (``thomas/marketplace/orchestrator/response_failures.py``)
  read nothing out of the same string and answered "The selected model is
  temporarily rate-limited. Please wait a moment or choose another model."

You met the second one on a plan limit with 36 hours left to run: "The limit
lasts until Saturday morning, not a moment, and there was no other model I
could choose." Both surfaces now read the string here, so neither can describe
a limit the other would describe differently.

Nothing in this module reaches the network or the clock except through ``at``,
so a caller can ask what a recorded failure said long after it happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# The provider error codes that mean "this account is out", not "slow down".
# Canonical here because three layers consult them: ``LLMError.quota_hint``
# (thomas/core/llm_shared.py), Praxis's classifier (thomas/server/praxis/quota.py)
# and the readers below.
QUOTA_CODES = frozenset(
    {
        "insufficient_quota",
        "quota_exceeded",
        "usage_limit_exceeded",
        "usage_limit_reached",
        "billing_hard_limit_reached",
        "resource_exhausted",
    }
)

# How the transports name themselves in a failure, and the account name a person
# recognises. A profile's own provider string ("openai_codex") is never shown.
PROVIDER_ACCOUNTS = {"ChatGPT/Codex": "ChatGPT", "Anthropic": "Anthropic", "Claude": "Claude"}

_FAILURE = re.compile(r"(?:(?P<provider>ChatGPT/Codex|Anthropic|Claude) )?HTTP (?P<status>\d{3})\b")
_CODE = re.compile(r'"(?:type|code)"\s*:\s*"([A-Za-z_-]+)"')
_PLAN = re.compile(r'"plan_type"\s*:\s*"([A-Za-z_ -]+)"')
_ESTIMATED = re.compile(r'"resets_at_estimated"\s*:\s*true')  # read from words, an hour late to be sure
# Whole numbers only: a truncated body leaves no delimiter after the digits, and so no match. Every
# transport cuts the provider's body (240 characters for a 429), so a half-read number must not count.
_RESETS_AT = re.compile(r'"resets_at"\s*:\s*(\d{10}(?:\.\d+)?)(?=\s*[,}])')
_RESETS_IN = re.compile(r'"resets_in_seconds"\s*:\s*(\d+(?:\.\d+)?)(?=\s*[,}])')
_RETRY_AFTER = re.compile(r"Retry after about (\d+)s")

MAX_AHEAD_S = 31 * 86400.0  # a reset further off than this is not believed
PLAN_LIMIT_MARGIN_S = 600.0  # a reset this far out is an account limit, not a burst (praxis.quota agrees)


def _believed(value: str, at: float, *, absolute: bool) -> float | None:
    """A reset in the past, or implausibly far off, is no reset at all."""
    try:
        moment = float(value) if absolute else at + float(value)
    except ValueError:
        return None
    return moment if at - 60 <= moment <= at + MAX_AHEAD_S else None


@dataclass(frozen=True)
class ModelLimit:
    """One refused model call, as facts rather than as a sentence."""

    provider: str  # as the transport named itself: "ChatGPT/Codex", "Anthropic", "Claude", or ""
    status: int
    codes: frozenset[str]
    plan: str  # the provider's own plan name, title-cased ("Pro", "Max"), or ""
    resets_at: float | None  # Unix seconds, believed
    resets_in_s: float | None  # seconds from the failure, believed; only when no absolute time was given
    estimated: bool  # the time was read from printed words in a zone this machine cannot look up

    @property
    def quota_code(self) -> str:
        """The account-exhaustion code the body carried, or "" when it carried none."""
        return next(iter(sorted(self.codes & QUOTA_CODES)), "")

    @property
    def reset_known(self) -> bool:
        return self.resets_at is not None or self.resets_in_s is not None

    @property
    def headers(self) -> dict[str, str]:
        """The reset as ``praxis.quota`` reads it, so one classifier judges every surface."""
        if self.resets_at is not None:
            return {"x-ratelimit-reset": f"{self.resets_at:.0f}"}
        if self.resets_in_s is not None:
            return {"retry-after": f"{self.resets_in_s:.0f}"}
        return {}

    @property
    def account(self) -> str:
        """Whose limit this is, as you would name it ("ChatGPT Pro", "Claude"), or "" when it named nobody."""
        name = PROVIDER_ACCOUNTS.get(self.provider, "")
        return f"{name} {self.plan}".strip() if name else ""

    def reached_at(self, at: float) -> float | None:
        """When it resets, in Unix seconds, however the body expressed it."""
        if self.resets_at is not None:
            return self.resets_at
        if self.resets_in_s is not None:
            return at + self.resets_in_s
        return None

    def is_account_limit(self, at: float) -> bool:
        """The account is out of allowance, rather than momentarily too fast.

        Either the provider said so with a quota code, or the reset it gave is
        further away than any burst limit ever is. The same two tests
        ``praxis.quota.QuotaClassifier`` applies -- minus its 429-streak rule,
        which needs a history one failure does not have.
        """
        if self.quota_code:
            return True
        moment = self.reached_at(at)
        return moment is not None and moment - at > PLAN_LIMIT_MARGIN_S


def read_limit(text: str, *, at: float) -> ModelLimit | None:
    """The limit a failure text describes, or None when it describes no HTTP failure.

    Reads from the failure marker onward, so prose wrapped around the error
    ("Reasoning failed: ...") cannot contribute a number.
    """
    failure = _FAILURE.search(str(text or ""))
    if failure is None:
        return None
    detail = str(text)[failure.start() :]
    resets_at = _believed(next(iter(_RESETS_AT.findall(detail)), ""), at, absolute=True)
    relative = _RESETS_IN.findall(detail) or _RETRY_AFTER.findall(detail)
    after_raw = "" if resets_at is not None else next(iter(relative), "")
    after = _believed(after_raw, at, absolute=False) if after_raw else None
    return ModelLimit(
        provider=failure.group("provider") or "",
        status=int(failure.group("status")),
        codes=frozenset(code.lower().replace("-", "_") for code in _CODE.findall(detail)),
        plan=next(iter(_PLAN.findall(detail)), "").replace("_", " ").strip().title(),
        resets_at=resets_at,
        resets_in_s=None if after is None else max(0.0, after - at),
        estimated=resets_at is not None and bool(_ESTIMATED.search(detail)),
    )


def when_words(moment: float) -> str:
    """A reset time in your words: "Saturday 26 September at 08:02".

    The server runs on your machine, so its local time is yours.
    """
    local = datetime.fromtimestamp(moment)
    return f"{local:%A} {local.day} {local:%B} at {local:%H:%M}"
