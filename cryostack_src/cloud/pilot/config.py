"""Gateway-only configuration of the hosted pilot account.

The file named by ``CRYOSTACK_PILOT_CONFIG`` describes the ONE project-owned
AWS account that invited participants run in, and the reviewed execution
profile every hosted job is bound to (``control_center.services.
project_execution.PilotExecutionProfile``). It holds the pilot role ARN and
ExternalId, so it is read by the gateway process only: the variable name is
deliberately absent from the Voila kernel environment allowlist, the file must
be owner-only (0600), and :class:`PilotConfig` never renders the role or
ExternalId.

No variable -> ``load_pilot_config()`` returns ``None`` and the feature is off.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

PILOT_CONFIG_ENV = "CRYOSTACK_PILOT_CONFIG"
_MAX_CONFIG_BYTES = 64 * 1024
SUPPORTED_MODELS = ("icepack", "issm")
#: fixed by the reviewed execution profile and worker
SSM_PARAMETER_PREFIX = "/cryostack/pilot-transfer/"
TASK_VCPU, TASK_MEMORY_MIB = 2, 8192
MAX_INPUT_MIB, MAX_INPUT_FILES = 64, 256

_REGION_RE = re.compile(r"\A[a-z]{2}-[a-z]+-[1-9]\Z")
_ACCOUNT_RE = re.compile(r"\A[0-9]{12}\Z")
_ROLE_RE = re.compile(r"\Aarn:aws:iam::(?P<account>[0-9]{12}):role/[A-Za-z0-9+=,.@_/-]{1,128}\Z")
_SHA_RE = re.compile(r"\A[a-f0-9]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,100}\Z")
_IMAGE_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/:-]{0,400}@sha256:[a-f0-9]{64}\Z")

_KEYS = {"enabled", "region", "account_id", "role_arn", "external_id", "execution_role_arn",
         "job_queue", "transfer_origin", "worker_sha256", "bootstrap_sha256", "network_review_id",
         "price_review_id", "compute_rate_usd_per_hour", "ancillary_allowance_cents", "limits",
         "ssm_parameter_prefix", "result_archive", "models", "matlab_license_requires_tunnel",
         "state_dir", "connector_license_runtime_sha256"}
_REQUIRED = ("region", "account_id", "role_arn", "external_id", "execution_role_arn", "job_queue",
             "transfer_origin", "worker_sha256", "bootstrap_sha256", "network_review_id",
             "result_archive", "models")
_LIMIT_KEYS = {"max_model_seconds", "task_timeout_seconds", "startup_timeout_seconds"}
_POLICY_REQUIRED = {"policy_id", "pool_id", "ceiling_cents", "campaign_cap_cents"}
_POLICY_KEYS = _POLICY_REQUIRED | {"max_seconds", "max_platform_jobs", "execution_profile", "image_digest"}


class PilotConfigError(ValueError):
    """The pilot configuration is unreadable, unsafe or malformed.

    Messages name the offending field, never its value.
    """


@dataclass(frozen=True)
class PilotLimits:
    max_model_seconds: int = 360
    task_timeout_seconds: int = 480
    startup_timeout_seconds: int = 900

    def public(self) -> dict:
        return {"vcpu": TASK_VCPU, "memory_mib": TASK_MEMORY_MIB,
                "max_seconds": self.max_model_seconds, "max_input_mib": MAX_INPUT_MIB,
                "max_input_files": MAX_INPUT_FILES}


@dataclass(frozen=True)
class PilotModel:
    """One model's pinned image and reviewed funding policy mapping."""
    image: str
    policy: Mapping[str, Any]


@dataclass(frozen=True)
class PilotConfig:
    enabled: bool
    region: str
    account_id: str
    role_arn: str = field(repr=False)
    external_id: str = field(repr=False)
    execution_role_arn: str = ""
    job_queue: str = ""
    transfer_origin: str = ""
    worker_sha256: str = ""
    bootstrap_sha256: str = ""
    network_review_id: str = ""
    price_review_id: str = "aws-ohio-fargate-20261019"
    compute_rate_usd_per_hour: str = "0.11985"
    ancillary_allowance_cents: int = 2
    limits: PilotLimits = field(default_factory=PilotLimits)
    ssm_parameter_prefix: str = SSM_PARAMETER_PREFIX
    result_bucket: str = ""
    result_prefix: str = ""
    model_settings: Mapping[str, PilotModel] = field(default_factory=dict)
    #: site fact: does the MATLAB license service need the Connector tunnel
    #: from a cloud task? ``None`` -> the deployment's own site profile decides,
    #: exactly as ``resolve_cloud_matlab_license`` does for connected accounts.
    matlab_license_requires_tunnel: bool | None = None
    #: gateway-only directory: transfer key, frozen inputs, license secret ARNs
    state_dir: str = ""
    #: Empty keeps hosted Connector licensing disabled. A digest pins its trusted runtime.
    connector_license_runtime_sha256: str = ""

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(self.model_settings)

    @property
    def queue_arn(self) -> str:
        return f"arn:aws:batch:{self.region}:{self.account_id}:job-queue/{self.job_queue}"

    def license_requires_tunnel(self) -> bool:
        if self.matlab_license_requires_tunnel is not None:
            return bool(self.matlab_license_requires_tunnel)
        try:
            from cryostack_src.cloud.matlab_license import site_requires_cloud_license_tunnel
            return bool(site_requires_cloud_license_tunnel())
        except Exception:  # noqa: BLE001 - unknown site: assume the stricter answer
            return True

    def __repr__(self) -> str:
        return (f"PilotConfig(enabled={self.enabled!r}, region={self.region!r}, "
                f"models={self.models!r}, role_arn=<redacted>, external_id=<redacted>)")

    __str__ = __repr__

    def public_view(self) -> dict:
        """Only what a participant may know."""
        return {"enabled": bool(self.enabled), "region": self.region,
                "models": list(self.models), "limits": self.limits.public()}


