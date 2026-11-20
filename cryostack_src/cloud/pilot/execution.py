"""Wiring of the reviewed, unwired pilot execution modules (gateway only).

``control_center.services.project_execution / project_broker / project_transfer
/ project_results`` and ``cryostack_src.cloud.pilot_worker`` implement the
stronger isolation from the October review: the participant's model task has
NO AWS identity (no ``jobRoleArn``, no S3 permission, no access key). This
module builds one *lane* per model -- funding policy, immutable execution
profile, transfer leases, durable result archive and submission broker bound
together -- from :class:`~cryostack_src.cloud.pilot.config.PilotConfig`.

Everything that talks to AWS is an injected client; the default factory makes
single-attempt boto3 clients from a fresh assumption of the pilot role. Wire
debug logging is never enabled here (it would print the transfer capability).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import stat
import threading
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from types import SimpleNamespace

from control_center.services.pilot_funding import PilotFunding, load_policy
from control_center.services.project_broker import PilotSubmissionBroker, validate_frozen_input
from control_center.services.project_execution import BOOTSTRAP, PilotExecutionProfile, _canonical
from control_center.services.project_funding import FundedRun
from control_center.services.project_results import PilotResultArchives, ResultArchiveBinding
from control_center.services.project_transfer import MAX_BYTES, MAX_FILES, PilotTransferLeases

ISSM_SCRIPT = "runme.m"
ISSM_RUNNER = "cryostack_issm_cloud_runner.sh"
MODEL_SCRIPT = {"icepack": "run.py", "issm": ISSM_SCRIPT}
_RESERVED_TOP = ("home", "tmp")
_CREDENTIAL_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
TRANSFER_KEY_NAME = "pilot_transfer.key"


# ── ISSM: the same reviewed task shape plus the participant's license secret ─
@dataclass(frozen=True)
class IssmExecutionProfile(PilotExecutionProfile):
    """The reviewed profile for an ISSM image.

    Identical bounds, role, bootstrap and worker. Two differences: the pinned
    image is ``cryostack-issm`` and the job definition's ``secrets`` block also
    names the PARTICIPANT'S OWN MATLAB-license secret, resolved by the ECS
    execution role. There is still no task role; the supervisor passes
    ``MLM_LICENSE_FILE`` (and nothing else) on to the model.
    """

    license_runtime_sha256: str = ""

    def __post_init__(self):
        if self.license_runtime_sha256 and not re.fullmatch(r"[a-f0-9]{64}", self.license_runtime_sha256):
            raise ValueError("Reviewed license runtime digest required")
        marker = re.escape(f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/cryostack-issm@sha256:")
        if not isinstance(self.image, str) or not re.fullmatch(marker + r"[a-f0-9]{64}", self.image):
            raise ValueError("A pinned ISSM image in the reviewed account is required")
        values = {f.name: getattr(self, f.name) for f in fields(PilotExecutionProfile)}
        values["image"] = self.image.replace("/cryostack-issm@", "/cryostack-icepack@")
        PilotExecutionProfile(**values)               # every other reviewed bound

    @property
    def fingerprint(self):
        values = asdict(self)
        values["bootstrap_sha256"] = hashlib.sha256(BOOTSTRAP.encode()).hexdigest()
        values["licensed_model"] = "issm"
        return hashlib.sha256(_canonical(values).encode()).hexdigest()

    def bind_license(self, license_arn_for, secrets_block) -> "IssmExecutionProfile":
        """``license_arn_for(user_id) -> ARN`` (raises when none) and the
        scope-checking ``secrets_block(user_id, arn, account_id=, region=)``."""
        object.__setattr__(self, "_license_arn_for", license_arn_for)
        object.__setattr__(self, "_secrets_block", secrets_block)
        return self

    def _spec(self, reservation, run):
        if not re.fullmatch(r"[a-f0-9]{32}", reservation or ""):
            raise ValueError("Canonical reservation identifier required")
        if not isinstance(run, FundedRun) or run.model != "issm":
            raise PermissionError("This profile runs ISSM only")
        if type(run.seconds) is not int or not 1 <= run.seconds <= self.max_model_seconds:
            raise ValueError("Reviewed execution bound is invalid")
        for value in (run.input_sha256, run.script_sha256):
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                raise ValueError("Expected a SHA-256 digest")
        result = dict(origin=self.transfer_origin, reservation=reservation,
                      input_sha256=run.input_sha256, script_sha256=run.script_sha256,
                      seconds=run.seconds, model=run.model)
        if self.license_runtime_sha256:
            result["license_runtime_sha256"] = self.license_runtime_sha256
        return result

    def definition(self, policy, *, reservation, user_id, run, transfer_parameter_arn):
        definition = super().definition(policy, reservation=reservation, user_id=user_id, run=run,
                                        transfer_parameter_arn=transfer_parameter_arn)
        resolve = getattr(self, "_license_arn_for", None)
        if resolve is None:
            raise PermissionError("No MATLAB license is bound to this execution profile")
        block = self._secrets_block(user_id, resolve(user_id), account_id=self.account_id,
                                    region=self.region)
        if [entry.get("name") for entry in block] != ["MLM_LICENSE_FILE"]:
            raise PermissionError("Only the MATLAB license may be delivered to an ISSM task")
        container = definition["containerProperties"]
        container["secrets"] = list(container["secrets"]) + [dict(entry) for entry in block]
        return definition

    @staticmethod
    def validate_input(data, run):
        validate_frozen_issm_input(data, run)


def validate_frozen_issm_input(data, run):
    """The ISSM counterpart of ``project_broker.validate_frozen_input``: the
    same bounded regular-ZIP rules; MATLAB sources are hashed, never parsed."""
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
        raise ValueError("Input archive exceeds its allowance")
    if hashlib.sha256(data).hexdigest() != run.input_sha256:
        raise PermissionError("Input bytes differ from the reviewed reservation")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= MAX_FILES:
            raise ValueError("Invalid pilot input entry count")
        names, size = set(), 0
        for entry in entries:
            name = entry.filename.rstrip("/")
            parts = name.split("/")
            mode = entry.external_attr >> 16
            if (not name or "\\" in name or any(p in ("", ".", "..") for p in parts)
                    or parts[0] in ("outputs", "home", "tmp") or name in names or entry.is_dir()
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG) or entry.flag_bits & 1):
                raise ValueError("Unsafe or reserved pilot input entry")
            names.add(name)
            size += entry.file_size
            if size > MAX_BYTES:
                raise ValueError("Expanded pilot input exceeds allowance")
            with archive.open(entry) as stream:
                count = 0
                while block := stream.read(65536):
                    count += len(block)
                    if count > entry.file_size:
                        raise ValueError("Input expansion changed")
        if not {ISSM_SCRIPT, ISSM_RUNNER} <= names:
            raise ValueError("The ISSM run script and its reviewed runner are required")
        for name in (ISSM_SCRIPT, ISSM_RUNNER):
            if archive.getinfo(name).file_size > 1024 ** 2 or not archive.read(name).strip():
                raise ValueError("Pilot source files must be non-empty and at most 1 MiB")
        if hashlib.sha256(archive.read(ISSM_SCRIPT)).hexdigest() != run.script_sha256:
            raise PermissionError("Model script differs from its review")


# ── frozen input ────────────────────────────────────────────────────────────
def freeze_tree(root: Path, source: Path, *, script: str, target: str | None = None,
                extra_files=None) -> tuple[bytes, str]:
    """A deterministic ZIP of the staged tree and the script's SHA-256.

    ``root`` is the owner's workspace (already real-pathed). Symbolic links and
    special files are refused -- a link out of the workspace as a permission
    error. A top-level ``outputs/`` (a previous run's products) is left out.
    ``script`` is the name the reviewed worker runs (``run.py`` / ``runme.m``);
    ``target``, the participant's chosen file, is copied to that name when it
    differs (refused if the staged tree already has a different ``script``).
    ``extra_files`` (name -> text) are trusted helpers added when not staged.
    """
    members: dict[str, bytes] = {}
    total = 0
    for parent, directories, names in os.walk(source, followlinks=False):
        if Path(parent) == source and "outputs" in directories:
            directories.remove("outputs")
        for entry in sorted(directories + names):
            path = Path(parent) / entry
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = Path(os.path.realpath(path))
                if target != root and root not in target.parents:
                    raise PermissionError("The staged run contains a link that points outside your workspace.")
                raise ValueError("The staged run contains a symbolic link; copy the file into the example instead.")
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                raise ValueError("The staged run contains a special file.")
            relative = path.relative_to(source).as_posix()
            if relative.split("/")[0] in _RESERVED_TOP or "\\" in relative:
                raise ValueError("The staged run uses a reserved folder name (home or tmp).")
            if len(members) >= MAX_FILES:
                raise ValueError(f"The staged run has more than {MAX_FILES} files.")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as reader:
                if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                    raise ValueError("The staged run changed while it was being read.")
                body = reader.read(MAX_BYTES - total + 1)
            total += len(body)
            if total > MAX_BYTES:
                raise ValueError(f"The staged run is larger than {MAX_BYTES // 1024 ** 2} MiB.")
            members[relative] = body
    target = script if target is None else target
    if target not in members:
        raise ValueError("The run target is not a file in the staged run.")
    if target != script:
        if script in members and members[script] != members[target]:
            raise ValueError(f"The staged run already has a different {script}; "
                             f"choose {script} as the run target or rename it.")
        members[script] = members[target]
    for name, text in (extra_files or {}).items():
        members.setdefault(name, text.encode("utf-8") if isinstance(text, str) else bytes(text))
    if len(members) > MAX_FILES:
        raise ValueError(f"The staged run has more than {MAX_FILES} files.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])
    data = buffer.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError(f"The staged run is larger than {MAX_BYTES // 1024 ** 2} MiB.")
    return data, hashlib.sha256(members[script]).hexdigest()


class InputStore:
    """Frozen input archives in gateway-only control state, by content hash.

    Written before any credit is held, so nothing fallible sits between the
    reservation and the broker. Never inside a participant workspace."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, participant: str, digest: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{16,64}", participant) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid frozen input reference")
        return self.directory / participant / f"{digest}.zip"

    def put(self, participant: str, digest: str, data: bytes) -> None:
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("frozen input digest mismatch")
        path = self._path(participant, digest)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)

    def get(self, participant: str, digest: str) -> bytes:
        data = self._path(participant, digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise PermissionError("Frozen input bytes changed")
        return data

    def delete(self, participant: str, digest: str) -> None:
        self._path(participant, digest).unlink(missing_ok=True)


# ── transfer key ────────────────────────────────────────────────────────────
def load_transfer_key(state_dir, *, has_active_leases) -> bytes:
    """The gateway-only HMAC key of the transfer capabilities, kept across
    restarts in owner-only local control state. It is created once; if it is
    missing while leases are still active this refuses rather than silently
    making a new key (which would strand running jobs)."""
    directory = Path(state_dir)
    path = directory / TRANSFER_KEY_NAME
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        if has_active_leases():
            raise RuntimeError("the pilot transfer key is missing while transfer leases are active; "
                               "restore it before starting the hosted pilot") from None
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = secrets.token_bytes(48)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
        return key
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RuntimeError("the pilot transfer key must be an owner-only regular file")
        key = handle.read(4096)
    if len(key) < 32:
        raise RuntimeError("the pilot transfer key is unusable")
    return key


def active_leases(storage, clock=time.time) -> bool:
    connection = storage._connect()
    try:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND "
                                  "name='pilot_transfer_leases'").fetchone():
            return False
        return bool(connection.execute(
            "SELECT 1 FROM pilot_transfer_leases WHERE state IN ('ready','uploading') AND expires>?",
            (clock(),)).fetchone())
    finally:
        connection.close()


