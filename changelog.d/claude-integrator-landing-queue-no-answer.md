### Fixed

- **A git that gives no answer is never proof that your change already landed.** The landing queue's git helper now tells "no answer" (a timeout or an error exit) apart from empty output, and the already-landed check reads any missing answer as "not landed". Before, with an earlier landing of the same key on dev, a `git status` that timed out read as "nothing else pending", and blob reads that both timed out compared nothing to nothing, so land.py could say "already landed" and skip the commit tool while your change was still pending.
- **`land.py --no-detach` answers a pre-check refusal in full** (stage, blocker and the path of the whole output), and an error inside the pre-check is logged and treated as advisory instead of ending the worker.
