"""Automatic status checks for the selected Remote ICESEE run.

The Run tab's **Check status** asks the cluster once and writes the scheduler
output to the activity log. :class:`RemoteStatusPoller` does the same check
quietly on a timer while the selected Remote run is still active, applies the
state through the same run lifecycle, and pauses after repeated failures
(an SSH key that is not loaded, a cluster that is down) so a broken
connection is not retried forever. **Check status** resumes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import run_lifecycle as lc
from .experiment_status import experiment_update_from_job_status

#: seconds between automatic checks
POLL_SECONDS = 60
#: consecutive failed checks before automatic checks pause
MAX_FAILURES = 3


@dataclass
class RemoteStatusPoller:
    """``selected()`` returns the selected run (or None); ``check(jobid)``
    returns a ``remote_job_status``-style dict; ``apply(run, update)``
    records an ``experiment_update_from_job_status`` update; ``notify(text,
    kind)`` shows a short message (kind: ``info`` / ``warn``)."""

    selected: Callable
    check: Callable[[str], dict]
    apply: Callable
    notify: Callable[[str, str], None] = lambda text, kind: None
    max_failures: int = MAX_FAILURES
    failures: int = 0
    paused: bool = False
    last_error: str = ""
    _job: str = field(default="", repr=False)

    def resume(self) -> None:
        self.failures, self.paused, self.last_error = 0, False, ""

    def tick(self) -> str:
        """One check; returns what happened (``skipped`` / ``paused`` /
        ``updated`` / ``unchanged`` / ``failed``)."""
        run = self.selected()
        if run is None or run.execution_mode != "remote" or not run.jobid:
            return "skipped"
        if lc.current_state(run) not in lc.ACTIVE:
            return "skipped"
        if str(run.jobid) != self._job:          # another run: a fresh failure budget
            self._job = str(run.jobid)
            self.resume()
        if self.paused:
            return "paused"
        try:
            result = self.check(str(run.jobid))
            if int(result.get("returncode", 1)) != 0:
                raise RuntimeError((result.get("stderr") or "the status command failed").strip()[:200])
        except Exception as exc:  # noqa: BLE001 - every failure counts the same
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            if self.failures >= self.max_failures:
                self.paused = True
                self.notify(f"Automatic status checks paused after {self.failures} failed attempts "
                            f"({self.last_error}). Use Check status to try again.", "warn")
            return "failed"
        self.failures = 0
        update = experiment_update_from_job_status(result)
        if not update:
            return "unchanged"
        self.apply(run, update)
        return "updated"
