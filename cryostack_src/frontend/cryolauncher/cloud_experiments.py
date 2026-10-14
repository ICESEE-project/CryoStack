"""Cloud runs in the shared experiment record.

HPC submissions are entered into the CryoStack experiments table through the
browser-side :class:`~icesee_jupyter_book.ui.experiment_bridge.ExperimentBridge`
(the user's own session; the kernel never holds the cookie). Cloud runs used
to be registered only in the user's workspace manifest, so the Control Center
execution records never showed them. These helpers build the same kind of
record for a cloud run and map the run controller's states onto experiment
statuses.

Only non-secret identity is recorded: provider, region, queue, job
definition, image, the masked AWS account, and the *requested* resource
shape (labelled as requested -- AWS Batch does not report measured usage).
"""
from __future__ import annotations

from . import cloud_run_controller as crc

#: controller state -> experiment status; states before a job exists
#: (staging, submitting) are not recorded
_STATUS = {
    crc.QUEUED: "queued",
    crc.RUNNING: "running",
    crc.COMPLETED: "completed",
    crc.FAILED: "failed",
    crc.CANCELLED: "cancelled",
}


def masked_account(account_id: str) -> str:
    digits = "".join(c for c in str(account_id or "") if c.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else ""


def experiment_status(state: str) -> str | None:
    return _STATUS.get(state)


def cloud_experiment_record(handle, *, result_metadata: dict | None = None,
                            configuration: dict | None = None,
                            application: str = "cryolauncher") -> dict:
    """Keyword arguments for ``ExperimentBridge.create`` for a submitted run."""
    meta = result_metadata or {}
    s3_run = str(getattr(handle, "s3_run", "") or "")
    model = str(getattr(handle, "model", "") or "").upper() or "Cloud"
    return {
        "application": application,
        "name": f"{model} AWS Batch run",
        "backend": "aws",
        "status": "queued",
        "job_id": str(handle.job_id),
        "cluster": "aws-batch",
        "working_directory": s3_run or None,
        "output_directory": meta.get("s3_outputs") or (f"{s3_run.rstrip('/')}/outputs" if s3_run else None),
        "log_path": None,
        "configuration": configuration or {},
        "metadata": {
            "provider": "aws",
            "execution_mode": "cloud",
            "region": getattr(handle, "region", "") or "",
            "aws_account": masked_account(getattr(handle, "account_id", "")),
            "job_queue": meta.get("job_queue") or "",
            "job_definition": meta.get("job_definition") or "",
            "run_id": getattr(handle, "run_id", "") or "",
            "example": getattr(handle, "example", "") or "",
            "run_target": getattr(handle, "run_target", "") or "",
            "image_label": getattr(handle, "image_label", "") or "",
            "image_digest": getattr(handle, "image_digest", "") or "",
            # the shape the Control Center reads as *requested* resources
            "cloud": {
                "region": getattr(handle, "region", "") or "",
                "job_queue": meta.get("job_queue") or "",
                "job_definition": meta.get("job_definition") or "",
                "vcpu": getattr(handle, "vcpu", 0) or 0,
                "memory_mib": int(round((getattr(handle, "memory_gib", 0) or 0) * 1024)),
            },
            "expected_runtime_minutes": getattr(handle, "expected_runtime_minutes", 0) or 0,
            # AWS Batch reports no CPU/memory usage for the job
            "measured_resources": None,
        },
    }


def cloud_failure_summary(state: str, reason: str = "") -> dict | None:
    """Bounded, redacted failure summary for a cloud run that ended
    unsuccessfully (AWS Batch ``statusReason`` when the caller has it)."""
    from icesee_jupyter_book.core.experiment_status import sanitize_failure

    status = experiment_status(state)
    if status not in {"failed", "cancelled"}:
        return None
    return sanitize_failure({
        "scheduler": "aws-batch",
        "state": "FAILED" if status == "failed" else "CANCELLED",
        "reason": reason or ("The AWS Batch job failed." if status == "failed"
                             else "The AWS Batch job was cancelled."),
    })


def cloud_status_update(state: str, reason: str = "") -> dict | None:
    """``ExperimentBridge.update_by_job`` fields for a run-controller state
    (or a raw AWS Batch status such as ``SUCCEEDED``); ``None`` for states
    before a job exists. Usable by any application that polls a Batch job."""
    from icesee_jupyter_book.core.experiment_status import failure_message

    if state and state.strip().isupper():
        state = crc.normalize_aws_state(state)
    status = experiment_status(state)
    if not status:
        return None
    fields = {"status": status}
    failure = cloud_failure_summary(state, reason)
    if failure:
        fields["failure"] = failure
        fields["error_message"] = failure_message(failure)
    return fields


class CloudExperimentRecorder:
    """Keeps the experiment of the active cloud run in step with the run
    controller; each status is sent once and nothing follows a terminal one.

    A run created in this kernel starts from its create call. A run
    re-attached after a page refresh (``CloudRunController.attach``) starts
    from the state its manifest replays -- that state is not re-sent; only
    the changes the next polls observe are. Updates never create a record.
    """

    def __init__(self, bridge, *, job_id=lambda: "", reason=lambda: ""):
        self._bridge = bridge
        self._job_id = job_id
        self._reason = reason
        self._sent: dict[str, str] = {}

    def created(self, record: dict) -> None:
        self._bridge.create(**record)
        self._sent[record["job_id"]] = record["status"]

    def state(self, state: str) -> None:
        from icesee_jupyter_book.core.experiment_status import TERMINAL_STATUSES

        status = experiment_status(state)
        job_id = str(self._job_id() or "")
        if not status or not job_id:
            return
        previous = self._sent.get(job_id)
        if previous is None:
            # re-attached run: baseline only, the record already has it
            self._sent[job_id] = status
            return
        if previous == status or previous in TERMINAL_STATUSES:
            return
        try:
            reason = str(self._reason() or "")
        except Exception:  # noqa: BLE001 - a reason is optional
            reason = ""
        self._bridge.update_by_job(job_id=job_id, **cloud_status_update(state, reason))
        self._sent[job_id] = status
