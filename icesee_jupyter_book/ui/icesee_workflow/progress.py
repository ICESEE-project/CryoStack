"""Workflow progress shared by ICESEE and CryoLauncher: which stepper steps are
done, current or need attention, given the setup steps and the run the
stepper follows.

Both applications use the same lifecycle vocabulary (core/run_lifecycle.py
and the workspace manifest): preparing/submitted/queued/running while a run
is in flight, then completed, failed or cancelled.
"""
from __future__ import annotations

#: setup steps come before these two; the order is the stepper's
MONITOR, RESULTS = "Monitor", "Results"
ACTIVE = frozenset({"preparing", "submitted", "queued", "pending", "running"})
COMPLETED = frozenset({"completed", "done", "succeeded"})
FAILED = frozenset({"failed", "error"})
CANCELLED = frozenset({"cancelled", "canceled"})


def run_step_states(setup: dict, run_state: str | None, *, viewing: str | None = None) -> dict:
    """Stepper classes for every step.

    ``setup`` holds the classes the application computed for its setup steps
    (Mode .. Review & launch: done, current or attention). ``run_state`` is the
    lifecycle state of the run the stepper follows, or None before a launch.
    ``viewing`` is the step whose workspace tab is open (Monitor or Results),
    so manual navigation moves the current marker without changing what is
    done.

    Before a launch the setup classes are returned unchanged. Once a run
    exists every setup step is done (it was completed to launch), except one
    that needs attention now; then Monitor is current while the run is in
    flight, done once it finished, and needs attention if it failed. Results
    becomes current when the run completed. A cancelled run marks Monitor as
    stopped.
    """
    states = dict(setup)
    state = str(run_state or "").strip().lower()
    if not state:
        return states
    for name, cls in setup.items():
        if "attention" not in cls:
            states[name] = "done"
    if state in ACTIVE:
        states[MONITOR] = "current active"
    elif state in COMPLETED:
        states[MONITOR] = "done current" if viewing == MONITOR else "done"
        states[RESULTS] = "" if viewing == MONITOR else "current"
    elif state in FAILED:
        states[MONITOR] = "current attention"
    elif state in CANCELLED:
        states[MONITOR] = "current stopped"
    return states


def follow_run(selected, launched, runs, *, matches):
    """The run the stepper follows, among runs of the current configuration
    (``matches(run)``: same execution mode and experiment): the run selected
    in the workspace, else the one launched in this session, else -- after a
    page reload -- the most recent one. Changing the experiment or mode
    therefore returns the stepper to Review & launch."""
    for run in (selected, launched):
        if run is not None and matches(run):
            return run
    candidates = [run for run in runs if matches(run)]
    return max(candidates, key=lambda run: getattr(run, "created", None) or 0, default=None)
