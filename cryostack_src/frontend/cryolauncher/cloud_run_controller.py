# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : CryoLauncher Cloud Run Controller
# File        : cloud_run_controller.py
#
# Description :
#     Non-blocking submit + auto-poll + auto-retrieve for an AWS Batch cloud
#     run, on the same asyncio worker/state pattern the auto-tail log worker
#     uses (cryostack_src/workspace/logs.py).
#
# Author(s)   :
#     Brian Kyanjo
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""CryoStack cloud run controller (C6).

Owns one cloud run's lifecycle so the gateway callback never blocks the Voilà
kernel:

    submit()  -> STAGING -> SUBMITTING -> (job id) -> QUEUED
              -> auto-poll -> RUNNING -> COMPLETED / FAILED / CANCELLED
              -> on COMPLETED: auto-sync outputs -> Results panel refresh

Every AWS call runs in a worker thread (:func:`asyncio.to_thread`); the
controller only touches widget state on the event loop. It converges on the
existing services -- ``CloudBridge`` for submit/status/logs/terminate,
``WorkspaceManager.sync_cloud_results`` for retrieval, the shared
``ResultPackage`` / visualizer for rendering -- and adds no parallel path.

This module holds **no ipywidgets import**: the gateway passes plain callables
(`on_state`, `on_log`, `on_results_ready`) so the controller stays unit
testable with fakes.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Callable

# ── states ────────────────────────────────────────────────────────────────
NOT_CONFIGURED = "not_configured"
CHECKING = "checking"
READY = "ready"
STAGING = "staging"
SUBMITTING = "submitting"
QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

CLOUD_STATES: tuple[str, ...] = (
    NOT_CONFIGURED, CHECKING, READY, STAGING, SUBMITTING,
    QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED,
)
_TERMINAL: frozenset[str] = frozenset({COMPLETED, FAILED, CANCELLED})

#: AWS Batch raw state -> CryoStack state (mirrors CloudBackend._normalize_state,
#: plus the two AWS states that have no CloudStatus mapping)
_AWS_STATE_MAP = {
    "SUBMITTED": QUEUED, "PENDING": QUEUED, "RUNNABLE": QUEUED,
    "STARTING": RUNNING, "RUNNING": RUNNING,
    "SUCCEEDED": COMPLETED, "FAILED": FAILED,
}


def is_terminal(state: str) -> bool:
    return state in _TERMINAL


def normalize_aws_state(raw: str) -> str:
    return _AWS_STATE_MAP.get((raw or "").strip().upper(), QUEUED)


# ── failure classification ────────────────────────────────────────────────
#: (predicate on the lowercased message, short user-facing message)
_FAILURE_RULES: tuple[tuple[str, str], ...] = (
    (r"could not connect to the endpoint|name resolution|network is unreachable",
     "Cannot reach AWS. Check your network and region."),
    (r"unable to locate credentials|no credentials|credentials not found|"
     r"expiredtoken|invalidclienttokenid|the security token included in the request is",
     "AWS credentials are not configured. Run `aws configure` (or set a profile) and retry."),
    (r"the config profile .* could not be found|profilenotfound|invalid profile",
     "That AWS profile does not exist. Fix the profile name under Advanced."),
    (r"could not connect to the endpoint url.*\bregion\b|invalid region|"
     r"illegal location constraint|the bucket is in this region",
     "Region mismatch. Set the region to match your bucket and Batch resources."),
    (r"not a valid s3 bucket name|s3 location must be a bucket|"
     r"invalid bucket name|the s3 bucket name is empty|not a usable s3 key prefix",
     "The S3 bucket / location is not valid. Enter a bucket name or an "
     "s3://bucket URI."),
    (r"nosuchbucket|bucket does not exist|not staging.*bucket|needs an s3 bucket",
     "The S3 bucket is missing. Prepare cloud storage or fix the bucket name."),
    (r"accessdenied|access denied|forbidden|not authorized to perform",
     "Access denied by AWS. Your identity lacks permission for this bucket / queue / job."),
    (r"repositorynotfoundexception|image .* not found|no such image|manifest unknown",
     "The container image is not in ECR. Prepare cloud compute (image push) first."),
    (r"job queue .* does not exist|jobqueue .* not found|invalid job queue",
     "The Batch job queue does not exist. Prepare cloud compute first."),
    (r"job definition .* does not exist|jobdefinition .* not found|"
     r"invalid job definition|revision .* is not valid",
     "The Batch job definition does not exist. Prepare cloud compute first."),
    (r"matlab licens", "ISSM cloud runs need a MATLAB license on the cloud "
                       "profile. Infrastructure can still be tested with the smoke test."),
    (r"execution descriptor failed|failed to upload the staged run|"
     r"staged run directory does not exist|run target .* is not present",
     "Could not stage the run inputs to S3. Check the working copy and the run target."),
    (r"submit-job failed|could not read a jobid|aws batch submit-job",
     "AWS Batch rejected the submission. See the log for the exact reason."),
    (r"cloud results sync failed|no cloud run location|output .* not found|"
     r"outputs/ is empty",
     "The job finished but its S3 outputs could not be retrieved."),
    (r"schema|metadata\.json|result package|resulterror|not readable",
     "The job produced outputs but the result package is malformed."),
    (r"\bfailed\b.*exit|job failed|essential container|task failed",
     "The Batch job ran but failed. Open the log for the container error."),
    (r"timed out|timeout", "The Batch job hit its time limit before finishing."),
)


