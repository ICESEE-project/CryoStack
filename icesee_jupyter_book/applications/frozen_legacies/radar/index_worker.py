"""Background indexing worker: one process per indexing run.

The gateway queues a run in the catalog (``index_runs``, status ``queued``)
and starts::

    python -m icesee_jupyter_book.applications.frozen_legacies.radar.index_worker \
        --catalog <catalog.db> --run <run_id>

The worker claims the run (``running``, with its PID), indexes the source
with :func:`radar.indexer.index_source`, and keeps the run row current:

* **progress** -- counts after every batch (at most once a second);
* **heartbeat** -- every few seconds, also while a slow listing page is
  outstanding, so the gateway can tell a live run from a dead one;
* **cancellation** -- the gateway sets ``cancel_requested`` (or sends
  SIGTERM); the run stops after its current batch as ``cancelled``, keeping
  what was indexed and marking nothing missing.

If the worker dies (crash, kill, host restart) its heartbeat stops and the
gateway marks the run ``interrupted`` (:meth:`RadarCatalog.reconcile_runs`).
Because indexing is incremental, a retry continues from what was stored.

The worker only reads the data source; it has no access to user
workspaces. Credentials, for remote providers, come from the server's
environment (e.g. the AWS default credential chain) and are never written
anywhere.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from .catalog import RadarCatalog
from .indexer import _clean_error, index_source
from .storage import StorageError, StorageKeyError, provider_for


HEARTBEAT_S = 5.0
PROGRESS_S = 1.0


class _Run:
    """Progress/heartbeat/cancel bookkeeping shared with the indexer."""

    def __init__(self, catalog: RadarCatalog, run_id: int):
        self.catalog = catalog
        self.run_id = run_id
        self.stop = threading.Event()
        self.counts: dict = {}
        self._last_write = 0.0
        self._lock = threading.Lock()

    def progress(self, counts: dict) -> None:
        with self._lock:
            self.counts = counts
            now = time.monotonic()
            if now - self._last_write < PROGRESS_S:
                return
            self._last_write = now
        self._write()

    def _write(self) -> None:
        try:
            if self.catalog.update_progress(self.run_id, self.counts):
                self.stop.set()
        except Exception as error:          # a busy database must not stop indexing
            print(f"[index-worker] progress not recorded: {error}", file=sys.stderr)

    def heartbeat(self, done: threading.Event) -> None:
        while not done.wait(HEARTBEAT_S):
            self._write()

    def should_stop(self) -> bool:
        return self.stop.is_set()


def run(catalog: RadarCatalog, run_id: int) -> dict:
    row = catalog.get_run(run_id)
    if row is None:
        raise SystemExit(f"run {run_id} does not exist")
    if not catalog.claim_run(run_id, os.getpid()):
        raise SystemExit(f"run {run_id} is not queued (status {row['status']})")
    state = _Run(catalog, run_id)
    signal.signal(signal.SIGTERM, lambda *_: state.stop.set())
    done = threading.Event()
    beat = threading.Thread(target=state.heartbeat, args=(done,), daemon=True)
    beat.start()
    try:
        source = catalog.get_source(row["source_id"])
        if source is None or source["status"] != "enabled":
            catalog.finish_run(run_id, row["source_id"], status="failed", counts={},
                               error="The data source is missing or disabled.")
            return {"status": "failed"}
        try:
            provider = provider_for(source["provider"], source["config"])
        except (StorageError, StorageKeyError) as error:
            catalog.finish_run(run_id, row["source_id"], status="unavailable", counts={},
                               error=_clean_error(error))
            return {"status": "unavailable"}
        return index_source(catalog, source, provider, full=bool(row["full"]),
                            allow_mass_missing=bool(row["allow_mass_missing"]),
                            retry_invalid=bool(row.get("retry_invalid")),
                            run_id=run_id, progress=state.progress,
                            should_stop=state.should_stop)
    finally:
        done.set()
        beat.join(timeout=HEARTBEAT_S)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index one Frozen Legacies data source.")
    parser.add_argument("--catalog", required=True, help="radar catalog database")
    parser.add_argument("--run", type=int, required=True, help="queued run ID")
    args = parser.parse_args(argv)
    result = run(RadarCatalog(args.catalog), args.run)
    print(f"[index-worker] run {args.run}: {result.get('status')}", file=sys.stderr)
    return 0 if result.get("status") in ("completed", "cancelled", "needs_confirmation") else 1


if __name__ == "__main__":
    sys.exit(main())
