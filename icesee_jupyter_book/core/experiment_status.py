"""Scheduler state -> CryoStack experiment record helpers.

Shared by the applications (which send updates through the browser
experiment bridge), the authentication server (which stores them) and the
Control Center (which displays them). Pure standard library on purpose: it is
imported inside Voila kernels and by the gateway.

Experiment statuses stay the six the experiments table knows (queued,
preparing, running, completed, failed, cancelled). *Why* a run ended --
TIMEOUT, OUT_OF_MEMORY, NODE_FAIL, PREEMPTED, ... -- is kept in a bounded,
redacted failure summary (``metadata["failure"]``), never as a new status.
"""

from __future__ import annotations

import re


TERMINAL_STATUSES = frozenset({
    "completed",
    "failed",
    "cancelled",
})

EXPERIMENT_STATUSES = frozenset({
    "queued",
    "preparing",
    "running",
}) | TERMINAL_STATUSES


def normalize_slurm_state(
    state: str | None,
) -> str:
    if not state:
        return ""

    state = str(state).strip().upper()

    # sacct can return states such as CANCELLED+ or "CANCELLED by 12345"
    state = state.split("+", 1)[0]

    state = state.split(None, 1)[0] if state.split() else ""

    return _SLURM_SHORT_CODES.get(state, state)


#: squeue ``%t`` compact codes -> the long state names sacct/squeue ``%T`` use
_SLURM_SHORT_CODES = {
    "BF": "BOOT_FAIL",
    "CA": "CANCELLED",
    "CD": "COMPLETED",
    "CF": "CONFIGURING",
    "CG": "COMPLETING",
    "DL": "DEADLINE",
    "F": "FAILED",
    "NF": "NODE_FAIL",
    "OOM": "OUT_OF_MEMORY",
    "PD": "PENDING",
    "PR": "PREEMPTED",
    "R": "RUNNING",
    "RD": "RESV_DEL_HOLD",
    "RF": "REQUEUE_FED",
    "RH": "REQUEUE_HOLD",
    "RQ": "REQUEUED",
    "RS": "RESIZING",
    "RV": "REVOKED",
    "SE": "SPECIAL_EXIT",
    "SI": "SIGNALING",
    "SO": "STAGE_OUT",
    "ST": "STOPPED",
    "S": "SUSPENDED",
    "TO": "TIMEOUT",
}

#: Slurm job state -> experiment status
SLURM_STATUS = {
    "PENDING": "queued",
    "REQUEUED": "queued",
    "REQUEUE_FED": "queued",
    "REQUEUE_HOLD": "queued",
    "RESV_DEL_HOLD": "queued",

    "CONFIGURING": "preparing",

    # the job still holds its allocation in all of these
    "RUNNING": "running",
    "SUSPENDED": "running",
    "STOPPED": "running",
    "SIGNALING": "running",
    "RESIZING": "running",
    "COMPLETING": "running",
    "STAGE_OUT": "running",

    "COMPLETED": "completed",

    "CANCELLED": "cancelled",

    "FAILED": "failed",
    "BOOT_FAIL": "failed",
    "DEADLINE": "failed",
    "LAUNCH_FAILED": "failed",
    "NODE_FAIL": "failed",
    "OUT_OF_MEMORY": "failed",
    "PREEMPTED": "failed",
    "REVOKED": "failed",
    "SPECIAL_EXIT": "failed",
    "TIMEOUT": "failed",
}

#: plain-language reason for every state that ends a run unsuccessfully
SLURM_REASONS = {
    "BOOT_FAIL": "The allocated nodes failed to boot.",
    "CANCELLED": "The job was cancelled.",
    "DEADLINE": "The job was stopped at its scheduling deadline.",
    "FAILED": "The job exited with a non-zero exit code.",
    "LAUNCH_FAILED": "The job could not be launched.",
    "NODE_FAIL": "A node allocated to the job failed.",
    "OUT_OF_MEMORY": "The job ran out of memory.",
    "PREEMPTED": "The job was preempted by the scheduler.",
    "REVOKED": "The job was revoked by the scheduler.",
    "SPECIAL_EXIT": "The job ended with a special exit state.",
    "TIMEOUT": "The job reached its wall-clock time limit.",
}


def slurm_state_to_experiment_status(
    state: str | None,
) -> str | None:
    return SLURM_STATUS.get(
        normalize_slurm_state(state)
    )


