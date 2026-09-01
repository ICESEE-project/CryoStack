"""Shared, model-neutral pre-submit validation helpers.

Pure functions -- no widgets, no I/O. Every CryoStack gateway calls the same
rules so a Remote run is checked identically in IceSheets, ICESEE and any
future Icepack UI.

Design rules:
* messages are short and actionable ("Nodes must be at least 1"), never a
  stack trace or a lecture;
* no universal cluster limits are invented -- we only check internal
  consistency (tasks/node <= tasks) and syntactic validity (wall time,
  memory), plus what a :class:`ComputeProfile` explicitly declares
  (``account_required``);
* ``account`` is required only when the resolved profile says so;
* HPC username and remote working directory are always required before a
  Remote run.
"""
from __future__ import annotations

import re

# Slurm wall-time: MM:SS | HH:MM:SS | D-HH:MM:SS
_WALLTIME_RE = re.compile(
    r"""
    \A
    (?:
        (?P<days>\d+) -              # optional  D-
    )?
    (?:
        (?P<h>\d{1,2}) :             # optional  HH:
    )?
    (?P<m>\d{1,2}) :
    (?P<s>\d{2})
    \Z
    """,
    re.VERBOSE,
)

# Slurm memory: 512M | 4G | 16GB | 1T  (also MB/GB/TB, KB, and plain bytes)
_MEMORY_RE = re.compile(r"\A\d+(?:\.\d+)?\s*(?:[KMGT]i?B?|B)?\Z", re.IGNORECASE)


def validate_wall_time(value: str) -> str | None:
    """Return an error message, or ``None`` when ``value`` is a valid wall time.

    Accepts ``MM:SS``, ``HH:MM:SS`` and ``D-HH:MM:SS``.
    """
    text = (value or "").strip()
    if not text:
        return "Wall time is required (MM:SS, HH:MM:SS or D-HH:MM:SS)."
    m = _WALLTIME_RE.match(text)
    if not m:
        return "Wall time must look like MM:SS, HH:MM:SS or D-HH:MM:SS."
    minutes = int(m.group("m"))
    seconds = int(m.group("s"))
    hours = int(m.group("h") or 0)
    if seconds > 59 or minutes > 59 or (m.group("h") and hours > 23):
        return "Wall time fields are out of range (minutes/seconds 0-59, hours 0-23)."
    if not m.group("days") and not m.group("h") and minutes == 0 and seconds == 0:
        return "Wall time must be greater than zero."
    return None


def validate_memory(value: str) -> str | None:
    """Return an error message, or ``None`` when ``value`` is a valid memory size.

    Accepts values such as ``512M``, ``4G``, ``16GB`` and ``1T``. Empty is
    allowed (the scheduler/template applies its own default).
    """
    text = (value or "").strip()
    if not text:
        return None
    if not _MEMORY_RE.match(text):
        return "Memory must look like 512M, 4G, 16GB or 1T."
    number = re.match(r"\A(\d+(?:\.\d+)?)", text)
    if number and float(number.group(1)) == 0:
        return "Memory must be greater than zero."
    return None


def validate_slurm_resources(
    *,
    nodes,
    tasks,
    tasks_per_node,
    wall_time: str = "",
    memory: str = "",
    account: str = "",
    account_required: bool = False,
) -> list[str]:
    """Validate the Slurm resource request. Returns a list of short messages
    (empty == valid).

    Only internal-consistency and syntax checks -- no site-specific ceilings.
    """
    messages: list[str] = []

    def _as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    n = _as_int(nodes)
    t = _as_int(tasks)
    tpn = _as_int(tasks_per_node)

    if n is None or n < 1:
        messages.append("Nodes must be a whole number of at least 1.")
    if t is None or t < 1:
        messages.append("Tasks must be a whole number of at least 1.")
    if tpn is None or tpn < 1:
        messages.append("Tasks / node must be a whole number of at least 1.")
    if t is not None and tpn is not None and t >= 1 and tpn >= 1 and tpn > t:
        messages.append("Tasks / node cannot exceed Tasks.")

    wt = validate_wall_time(wall_time)
    if wt:
        messages.append(wt)

    mem = validate_memory(memory)
    if mem:
        messages.append(mem)

    if account_required and not (account or "").strip():
        messages.append("Account is required for this resource.")

    return messages


def validate_remote_identity(*, hpc_username: str, remote_directory: str) -> list[str]:
    """HPC username and remote working directory are required before a Remote
    run. Returns a list of short messages (empty == valid)."""
    messages: list[str] = []
    if not (hpc_username or "").strip():
        messages.append("HPC username is required for Remote execution.")
    if not (remote_directory or "").strip():
        messages.append("Remote working directory is required for Remote execution.")
    return messages