def _text(raw: Mapping, key: str, pattern: re.Pattern | None = None, default=None) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise PilotConfigError(f"pilot config field {key!r} must be a non-empty string")
    value = value.strip()
    if pattern is not None and not pattern.match(value):
        raise PilotConfigError(f"pilot config field {key!r} is not valid")
    return value


def _integer(raw: Mapping, key: str, default: int, low: int, high: int) -> int:
    value = raw.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise PilotConfigError(f"pilot config value {key!r} must be a whole number between {low} and {high}")
    return value


def parse_pilot_config(raw: Any, *, default_state_dir: str = "") -> PilotConfig:
    if not isinstance(raw, dict):
        raise PilotConfigError("pilot config must be a JSON object")
    unknown = sorted(str(k) for k in raw if k not in _KEYS)
    if unknown:
        raise PilotConfigError("unknown pilot config field(s): " + ", ".join(unknown))
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise PilotConfigError("missing pilot config field(s): " + ", ".join(missing))
    enabled = raw.get("enabled", False)
    if type(enabled) is not bool:
        raise PilotConfigError("pilot config field 'enabled' must be true or false")

    account_id = _text(raw, "account_id", _ACCOUNT_RE)
    role_arn = _text(raw, "role_arn", _ROLE_RE)
    execution_role_arn = _text(raw, "execution_role_arn", _ROLE_RE)
    for key, arn in (("role_arn", role_arn), ("execution_role_arn", execution_role_arn)):
        if _ROLE_RE.match(arn).group("account") != account_id:
            raise PilotConfigError(f"pilot config field {key!r} is not in the pilot account")
    if role_arn == execution_role_arn:
        raise PilotConfigError("pilot config field 'execution_role_arn' must be a separate role")
    external_id = _text(raw, "external_id")
    if not re.fullmatch(r"[A-Za-z0-9+=,.@:/_-]{2,1224}", external_id):
        raise PilotConfigError("pilot config field 'external_id' is not valid")
    origin = _text(raw, "transfer_origin")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]{1,253}(?::[0-9]{1,5})?/?", origin):
        raise PilotConfigError("pilot config field 'transfer_origin' must be a bare https:// origin")
    prefix = _text(raw, "ssm_parameter_prefix", default=SSM_PARAMETER_PREFIX)
    if prefix != SSM_PARAMETER_PREFIX:
        raise PilotConfigError("pilot config field 'ssm_parameter_prefix' differs from the reviewed prefix")
    rate = _text(raw, "compute_rate_usd_per_hour", re.compile(r"\A[0-9]{1,2}(?:\.[0-9]{1,6})?\Z"), "0.11985")

    limits_raw = raw.get("limits", {})
    if not isinstance(limits_raw, dict) or set(limits_raw) - _LIMIT_KEYS:
        raise PilotConfigError("pilot config field 'limits' has unknown or invalid entries")
    limits = PilotLimits(
        max_model_seconds=_integer(limits_raw, "max_model_seconds", 360, 1, 600),
        task_timeout_seconds=_integer(limits_raw, "task_timeout_seconds", 480, 60, 900),
        startup_timeout_seconds=_integer(limits_raw, "startup_timeout_seconds", 900, 60, 900))
    if limits.task_timeout_seconds < limits.max_model_seconds + 30:
        raise PilotConfigError("pilot limit 'task_timeout_seconds' must exceed the model time by 30 s")

    archive = raw.get("result_archive")
    if not isinstance(archive, dict) or set(archive) != {"bucket", "prefix"}:
        raise PilotConfigError("pilot config field 'result_archive' needs exactly bucket and prefix")
    bucket = _text(archive, "bucket", re.compile(r"\A[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]\Z"))
    result_prefix = _text(archive, "prefix", re.compile(r"\A(?:[A-Za-z0-9_-]+/)*pilot-results/\Z"))

    models_raw = raw.get("models")
    if not isinstance(models_raw, dict) or not models_raw or set(models_raw) - set(SUPPORTED_MODELS):
        raise PilotConfigError("pilot config field 'models' must map supported models ("
                               + ", ".join(SUPPORTED_MODELS) + ") to their image and policy")
    settings: dict[str, PilotModel] = {}
    pools = set()
    for name in SUPPORTED_MODELS:
        if name not in models_raw:
            continue
        entry = models_raw[name]
        if not isinstance(entry, dict) or set(entry) != {"image", "policy"}:
            raise PilotConfigError(f"pilot model {name!r} needs exactly image and policy")
        image, policy = entry["image"], entry["policy"]
        if not isinstance(image, str) or not _IMAGE_RE.match(image) \
                or f"/cryostack-{name}@sha256:" not in image:
            raise PilotConfigError(
                f"pilot model {name!r} needs the cryostack-{name} image pinned by sha256 digest")
        if not isinstance(policy, dict) or set(policy) - _POLICY_KEYS or _POLICY_REQUIRED - set(policy):
            raise PilotConfigError(f"pilot model {name!r} has an incomplete or unknown funding policy")
        pools.add(str(policy.get("pool_id")))
        settings[name] = PilotModel(image=image, policy=MappingProxyType(dict(policy)))
    if len(pools) != 1:
        raise PilotConfigError("every pilot model policy must use the same credit pool")

    tunnel = raw.get("matlab_license_requires_tunnel")
    if tunnel is not None and type(tunnel) is not bool:
        raise PilotConfigError("pilot config field 'matlab_license_requires_tunnel' must be true or false")
    connector_digest = raw.get("connector_license_runtime_sha256", "")
    if not isinstance(connector_digest, str) or (connector_digest and not _SHA_RE.fullmatch(connector_digest)):
        raise PilotConfigError("pilot config field 'connector_license_runtime_sha256' is not valid")
    state_dir = raw.get("state_dir", default_state_dir)
    if not isinstance(state_dir, str) or not state_dir or not os.path.isabs(state_dir):
        raise PilotConfigError("pilot config field 'state_dir' must be an absolute path")

    return PilotConfig(
        enabled=enabled, region=_text(raw, "region", _REGION_RE), account_id=account_id,
        role_arn=role_arn, external_id=external_id, execution_role_arn=execution_role_arn,
        job_queue=_text(raw, "job_queue", re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")),
        transfer_origin=origin.rstrip("/"), worker_sha256=_text(raw, "worker_sha256", _SHA_RE),
        bootstrap_sha256=_text(raw, "bootstrap_sha256", _SHA_RE),
        network_review_id=_text(raw, "network_review_id", _ID_RE),
        price_review_id=_text(raw, "price_review_id", _ID_RE, "aws-ohio-fargate-20261019"),
        compute_rate_usd_per_hour=rate,
        ancillary_allowance_cents=_integer(raw, "ancillary_allowance_cents", 2, 2, 100),
        limits=limits, ssm_parameter_prefix=prefix, result_bucket=bucket, result_prefix=result_prefix,
        model_settings=MappingProxyType(settings), matlab_license_requires_tunnel=tunnel,
        state_dir=state_dir, connector_license_runtime_sha256=connector_digest)


def load_pilot_config(path: str | os.PathLike | None = None,
                      env: Mapping[str, str] | None = None) -> PilotConfig | None:
    """The pilot configuration, or ``None`` when none is configured.

    Raises :class:`PilotConfigError` for a file that is missing, readable by
    group/other (anything but owner-only, e.g. 0600) or malformed.
    """
    source = os.environ if env is None else env
    location = str(path) if path is not None else (source.get(PILOT_CONFIG_ENV) or "").strip()
    if not location:
        return None
    try:
        descriptor = os.open(location, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise PilotConfigError("the pilot config file cannot be opened") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise PilotConfigError("the pilot config must be a regular file")
        if info.st_mode & 0o077:
            raise PilotConfigError("the pilot config file must be readable by its owner only (chmod 600)")
        if info.st_size > _MAX_CONFIG_BYTES:
            raise PilotConfigError("the pilot config file is too large")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            data = handle.read(_MAX_CONFIG_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise PilotConfigError("the pilot config file is not valid JSON") from None
    return parse_pilot_config(raw, default_state_dir=os.path.dirname(os.path.abspath(location)))


__all__ = ["PILOT_CONFIG_ENV", "PilotConfig", "PilotConfigError", "PilotLimits", "PilotModel",
           "SSM_PARAMETER_PREFIX", "load_pilot_config", "parse_pilot_config"]