# ── clients ─────────────────────────────────────────────────────────────────
class ReviewedClient:
    """A single-attempt SDK client that re-creates itself as the short-lived
    pilot-role session ages. ``meta`` states what the broker reviews."""

    def __init__(self, make, region: str, *, ttl: float = 600.0, clock=time.monotonic):
        self.meta = SimpleNamespace(region_name=region,
                                    config=SimpleNamespace(retries={"total_max_attempts": 1}))
        self._make, self._ttl, self._clock = make, ttl, clock
        self._lock, self._client, self._made = threading.Lock(), None, 0.0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        with self._lock:
            if self._client is None or self._clock() - self._made > self._ttl:
                self._client, self._made = self._make(), self._clock()
            return getattr(self._client, name)


class PilotClients:
    """``clients(service)`` -> reviewed client in the pilot account and Region.

    ``assume(role_arn, external_id, region, policy)`` returns temporary
    credentials; the result is checked to be the pilot account."""

    def __init__(self, config, assume):
        self.config, self.assume = config, assume
        self._cache: dict[str, ReviewedClient] = {}

    def credentials(self) -> dict:
        issued = self.assume(self.config.role_arn, self.config.external_id, self.config.region, None)
        account = getattr(issued, "account_id", None)
        if account is not None and str(account) != self.config.account_id:
            raise RuntimeError("assumed session is not in the pilot account")
        values = issued.environment() if hasattr(issued, "environment") else dict(issued or {})
        credentials = {k: values.get(k, "") for k in _CREDENTIAL_KEYS}
        if not all(credentials.values()):
            raise RuntimeError("assume did not return temporary credentials")
        return credentials

    def _make(self, service: str):
        import boto3
        from botocore.config import Config

        credentials = self.credentials()
        return boto3.client(
            service, region_name=self.config.region,
            aws_access_key_id=credentials["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=credentials["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=credentials["AWS_SESSION_TOKEN"],
            config=Config(retries={"total_max_attempts": 1}, connect_timeout=10, read_timeout=60))

    def __call__(self, service: str):
        if service not in self._cache:
            self._cache[service] = ReviewedClient(lambda: self._make(service), self.config.region)
        return self._cache[service]


# ── lanes ───────────────────────────────────────────────────────────────────
@dataclass
class Lane:
    """One model's reviewed binding: policy, profile, leases, archive, broker."""
    model: str
    funding: object
    profile: object
    leases: object
    archives: object
    broker: object

    @property
    def script(self) -> str:
        return MODEL_SCRIPT[self.model]

    def run(self, seconds: int, input_sha256: str, script_sha256: str) -> FundedRun:
        return FundedRun(self.model, seconds, input_sha256, script_sha256)

    def validate_input(self, data: bytes, run) -> None:
        getattr(self.profile, "validate_input", validate_frozen_input)(data, run)

    def job(self, reservation: str):
        """Trusted lookup of a reservation row (owner id, spec, state)."""
        return self.funding.ledger.job(reservation)


class LaneLeases:
    """The one ``leases`` object the transfer routes see: each reservation is
    served by the lane (execution profile) it was reserved under."""

    def __init__(self, lanes: dict):
        self._lanes = lanes

    def _lane(self, reservation):
        if not isinstance(reservation, str) or not re.fullmatch(r"[a-f0-9]{32}", reservation):
            raise PermissionError("Invalid transfer capability")
        for lane in self._lanes.values():
            row = lane.job(reservation)
            if row is not None:
                try:
                    model = json.loads(row["spec_json"]).get("model")
                except (ValueError, TypeError, KeyError):
                    model = None
                if model in self._lanes:
                    return self._lanes[model]
                break
        raise PermissionError("Invalid transfer capability")

    def authorize(self, reservation, token, *, operation):
        return self._lane(reservation).leases.authorize(reservation, token, operation=operation)

    def read(self, reservation, token, *, operation, read_input):
        return self._lane(reservation).leases.read(reservation, token, operation=operation,
                                                    read_input=read_input)

    def accept_output(self, reservation, token, data, *, admit_output):
        return self._lane(reservation).leases.accept_output(reservation, token, data,
                                                             admit_output=admit_output)


@dataclass
class PilotRuntime:
    lanes: dict
    inputs: InputStore
    transfer_leases: LaneLeases
    clients: object
    participant_key: object

    def lane_of(self, reservation: str):
        return self.transfer_leases._lane(reservation)

    def read_input(self, user_id: str, reservation: str) -> bytes:
        """Frozen owner input for the broker and the transfer route."""
        lane = self.lane_of(reservation)
        row = lane.job(reservation)
        if row is None or row["user_id"] != user_id:
            raise PermissionError("Reservation owner mismatch")
        return self.inputs.get(self.participant_key(user_id),
                               json.loads(row["spec_json"])["input_sha256"])

    def stage_output(self, user_id: str, reservation: str, data: bytes, digest: str):
        """The worker's result upload: durable retention first, workspace later."""
        return self.lane_of(reservation).archives.stage(user_id, reservation, data, digest)


def build_runtime(config, storage, *, clients=None, assume=None, license_arn_for=None,
                  secrets_block=None, participant_key=None, worker_source: bytes | None = None,
                  clock=time.time) -> PilotRuntime:
    """Bind every reviewed module for an enabled pilot config. Raises (and the
    caller leaves the feature off) when any review does not line up."""
    if hashlib.sha256(BOOTSTRAP.encode()).hexdigest() != config.bootstrap_sha256:
        raise ValueError("the container bootstrap differs from the pinned bootstrap_sha256")
    if worker_source is None:
        from cryostack_src.cloud import pilot_worker
        worker_source = Path(pilot_worker.__file__).read_bytes()
    if hashlib.sha256(worker_source).hexdigest() != config.worker_sha256:
        raise ValueError("the pilot worker source differs from the pinned worker_sha256")
    if participant_key is None:
        from .identity import participant_key
    if secrets_block is None:
        from .isolation import participant_secrets_block as secrets_block
    if clients is None:
        if assume is None:
            from cryostack_src.cloud.connect.assume_role import assume_role

            def assume(role_arn, external_id, region, policy):
                return assume_role(role_arn=role_arn, external_id=external_id, region=region)
        clients = PilotClients(config, assume)

    binding = ResultArchiveBinding(config.account_id, config.region, config.result_bucket,
                                   config.result_prefix)
    key = load_transfer_key(config.state_dir, has_active_leases=lambda: active_leases(storage, clock))
    inputs = InputStore(Path(config.state_dir) / "pilot_inputs")
    lanes: dict[str, Lane] = {}
    runtime = PilotRuntime(lanes=lanes, inputs=inputs, transfer_leases=LaneLeases(lanes),
                           clients=clients, participant_key=participant_key)
    for model, settings in config.model_settings.items():
        kind = IssmExecutionProfile if model == "issm" else PilotExecutionProfile
        profile = kind(
            account_id=config.account_id, region=config.region, queue_arn=config.queue_arn,
            execution_role_arn=config.execution_role_arn, image=settings.image,
            worker_sha256=config.worker_sha256, transfer_origin=config.transfer_origin,
            network_review_id=config.network_review_id,
            max_model_seconds=config.limits.max_model_seconds,
            task_timeout_seconds=config.limits.task_timeout_seconds,
            startup_timeout_seconds=config.limits.startup_timeout_seconds,
            ancillary_allowance_cents=config.ancillary_allowance_cents,
            compute_rate_usd_per_hour=config.compute_rate_usd_per_hour,
            price_review_id=config.price_review_id,
            result_archive_review_sha256=binding.fingerprint)
        if model == "issm":
            if config.license_requires_tunnel() and config.connector_license_runtime_sha256:
                object.__setattr__(profile, "license_runtime_sha256", config.connector_license_runtime_sha256)
            if license_arn_for is None:
                raise ValueError("an ISSM lane needs the participant license resolver")
            profile.bind_license(license_arn_for, secrets_block)
        mapping = dict(settings.policy)
        for name, value in (("execution_profile", profile.profile_id), ("image_digest", profile.image_digest)):
            if mapping.setdefault(name, value) != value:
                raise ValueError(f"pilot model {model}: policy {name} does not match the execution profile")
        mapping.setdefault("max_seconds", config.limits.max_model_seconds)
        policy = load_policy(mapping)
        try:
            profile.validate_funding(policy)
        except PermissionError:
            raise ValueError(f"pilot model {model}: the hold must be at least "
                             f"{profile.minimum_hold_cents} cents for this execution profile") from None
        funding = PilotFunding(storage, policy, admission_enabled=True, clock=clock)
        leases = PilotTransferLeases(funding.ledger, profile, key=key, worker_source=worker_source,
                                     enabled=True, clock=clock)
        archives = PilotResultArchives(funding.ledger, profile, binding, s3=clients("s3"), enabled=True)
        broker = PilotSubmissionBroker(
            funding.ledger, profile, leases, batch=clients("batch"), ssm=clients("ssm"),
            read_input=runtime.read_input, enabled=True, supervision_enabled=True,
            result_archives=archives)
        lanes[model] = Lane(model, funding, profile, leases, archives, broker)
    return runtime


__all__ = ["IssmExecutionProfile", "InputStore", "Lane", "LaneLeases", "PilotClients", "PilotRuntime",
           "ReviewedClient", "active_leases", "build_runtime", "freeze_tree", "load_transfer_key",
           "validate_frozen_issm_input"]
