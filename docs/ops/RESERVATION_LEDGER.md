# The reservation ledger

Last updated: 2026-10-12

## What it is

One file that every Thomas server on this machine reads and writes before it starts a test process for a check: your
own server and the caged one. A check splits its tests into shards, one pytest process each. Each shard takes a place
from the ledger first, and the ledger hands out at most P places across both servers together (P is the smaller of the
two servers' own figures). Each server also records its own P there. Only the shards of a check use it today.

It lives in the one folder both servers share, beside `hand_in_holds.json`:

    <the checkout>\.thomas\evolve\agent\reservations.json

Next to it you will find `reservations.json.lock` (the lock both servers take for every read and write) and one
`owner-<pid>-<token>.lock` for each running server (a server holds its own for its whole life; a stopped server's is
removed by the next look). A row whose server has stopped is dropped by itself, so a crash needs no clean-up.

## Signs the file is corrupt

The file must be a list of whole rows. A server never treats a file it cannot read as an empty ledger, because the next
write would erase the other server's rows. You will see:

- Changes held before their card, with a reason such as "Not checked before this card: some of the tests could not be
  started ... the pool's reservation ledger could not be used, so the shard did not start: ...\reservations.json cannot
  be read". The code calls this failure `LedgerUnreadable`.
- The same words in the server log: "a check shard was not started: the pool's reservation ledger could not be used".

A held change is not marked as failed and does not count as a strike. It is tried again.

## How to recover

A server moves a file it cannot read aside, to `reservations.json.corrupt-<seconds>-<token>`, and starts an empty
ledger, when nothing could have rows in it: no job of its own holds a row, and no other running server began using the
ledger before the file was last written. Servers that both began after the damage recover it with no help from you.
When one began before, it may hold rows in the file, so the file is left alone until you do one of these:

1. Make sure no check's shards still run (no pytest processes started by a check), then rename the file to
   `reservations.json.corrupt-<date>`. The next look starts an empty ledger.
2. Or stop one server. The other moves the file aside on its next look, once none of its own checks still holds a
   place.

The rule trusts file times to move forward. If the computer's clock is ever set back, or the file is restored from a
copy that keeps its old time, restart both servers before checks run again.

## A server that froze while holding the lock

Every ledger call waits up to 60 seconds for the file lock. If a server froze while it held `reservations.json.lock`,
the shards waiting in each server are refused one after another, each about 60 seconds after the one before it ("stayed
locked for 60 s"), and the held changes pile up. End the
frozen server process (the one that is not answering); the lock goes when its process does.

## The off switch

`THOMAS_PRECARD_PARALLEL=off` (or `0`, `false`, `no`) sends checks back to the earlier way: one check at a time
on each server, each side split over as many pytest processes as that server's own memory formula allows (fewer than
the shared pool), and the ledger is never read. It is read by each server process on its own, so setting it for
one leaves the other using the pool. To turn the pool off everywhere, set it for both servers' accounts (yours and the
caged one) and restart both.

## One ledger folder

Every process that runs real checks must use the same folder, or its shards are invisible to the servers and the
machine can be loaded past P and past the disk floor.

- A tool that runs real checks, such as `scripts/praxis/check_load.py`, runs from the live checkout, or has
  `THOMAS_CAPACITY_LEDGER_ROOT` set to the live ledger's folder (the `agent` folder above).
- Never set `THOMAS_CAPACITY_LEDGER_ROOT` in a live server. It is for tests and tools: a server that sets it splits
  itself off from the other server's ledger.

## Keep the folder's permissions

Both accounts need to read, write and create files in the `agent` folder. Leave its permissions as they are, and do
not recreate or move the folder: a copy that loses them leaves one server unable to open the file, and its shards are
refused until the permissions are back.

## Restarting

Restart a server between checks when you can. The ledger gives back a stopped server's rows by itself, but a check that
was cut off mid-run has to start over.
