### Added
- Work mode runs a job through a step ledger that only a gate verdict can
  advance. The agent keeps every tool; what it cannot do is declare a step
  finished, and the open step's requirement is restated on every turn so a long
  conversation cannot erode it.
- A gate does not count until it has been observed failing. Each one declares an
  input it rejects, and the proof is re-earned every time a lane loads, so a gate
  edited into one that always passes is refused rather than trusted.
- Onboarding shows a step rail built from that same ledger: done, in progress,
  not started, blocked, or skipped-and-not-verified, with the reason named on the
  step that is waiting.
- Thomas proposes changes to its own gates and waits. Each proposal carries the
  evidence that produced it, refusals are remembered against that evidence, and
  applying one needs a Windows sign-in.

### Fixed
- A Work job could be created while its onboarding was still on the goal
  question with no goal written. The onboarding phase machine was strict but
  guarded a route job creation did not take.
- The wizard reported its first step complete the moment it opened, before any
  goal existed, and its later steps lit from the model's own account of its
  progress rather than from anything checked.
- "This workflow is configured" was decided by reading the same field it set, so
  the claim approved itself. Readiness now needs both the model's judgement and
  a workflow choice recorded against a real user turn.
- A recorded workflow choice was erased when the server had not stored it yet,
  which could leave the wizard unable to finish.
