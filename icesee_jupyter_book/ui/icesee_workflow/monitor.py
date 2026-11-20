"""Live run monitoring shared by ICESEE and CryoLauncher.

After Launch/Submit the application hands the new run to a
:class:`RunFollower`: it opens Monitor (the run log) at once, and when the
run reaches a terminal state it moves on to Results (completed) or stays on
the log with the final state (failed/cancelled). :func:`monitor_banner`
renders the state, the lifecycle so far and what happens next above the log,
so the panel is never blank while the first output is on its way.
"""
from __future__ import annotations

from datetime import datetime

from icesee_jupyter_book.core import run_lifecycle as lc
from icesee_jupyter_book.ui.icesee_workflow.components import callout, esc, state_badge

#: what the log panel says while a run is in each state
STATE_MESSAGES = {
    lc.PREPARING: ("info", "Preparing the run: staging the experiment and its inputs."),
    lc.SUBMITTED: ("info", "Submitted. Waiting for the scheduler to start the job."),
    lc.QUEUED: ("info", "Queued. The job is waiting for resources."),
    lc.RUNNING: ("info", "Running. The log below updates as the model writes output."),
    lc.COMPLETED: ("ok", "Completed. The results are ready in Results."),
    lc.FAILED: ("bad", "Failed. The log below shows the last output; look for the error near the end."),
    lc.CANCELLED: ("warn", "Cancelled. The run was stopped before it finished."),
}


def _clock(value) -> str:
    if not value:
        return ""
    try:
        when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return when.strftime("%H:%M:%S")


def lifecycle_events(run) -> list[tuple[str, str]]:
    """``(state, time)`` pairs: the recorded lifecycle (ICESEE runs), else the
    run's creation and, once finished, its final state (workspace manifests)."""
    events = [(e.get("state", ""), _clock(e.get("at"))) for e in lc.history(run) if e.get("state")]
    if events:
        return events
    state = lc.current_state(run) or lc.SUBMITTED
    out = [(lc.SUBMITTED, _clock(getattr(run, "created", None)))]
    if state != lc.SUBMITTED:
        out.append((state, _clock(getattr(run, "finished", None)) if state in lc.TERMINAL else ""))
    return out


def monitor_banner(run, *, every: float | None = None, error: str = "", no_log: str = "") -> str:
    """HTML above the run log: state badge, lifecycle timeline, what the user
    can expect next, and -- when given -- a connection error or a no-output
    note. ``every`` is the polling interval in seconds while the run is active."""
    if run is None:
        return callout("Launch a run to follow it here. Its log appears as soon as it starts.", "info")
    state = lc.current_state(run) or lc.SUBMITTED
    steps = " → ".join(f"{esc(lc.LABELS.get(s, s.title()))}{' ' + esc(t) if t else ''}"
                       for s, t in lifecycle_events(run))
    tone, message = STATE_MESSAGES.get(state, ("info", lc.LABELS.get(state, state.title())))
    if state in lc.ACTIVE and every:
        message += f" Checked every {int(every)} s; no need to refresh the page."
    parts = [f'<div class="icw-badges">{state_badge(state)}'
             f'<span class="icw-card-sub" style="margin:0">{steps}</span></div>',
             callout(message, tone)]
    if error:
        parts.append(callout(error, "warn"))
    if no_log and state not in lc.TERMINAL:
        parts.append(callout(no_log, "info"))
    return f'<div class="icw-monitor" role="status" aria-live="polite">{"".join(parts)}</div>'


class RunFollower:
    """Follow the run just launched: Monitor until it ends, then Results.

    ``open_monitor(run_id)`` shows the run log, ``open_results(run_id)`` the
    results, ``state_of(run_id)`` (optional) the run's current state, so a run
    that finished before following started still moves on. Leaving the log tab by hand stops the automatic move to Results
    (the user chose where to look); following a new launch starts again."""

    def __init__(self, *, open_monitor, open_results, state_of=None):
        self.open_monitor, self.open_results = open_monitor, open_results
        self.state_of = state_of
        self.run_id: str | None = None
        self.auto = False

    def start(self, run_id: str | None) -> None:
        if not run_id:
            return
        self.run_id, self.auto = run_id, True
        self.open_monitor(run_id)
        if self.state_of is not None:              # a run that already finished
            self.update(run_id, self.state_of(run_id))

    def resume(self, run_id: str | None, *, auto: bool) -> None:
        """Follow a run already in flight when the page was reloaded, without
        moving the view; ``auto`` (the log is open) moves to Results when it
        completes, as after a launch."""
        if run_id:
            self.run_id, self.auto = run_id, auto

    def navigated(self, step: str | None) -> None:
        """The user opened another workspace view (``Monitor``, ``Results``,
        or anything else)."""
        if self.run_id and step != "Monitor":
            self.auto = False

    def update(self, run_id: str | None, state: str | None) -> str:
        """Apply a state change of ``run_id``; returns what happened
        (``ignored`` / ``following`` / ``results`` / ``finished``)."""
        if not run_id or run_id != self.run_id:
            return "ignored"
        state = str(state or "").lower()
        if state not in lc.TERMINAL:
            return "following"
        auto, self.run_id, self.auto = self.auto, None, False
        if state == lc.COMPLETED and auto:
            self.open_results(run_id)
            return "results"
        return "finished"
