"""Gateway-side hosted-pilot runs on the reviewed no-task-role runtime.

One :class:`HostedPilot` lives in the gateway process. A participant's kernel
never sees the pilot role, its ExternalId, a transfer capability or any AWS
credential: it calls the loopback routes in ``routes.py`` and the gateway does
every AWS operation here, after the route has authenticated the user id.

Isolation (decided 15 November): the participant's job carries NO AWS
identity. The reviewed runtime (``execution.build_runtime``) binds, per model,
a funding policy, an immutable execution profile, single-use transfer leases,
a durable result archive and the submission broker. The job's root supervisor
fetches its frozen input from this gateway with the lease, runs the model
unprivileged and posts the result archive back (``pilot_transfer.py``).

Credit: :meth:`HostedPilot.submit` freezes the staged run BEFORE any hold,
holds the policy ceiling, and lets the broker claim and submit. A failure
before the claim releases the hold; from the claim on the hold is kept and a
reconciliation event is recorded -- an uncertain submission is never released
automatically. A terminal job is settled once from its own AWS timestamps.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .charge import charge_cents
from .execution import MODEL_SCRIPT, freeze_tree

LOG = logging.getLogger("cryostack.pilot")

#: statusReason the gateway sets when the participant stops a job
CANCEL_REASON = "Cancelled by the participant (CryoStack pilot)"
LOG_GROUP = "/cryostack/pilot"
_RESERVATION_RE = re.compile(r"\A[a-f0-9]{32}\Z")
_SECRET_ARN_RE = re.compile(
    r"\Aarn:aws:secretsmanager:(?P<region>[a-z0-9-]+):(?P<account>[0-9]{12}):secret:[A-Za-z0-9/_+=.@-]{1,512}\Z")
_MAX_LICENSE_CHARS = 2048
_RECEIPT = ".cryostack-worker.json"
_QUEUED = {"SUBMITTED", "PENDING", "RUNNABLE"}
_RUNNING = {"STARTING", "RUNNING"}
_ZERO_SUMMARY = dict(
    enabled=False, eligible=False, pool_name="", credit_cents=0, reserved_cents=0,
    charged_cents=0, available_cents=0, hold_cents=0, holds={}, expires_at=0, expired=False,
    region="", models=[], limits={}, active_reservation=None,
    matlab_license={"configured": False, "available": False})


class HostedRunError(RuntimeError):
    """A hosted run operation failed. The message is safe to show a participant."""


class SubmissionUncertainError(HostedRunError):
    """A submission may have reached AWS; the hold is kept for reconciliation."""


# ── defaults bound to the real application ──────────────────────────────────
def _default_owner_root(user_id: str) -> Path:
    from cryostack_src.workspace.identity import WorkspaceUser
    from cryostack_src.workspace.roots import owner_root
    return owner_root(WorkspaceUser(user_id=user_id, source="cryostack-auth"))


def _default_workspace_write(owner_root: Path, user_id: str, size: int):
    from cryostack_src.workspace.storage_policy import workspace_write
    return workspace_write(owner_root, user_id, size, what="receiving hosted pilot results")


def _default_helpers(model: str) -> dict:
    """Trusted helper files the reviewed worker expects beside the script."""
    from cryostack_src.cloud import runtime
    if model == "issm":
        files = dict(runtime.issm_postprocess_extra_files())
        files.update(runtime.issm_cloud_runner_extra_files())
        return files
    return dict(runtime.icepack_postprocess_extra_files())


class LicenseRecords:
    """Gateway-side record of each participant's MATLAB license SECRET ARN.

    One owner-only JSON file outside every workspace, keyed by participant
    key. It holds ARNs only -- never a license value, never a user id.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError("license record file is malformed")
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_name(self.path.name + f".{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True)
        os.replace(temporary, self.path)

    def get(self, key: str) -> str:
        with self._lock:
            entry = self._read().get(key)
        return str(entry.get("secret_arn") or "") if isinstance(entry, dict) else ""

    def set(self, key: str, arn: str, *, at: float = 0.0) -> None:
        with self._lock:
            data = self._read()
            data[key] = {"secret_arn": arn, "updated_at": at}
            self._write(data)

    def clear(self, key: str) -> None:
        with self._lock:
            data = self._read()
            if data.pop(key, None) is not None:
                self._write(data)


def _error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        return str((response.get("Error") or {}).get("Code") or "")
    return ""


class HostedPilot:
    """The participant-facing operations of an enabled hosted pilot.

    ``runtime`` is a :class:`~.execution.PilotRuntime` (tests inject one built
    from fakes). Without it, :func:`~.execution.build_runtime` binds the real
    reviewed modules to ``storage``; any review mismatch raises and the caller
    leaves the feature off.
    """

    def __init__(self, config, storage, *, runtime=None, identity=None, isolation=None,
                 owner_root_for=None, workspace_write=None, helpers=None,
                 license_records=None, clients=None, worker_source=None, clock=time.time,
                 logger=None, connector_licenses=None):
        if config is None or not config.enabled:
            raise ValueError("the hosted pilot is not enabled")
        self.config, self.storage, self.clock = config, storage, clock
        self.log = logger or LOG
        if identity is None:
            from . import identity as identity          # noqa: PLW0127
        if isolation is None:
            from . import isolation as isolation        # noqa: PLW0127
        self.identity, self.isolation = identity, isolation
        self._owner_root_for = owner_root_for or _default_owner_root
        self._workspace_write = workspace_write or _default_workspace_write
        self._helpers = helpers or _default_helpers
        if license_records is None:
            license_records = LicenseRecords(Path(config.state_dir) / "pilot_matlab_licenses.json")
        self._licenses = license_records
        if runtime is None:
            from .execution import build_runtime
            runtime = build_runtime(config, storage, clients=clients,
                                    license_arn_for=self._license_arn_required,
                                    participant_key=identity.participant_key,
                                    worker_source=worker_source, clock=clock)
        self.runtime = runtime
        self.connector_licenses = None
        if config.license_requires_tunnel() and config.connector_license_runtime_sha256:
            if connector_licenses is None:
                from .connector_license import ConnectorLicenses
                connector_licenses = ConnectorLicenses(config)
            self.connector_licenses = connector_licenses
        self._guard = threading.Lock()
        self._user_locks: dict[str, threading.Lock] = {}
        self._settle_lock = threading.Lock()
        #: recent reconciliation-needed events (also logged); never holds a token
        self.reconciliation_events: list[dict] = []

    # ── small helpers ───────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled)

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(m for m in self.config.models if m in self.runtime.lanes)

    def _user_lock(self, user_id: str) -> threading.Lock:
        with self._guard:
            return self._user_locks.setdefault(user_id, threading.Lock())

    def _fail(self, message: str, error: BaseException | None = None, *, cls=HostedRunError):
        reference = uuid.uuid4().hex[:8]
        self.log.error("pilot operation failed ref=%s: %s (%s)", reference, message,
                       type(error).__name__ if error is not None else "-")
        return cls(f"{message} (reference {reference})")

    def _needs_reconciliation(self, user_id, reservation_id, stage):
        event = {"reservation_id": reservation_id, "stage": stage,
                 "participant": self.identity.participant_key(user_id), "at": self.clock()}
        self.reconciliation_events = (self.reconciliation_events + [event])[-200:]
        self.log.error("pilot reconciliation needed: %s", json.dumps(event, sort_keys=True))

    def _lane(self, model: str):
        lane = self.runtime.lanes.get(model)
        if lane is None:
            raise ValueError("This model is not available on pilot credit.")
        return lane

    def _owned(self, user_id: str, reservation):
        """(lane, row) for a reservation this user owns; refuses anything else."""
        if not isinstance(reservation, str) or not _RESERVATION_RE.match(reservation):
            raise ValueError("A hosted run id is required.")
        try:
            lane = self.runtime.lane_of(reservation)
            row = lane.funding.ledger.owned(user_id, reservation)
        except (PermissionError, LookupError, KeyError, TypeError):
            raise PermissionError("This run does not belong to your account.") from None
        return lane, dict(row)

    # ── local path containment ──────────────────────────────────────────────
    def _owner_root(self, user_id: str) -> Path:
        return Path(os.path.realpath(self._owner_root_for(user_id)))

    def _inside_owner(self, user_id: str, path, *, what: str) -> tuple[Path, Path]:
        if not isinstance(path, (str, os.PathLike)) or not str(path).strip() \
                or not os.path.isabs(str(path)):
            raise ValueError(f"{what} must be an absolute path in your workspace.")
        root = self._owner_root(user_id)
        real = Path(os.path.realpath(str(path)))
        if real == root or root not in real.parents:
            raise PermissionError(f"{what} is outside your workspace.")
        return root, real

    # ── MATLAB license: the participant's own secret in the pilot account ───
    def _license_arn(self, user_id: str) -> str:
        """The participant's recorded secret ARN if it is still in scope, else ''."""
        arn = self._licenses.get(self.identity.participant_key(user_id))
        match = _SECRET_ARN_RE.match(arn or "")
        if not match or match.group("account") != self.config.account_id \
                or match.group("region") != self.config.region:
            return ""
        try:
            self.isolation.assert_secret_scope(user_id, arn, account_id=self.config.account_id,
                                               region=self.config.region)
        except Exception:  # noqa: BLE001 - out of scope == not configured
            return ""
        return arn

    def _license_arn_required(self, user_id: str) -> str:
        """Resolver bound into the ISSM execution profile; raises when absent."""
        arn = self._license_arn(user_id)
        if not arn:
            raise PermissionError("No MATLAB license is configured for hosted runs.")
        return arn

    def _issm_available(self) -> bool:
        return "issm" in self.models and (not self.config.license_requires_tunnel()
                                         or self.connector_licenses is not None)

    def _license_view(self, user_id: str) -> dict:
        try:
            configured = bool(self._license_arn(user_id))
        except Exception:  # noqa: BLE001
            configured = False
        view = {"configured": configured, "available": self._issm_available()}
        if self.connector_licenses is not None:
            view.update(requires_connector=True,
                        connector_connected=self.connector_licenses.connected(user_id))
        return view

    def set_matlab_license(self, user_id: str, *, value) -> dict:
        """Store the license value as THIS participant's secret in the pilot
        account. Only the returned ARN is kept; the value is never logged,
        echoed, persisted or placed in an exception."""
        if not self._issm_available():
            raise PermissionError("ISSM is not available on pilot credit at this site.")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("A license value is required.")
        value = value.strip()
        if len(value) > _MAX_LICENSE_CHARS or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            raise ValueError("The license value must be a single line of at most "
                             f"{_MAX_LICENSE_CHARS} characters.")
        if not bool(self._funding_summary(user_id).get("eligible")):
            raise PermissionError("Pilot credit is required to configure a hosted MATLAB license.")
        name = self.identity.participant_secret_name(user_id)
        failure = None
        try:
            client = self.runtime.clients("secretsmanager")
            try:
                arn = client.create_secret(Name=name, SecretString=value)["ARN"]
            except Exception as error:  # noqa: BLE001
                code = _error_code(error)
                if code == "InvalidRequestException":        # scheduled for deletion
                    client.restore_secret(SecretId=name)
                elif code != "ResourceExistsException":
                    raise
                arn = client.put_secret_value(SecretId=name, SecretString=value)["ARN"]
            match = _SECRET_ARN_RE.match(str(arn))
            if not match or match.group("account") != self.config.account_id:
                raise RuntimeError("unexpected secret location")
            self.isolation.assert_secret_scope(user_id, arn, account_id=self.config.account_id,
                                               region=self.config.region)
            self._licenses.set(self.identity.participant_key(user_id), arn, at=self.clock())
        except BaseException as error:  # the error may quote the value: keep only its type
            failure = type(error).__name__
            if not isinstance(error, Exception):
                raise
        if failure is not None:
            reference = uuid.uuid4().hex[:8]
            self.log.error("pilot license store failed ref=%s (%s)", reference, failure)
            raise HostedRunError(f"The MATLAB license could not be stored. (reference {reference})")
        return {"configured": True}

    def clear_matlab_license(self, user_id: str) -> dict:
        """Forget the license and schedule its secret for deletion."""
        self._licenses.clear(self.identity.participant_key(user_id))
        try:
            self.runtime.clients("secretsmanager").delete_secret(
                SecretId=self.identity.participant_secret_name(user_id), RecoveryWindowInDays=7)
        except Exception as error:  # noqa: BLE001 - forgetting locally is what matters
            if _error_code(error) != "ResourceNotFoundException":
                self.log.error("pilot license delete failed (%s)", type(error).__name__)
        return {"configured": False}

    def license_runtime(self, reservation, token):
        """Only the reservation's supervisor can request the trusted runtime."""
        row = self.runtime.transfer_leases.authorize(reservation, token, operation="input")
        spec = json.loads(row["spec_json"])
        if (self.connector_licenses is None or spec.get("model") != "issm"
                or self.runtime.lane_of(reservation).profile.license_runtime_sha256
                   != self.config.connector_license_runtime_sha256):
            raise PermissionError("This reservation has no reviewed license tunnel")
        return self.connector_licenses.issue(row["user_id"], reservation)

    def release_license(self, reservation, token):
        row = self.runtime.transfer_leases.authorize(reservation, token, operation="input")
        if self.connector_licenses is not None:
            self.connector_licenses.revoke(row["user_id"], reservation)
        return b"{}"

    def _revoke_license(self, user_id, reservation):
        if self.connector_licenses is not None:
            try:
                self.connector_licenses.revoke(user_id, reservation)
            except Exception as error:
                self.log.error("pilot license revoke failed (%s)", type(error).__name__)

    # ── summary ─────────────────────────────────────────────────────────────
    def _funding_summary(self, user_id: str) -> dict:
        lanes = [self.runtime.lanes[m] for m in self.models]
        if not lanes:
            return {}
        return dict(lanes[0].funding.summary(user_id))

    def summary(self, user_id: str) -> dict:
        result = dict(_ZERO_SUMMARY)
        try:
            funding = self._funding_summary(user_id)
            if not funding.get("admission_enabled"):
                return result
            for key in ("eligible", "pool_name", "credit_cents", "reserved_cents", "charged_cents",
                        "available_cents", "hold_cents", "expires_at", "expired", "active_reservation"):
                if key in funding:
                    result[key] = funding[key]
            result.update(self.config.public_view())
            result["enabled"] = True
            result["models"] = [m for m in self.models if m != "issm" or self._issm_available()]
            result["holds"] = {m: self.runtime.lanes[m].funding.policy.ceiling_cents
                               for m in result["models"]}
            result["matlab_license"] = self._license_view(user_id)
            return result
        except Exception as error:  # noqa: BLE001 - a summary never raises
            self.log.error("pilot summary failed (%s)", type(error).__name__)
            return dict(_ZERO_SUMMARY)

    # ── submit ──────────────────────────────────────────────────────────────
    def submit(self, user_id: str, *, staged_source, model, run_target, request_key,
               seconds=None) -> dict:
        model = model.strip().lower() if isinstance(model, str) else ""
        lane = self._lane(model)
        target = run_target.strip() if isinstance(run_target, str) else ""
        parts = PurePosixPath(target).parts
        if not target or target.startswith(("/", "~")) or "\\" in target or ".." in parts:
            raise ValueError("The run target must be a file inside the staged run.")
        target = PurePosixPath(target).as_posix()
        if model == "issm" and PurePosixPath(target).suffix != ".m":
            raise ValueError("An ISSM run target must be a MATLAB .m script.")
        if model == "icepack" and PurePosixPath(target).suffix != ".py":
            raise ValueError("An Icepack run target must be a Python .py script.")
        limit = min(int(lane.funding.policy.max_seconds), int(self.config.limits.max_model_seconds))
        seconds = limit if seconds is None else seconds
        if type(seconds) is not int or not 1 <= seconds <= limit:
            raise ValueError(f"Run time must be between 1 and {limit} seconds.")
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 200:
            raise ValueError("A request key is required.")
        root, source = self._inside_owner(user_id, staged_source, what="The staged run")
        if not source.is_dir():
            raise ValueError("The staged run is not a directory.")
        if model == "issm":           # checked BEFORE any hold
            if not self._issm_available():
                raise PermissionError(
                    "ISSM on pilot credit needs a MATLAB license service reachable from AWS, "
                    "which this site does not have. Run ISSM on your own AWS account instead.")
            if self.config.license_requires_tunnel() and not self.connector_licenses.connected(user_id):
                raise PermissionError("Connect your institutional Connector before launching ISSM on pilot credit.")
            if not self._license_arn(user_id):
                raise PermissionError(
                    "Configure your MATLAB license for hosted runs before launching ISSM.")

        lock = self._user_lock(user_id)
        if not lock.acquire(blocking=False):
            raise PermissionError("A hosted run is already being submitted for your account.")
        try:
            try:
                data, script_sha = freeze_tree(root, source, script=MODEL_SCRIPT[model],
                                               target=target, extra_files=self._helpers(model))
            except OSError as error:
                if error.errno is None:          # our own containment refusal
                    raise
                raise ValueError("The staged run could not be read.") from None
            input_sha = hashlib.sha256(data).hexdigest()
            run = lane.run(seconds, input_sha, script_sha)
            lane.validate_input(data, run)               # clear errors before any hold
            # frozen bytes are durable before credit is held: nothing fallible
            # sits between the hold and the broker's own read
            self.runtime.inputs.put(self.identity.participant_key(user_id), input_sha, data)
            held = lane.funding.reserve(user_id, request_key=request_key, model=model,
                                        seconds=seconds, input_sha256=input_sha,
                                        script_sha256=script_sha)
            reservation = held["id"]
            try:
                lane.broker.submit(user_id, reservation)
            except Exception as error:  # noqa: BLE001
                self._after_failed_submit(lane, user_id, reservation, error)
            row = dict(lane.funding.ledger.owned(user_id, reservation))
            return {"reservation_id": row["id"], "job_id": row.get("external_job_id") or "",
                    "model": model, "region": self.config.region,
                    "hold_cents": int(row.get("ceiling") or 0), "state": "queued"}
        finally:
            lock.release()

    def _after_failed_submit(self, lane, user_id, reservation, error):
        try:
            state = lane.funding.ledger.owned(user_id, reservation)["state"]
        except Exception:  # noqa: BLE001
            state = "unknown"
        if state == "submitting":
            try:
                attempt = lane.broker.attempt_for_owner(user_id, reservation)
                phase = (attempt or {}).get("phase")
                if phase in ("claimed", "parameter_ready", "definition_ready"):
                    lane.funding.ledger.release_pre_submit_failure(
                        user_id, reservation, profile_sha256=lane.broker.profile.fingerprint,
                        expected_phase=phase, reason="Hosted adapter failed before durable SubmitJob attempt.")
                    state = "released"
            except Exception:  # noqa: BLE001 - changed/uncertain evidence retains the hold
                state = "unknown"
        if state == "released":
            self._cleanup(lane, reservation)
            raise self._fail("The hosted run could not be started; no credit was used.", error) from None
        if state == "reserved":                          # never claimed: no job can exist
            try:
                lane.funding.release(user_id, reservation)
            except Exception as release_error:  # noqa: BLE001
                self._needs_reconciliation(user_id, reservation, "release")
                raise self._fail("The hosted run could not be started.", release_error) from None
            raise self._fail("The hosted run could not be started; no credit was used.",
                             error) from None
        self._needs_reconciliation(user_id, reservation, "submit")
        raise self._fail("The hosted run may have started but could not be confirmed; its credit "
                         "is held until an operator checks it.", error,
                         cls=SubmissionUncertainError) from None

    # ── observe and settle ──────────────────────────────────────────────────
    def _describe(self, user_id: str, row: dict) -> dict:
        """DescribeJobs, refusing a job that is not this reservation's."""
        job_id = row.get("external_job_id")
        if not job_id:
            return {}
        jobs = self.runtime.clients("batch").describe_jobs(jobs=[job_id]).get("jobs") or []
        jobs = [j for j in jobs if j.get("jobId") == job_id]
        if len(jobs) != 1:
            raise LookupError("job not found")
        job = jobs[0]
        tags = job.get("tags") or {}
        if (job.get("jobName") != "cryostack-pilot-" + row["id"]
                or tags.get("cryostack:reservation") != row["id"]
                or tags.get("cryostack:owner") != hashlib.sha256(user_id.encode()).hexdigest()):
            raise PermissionError("This run does not belong to your account.")
        return job

    def _settle(self, lane, row: dict, evidence: dict) -> int:
        """Settle a terminal job exactly once from its AWS timestamps."""
        with self._settle_lock:
            current = lane.funding.ledger.job(row["id"])
            if current and current["state"] == "settled":
                return int(current.get("charged") or 0)
            hold = int(row.get("ceiling") or 0)
            try:
                charge = charge_cents(
                    vcpu=2, memory_mib=8192, started_at=evidence.get("started_at_ms") or None,
                    stopped_at=evidence.get("stopped_at_ms") or None,
                    created_at=evidence.get("created_at_ms") or None,
                    task_rate_usd_per_hour=self.config.compute_rate_usd_per_hour,
                    ancillary_cents=self.config.ancillary_allowance_cents)
            except (ValueError, TypeError):
                charge = hold                      # no usable evidence: charge the whole hold
            charge = max(0, min(hold, int(charge)))
            lane.funding.settle(row["id"], external_job_id=row["external_job_id"],
                                outcome=evidence["status"], charge_cents=charge)
        self._cleanup(lane, row["id"])
        return charge

    def _cleanup(self, lane, reservation: str) -> None:
        """After settlement: revoke the lease, delete the transfer parameter
        and the one-off job definition. Best effort; failures only log."""
        row = lane.job(reservation)
        if row:
            self._revoke_license(row["user_id"], reservation)
        try:
            lane.leases.revoke(reservation)
        except Exception as error:  # noqa: BLE001
            self.log.error("pilot lease revoke failed (%s)", type(error).__name__)
        try:
            self.runtime.clients("ssm").delete_parameter(
                Name=self.config.ssm_parameter_prefix + reservation)
        except Exception as error:  # noqa: BLE001
            if _error_code(error) != "ParameterNotFound":
                self.log.error("pilot parameter delete failed (%s)", type(error).__name__)
        try:
            attempt = lane.broker.attempt_for_owner(lane.job(reservation)["user_id"], reservation)
            arn = (attempt or {}).get("definition_arn")
            if arn:
                self.runtime.clients("batch").deregister_job_definition(jobDefinition=arn)
        except Exception as error:  # noqa: BLE001
            self.log.error("pilot definition cleanup failed (%s)", type(error).__name__)

    def _results_state(self, reservation: str) -> str:
        connection = self.storage._connect()
        try:
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                                      "name='pilot_result_archives'").fetchone():
                return ""
            row = connection.execute("SELECT state FROM pilot_result_archives WHERE reservation=?",
                                     (reservation,)).fetchone()
            return str(row[0]) if row else ""
        finally:
            connection.close()

    def status(self, user_id: str, reservation) -> dict:
        lane, row = self._owned(user_id, reservation)
        view = {"reservation_id": row["id"], "job_id": row.get("external_job_id") or "",
                "model": lane.model, "hold_cents": int(row.get("ceiling") or 0),
                "charged_cents": None, "raw_state": "", "status_reason": "", "results": ""}
        state = row["state"]
        if state == "reserved":
            view["state"] = "submitting"
        elif state == "released":
            view["state"] = "not_started"
        elif state == "submitting":
            view.update(state="uncertain", status_reason=(
                "The submission could not be confirmed; its credit is held until an operator "
                "checks it."))
        else:
            if state == "running":
                try:
                    evidence = lane.broker.watch_reservation(row["id"], now=self.clock())
                except Exception as error:  # noqa: BLE001
                    raise self._fail("The hosted run status could not be read.", error) from None
                raw = evidence["status"]
                if evidence.get("terminal_confirmed"):
                    try:
                        view["charged_cents"] = self._settle(lane, row, evidence)
                    except Exception as error:  # noqa: BLE001 - reconcile() retries
                        self._needs_reconciliation(user_id, row["id"], "settle")
                        self.log.error("pilot settlement failed (%s)", type(error).__name__)
            else:                                        # settled
                raw = str(row.get("outcome") or "")
                view["charged_cents"] = int(row.get("charged") or 0)
            reason = ""
            if raw != "SUCCEEDED":
                try:
                    job = self._describe(user_id, row)
                    reason = str(job.get("statusReason") or
                                 (job.get("container") or {}).get("reason") or "")
                except Exception:  # noqa: BLE001 - the reason is a courtesy
                    reason = ""
            if raw in _QUEUED:
                view["state"] = "queued"
            elif raw in _RUNNING:
                view["state"] = "running"
            elif raw == "SUCCEEDED":
                view["state"] = "completed"
            elif raw == "FAILED":
                view["state"] = "cancelled" if reason.startswith(CANCEL_REASON) else "failed"
            else:
                view["state"] = "unknown"
            view["raw_state"] = raw
            view["status_reason"] = reason[:500]
        view["results"] = self._results_state(row["id"])
        return view

    def logs(self, user_id: str, reservation, *, limit: int = 200) -> str:
        lane, row = self._owned(user_id, reservation)
        if not row.get("external_job_id"):
            return "Logs are not available yet."
        try:
            job = self._describe(user_id, row)
            stream = (job.get("container") or {}).get("logStreamName")
            if not stream:
                return f"Logs are not available yet. Job status: {job.get('status', 'UNKNOWN')}"
            if not str(stream).startswith("pilot/"):
                raise PermissionError("This log stream does not belong to your account.")
            try:
                events = self.runtime.clients("logs").get_log_events(
                    logGroupName=LOG_GROUP, logStreamName=stream,
                    limit=max(1, min(1000, int(limit))), startFromHead=False).get("events") or []
            except Exception as error:  # noqa: BLE001
                if _error_code(error) == "ResourceNotFoundException":
                    return "Logs are not available yet."
                raise
            return "\n".join(str(e.get("message", "")) for e in events) or "(no log output yet)"
        except PermissionError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._fail("The hosted run logs could not be read.", error) from None

    def terminate(self, user_id: str, reservation) -> dict:
        lane, row = self._owned(user_id, reservation)
        if row["state"] == "reserved":
            try:
                lane.funding.release(user_id, row["id"])
                return {"ok": True, "action": "released", "reservation_id": row["id"]}
            except ValueError:                           # claimed meanwhile
                row = dict(lane.funding.ledger.owned(user_id, row["id"]))
        if row["state"] in ("settled", "released"):
            return {"ok": True, "action": "none", "reservation_id": row["id"]}
        if row["state"] == "submitting" or not row.get("external_job_id"):
            raise PermissionError("This run cannot be stopped until an operator confirms it started.")
        try:
            job = self._describe(user_id, row)
            if str(job.get("status") or "").upper() in ("SUCCEEDED", "FAILED"):
                return {"ok": True, "action": "none", "reservation_id": row["id"]}
            self.runtime.clients("batch").terminate_job(jobId=row["external_job_id"],
                                                        reason=CANCEL_REASON)
        except PermissionError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._fail("The hosted run could not be stopped.", error) from None
        self._revoke_license(user_id, row["id"])
        # no result upload after a stop; settlement follows once AWS reports the end
        try:
            lane.leases.revoke(row["id"])
        except Exception as error:  # noqa: BLE001
            self.log.error("pilot lease revoke failed (%s)", type(error).__name__)
        return {"ok": True, "action": "stopping", "reservation_id": row["id"]}

    # ── results ─────────────────────────────────────────────────────────────
    def _extractor(self, root: Path, target: Path):
        """The quota-admitted workspace writer ``import_to_workspace`` calls.

        It must raise ``QuotaExceeded`` (from the quota reservation) BEFORE
        writing anything; the archive was validated by the archive module."""
        def admit(user_id, reservation, data, digest):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = [e for e in archive.infolist()
                           if not e.is_dir() and e.filename.rstrip("/") != _RECEIPT]
                size = sum(e.file_size for e in entries)
                with self._workspace_write(root, user_id, size):
                    target.mkdir(parents=True, exist_ok=True)
                    base = Path(os.path.realpath(target))
                    if base == root or root not in base.parents:
                        raise PermissionError("The results folder is outside your workspace.")
                    for entry in entries:
                        name = PurePosixPath(entry.filename)
                        if name.is_absolute() or ".." in name.parts:
                            raise ValueError("Unsafe result entry")
                        destination = base.joinpath(*name.parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        parent = Path(os.path.realpath(destination.parent))
                        if parent != base and base not in parent.parents:
                            raise PermissionError("A result path leaves the results folder.")
                        if destination.is_symlink() or (destination.exists()
                                                        and not destination.is_file()):
                            raise ValueError("A result would replace a link or folder.")
                        temporary = destination.with_name(f".{uuid.uuid4().hex}.part")
                        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                             | getattr(os, "O_NOFOLLOW", 0), 0o644)
                        with os.fdopen(descriptor, "wb") as handle, archive.open(entry) as stream:
                            while block := stream.read(1 << 20):
                                handle.write(block)
                        os.replace(temporary, destination)
        return admit

    def sync_results(self, user_id: str, reservation, *, destination) -> dict:
        lane, row = self._owned(user_id, reservation)
        root, target = self._inside_owner(user_id, destination, what="The results folder")
        if target.exists() and not target.is_dir():
            raise ValueError("The results folder is not a directory.")
        try:
            outcome = lane.archives.import_to_workspace(user_id, row["id"],
                                                        admit_output=self._extractor(root, target))
        except FileNotFoundError:
            raise ValueError("No results were returned for this run.") from None
        except PermissionError:
            raise
        except Exception as error:  # noqa: BLE001
            raise self._fail("The hosted run results could not be retrieved.", error) from None
        if not outcome.get("workspace_admitted"):
            raise PermissionError("Your workspace is full. Free some space, then fetch the results "
                                  "again; they are kept in the cloud until the pilot ends.")
        files = sum(len(names) for _p, _d, names in os.walk(target)) if target.is_dir() else 0
        return {"synced": True, "reservation_id": row["id"], "files": files}

    # ── reconciliation ──────────────────────────────────────────────────────
    def _running_rows(self) -> list[dict]:
        connection = self.storage._connect()
        try:
            return [dict(r) for r in connection.execute(
                "SELECT id,user_id,external_job_id,ceiling,state FROM project_funding_jobs "
                "WHERE state='running' AND external_job_id IS NOT NULL")]
        finally:
            connection.close()

    def reconcile(self) -> dict:
        """Observe every recorded job; settle the ended ones. Safe to repeat.

        Covers a kernel or browser that went away. The broker asks AWS to stop
        a job past its startup or task allowance, or whose account or pool is
        no longer active. Absence of a job never releases or settles a hold.
        """
        report = {"checked": 0, "settled": 0, "pending": 0, "errors": 0, "stopped": 0}
        try:
            rows = self._running_rows()
        except Exception as error:  # noqa: BLE001
            self.log.error("pilot reconcile could not list jobs (%s)", type(error).__name__)
            report["errors"] += 1
            return report
        for row in rows:
            report["checked"] += 1
            try:
                lane = self.runtime.lane_of(row["id"])
                evidence = lane.broker.watch_reservation(row["id"], now=self.clock())
                if evidence.get("termination_requested"):
                    report["stopped"] += 1
                if evidence.get("terminal_confirmed"):
                    self._settle(lane, row, evidence)
                    report["settled"] += 1
                else:
                    report["pending"] += 1
            except Exception as error:  # noqa: BLE001
                report["errors"] += 1
                self.log.error("pilot reconcile failed for reservation %s (%s)",
                               row.get("id"), type(error).__name__)
        return report


__all__ = ["CANCEL_REASON", "HostedPilot", "HostedRunError", "LicenseRecords",
           "SubmissionUncertainError"]