def parse_exit_code(
    value,
) -> tuple[int | None, int | None]:
    """Slurm ``"<exit>:<signal>"`` (or a plain int) -> ``(exit, signal)``."""

    if value is None or value == "":
        return None, None

    if isinstance(value, bool):
        return None, None

    if isinstance(value, int):
        return value, None

    parts = str(value).strip().split(":", 1)

    def _int(text):
        try:
            return int(text.strip())
        except (TypeError, ValueError):
            return None

    exit_code = _int(parts[0])
    signal = _int(parts[1]) if len(parts) > 1 else None

    return exit_code, (signal or None)


# ------------------------------------------------------------
# Redaction and the bounded failure summary
# ------------------------------------------------------------

REDACTED = "<redacted>"

_SECRET_KEY_WORDS = (
    r"password|passwd|passphrase|secret|token|session|cookie|api[_-]?key|"
    r"apikey|credential|external[_-]?id|pairing[_-]?code|code[_-]?verifier|"
    r"private[_-]?key|authorization|signature|access[_-]?key"
)

_REDACTIONS: tuple[tuple[re.Pattern, str], ...] = (
    # PEM / OpenSSH private keys (whole block, or the tail of a cut one)
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
            r".*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
        "<redacted private key>",
    ),
    # AWS access key ids (long-term and temporary)
    (
        re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|ANPA)[A-Z0-9]{12,}\b"),
        REDACTED,
    ),
    # Authorization: Bearer/Basic <credential>
    (
        re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"),
        r"\1 " + REDACTED,
    ),
    # key=value / key: value / "key": "value" with a secret-looking key
    (
        re.compile(
            r"(?i)([\w.-]*(?:" + _SECRET_KEY_WORDS + r")[\w.-]*)"
            r"(\"?'?\s*[:=]\s*\"?'?)"
            r"([^\s\"',;&}\]]+)"
        ),
        r"\1\2" + REDACTED,
    ),
    # credentials embedded in a URL
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"),
        r"\1" + REDACTED + "@",
    ),
    # FlexNet / MATLAB license server (<port>@<host>)
    (
        re.compile(r"\b\d{2,5}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"),
        "<license-server>",
    ),
    # AWS account ids inside ARNs: keep only the last four digits
    (
        re.compile(r"(arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:)\d{8}(\d{4})"),
        r"\1********\2",
    ),
    # long opaque tokens (session ids, signed URLs, keys)
    (
        re.compile(r"(?<![\w.-])[A-Za-z0-9_+-]{40,}={0,2}(?![\w.-])"),
        REDACTED,
    ),
)

#: a bare 40-character AWS secret access key (base64 alphabet incl. "/")
_AWS_SECRET = re.compile(r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+=])")

_CONTROL_CHARACTERS = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]"
)


def _aws_secret(match: re.Match) -> str:
    text = match.group(0)
    if (
        not text.startswith("/")
        and re.search(r"[A-Z]", text)
        and re.search(r"[a-z]", text)
        and re.search(r"[0-9]", text)
    ):
        return REDACTED
    return text


def redact_secrets(
    value,
    *,
    limit: int = 500,
) -> str:
    """``value`` as a bounded, single-record-safe string with secret-looking
    material (keys, tokens, AWS key ids, passwords, private key blocks,
    license servers) replaced. ``None`` becomes ``""``."""

    if value is None:
        return ""

    text = _CONTROL_CHARACTERS.sub("", str(value))

    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)

    text = _AWS_SECRET.sub(_aws_secret, text).strip()

    if limit and len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"

    return text


#: bounds of the stored failure summary
FAILURE_REASON_LIMIT = 300
FAILURE_LOG_LINES = 20
FAILURE_LOG_LINE_LIMIT = 200

_STATE_TEXT = re.compile(r"[^A-Z0-9_]")


def sanitize_failure(
    raw,
) -> dict | None:
    """
    The allowlisted, bounded and redacted form of a failure summary::

        {"scheduler": "slurm", "state": "TIMEOUT", "exit_code": 0,
         "signal": 9, "reason": "...", "log_tail": ["...", ...]}

    ``log_tail`` is only kept when the caller already had log text; it is
    capped at the last :data:`FAILURE_LOG_LINES` lines. Returns ``None`` for
    anything that is not a dict or carries nothing worth keeping.
    """

    if not isinstance(raw, dict):
        return None

    summary: dict = {}

    scheduler = str(raw.get("scheduler") or "").strip().lower()
    if scheduler in {"slurm", "aws-batch"}:
        summary["scheduler"] = scheduler

    state = _STATE_TEXT.sub("", str(raw.get("state") or "").strip().upper())[:32]
    if state:
        summary["state"] = state

    for key in ("exit_code", "signal"):
        value = raw.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and -(2 ** 31) <= value < 2 ** 31:
            summary[key] = value

    reason = redact_secrets(raw.get("reason"), limit=FAILURE_REASON_LIMIT)
    if reason:
        summary["reason"] = reason

    lines = raw.get("log_tail")
    if isinstance(lines, str):
        lines = lines.splitlines()
    if isinstance(lines, (list, tuple)):
        tail = [
            redact_secrets(line, limit=FAILURE_LOG_LINE_LIMIT)
            for line in list(lines)[-FAILURE_LOG_LINES:]
            if str(line or "").strip()
        ]
        if tail:
            summary["log_tail"] = tail

    if not (set(summary) - {"scheduler"}):
        return None

    return summary


