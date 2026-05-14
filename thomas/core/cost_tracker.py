from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore


# ----------------------------
# Default pricing (USD / 1K tokens)
# ----------------------------

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    # OpenAI examples (adjust to your needs)
    "gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015},
    "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    # Anthropic-ish examples
    "claude-3-5-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    # Gemini-ish examples
    "gemini-1.5-pro": {"input_per_1k": 0.00125, "output_per_1k": 0.005},
}

FALLBACK_UNKNOWN: dict[str, float] = {"input_per_1k": 0.002, "output_per_1k": 0.002}


# ----------------------------
# Best-effort file locking (cross-platform)
# ----------------------------

class _FileLock:
    def __init__(self, f, exclusive: bool = True) -> None:
        self._f = f
        self._exclusive = exclusive

    def __enter__(self):
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore
                # Windows locking doesn't have true shared locks; use exclusive.
                msvcrt.locking(self._f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl  # type: ignore
                flag = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
                fcntl.flock(self._f.fileno(), flag)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # type: ignore
                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        return False


# ----------------------------
# Token usage normalization
# ----------------------------

def _get(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def extract_token_usage(any_obj: Any) -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from common provider response shapes.

    - OpenAI: response.usage.prompt_tokens / completion_tokens
    - Anthropic: response.usage.input_tokens / output_tokens
    - Gemini: response.usage_metadata.prompt_token_count / candidates_token_count
    - Dict equivalents also supported
    """
    if any_obj is None:
        return (0, 0)

    # direct dict usage
    if isinstance(any_obj, dict):
        for pk, ck in (
            ("prompt_tokens", "completion_tokens"),
            ("input_tokens", "output_tokens"),
            ("prompt", "completion"),
            ("input", "output"),
        ):
            if pk in any_obj or ck in any_obj:
                p = int(any_obj.get(pk, 0) or 0)
                c = int(any_obj.get(ck, 0) or 0)
                if p or c:
                    return (max(p, 0), max(c, 0))

        # gemini-ish
        p = any_obj.get("prompt_token_count")
        c = any_obj.get("candidates_token_count")
        if p is not None or c is not None:
            return (max(int(p or 0), 0), max(int(c or 0), 0))

        t = any_obj.get("total_token_count")
        if t is not None:
            tt = max(int(t or 0), 0)
            return (tt, 0)

        # nested usage
        nested = any_obj.get("usage") or any_obj.get("usage_metadata")
        if nested is not None:
            return extract_token_usage(nested)

    # SDK responses usually have .usage
    usage = _get(any_obj, "usage")
    if usage is not None and usage is not any_obj:
        pt, ct = extract_token_usage(usage)
        if pt or ct:
            return (pt, ct)

    # openai style
    pt = _get(any_obj, "prompt_tokens")
    ct = _get(any_obj, "completion_tokens")
    if pt is not None or ct is not None:
        return (max(int(pt or 0), 0), max(int(ct or 0), 0))

    # anthropic style
    it = _get(any_obj, "input_tokens")
    ot = _get(any_obj, "output_tokens")
    if it is not None or ot is not None:
        return (max(int(it or 0), 0), max(int(ot or 0), 0))

    # gemini style
    um = _get(any_obj, "usage_metadata")
    if um is not None and um is not any_obj:
        p = _get(um, "prompt_token_count")
        c = _get(um, "candidates_token_count")
        if p is not None or c is not None:
            return (max(int(p or 0), 0), max(int(c or 0), 0))
        t = _get(um, "total_token_count")
        if t is not None:
            return (max(int(t or 0), 0), 0)

    return (0, 0)


# ----------------------------
# Records + pubsub for SSE
# ----------------------------

@dataclass(frozen=True)
class SpendRecord:
    ts: str
    day: str
    model: str
    provider: str
    prompt_tokens: int
    completion_tokens: int
    usd_prompt: float
    usd_completion: float
    usd_total: float

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "ts": self.ts,
                "day": self.day,
                "model": self.model,
                "provider": self.provider,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "usd_prompt": self.usd_prompt,
                "usd_completion": self.usd_completion,
                "usd_total": self.usd_total,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


class SpendSubscriber:
    """Small in-memory subscriber queue for SSE."""

    def __init__(self, maxlen: int = 256) -> None:
        from collections import deque

        self._q = deque(maxlen=maxlen)
        self._cv = threading.Condition()
        self._alive = True

    def close(self) -> None:
        with self._cv:
            self._alive = False
            self._cv.notify_all()

    def put(self, payload: dict) -> bool:
        with self._cv:
            if not self._alive:
                return False
            self._q.append(payload)
            self._cv.notify()
            return True

    def get(self, timeout_s: float = 15.0) -> dict | None:
        with self._cv:
            if not self._alive:
                return None
            if self._q:
                return self._q.popleft()
            self._cv.wait(timeout=timeout_s)
            if self._q:
                return self._q.popleft()
            return None


# ----------------------------
# CostTracker
# ----------------------------

class CostTracker:
    """Token/cost tracker with JSONL persistence + fast aggregates.

    Files:
      - JSONL ledger: thomas_spend.jsonl (env: THOMAS_SPEND_PATH)
      - Pricing config: thomas.toml (env: THOMAS_TOML_PATH)

    Pricing precedence:
      1) [pricing."provider:model"] (or provider/model)
      2) [pricing.model]
      3) [pricing.defaults]
      4) FALLBACK_UNKNOWN
    """

    def __init__(self, spend_path: Path | None = None, toml_path: Path | None = None) -> None:
        self._lock = threading.Lock()

        repo_root = Path(__file__).resolve().parents[2]
        self._spend_path = spend_path or Path(os.environ.get("THOMAS_SPEND_PATH", str(repo_root / "thomas_spend.jsonl")))
        self._toml_path = toml_path or Path(os.environ.get("THOMAS_TOML_PATH", str(repo_root / "thomas.toml")))

        self._pricing: dict[str, dict[str, float]] = {}
        self._fallback_unknown: dict[str, float] = dict(FALLBACK_UNKNOWN)
        self._load_pricing()

        # persisted aggregates
        self._daily_usd: dict[str, float] = {}
        self._daily_calls: dict[str, int] = {}
        self._daily_prompt_tok: dict[str, int] = {}
        self._daily_completion_tok: dict[str, int] = {}
        self._daily_model_usd: dict[str, dict[str, float]] = {}
        self._daily_model_calls: dict[str, dict[str, int]] = {}
        self._daily_model_prompt: dict[str, dict[str, int]] = {}
        self._daily_model_completion: dict[str, dict[str, int]] = {}

        # incremental parse state
        self._processed_pos = 0
        self._file_size = 0
        self._file_mtime_ns = 0

        # session aggregates (in-process)
        self._session_usd = 0.0
        self._session_calls = 0
        self._session_prompt_tok = 0
        self._session_completion_tok = 0
        self._session_model_usd: dict[str, float] = {}
        self._session_model_calls: dict[str, int] = {}
        self._session_model_prompt: dict[str, int] = {}
        self._session_model_completion: dict[str, int] = {}

        # subscribers
        self._subs: set[SpendSubscriber] = set()

        self._refresh_cache(force=True)

    # ---- public API ----

    def record(self, model: str, prompt_tokens: int, completion_tokens: int, provider: str = "") -> None:
        model = (model or "").strip() or "unknown"
        provider = (provider or "").strip()

        pt = int(prompt_tokens or 0)
        ct = int(completion_tokens or 0)
        if pt < 0:
            pt = 0
        if ct < 0:
            ct = 0

        now = datetime.now()
        day_str = now.date().isoformat()
        ts = now.isoformat(timespec="seconds")

        price = self._get_price(model=model, provider=provider)
        usd_prompt = (pt / 1000.0) * float(price["input_per_1k"])
        usd_completion = (ct / 1000.0) * float(price["output_per_1k"])
        usd_total = float(round(usd_prompt + usd_completion, 10))

        rec = SpendRecord(
            ts=ts,
            day=day_str,
            model=model,
            provider=provider,
            prompt_tokens=pt,
            completion_tokens=ct,
            usd_prompt=float(round(usd_prompt, 10)),
            usd_completion=float(round(usd_completion, 10)),
            usd_total=usd_total,
        )

        line = rec.to_json_line() + "\n"

        with self._lock:
            self._spend_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._spend_path, "a", encoding="utf-8") as f, _FileLock(f, exclusive=True):
                f.write(line)
                f.flush()

            # update persisted aggregates (fast path)
            self._apply_row(day_str, model, usd_total, pt, ct)

            # update session aggregates
            self._session_usd += usd_total
            self._session_calls += 1
            self._session_prompt_tok += pt
            self._session_completion_tok += ct

            self._session_model_usd[model] = self._session_model_usd.get(model, 0.0) + usd_total
            self._session_model_calls[model] = self._session_model_calls.get(model, 0) + 1
            self._session_model_prompt[model] = self._session_model_prompt.get(model, 0) + pt
            self._session_model_completion[model] = self._session_model_completion.get(model, 0) + ct

            # bump parse state to EOF
            try:
                st = self._spend_path.stat()
                self._file_size = int(st.st_size)
                self._file_mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
                self._processed_pos = self._file_size
            except FileNotFoundError:
                pass

        self._notify(rec)

    def record_from_any(self, model: str, provider: str, any_usage_or_response: Any) -> None:
        pt, ct = extract_token_usage(any_usage_or_response)
        self.record(model=model, provider=provider, prompt_tokens=pt, completion_tokens=ct)

    def today_usd(self) -> float:
        self._refresh_cache()
        return float(self._daily_usd.get(date.today().isoformat(), 0.0))

    def today_call_count(self) -> int:
        self._refresh_cache()
        return int(self._daily_calls.get(date.today().isoformat(), 0))

    def today_tokens(self) -> dict[str, int]:
        self._refresh_cache()
        d = date.today().isoformat()
        p = int(self._daily_prompt_tok.get(d, 0))
        c = int(self._daily_completion_tok.get(d, 0))
        return {"prompt": p, "completion": c, "total": p + c}

    def by_model(self) -> dict[str, float]:
        self._refresh_cache()
        d = date.today().isoformat()
        raw = self._daily_model_usd.get(d, {})
        return {k: float(v) for k, v in sorted(raw.items(), key=lambda kv: kv[0].lower())}

    def today_by_model_detail(self) -> dict[str, dict[str, Any]]:
        self._refresh_cache()
        d = date.today().isoformat()
        models = set()
        models |= set(self._daily_model_usd.get(d, {}).keys())
        models |= set(self._daily_model_calls.get(d, {}).keys())
        models |= set(self._daily_model_prompt.get(d, {}).keys())
        models |= set(self._daily_model_completion.get(d, {}).keys())

        out: dict[str, dict[str, Any]] = {}
        for m in models:
            usd = float(self._daily_model_usd.get(d, {}).get(m, 0.0))
            calls = int(self._daily_model_calls.get(d, {}).get(m, 0))
            pt = int(self._daily_model_prompt.get(d, {}).get(m, 0))
            ct = int(self._daily_model_completion.get(d, {}).get(m, 0))
            out[m] = {
                "usd": usd,
                "calls": calls,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": pt + ct,
            }
        return dict(sorted(out.items(), key=lambda kv: (-float(kv[1].get("usd", 0.0)), kv[0].lower())))

    def by_day(self, days: int = 7) -> list[dict[str, Any]]:
        self._refresh_cache()
        days = int(days or 7)
        if days < 1:
            days = 1
        if days > 365:
            days = 365

        out: list[dict[str, Any]] = []
        today = date.today()
        start = today - timedelta(days=days - 1)
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            out.append({"date": d, "usd": float(self._daily_usd.get(d, 0.0))})
        return out

    def session_usd(self) -> float:
        return float(self._session_usd)

    def session_call_count(self) -> int:
        return int(self._session_calls)

    def session_tokens(self) -> dict[str, int]:
        p = int(self._session_prompt_tok)
        c = int(self._session_completion_tok)
        return {"prompt": p, "completion": c, "total": p + c}

    def session_by_model_detail(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for m in self._session_model_usd.keys():
            usd = float(self._session_model_usd.get(m, 0.0))
            calls = int(self._session_model_calls.get(m, 0))
            pt = int(self._session_model_prompt.get(m, 0))
            ct = int(self._session_model_completion.get(m, 0))
            out[m] = {"usd": usd, "calls": calls, "prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}
        return dict(sorted(out.items(), key=lambda kv: (-float(kv[1].get("usd", 0.0)), kv[0].lower())))

    def reset_session(self) -> None:
        with self._lock:
            self._session_usd = 0.0
            self._session_calls = 0
            self._session_prompt_tok = 0
            self._session_completion_tok = 0
            self._session_model_usd = {}
            self._session_model_calls = {}
            self._session_model_prompt = {}
            self._session_model_completion = {}

    def pricing_table(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for k, v in self._pricing.items():
            out[k] = {"input_per_1k": float(v["input_per_1k"]), "output_per_1k": float(v["output_per_1k"])}
        out.setdefault("defaults", {"input_per_1k": float(self._fallback_unknown["input_per_1k"]), "output_per_1k": float(self._fallback_unknown["output_per_1k"])})
        return out

    # ---- SSE pubsub ----

    def subscribe(self) -> SpendSubscriber:
        sub = SpendSubscriber()
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: SpendSubscriber) -> None:
        with self._lock:
            self._subs.discard(sub)

    # ---- internals ----

    def _notify(self, rec: SpendRecord) -> None:
        payload = {
            "ts": rec.ts,
            "day": rec.day,
            "model": rec.model,
            "provider": rec.provider,
            "prompt_tokens": rec.prompt_tokens,
            "completion_tokens": rec.completion_tokens,
            "usd_total": rec.usd_total,
            "today_usd": self.today_usd(),
            "today_tokens": self.today_tokens(),
            "today_calls": self.today_call_count(),
        }
        dead: list[SpendSubscriber] = []
        with self._lock:
            for sub in list(self._subs):
                if not sub.put(payload):
                    dead.append(sub)
            for d in dead:
                self._subs.discard(d)

    def _apply_row(self, day: str, model: str, usd_total: float, pt: int, ct: int) -> None:
        self._daily_usd[day] = self._daily_usd.get(day, 0.0) + float(usd_total)
        self._daily_calls[day] = self._daily_calls.get(day, 0) + 1
        self._daily_prompt_tok[day] = self._daily_prompt_tok.get(day, 0) + int(pt)
        self._daily_completion_tok[day] = self._daily_completion_tok.get(day, 0) + int(ct)

        self._daily_model_usd.setdefault(day, {})
        self._daily_model_calls.setdefault(day, {})
        self._daily_model_prompt.setdefault(day, {})
        self._daily_model_completion.setdefault(day, {})

        self._daily_model_usd[day][model] = self._daily_model_usd[day].get(model, 0.0) + float(usd_total)
        self._daily_model_calls[day][model] = self._daily_model_calls[day].get(model, 0) + 1
        self._daily_model_prompt[day][model] = self._daily_model_prompt[day].get(model, 0) + int(pt)
        self._daily_model_completion[day][model] = self._daily_model_completion[day].get(model, 0) + int(ct)

    def _get_price(self, model: str, provider: str = "") -> dict[str, float]:
        m = (model or "").strip()
        p = (provider or "").strip()

        if p:
            for k in (f"{p}:{m}", f"{p}/{m}", f"{p}:{m}".lower(), f"{p}/{m}".lower()):
                if k in self._pricing:
                    return dict(self._pricing[k])

        if m in self._pricing:
            return dict(self._pricing[m])

        lm = m.lower()
        if lm in self._pricing:
            return dict(self._pricing[lm])

        return dict(self._fallback_unknown)

    def _load_pricing(self) -> None:
        merged = {k: dict(v) for k, v in DEFAULT_PRICING.items()}
        fallback = dict(FALLBACK_UNKNOWN)

        raw: dict[str, Any] = {}
        if tomllib is not None:
            try:
                if self._toml_path.exists():
                    raw = tomllib.loads(self._toml_path.read_text(encoding="utf-8"))
            except Exception:
                raw = {}

        pricing = raw.get("pricing", {}) if isinstance(raw, dict) else {}
        if isinstance(pricing, dict):
            defaults = pricing.get("defaults")
            if isinstance(defaults, dict):
                if defaults.get("input_per_1k") is not None:
                    fallback["input_per_1k"] = float(defaults["input_per_1k"])
                if defaults.get("output_per_1k") is not None:
                    fallback["output_per_1k"] = float(defaults["output_per_1k"])

            for key, cfg in pricing.items():
                if key == "defaults" or not isinstance(cfg, dict):
                    continue
                inp = cfg.get("input_per_1k")
                outp = cfg.get("output_per_1k")
                if inp is None and outp is None:
                    continue
                base = merged.get(str(key), merged.get(str(key).lower(), fallback))
                merged[str(key)] = {
                    "input_per_1k": float(inp) if inp is not None else float(base["input_per_1k"]),
                    "output_per_1k": float(outp) if outp is not None else float(base["output_per_1k"]),
                }

        # lowercase aliases
        for k, v in list(merged.items()):
            merged.setdefault(k.lower(), v)

        self._pricing = merged
        self._fallback_unknown = fallback

    def _refresh_cache(self, force: bool = False) -> None:
        """Incremental parse of JSONL ledger. Rebuild on truncation."""
        path = self._spend_path
        try:
            st = path.stat()
        except FileNotFoundError:
            return

        size = int(st.st_size)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        if not force and size == self._file_size and mtime_ns == self._file_mtime_ns:
            return

        with self._lock:
            try:
                st = path.stat()
            except FileNotFoundError:
                return
            size = int(st.st_size)
            mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))

            if size < self._processed_pos:
                # rotated/truncated -> rebuild
                self._daily_usd.clear()
                self._daily_calls.clear()
                self._daily_prompt_tok.clear()
                self._daily_completion_tok.clear()
                self._daily_model_usd.clear()
                self._daily_model_calls.clear()
                self._daily_model_prompt.clear()
                self._daily_model_completion.clear()
                self._processed_pos = 0

            if self._processed_pos >= size and not force:
                self._file_size = size
                self._file_mtime_ns = mtime_ns
                return

            with open(path, "rb") as f, _FileLock(f, exclusive=False):
                f.seek(self._processed_pos)
                blob = f.read()

            if not blob:
                self._file_size = size
                self._file_mtime_ns = mtime_ns
                return

            last_nl = blob.rfind(b"\n")
            if last_nl == -1:
                self._file_size = size
                self._file_mtime_ns = mtime_ns
                return

            parse_blob = blob[: last_nl + 1]
            next_pos = self._processed_pos + (last_nl + 1)

            text = parse_blob.decode("utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    day = str(obj.get("day", "")).strip()
                    model = str(obj.get("model", "unknown")).strip() or "unknown"
                    usd_total = float(obj.get("usd_total", 0.0) or 0.0)
                    pt = int(obj.get("prompt_tokens", 0) or 0)
                    ct = int(obj.get("completion_tokens", 0) or 0)
                    if not day:
                        continue
                except Exception:
                    continue
                self._apply_row(day, model, usd_total, pt, ct)

            self._processed_pos = next_pos
            self._file_size = size
            self._file_mtime_ns = mtime_ns


_cost_tracker_singleton: CostTracker | None = None
_cost_tracker_lock = threading.Lock()


def get_cost_tracker() -> CostTracker:
    global _cost_tracker_singleton
    if _cost_tracker_singleton is not None:
        return _cost_tracker_singleton
    with _cost_tracker_lock:
        if _cost_tracker_singleton is None:
            _cost_tracker_singleton = CostTracker()
    return _cost_tracker_singleton
