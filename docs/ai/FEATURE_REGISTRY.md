# Feature Registry

This registry tracks intentional feature domains and current implementation
maturity.

| Domain | Filesystem Path | Status | Public Entrypoints | Purpose |
|---|---|---|---|---|
| Agriculture | `thomas/agriculture` | skeleton | `thomas.agriculture` | Farm planning, crop and soil workflows |
| Autonomous Vehicles | `thomas/autonomous_vehicles` | skeleton | `thomas.autonomous_vehicles` | AV planning, safety, simulation |
| Food Tech | `thomas/food_tech` | skeleton | `thomas.food_tech` | Nutrition, meal and recipe workflows |
| HR Platform | `thomas/hr_platform` | skeleton | `thomas.hr_platform` | Employee, payroll, leave, recruitment |
| Legal | `thomas/legal` | skeleton | `thomas.legal` | Case, contract, billing, discovery workflows |
| Quant Finance | `thomas/quantfin` | skeleton | `thomas.quantfin` | Pricing, risk, backtesting, orderbook |
| Real Estate | `thomas/real_estate` | skeleton | `thomas.real_estate` | Leasing, market, valuation, investment |
| Supply Chain | `thomas/supply_chain` | skeleton | `thomas.supply_chain` | Demand, inventory, logistics, transport |
| Travel | `thomas/travel` | skeleton | `thomas.travel` | Flights, hotels, itinerary, loyalty |
| Group Chat | `thomas/groupchat` | skeleton | `thomas.groupchat` | Multi-participant discussion flows |
| Conversations | `thomas/conversations` | skeleton | `thomas.conversations` | Nested conversation and speaker control |
| Human Loop | `thomas/human_loop` | skeleton | `thomas.human_loop` | Escalation, approvals, human handoff |
| Learning | `thomas/learning` | skeleton | `thomas.learning` | Lesson capture, feedback loops |
| Sandbox | `thomas/sandbox` | skeleton | `thomas.sandbox` | Isolated code execution surfaces |

## Status Legend

- `skeleton`: import-safe scaffolding present, behavior not complete.
- `in_progress`: partial behavior exists, coverage and stability in progress.
- `implemented`: behavior and validation considered production-ready.