def classify_cloud_failure(error: Any) -> tuple[str, str]:
    """Map an exception / message to ``(short_actionable, full_detail)``.

    The short message is safe to show a user; the detail is the original text
    for the log. Never returns a secret -- the inputs are already screened
    upstream, and this only pattern-matches.
    """
    detail = str(error).strip()
    low = detail.lower()
    for pattern, short in _FAILURE_RULES:
        if re.search(pattern, low):
            return short, detail
    return ("The cloud operation failed. See the log for details.", detail or "unknown error")


# ── job-definition controlled selection ───────────────────────────────────
def resolve_job_definition(
    model: str, override: str, *, allow_list: dict[str, str],
) -> tuple[str, list[str]]:
    """Return ``(job_definition, warnings)``.

    Selection is controlled: the model's deterministic name is the default, and
    an override is accepted **only** if it names a known CryoStack job
    definition (optionally with a ``:revision`` suffix). Anything else is
    ignored with a warning -- a UI/agent free string can never pick an
    arbitrary Batch job definition.
    """
    model = (model or "").strip().lower()
    default = allow_list.get(model, f"cryostack-{model}")
    ov = (override or "").strip()
    if not ov:
        return default, []
    base = ov.split(":", 1)[0]
    if base in allow_list.values() or base == default:
        return ov, []
    return default, [
        f"Ignoring job-definition override {ov!r}: not a CryoStack job "
        f"definition. Using {default!r}."
    ]


# ── cost / resource preview ───────────────────────────────────────────────
def cloud_run_plan_summary(
    *, model: str, region: str, bucket: str, job_queue: str, job_definition: str,
    vcpu: str = "2", memory_mib: str = "8192", timeout_seconds: int = 3600,
) -> str:
    """A short pre-submit summary. No dollar figure -- AWS pricing depends on
    the account, so we state the resources and that charges apply."""
    gib = "?"
    try:
        gib = f"{int(memory_mib) / 1024:.0f}"
    except (TypeError, ValueError):
        pass
    return (
        "This submits an AWS Batch (Fargate) job. It will use AWS resources "
        "and may incur charges on your account.\n"
        f"  model          {model}\n"
        f"  region         {region}\n"
        f"  S3 bucket      {bucket}\n"
        f"  job queue      {job_queue}\n"
        f"  job definition {job_definition}\n"
        f"  resources      {vcpu} vCPU · {gib} GiB · time limit "
        f"{int(timeout_seconds) // 60} min (from the job definition)\n"
        "  outputs        s3://<bucket>/runs/<user>/<run-id>/outputs/  -> your run cache"
    )


