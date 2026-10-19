"""One run lifecycle for every ICESEE execution backend.

Local processes, Slurm jobs and AWS Batch jobs all report their progress in
their own words (``R``/``PD``/``CD``, ``RUNNABLE``/``SUCCEEDED``, an exit
code ...). The launcher shows one set of states and records every change in
the run's manifest, so a run can be followed, and later audited, the same way
whichever backend ran it::

    preparing -> submitted -> queued -> running -> completed
                                              \\-> failed
                                              \\-> cancelled

``preparing`` is the launcher's own work before anything is handed to a
backend (staging, validation, upload); a local run goes straight from
``preparing`` to ``running``. ``completed``, ``failed`` and ``cancelled`` are
final. The history of transitions lives in the manifest's
``metadata["lifecycle"]`` as ``[{"state", "at", "detail"}, ...]``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import run_records

PREPARING, SUBMITTED, QUEUED, RUNNING = "preparing", "submitted", "queued", "running"
COMPLETED, FAILED, CANCELLED = "completed", "failed", "cancelled"
STATES = (PREPARING, SUBMITTED, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})
ACTIVE = frozenset({PREPARING, SUBMITTED, QUEUED, RUNNING})

_NEXT = {
    None: {PREPARING, SUBMITTED, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED},
    PREPARING: {SUBMITTED, QUEUED, RUNNING, FAILED, CANCELLED},
    SUBMITTED: {QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED},
    QUEUED: {RUNNING, COMPLETED, FAILED, CANCELLED},
    RUNNING: {COMPLETED, FAILED, CANCELLED},
    COMPLETED: set(), FAILED: set(), CANCELLED: set(),
}

#: backend vocabularies -> lifecycle states (Slurm squeue/sacct codes and
#: names, AWS Batch states, the launcher's historical labels)
_ALIASES = {
    PREPARING: {"preparing", "staging", "creating"},
    SUBMITTED: {"submitted", "submit"},
    QUEUED: {"queued", "pending", "pd", "runnable", "configuring", "cf", "requeued", "rq",
             "resv_del_hold", "suspended", "s"},
    RUNNING: {"running", "r", "starting", "completing", "cg", "started"},
    COMPLETED: {"completed", "complete", "cd", "succeeded", "success", "done", "finished"},
    FAILED: {"failed", "f", "fail", "error", "timeout", "to", "node_fail", "nf", "out_of_memory",
             "oom", "boot_fail", "bf", "deadline", "dl", "preempted", "pr", "lost"},
    CANCELLED: {"cancelled", "canceled", "ca", "terminated", "killed", "stopped"},
}
_LOOKUP = {alias: state for state, aliases in _ALIASES.items() for alias in aliases}

LABELS = {
    PREPARING: "Preparing", SUBMITTED: "Submitted", QUEUED: "Queued", RUNNING: "Running",
    COMPLETED: "Completed", FAILED: "Failed", CANCELLED: "Cancelled",
}


class InvalidTransition(ValueError):
    pass


def normalize(raw) -> str | None:
    """A lifecycle state for any backend's status word, or ``None`` when it
    is not one (never a guess). ``"CANCELLED by 123"`` -> ``cancelled``."""
    if raw is None:
        return None
    word = str(raw).strip().lower()
    if not word:
        return None
    if word in _LOOKUP:
        return _LOOKUP[word]
    head = word.replace("+", " ").split()[0]
    return _LOOKUP.get(head)


def can_transition(current: str | None, new: str) -> bool:
    return new == current or new in _NEXT.get(current, set())


def history(info) -> list[dict]:
    return list(((info.metadata or {}) if info else {}).get("lifecycle") or [])


def current_state(info) -> str | None:
    """The run's lifecycle state (normalising manifests written before the
    lifecycle existed, whose ``status`` was e.g. ``done`` or ``running``)."""
    if info is None:
        return None
    return normalize(info.status)


def transition(run_dir: Path | str, new_state: str, *, detail: str = "", jobid=None,
               remote_directory=None, extra_metadata: dict | None = None, force: bool = False):
    """Move a recorded run to ``new_state`` and append it to the history.

    An illegal move (e.g. ``completed -> running``, a stale poll arriving
    after the run finished) raises :class:`InvalidTransition` unless
    ``force``; repeating the current state only refreshes ``detail``.
    Returns the updated :class:`~cryostack_src.workspace.RunInfo`, or
    ``None`` when the run has no manifest."""
    if new_state not in STATES:
        raise InvalidTransition(f"unknown run state {new_state!r}")
    run_dir = Path(run_dir)
    manifest = run_dir / run_records.MANIFEST_NAME
    if not manifest.is_file():
        return None
    from cryostack_src.workspace import read_manifest

    info = read_manifest(manifest)
    current = current_state(info)
    if not force and not can_transition(current, new_state):
        raise InvalidTransition(f"run {info.id}: {current} -> {new_state} is not allowed")
    events = history(info)
    now = datetime.now().isoformat(timespec="seconds")
    if events and events[-1].get("state") == new_state:
        if detail:
            events[-1] = {**events[-1], "detail": detail}
    else:
        events.append({"state": new_state, "at": now, "detail": detail})
    meta = {"lifecycle": events, **(extra_metadata or {})}
    if new_state in TERMINAL and detail:
        meta["final_detail"] = detail
    return run_records.update_run(run_dir, status=new_state, jobid=jobid,
                                  remote_directory=remote_directory, extra_metadata=meta)


def apply_backend_status(run_dir: Path | str, raw_status, *, detail: str = ""):
    """Record a backend's status report if it means a legal step forward;
    unknown words and stale reports are ignored (returns ``None``)."""
    state = normalize(raw_status)
    if state is None:
        return None
    try:
        return transition(run_dir, state, detail=detail or str(raw_status))
    except InvalidTransition:
        return None
