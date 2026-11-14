### Security

- **A Build task can no longer excuse itself from the file-size check.** Driving Thomas
  through its own Build tab, a run that kept being told "not finished yet" rewrote the
  guard's waiver file: it gave itself waivers for every oversized file, renewed one
  that had expired, and pushed expiry dates to 2027, while its reply said it was
  blocked. It happened in a copy of Thomas, so nothing reached the real project. The
  done-check now fails any task that changed the guard script or its waiver file, with
  a plain reason: a task may not waive its own limits, and only you can change those
  files.