# ── user-scoped S3 prefix ─────────────────────────────────────────────────
_S3_SEG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def user_run_prefix(safe_user_id: str) -> str:
    """``<safe-user>/`` -- the S3 key prefix under ``runs/`` that isolates one
    CryoStack user's cloud runs from another's.

    Pass ``WorkspaceManager.owner.safe_id`` (already a collision-resistant,
    filesystem-safe namespace key). A defensive re-slug here guarantees a
    single clean path segment even if a caller hands a raw id.
    """
    seg = _S3_SEG_RE.sub("-", (safe_user_id or "").strip()).strip("-.") or "user"
    return f"{seg[:64]}/"


# ── the controller ────────────────────────────────────────────────────────
@dataclass
class _RunHandle:
    job_id: str = ""
    s3_run: str = ""
    run_id: str = ""
    model: str = ""
    state: str = NOT_CONFIGURED
    region: str = ""
    profile: str | None = None
    metadata: dict = field(default_factory=dict)


class CloudRunController:
    """One-per-gateway owner of the active cloud run's async lifecycle."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], Any],
        register_run: Callable[..., Any],
        sync_results: Callable[..., Any],
        on_state: Callable[[str], None],
        on_log: Callable[[str], None],
        on_results_ready: Callable[[], None] = lambda: None,
        poll_interval: float = 15.0,
        to_thread: Callable[..., Any] = asyncio.to_thread,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._register_run = register_run
        self._sync_results = sync_results
        self._on_state = on_state
        self._on_log = on_log
        self._on_results_ready = on_results_ready
        self._poll_interval = max(0.0, float(poll_interval))
        self._to_thread = to_thread
        self._sleep_fn = sleep

        self._handle = _RunHandle()
        self._task = None                       # the single active lifecycle task

    # -- public state ----------------------------------------------------
    @property
    def state(self) -> str:
        return self._handle.state

    @property
    def job_id(self) -> str:
        return self._handle.job_id

    def _set_state(self, state: str) -> None:
        self._handle.state = state
        try:
            self._on_state(state)
        except Exception:
            pass

    def _log(self, message: str) -> None:
        try:
            self._on_log(message)
        except Exception:
            pass

    # -- submit --------------------------------------------------------
    def submit(self, **submit_kwargs) -> None:
        """Kick off the whole lifecycle (stage -> submit -> poll -> retrieve)
        on the event loop and return at once.

        ``submit_kwargs`` (minus the ``_region`` / ``_profile`` /
        ``_md_provenance`` hints) are forwarded verbatim to
        ``CloudBridge.submit`` -- the gateway is responsible for having already
        run ``validate_cloud_config`` + ``cloud_run_preflight`` and staged the
        user-owned working copy.
        """
        if self._task is not None and not self._task.done():
            self._log("[cloud] A cloud run is already in progress.")
            return
        self._handle = _RunHandle(
            model=(submit_kwargs.get("model") or "").strip().lower(),
            region=submit_kwargs.pop("_region", "") or "",
            profile=submit_kwargs.pop("_profile", None),
            metadata=dict(submit_kwargs.pop("_md_provenance", None) or {}),
        )
        self._task = self._spawn(self.run_once(**submit_kwargs))

    async def run_once(self, **submit_kwargs) -> None:
        """The full lifecycle as one coroutine (Voilà spawns it as a task;
        tests ``asyncio.run`` it directly)."""
        try:
            self._set_state(STAGING)
            self._set_state(SUBMITTING)
            self._log("[cloud] Staging inputs to S3 and submitting to AWS Batch…")
            result = await self._to_thread(
                lambda: self._bridge_factory().submit(**submit_kwargs)
            )
            job_id = getattr(result, "job_id", None)
            meta = getattr(result, "metadata", {}) or {}
            s3_run = meta.get("s3_run") or getattr(result, "working_directory", None)
            run_id = meta.get("run_id")
            for m in getattr(result, "messages", []) or []:
                self._log(str(m))
            if not job_id or not s3_run:
                raise RuntimeError(
                    "submit-job did not return a job id / S3 run location")
            self._handle.job_id = str(job_id)
            self._handle.s3_run = str(s3_run)
            self._handle.run_id = str(run_id or job_id)
            self._log(f"[cloud] Submitted. job id {job_id}")
            try:
                self._register_run(handle=self._handle, result=result)
            except Exception as reg_err:  # registration must not lose the run
                self._log(f"[cloud] (run registration warning) {reg_err}")
            self._set_state(QUEUED)
            await self._poll_loop(self._handle.job_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- surfaced, classified
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")
            self._set_state(FAILED)

    # -- polling ------------------------------------------------------
    def start_polling(self, job_id: str, *, s3_run: str = "", model: str = "") -> None:
        """Re-attach polling to an already-submitted job (no new submission)."""
        if not job_id:
            return
        if self._task is not None and not self._task.done():
            return  # duplicate-poll guard
        self._handle.job_id = str(job_id)
        if s3_run:
            self._handle.s3_run = s3_run
        if model:
            self._handle.model = model
        self._task = self._spawn(self._poll_loop(str(job_id)))

    async def _poll_loop(self, job_id: str) -> None:
        while not is_terminal(self._handle.state):
            try:
                status = await self._to_thread(
                    lambda: self._bridge_factory().status(job_id=job_id))
                state = getattr(status, "state", "") or normalize_aws_state(
                    getattr(status, "raw_state", ""))
                reason = getattr(status, "reason", "") or ""
            except Exception as poll_err:  # transient AWS/CLI hiccup: keep polling
                self._log(f"[cloud] status check failed, retrying: {poll_err}")
                await self._sleep(self._poll_interval)
                continue

            if state and state != self._handle.state:
                self._set_state(state)
                self._log(f"[cloud] {state}"
                          + (f" — {reason}" if reason and state == FAILED else ""))

            if state == COMPLETED:
                await self._retrieve_results()
                return
            if state in (FAILED, CANCELLED):
                return
            await self._sleep(self._poll_interval)

    async def _retrieve_results(self) -> None:
        self._log("[cloud] Job completed. Retrieving outputs from S3…")
        try:
            path = await self._to_thread(
                lambda: self._sync_results(
                    s3_uri=self._handle.s3_run,
                    region=self._handle.region or None,
                    profile=self._handle.profile,
                )
            )
            self._log(f"[cloud] Outputs synced to {path}")
            self._on_results_ready()
        except Exception as error:  # noqa: BLE001
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")
            # the job DID complete; keep COMPLETED, just report the sync failure

    # -- terminate --------------------------------------------------
    def terminate(self, job_id: str = "") -> None:
        job_id = str(job_id or self._handle.job_id)
        if not job_id:
            self._log("[cloud] No job to terminate.")
            return
        self._spawn(self._terminate_worker(job_id))

    async def _terminate_worker(self, job_id: str) -> None:
        try:
            self._log(f"[cloud] Requesting termination of job {job_id}…")
            await self._to_thread(
                lambda: self._bridge_factory().terminate(job_id=job_id))
            self._set_state(CANCELLED)      # stops the poll loop on its next check
            self._log("[cloud] Termination requested.")
        except Exception as error:  # noqa: BLE001
            short, detail = classify_cloud_failure(error)
            self._log(f"[cloud][ERROR] {short}")
            self._log(f"[cloud][detail] {detail}")

    # -- lifecycle -------------------------------------------------
    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    def attach(self, *, job_id: str, s3_run: str, model: str = "",
               region: str = "", profile: str | None = None,
               state: str = QUEUED) -> None:
        """Re-attach to a run that already exists (e.g. selected from run
        history after a kernel restart) and resume polling if it is not
        terminal."""
        self._handle = _RunHandle(
            job_id=str(job_id), s3_run=str(s3_run), model=model,
            region=region, profile=profile, state=state,
        )
        self._set_state(state)
        if not is_terminal(state):
            self.start_polling(str(job_id))

    # -- internals ------------------------------------------------
    def _spawn(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            return loop.create_task(coro)          # Voilà / async context
        # no running loop (print-mode / a test that used submit()): run to
        # completion now. A test that wants step control awaits run_once itself.
        return asyncio.run(coro)

    async def _sleep(self, seconds: float) -> None:
        # chunked so stop()/cancel() is responsive
        remaining = float(seconds)
        if remaining <= 0:
            await self._sleep_fn(0)
            return
        while remaining > 0 and not is_terminal(self._handle.state):
            await self._sleep_fn(min(0.5, remaining))
            remaining -= 0.5
