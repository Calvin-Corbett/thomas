### Fixed

- Work onboarding now persists intermediate phases in order when a streamed response advances from goal discovery to workflow configuration, preventing the store from rejecting a skipped mapping phase without relaxing its transition checks.
- The browser retains each acknowledged onboarding phase so a failed later save can retry from the last successful transition. Regression coverage replays the browser's phase updates against `WorkStore` and checks that successful progress emits no UI issue report.
