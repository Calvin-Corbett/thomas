# Feature 14 v3 — Real-time Token / Cost Dashboard (Thomas)

This is a drop-in **upgrade** that turns the spend tracking into something you can actually *use*.

## What you get

- Header badge: **$ today + token count**
- Modal dashboard:
  - Today / Session tabs
  - By-model table (USD, tokens, calls)
  - 7-day chart (hover tooltip)
  - 30-day projection (7d avg * 30)
  - Export CSV + reset session
- Live updates:
  - SSE stream at `/api/spend/stream`
  - Polling fallback

## Install

1) Unzip into repo root so `thomas/` merges.
2) Run:

```bash
python tools/apply_feature_14.py
```

3) Restart server

## Wire the tracker (required)

Call this after each LLM response:

```py
from thomas.core.cost_tracker import get_cost_tracker
get_cost_tracker().record_from_any(model=model_name, provider=provider_name, any_usage_or_response=response)
```

Or if you already have tokens:

```py
get_cost_tracker().record(model=model_name, provider=provider_name, prompt_tokens=pt, completion_tokens=ct)
```

## Pricing overrides (thomas.toml)

```toml
[pricing.defaults]
input_per_1k = 0.002
output_per_1k = 0.002

[pricing.gpt-4o]
input_per_1k = 0.005
output_per_1k = 0.015

[pricing."openai:gpt-4o"]
input_per_1k = 0.005
output_per_1k = 0.015
```

## API

- GET `/api/spend/today`
- GET `/api/spend/session`
- POST `/api/spend/session/reset`
- GET `/api/spend/history?days=7`
- GET `/api/spend/export.csv?days=30`
- GET `/api/spend/pricing`
- GET `/api/spend/stream` (SSE)

## Tests

- `tests/test_cost_tracker.py`
- `tests/test_spend_routes.py`
