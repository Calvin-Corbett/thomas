### Changed

- **Every model call can now come from one place.** Thomas gains a shared models slot (`thomas/core/llm_slot.py`) that builds the same client each call site builds today, so nothing you use behaves differently yet. The kernel's `LLMSeam` asked for a `stream` call that the client never had; it now describes what the client really offers, and tests fail if a provider stops meeting it. The 25 places that build a client directly move onto the slot in later commits.
