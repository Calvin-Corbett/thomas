# Paper Trading

A Thomas command center for **simulated** stock & ETF trading. Thomas can research
the market and **propose** trades — but **you approve every order**, and nothing
ever touches real money.

## What it does

- **Reads the market** (account, positions, quotes, price bars) from a free Alpaca
  paper account, or a built-in offline simulator when no keys are set.
- **Proposes trades with a thesis.** Every proposal records *why* (thesis) and
  *what would prove it wrong* (invalidation). The model can only propose.
- **Human approval gate.** You approve or reject each proposal in this workspace.
  Only an approved proposal is ever sent to the broker.
- **Risk rules** check every proposal before you see it: per-order cap, position
  concentration, daily trade count, a penny-stock guard, and market hours.
- **Learns over time.** Closed trades are scored against their thesis and written
  to Thomas's memory, so future proposals are informed by past calls.

## Safety

This module is **paper-only by construction**. The trading endpoint is a hardcoded
Alpaca *paper* URL, re-asserted before every request; there is no "go live" flag.
Going to real money would be a deliberate, reviewed code change — not a setting.

## Setup (free)

1. Create a free account at <https://alpaca.markets> and generate **paper** API keys.
2. Open this workspace and paste the key + secret (stored locally), or set env vars
   `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` (env takes precedence).
3. With no keys configured, the module runs against a deterministic **simulator** so
   you can try the full loop immediately.

## How Thomas uses it

Agent tools: `paper_trading.account`, `.positions`, `.quote`, `.bars`,
`.propose`, `.list_proposals`, `.submit` (approved only), and `.review` (score the
track record). The iterative loop is: research → propose → *you approve* → execute
→ score → review → propose better.

## Risk defaults

Max $1,000 per order · max 20% of the account in any one symbol · max 10 trades/day ·
stocks & ETFs ≥ $1 · regular market hours only. Override via `THOMAS_PAPER_*` env vars.
