### Fixed

- **The Docker production image can resolve its lock file again.** `docker build .`
  and `docker compose up` install `requirements-lock.txt`, and pip stopped with
  `ResolutionImpossible`: the May security bump raised Twisted and pypdf without
  raising what they depend on. Twisted 26.4.0 needs `attrs>=22.2.0`,
  `automat>=24.8.0` and `incremental>=24.7.0` (the file held 21.2.0, 20.2.0 and
  21.3.0), pipx 1.0.0 needs `argcomplete>=1.9.4` (it held 1.8.1), pyasn1-modules
  0.2.1 requires `pyasn1<0.5` while the file pins pyasn1 0.6.3 (it now holds
  pyasn1-modules 0.4.2), and camelot-py 1.0.9 needs `pypdf<6`. Those five pins are
  raised to releases that agree with each other, and camelot-py is dropped so pypdf
  stays on 6.10.2. pip's resolver now accepts each group, and
  `tests/test_a_production_lock_file_does_not_contradict_itself.py` fails on the old
  file. The Docker daemon was not run, so the image itself has not been built yet.

### Removed

- **camelot-py is no longer installed in the Docker production image.** Nothing in
  Thomas imports it, and keeping it would hold pypdf below 6, which undoes the
  security bump.
