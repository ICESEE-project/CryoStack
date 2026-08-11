from __future__ import annotations


def slurm_state_to_experiment_status(
    state: str | None,
) -> str | None:
    if not state:
        return None

    state = (
        str(state)
        .strip()
        .upper()
        .split("+", 1)[0]
    )

    if state in {
        "PENDING",
        "REQUEUED",
        "REQUEUE_FED",
    }:
        return "queued"

    if state in {
        "CONFIGURING",
        "COMPLETING",
        "RESIZING",
        "STAGE_OUT",
    }:
        return "preparing"

    if state in {
        "RUNNING",
        "SUSPENDED",
    }:
        return "running"

    if state == "COMPLETED":
        return "completed"

    if state in {
        "CANCELLED",
        "DEADLINE",
    }:
        return "cancelled"

    if state in {
        "FAILED",
        "BOOT_FAIL",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "REVOKED",
        "TIMEOUT",
    }:
        return "failed"

    return None