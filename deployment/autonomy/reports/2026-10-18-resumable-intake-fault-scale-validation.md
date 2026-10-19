# Resumable intake fault and scale validation

Date: 2026-10-18

## Scope

This increment validates the first resumable scientific-intake slice without
creating large test data or changing production.  Large workloads are modeled
as logical reservations; byte-path tests use at most one 8 MiB chunk.

## Automated evidence

The fault suite proves:

- a 3 GiB declaration reserves capacity with a manifest smaller than 16 KiB
  and allocates no payload file;
- an interrupted two-chunk upload exposes committed progress, accepts an
  idempotent retry, transfers only the missing chunk, and reconstructs the
  exact original bytes;
- whole-file verification detects same-length corruption of a committed chunk
  and leaves the session open rather than exposing an assembled result;
- the configured free-space reserve is enforced both when reserving a session
  and immediately before a chunk write;
- disappearance of the configured intake mount fails closed during session
  creation, upload, and finalize, without recreating the mount path locally;
- two concurrent creators racing for the final session slot produce exactly
  one reservation and one bounded-capacity rejection.

The focused resumable-intake suite passes: **11 passed**.

## Restart-recovery contract

Session manifests and committed chunks reside beneath the configured intake
volume.  Recovery reads the durable manifest on each request; it does not rely
on browser memory or an in-process session table.  The interruption test
therefore simulates a fresh request after lost client state and verifies that
the server reports the committed byte count and missing chunk correctly.

## Remaining release gates

These items are intentionally not represented as completed:

1. Replace the process-local lock with cross-process locking or transactional
   reservation accounting before enabling multiple gateway workers.
2. Add an operator-attested volume identity.  A missing path fails closed now,
   but a writable local directory deliberately placed at the same configured
   mount path cannot yet be distinguished from the intended CEDAR mount.
3. Add startup reconciliation for interrupted assembly, receipt creation,
   release rename, catalog registration, and repeated finalize requests.
4. Add an audited, symlink-safe abandoned-session janitor with dry-run mode.
5. Exercise inode, account, dataset, and aggregate quotas in addition to the
   current file count, byte count, free-space, session, and reserved-byte caps.
6. Run the documented 1 TiB / 10,000-file test against an isolated CEDAR test
   volume and record throughput, p95 latency, memory, temporary amplification,
   recovery time, CEDAR load, and indexing duration.  CI should continue using
   logical fixtures rather than materializing that volume.
7. Perform isolated backup/restore and prove that restored open sessions resume
   without escalating publication state.

No service was restarted and no production or CEDAR data was changed by this
validation increment.