def failure_message(
    failure: dict | None,
) -> str | None:
    """One line for ``error_message`` from a sanitized failure summary."""

    if not failure:
        return None

    parts = []

    if failure.get("state"):
        parts.append(failure["state"])

    if failure.get("exit_code") is not None:
        code = f"exit {failure['exit_code']}"
        if failure.get("signal"):
            code += f" (signal {failure['signal']})"
        parts.append(code)

    head = ", ".join(parts)
    reason = failure.get("reason") or ""

    text = f"{head}: {reason}" if head and reason else (head or reason)

    return text or None


def slurm_failure_summary(
    state: str | None,
    exit_code=None,
    *,
    reason: str | None = None,
    log_tail=None,
) -> dict | None:
    """Failure summary for a Slurm state that ended a run unsuccessfully
    (failed or cancelled); ``None`` for every other state."""

    name = normalize_slurm_state(state)

    if SLURM_STATUS.get(name) not in {"failed", "cancelled"}:
        return None

    code, signal = parse_exit_code(exit_code)

    return sanitize_failure({
        "scheduler": "slurm",
        "state": name,
        "exit_code": code,
        "signal": signal,
        "reason": reason or SLURM_REASONS.get(name, ""),
        "log_tail": log_tail,
    })


def parse_sacct_state(
    output: str | None,
    job_id: str,
) -> tuple[str | None, str | None]:
    """
    Parse:

        JobIDRaw|State|ExitCode

    Prefer the parent batch job row rather than .batch/.extern steps.
    """
    if not output:
        return None, None

    target = str(job_id)

    fallback = None

    for raw_line in output.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parts = line.split("|")

        if len(parts) < 3:
            continue

        row_job_id = parts[0].strip()
        state = parts[1].strip()
        exit_code = parts[2].strip()

        if fallback is None:
            fallback = (state, exit_code)

        if row_job_id == target:
            return state, exit_code

    return fallback or (None, None)

def remote_job_status(
    host: str,
    user: str,
    port: int,
    jobid: str,
) -> dict:
    # ---------------------------------------------------------
    # First: live queue
    # ---------------------------------------------------------
    r = ssh_run(
        host,
        user,
        port,
        (
            f"squeue -j {jobid} "
            "-h -o '%i|%T|%M|%D|%R'"
        ),
        timeout=15,
    )

    squeue_out = (r.stdout or "").strip()

    if r.returncode == 0 and squeue_out:
        parts = squeue_out.splitlines()[0].split("|")

        return {
            "returncode": r.returncode,
            "stdout": r.stdout,
            "stderr": r.stderr,
            "source": "squeue",
            "state": (
                parts[1].strip()
                if len(parts) > 1
                else None
            ),
            "exit_code": None,
        }

    # ---------------------------------------------------------
    # Job left squeue: query Slurm accounting
    # ---------------------------------------------------------
    a = ssh_run(
        host,
        user,
        port,
        (
            f"sacct -j {jobid} "
            "--noheader "
            "--parsable2 "
            "--format=JobIDRaw,State,ExitCode"
        ),
        timeout=15,
    )

    state = None
    exit_code = None

    if a.returncode == 0:
        for line in (a.stdout or "").splitlines():
            line = line.strip()

            if not line:
                continue

            parts = line.split("|")

            if len(parts) < 3:
                continue

            row_jobid = parts[0].strip()

            # Prefer the parent job, not .batch/.extern steps.
            if row_jobid == str(jobid):
                state = parts[1].strip()
                exit_code = parts[2].strip()
                break

    return {
        "returncode": a.returncode,
        "stdout": a.stdout,
        "stderr": a.stderr,
        "source": "sacct",
        "state": state,
        "exit_code": exit_code,
    }

