### Added

- **Praxis checks a dispatch without re-deciding it.** `thomas/core/praxis/dispatch_validate.py` validates the enums, the named project and the acceptance citations on a `send_task` payload. A specialist that looks wrong for the kind is reported as a note, never silently reclassified, because quietly overriding the model's structured decision is the failure this design exists to prevent.
- **Validation can never become a refusal.** Once two repair attempts in one turn are spent the task dispatches anyway, with the uncited acceptance items dropped and the best reachable end state degraded to `completed_unverified`, so a validator can never harden into a way for Thomas to say it cannot do something.
