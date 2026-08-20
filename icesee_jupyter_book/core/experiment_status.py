from __future__ import annotations


def normalize_slurm_state(
    state: str | None,
) -> str:
    if not state:
        return ""

    state = str(state).strip().upper()

    # sacct can return states such as CANCELLED+
    return state.split("+", 1)[0]


def slurm_state_to_experiment_status(
    state: str | None,
) -> str | None:
    state = normalize_slurm_state(state)

    if not state:
        return None

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

    raw_exit_code = result.get("exit_code")

    if raw_exit_code:
        try:
            update["exit_code"] = int(
                str(raw_exit_code).split(":", 1)[0]
            )
        except (TypeError, ValueError):
            pass

    return update