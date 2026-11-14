### Fixed

- **Asking Thomas to fix himself now reaches his own code.** On Autopilot you
  asked him to pick the top issue from `self.issues` and fix it. He chose
  correctly and marked the task as self-development, but because it was code,
  Chat sent it to Build anyway, and Build started a brand-new empty project.
  The run could not reach the code it was asked to fix and ended "the run
  crashed before finishing ... no files changed". Build refuses Thomas's own
  source by design, so it was never going to work. Self-development tasks now
  go to the self-development worker, which the design spec names as the
  default for this case. On the second try, the same request started work in
  Thomas's own checkout.
