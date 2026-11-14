"""The ratchet: Thomas lands his own backlog, one proven candidate at a time.

You asked: "we have a shit load of commits that arent l;anded. thats an
autpomatic process thomas can run". dev only moves forward, and only by proof:
a candidate lands when, on dev's current tip, its proof shows no test failing
that does not already fail there, and only through your promoter card. Every
candidate ends in exactly one recorded state (``ledger``).

A candidate goes through these modules in this order:

* ``candidates`` -- what is on refs and not on dev, and in what order to prove it;
* ``screen`` -- what merging it onto dev would do, measured without a checkout;
* ``proof_set`` / ``proof`` -- which tests prove it, run in the cage, read from JUnit;
* ``attempt`` -- the candidate merged in a green, proven, and handed to your card;
* ``landing`` / ``archive`` -- your card's verdict, confirmed in git, and the landed refs given a
  second name under ``refs/archive/ratchet/``; no branch is ever deleted;
* ``repair`` -- a Build team in the same green when the merge needs a model;
* ``service`` / ``report`` -- the daily run, the lease, and what the page and Chat read.
"""
