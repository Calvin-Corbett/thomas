### Fixed

- Native Improve Thomas tasks now use server-bound private candidates with an explicit file scope, independent checks, reviewed Apply, exact dirty-file Undo, and restart controls. Canonical runner imports and runtime protection stay anchored to the running source. Candidates cannot promote changes to verification or protection authority.

- Build helpers can receive an explicit, bounded set of context files for large projects. Their receipt distinguishes selected context from a complete project snapshot; one-file write ownership and stale-target rejection remain enforced.

- Connected the Build library entry and run-bound review, Apply, Undo and restart controls; corrected the modal placement and opaque background in the real browser.

- Allow native self-edit in its default confined workspace, preserve the exact existing startup hook during independent checks, and show active private-copy status while working. New or changed verification hooks and unrestricted native file access still refuse.