def experiment_update_from_job_status(
    result: dict,
) -> dict | None:
    """
    Convert a remote_job_status()-style result into fields
    suitable for ExperimentBridge.update_by_job().

    A run that ended unsuccessfully also carries a bounded, redacted
    ``failure`` summary (scheduler state, exit code, signal, reason) and a
    one-line ``error_message``. Scheduler stdout/stderr is not log text and
    is never copied into the record.
    """

    state = result.get("state")

    status = slurm_state_to_experiment_status(
        state
    )

    if status is None:
        return None

    update = {
        "status": status,
    }

    exit_code, _signal = parse_exit_code(
        result.get("exit_code")
    )

    if exit_code is not None:
        update["exit_code"] = exit_code

    failure = slurm_failure_summary(
        state,
        result.get("exit_code"),
        reason=result.get("reason"),
    )

    if failure:
        update["failure"] = failure
        update["error_message"] = failure_message(failure)

    return update


# ------------------------------------------------------------
# What a record says about the run (Control Center, API)
# ------------------------------------------------------------

_SLURM_REQUEST_FIELDS = (
    "nodes", "tasks", "tasks_per_node", "partition", "time", "memory",
)

_CLOUD_REQUEST_FIELDS = (
    "vcpu", "memory_mib",
)

#: measured usage is only shown when a run actually recorded it
_MEASURED_FIELDS = (
    "elapsed_seconds", "cpu_seconds", "max_rss_mib", "nodes", "tasks",
    "vcpu", "memory_mib",
)


def _positive_int(
    value,
) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _short(
    value,
    limit: int = 80,
) -> str:
    return redact_secrets(value, limit=limit) if value not in (None, "") else ""


def experiment_overview(
    configuration: dict | None,
    metadata: dict | None,
) -> dict:
    """
    The scientific and execution facts of one record, from what the
    application already captured (configuration snapshot + metadata)::

        {"execution_mode", "model", "example", "preset", "filter",
         "ensemble_size", "requested": {...}, "measured": {...} | None}

    ``requested`` is what the run asked the scheduler for; ``mpi_ranks`` is
    the Slurm task count (or nodes x tasks per node). ``measured`` is only
    present when the record carries recorded usage -- nothing is estimated.
    """

    configuration = configuration if isinstance(configuration, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}

    def pick(key):
        value = metadata.get(key)
        if value in (None, ""):
            value = configuration.get(key)
        return value

    overview = {
        "execution_mode": _short(pick("execution_mode"), 20).lower(),
        "model": _short(pick("model"), 40),
        "example": _short(pick("example")),
        "preset": _short(pick("preset")),
        "filter": _short(pick("filter"), 40),
        "ensemble_size": _positive_int(
            pick("ensemble_size") or pick("ens_size")
        ),
    }

    requested: dict = {}

    slurm = configuration.get("slurm")
    if isinstance(slurm, dict):
        for field in _SLURM_REQUEST_FIELDS:
            value = slurm.get(field)
            if field in {"nodes", "tasks", "tasks_per_node"}:
                value = _positive_int(value)
                if value is not None:
                    requested[field] = value
            elif value not in (None, ""):
                requested[field] = _short(value, 40)

    if "tasks" in requested:
        requested["mpi_ranks"] = requested["tasks"]
    elif "nodes" in requested and "tasks_per_node" in requested:
        requested["mpi_ranks"] = requested["nodes"] * requested["tasks_per_node"]

    for section in (configuration.get("cloud"), metadata.get("cloud")):
        if isinstance(section, dict):
            for field in _CLOUD_REQUEST_FIELDS:
                value = _positive_int(section.get(field))
                if value is not None and field not in requested:
                    requested[field] = value

    overview["requested"] = requested

    measured = metadata.get("measured_resources")
    overview["measured"] = None

    if isinstance(measured, dict):
        values = {}
        for field in _MEASURED_FIELDS:
            value = measured.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                values[field] = value
        overview["measured"] = values or None

    return overview


def record_metadata(
    configuration: dict | None,
    metadata: dict | None,
) -> dict:
    """``metadata`` with the run's scientific/execution facts filled in from
    the configuration snapshot where the application did not set them, so
    every record carries them in one shape. Existing keys are never changed."""

    result = dict(metadata or {})
    overview = experiment_overview(configuration, result)

    for key in ("execution_mode", "model", "example", "preset", "filter", "ensemble_size"):
        if result.get(key) in (None, "") and overview.get(key) not in (None, ""):
            result[key] = overview[key]

    if overview["requested"] and "requested_resources" not in result:
        result["requested_resources"] = overview["requested"]

    return result
