### Changed

- **A push no longer stops on a protected overhead edit you already approved.** The core overhead guard now judges each pushed commit by its own message: an approval counts only if it is a trailer with a reason in a real local push, or the promoter's block backed by the promoter's own record of that exact commit. An unapproved commit is listed by sha, and a commit-time edit still fails as before.
