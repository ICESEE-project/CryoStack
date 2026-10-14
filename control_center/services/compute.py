"""
Control Center view of CryoStack compute: HPC resources, cloud execution
configuration, execution records and compute-related service logs.

Everything here is read-only over sources that already exist:

    compute profiles       cryostack_src.resources.profiles (installation-wide
                           RESOURCE facts; never personal)
    cloud configuration    cryostack_src.cloud (deterministic AWS Batch names,
                           Fargate/EC2 shapes, guardrails) + the deployment
                           environment the onboarding flow reads
    execution records      the shared experiments table (the Control Center's
                           existing cross-user operational record)
    service logs           the runtime logs declared in
                           deployment/applications.yaml

Per-user data is deliberately NOT read: researchers' SSH identities,
Connector sessions, HPC usernames, allocations, remote directories and
bring-your-own AWS connection records stay inside each user's workspace
(USER x RESOURCE ownership boundary). A live scheduler check would need one
of those, so it is reported as "requires a connected session" instead.

Every string that originates from a record or a log passes through
:func:`redact_text` before it leaves this module.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from ..storage import ControlStorage


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

REGISTRY_PATH = REPOSITORY_ROOT / "deployment" / "applications.yaml"

#: roles that may run operational compute actions (the live relay check)
OPERATOR_ROLES = frozenset({"maintainer", "admin", "owner"})


# ============================================================
# Redaction
# ============================================================

REDACTED = "<redacted>"

_SECRET_KEY_WORDS = (
    r"password|passwd|passphrase|secret|token|session|cookie|api[_-]?key|"
    r"apikey|credential|external[_-]?id|pairing[_-]?code|code[_-]?verifier|"
    r"private[_-]?key|authorization|signature"
)

_REDACTIONS: tuple[tuple[re.Pattern, str], ...] = (
    # PEM private keys (whole block, or the tail of a truncated one)
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

_CONTROL_CHARACTERS = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b-\x1f\x7f]"
)


def redact_text(
    value,
    *,
    limit: int = 500,
) -> str:
    """
    Return ``value`` as a bounded, display-safe string with secret-looking
    material replaced. ``None`` becomes ``""``.
    """

    if value is None:
        return ""

    text = _CONTROL_CHARACTERS.sub(
        "",
        str(value),
    )

    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(
            replacement,
            text,
        )

    text = text.strip()

    if limit and len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"

    return text


def mask_account_id(
    account_id: str | None,
) -> str:
    """``123456789012`` -> ``********9012``; anything else -> ``""``."""

    value = (account_id or "").strip()

    if not (value.isdigit() and len(value) == 12):
        return ""

    return "********" + value[-4:]


# ============================================================
# HPC resources
# ============================================================

#: what every registered resource uses today. RemoteBackend submits with
#: sbatch and reads squeue/sacct; container runs use apptainer; native runs
#: use the ICESEE-Spack environment (cryostack_src.remote.spack_env).
_SCHEDULER = "Slurm"
_CONTAINER_RUNTIME = "Apptainer"


def _resource_view(
    profile,
    aliases: list[str],
) -> dict:

    from cryostack_src.remote import spack_env

    scheduler = profile.scheduler_defaults

    return {
        "name": profile.name,
        "aliases": sorted(aliases),
        "login_host": profile.login_host,
        "ssh_port": int(profile.ssh_port),
        "requires_vpn": bool(profile.requires_vpn),
        "requires_mfa": bool(profile.requires_mfa),
        "access_modes": list(profile.supported_access_modes),
        "auth_modes": list(profile.auth_modes),
        "direct_ssh_trust": profile.direct_ssh_trust,
        "key_registration_method": profile.key_registration_method,
        "portal_name": profile.portal_name,
        "portal_url": profile.portal_url,
        "account_required": bool(profile.account_required),
        "scheduler": {
            "type": _SCHEDULER,
            "default_partition": scheduler.partition,
            "default_wall_time": scheduler.wall_time,
        },
        "container_runtime": _CONTAINER_RUNTIME,
        "software_environment": {
            "name": "ICESEE-Spack",
            "repository": spack_env.DEFAULT_SPACK_REPO,
            "models": sorted(spack_env._INSTALL_FLAG),
        },
        #: compute profiles do not declare environment modules
        "modules": [],
        # The license value names an institutional license server: only
        # whether one is configured is shown, never the value or its port.
        "matlab_license": {
            "configured": bool(profile.has_matlab_license),
            "environment_variable": profile.matlab_license_env,
            "value": (
                "configured (withheld)"
                if profile.has_matlab_license
                else ""
            ),
            "cloud_requires_tunnel": bool(
                profile.matlab_license_cloud_requires_tunnel
            ),
            "vendor_port_configured": (
                profile.matlab_license_vendor_port is not None
            ),
        },
    }


def registered_resources(
    profiles: dict | None = None,
) -> list[dict]:
    """
    One entry per distinct compute profile; alias keys that resolve to the
    same profile (``pace`` / ``phoenix`` / ``pace-phoenix``) are grouped.
    """

    if profiles is None:
        from cryostack_src.resources.profiles import COMPUTE_PROFILES

        profiles = COMPUTE_PROFILES

    grouped: dict[int, tuple[object, list[str]]] = {}

    for key, profile in profiles.items():
        entry = grouped.setdefault(
            id(profile),
            (profile, []),
        )
        entry[1].append(key)

    return [
        _resource_view(profile, aliases)
        for profile, aliases in grouped.values()
    ]


# ============================================================
# Execution records
# ============================================================

_CLOUD_BACKENDS = frozenset({
    "aws", "aws_batch", "aws-batch", "batch", "cloud", "fargate", "ec2",
})

_LOCAL_BACKENDS = frozenset({
    "local",
})

_FAILED = "failed"

_ACTIVE = frozenset({
    "queued", "preparing", "running",
})

#: requested-resource fields that may be shown, per configuration section
_SLURM_FIELDS = (
    "nodes", "tasks", "tasks_per_node", "partition", "time", "memory",
)

_CLOUD_FIELDS = (
    "region", "job_queue", "job_definition", "compute_mode",
    "aws_batch_compute", "vcpu", "memory_mib", "timeout_seconds",
)


def _json_object(
    raw,
) -> dict:

    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}

    return value if isinstance(value, dict) else {}


def execution_target(
    *,
    backend: str | None,
    configuration: dict,
    metadata: dict,
) -> str:
    """``"cloud"``, ``"local"`` or ``"hpc"`` for one experiment record."""

    mode = str(
        metadata.get("execution_mode")
        or configuration.get("execution_mode")
        or ""
    ).strip().lower()

    name = (backend or "").strip().lower()

    if mode == "cloud" or name in _CLOUD_BACKENDS:
        return "cloud"

    if mode == "local" or name in _LOCAL_BACKENDS:
        return "local"

    return "hpc"


def _requested_resources(
    configuration: dict,
    metadata: dict,
) -> dict:

    resources = {}

    slurm = configuration.get("slurm")

    if isinstance(slurm, dict):
        for field in _SLURM_FIELDS:
            value = slurm.get(field)
            if value not in (None, ""):
                resources[field] = redact_text(value, limit=60)

    for section in (
        configuration.get("cloud"),
        metadata.get("cloud"),
    ):
        if isinstance(section, dict):
            for field in _CLOUD_FIELDS:
                value = section.get(field)
                if value not in (None, "") and field not in resources:
                    resources[field] = redact_text(value, limit=80)

    return resources


#: an active record with no update for this long shows "status unknown"
STALE_AFTER_SECONDS = 24 * 3600

#: a running record past its requested wall time by this much is unknown too
WALLTIME_GRACE_SECONDS = 3600


def slurm_time_seconds(
    value,
) -> int | None:
    """Slurm ``--time`` (``MM``, ``MM:SS``, ``HH:MM:SS``, ``D-HH``,
    ``D-HH:MM``, ``D-HH:MM:SS``) in seconds; ``None`` when unparseable."""

    text = str(value or "").strip()

    match = re.fullmatch(
        r"(?:(\d+)-)?(\d+)(?::(\d+))?(?::(\d+))?",
        text,
    )

    if not match:
        return None

    days, first, second, third = match.groups()

    if days is not None:
        hours, minutes, seconds = first, second or 0, third or 0
    elif third is not None:
        hours, minutes, seconds = first, second, third
    elif second is not None:
        hours, minutes, seconds = 0, first, second
    else:
        hours, minutes, seconds = 0, first, 0

    total = (
        int(days or 0) * 86400
        + int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
    )

    return total or None


def status_unknown_since(
    row: dict,
    configuration: dict,
    *,
    now: float,
    stale_after: float = STALE_AFTER_SECONDS,
) -> float | None:
    """
    When an active (queued/preparing/running) record has stopped hearing
    from its run, the time of its last update; otherwise ``None``.

    A record is never marked failed for this -- only the application that
    owns the run's SSH/Connector session or AWS role can learn its real
    state. Stale means: no update for ``stale_after`` seconds, or running
    longer than its requested Slurm wall time plus a grace period.
    """

    status = (row.get("status") or "").strip().lower()

    if status not in _ACTIVE:
        return None

    last = row.get("updated_at") or row.get("created_at")

    if not last:
        return None

    if now - last > stale_after:
        return last

    slurm = configuration.get("slurm")

    walltime = (
        slurm_time_seconds(slurm.get("time"))
        if isinstance(slurm, dict)
        else None
    )

    started = row.get("started_at")

    if (
        status == "running"
        and walltime
        and started
        and now - started > walltime + WALLTIME_GRACE_SECONDS
    ):
        return last

    return None


def _failure_view(
    metadata: dict,
) -> dict | None:

    from icesee_jupyter_book.core.experiment_status import sanitize_failure

    failure = sanitize_failure(metadata.get("failure"))

    if failure is None:
        return None

    view = dict(failure)

    if "reason" in view:
        view["reason"] = redact_text(view["reason"], limit=300)

    if "log_tail" in view:
        view["log_tail"] = [
            redact_text(line, limit=200)
            for line in view["log_tail"]
        ]

    return view


def _overview_view(
    configuration: dict,
    metadata: dict,
) -> dict:

    from icesee_jupyter_book.core.experiment_status import experiment_overview

    overview = experiment_overview(configuration, metadata)

    return {
        key: (
            redact_text(value, limit=80)
            if isinstance(value, str)
            else value
        )
        for key, value in overview.items()
    }


def _runtime_seconds(
    row: dict,
    now: float,
) -> int | None:

    start = row.get("started_at") or row.get("created_at")

    if not start:
        return None

    end = row.get("finished_at")

    if end is None:
        if row.get("status") not in _ACTIVE:
            return None
        end = now

    return max(0, int(end - start))


def _execution_view(
    row: dict,
    *,
    now: float,
    last_failure: str | None,
    stale_after: float = STALE_AFTER_SECONDS,
) -> dict:

    from icesee_jupyter_book.core.experiment_status import failure_message

    configuration = _json_object(
        row.get("configuration_snapshot_json")
    )

    metadata = _json_object(
        row.get("metadata_json")
    )

    failure = _failure_view(metadata)

    error = row.get("error_message") or failure_message(failure) or (
        last_failure
        if row.get("status") == _FAILED
        else None
    )

    overview = _overview_view(configuration, metadata)

    return {
        "id": row["id"],
        "application": row.get("application") or "",
        "name": redact_text(row.get("name"), limit=120),
        "backend": row.get("backend") or "",
        "target": execution_target(
            backend=row.get("backend"),
            configuration=configuration,
            metadata=metadata,
        ),
        "status": (row.get("status") or "").strip().lower(),
        "job_id": redact_text(row.get("job_id"), limit=64),
        "cluster": redact_text(row.get("cluster"), limit=80),
        "user_id": row.get("user_id"),
        "user_name": row.get("user_name") or "",
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "updated_at": row.get("updated_at"),
        "runtime_seconds": _runtime_seconds(row, now),
        "exit_code": row.get("exit_code"),
        "error": redact_text(error, limit=500),
        "failure": failure,
        "resources": _requested_resources(configuration, metadata),
        "overview": overview,
        "status_unknown_since": status_unknown_since(
            row,
            configuration,
            now=now,
            stale_after=stale_after,
        ),
    }


def _summarise(
    executions: list[dict],
) -> dict:

    statuses = Counter(
        item["status"] for item in executions
    )

    clusters = Counter(
        item["cluster"] or "—" for item in executions
    )

    finished = [
        item for item in executions
        if item["status"] in {"completed", _FAILED, "cancelled"}
    ]

    failed = statuses.get(_FAILED, 0)

    return {
        "total": len(executions),
        "active": sum(statuses.get(s, 0) for s in _ACTIVE),
        "status_unknown": sum(
            1 for item in executions
            if item.get("status_unknown_since")
        ),
        "completed": statuses.get("completed", 0),
        "failed": failed,
        "cancelled": statuses.get("cancelled", 0),
        "failure_rate": (
            round(failed / len(finished), 3)
            if finished
            else None
        ),
        "by_status": dict(sorted(statuses.items())),
        "by_cluster": dict(clusters.most_common()),
    }


# ============================================================
# Logs
# ============================================================

#: compute-relevant log lines (case-insensitive substrings)
LOG_TOPICS: dict[str, tuple[str, ...]] = {
    "hpc": (
        "remote", "slurm", "sbatch", "squeue", "sacct", "scancel",
        "connector", "ssh", "spack", "hpc", "pace", "apptainer",
    ),
    "cloud": (
        "cloud", "aws", "batch", "fargate", "ec2", "s3", "ecr",
        "cloudformation", "assumerole", "license",
    ),
}

_LOG_ERROR_WORDS = (
    "error", "traceback", "exception", "failed", "fatal", "critical",
)

_LOG_LABELS = {
    "gui": "Gateway and Voilà services",
    "connector": "Connector relay",
}

MAX_LOG_LINES = 200
DEFAULT_LOG_LINES = 80
_LOG_TAIL_BYTES = 512 * 1024
_LOG_LINE_LIMIT = 400


def registry_log_sources(
    *,
    registry_path: Path = REGISTRY_PATH,
    root: Path = REPOSITORY_ROOT,
) -> dict[str, dict]:
    """
    The runtime logs the deployment registry declares
    (``platform.runtime.<name>.log``), resolved under ``root``. Entries
    that are absolute or escape ``root`` are ignored.
    """

    try:
        import yaml

        registry = yaml.safe_load(
            registry_path.read_text(encoding="utf-8")
        ) or {}
    except Exception:
        return {}

    runtime = (
        (registry.get("platform") or {}).get("runtime") or {}
    )

    sources = {}

    for key, spec in runtime.items():

        if not isinstance(spec, dict):
            continue

        relative = str(spec.get("log") or "").strip()

        if not relative or Path(relative).is_absolute():
            continue

        path = (root / relative).resolve()

        if not path.is_relative_to(root.resolve()):
            continue

        sources[str(key)] = {
            "label": _LOG_LABELS.get(str(key), str(key)),
            "path": path,
        }

    return sources


def _tail(
    path: Path,
    max_bytes: int,
) -> tuple[list[str], bool]:

    with path.open("rb") as handle:

        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max_bytes)
        handle.seek(start)
        data = handle.read()

    lines = data.decode(
        "utf-8",
        errors="replace",
    ).splitlines()

    if start > 0 and lines:
        # the first line is probably cut in half
        lines = lines[1:]

    return lines, start > 0


# ============================================================
# Relay probe
# ============================================================

_RELAY_PROBE_SESSION = "control-center-probe"


def probe_relay(
    base_url: str,
    *,
    timeout: float = 4.0,
) -> dict:
    """
    One request to the relay's existing public, unauthenticated status
    endpoint for a session id that never exists. A JSON answer means the
    relay is up; no credential is sent and nothing is created.
    """

    url = (
        base_url.rstrip("/")
        + "/connector/status/"
        + _RELAY_PROBE_SESSION
    )

    started = time.monotonic()

    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read(4096) or b"{}")
            status = response.status

    except urllib.error.HTTPError as error:
        return {
            "status": "failed",
            "detail": f"Relay answered HTTP {error.code}.",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    except Exception as error:
        return {
            "status": "failed",
            "detail": f"Relay unreachable ({type(error).__name__}).",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    healthy = status == 200 and isinstance(body, dict) and "state" in body

    return {
        "status": "healthy" if healthy else "failed",
        "detail": (
            "Relay status endpoint responding."
            if healthy
            else f"Unexpected relay response (HTTP {status})."
        ),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }


def _default_relay_url() -> str:

    try:
        from icesee_jupyter_book.core.connector_relay_client import RELAY_URL
    except Exception:
        return ""

    return RELAY_URL


# ============================================================
# Service
# ============================================================

class ComputeService:

    def __init__(
        self,
        storage: ControlStorage,
        *,
        access=None,
        profiles: dict | None = None,
        environ: dict | None = None,
        log_sources: dict[str, dict] | None = None,
        relay_url: str | None = None,
        relay_probe: Callable[[str], dict] | None = None,
        clock: Callable[[], float] = time.time,
        stale_after: float = STALE_AFTER_SECONDS,
    ) -> None:

        self.storage = storage
        self.stale_after = stale_after
        self._access = access
        self._profiles = profiles
        self._environ = os.environ if environ is None else environ
        self._log_sources = (
            registry_log_sources()
            if log_sources is None
            else log_sources
        )
        self._relay_url = (
            _default_relay_url()
            if relay_url is None
            else relay_url
        )
        self._relay_probe = relay_probe or probe_relay
        self._clock = clock
        self._last_relay_check: dict | None = None

    # --------------------------------------------------------
    # Roles
    # --------------------------------------------------------

    def can_operate(
        self,
        *,
        user_id: str,
    ) -> bool:

        if self._access is not None:
            return bool(
                self._access.can_operate_compute(
                    user_id=user_id,
                )
            )

        with self.storage._connect() as connection:
            rows = connection.execute(
                "SELECT role FROM user_roles WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        roles = {
            str(row["role"]).strip().lower()
            for row in rows
        }

        return bool(roles & OPERATOR_ROLES)

    # --------------------------------------------------------
    # Execution records
    # --------------------------------------------------------

    def _execution_rows(
        self,
        *,
        limit: int,
    ) -> tuple[list[dict], dict[str, str]]:

        with self.storage._connect() as connection:

            rows = connection.execute(
                """
                SELECT
                    e.id,
                    e.application,
                    e.name,
                    e.backend,
                    e.status,
                    e.job_id,
                    e.cluster,
                    e.exit_code,
                    e.error_message,
                    e.configuration_snapshot_json,
                    e.metadata_json,
                    e.created_at,
                    e.started_at,
                    e.finished_at,
                    e.updated_at,

                    u.id AS user_id,
                    u.display_name AS user_name

                FROM experiments e

                JOIN users u
                    ON u.id = e.user_id

                ORDER BY e.created_at DESC

                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

            failures = connection.execute(
                """
                SELECT experiment_id, message

                FROM experiment_events

                WHERE event_type = 'failed'

                ORDER BY created_at ASC
                """
            ).fetchall()

        last_failure = {
            row["experiment_id"]: row["message"]
            for row in failures
            if row["message"]
        }

        return [dict(row) for row in rows], last_failure

    def executions(
        self,
        *,
        target: str,
        limit: int = 200,
    ) -> dict:

        rows, last_failure = self._execution_rows(
            limit=limit,
        )

        now = self._clock()

        items = [
            _execution_view(
                row,
                now=now,
                last_failure=last_failure.get(row["id"]),
                stale_after=self.stale_after,
            )
            for row in rows
        ]

        items = [
            item for item in items
            if target == "all" or item["target"] == target
        ]

        return {
            "summary": _summarise(items),
            "active": [
                item for item in items
                if item["status"] in _ACTIVE
            ][:25],
            "failures": [
                item for item in items
                if item["status"] == _FAILED
            ][:25],
            "recent": items[:50],
        }

    # --------------------------------------------------------
    # HPC
    # --------------------------------------------------------

    def hpc_overview(
        self,
    ) -> dict:

        resources = registered_resources(self._profiles)

        return {
            "resources": resources,
            "scheduler_checks": [
                {
                    "resource": resource["name"],
                    "status": "requires_session",
                    "detail": (
                        "Scheduler state is only read through a "
                        "researcher's own SSH identity or Connector "
                        "session. The Control Center never borrows one; "
                        "connect from CryoLauncher or ICESEE to check "
                        "this resource."
                    ),
                }
                for resource in resources
            ],
            "relay": self.relay_status(),
            "executions": self.executions(target="hpc"),
            "ownership": {
                "installation": [
                    "Login host, SSH port, VPN/MFA requirements",
                    "Access and authentication mechanisms",
                    "Scheduler defaults (partition, wall time)",
                    "Allocation requirement",
                    "MATLAB license mechanism",
                ],
                "per_user": [
                    "HPC username and SSH keys",
                    "Remote working directory",
                    "Slurm allocation / account",
                    "Connector pairing and sessions",
                ],
            },
        }

    def relay_status(
        self,
    ) -> dict:

        return {
            "configured": bool(self._relay_url),
            "endpoint": _host_of(self._relay_url),
            "last_check": self._last_relay_check,
        }

    def run_relay_check(
        self,
        *,
        actor_user_id: str,
    ) -> dict:
        """
        Probe the Connector relay through its existing public status
        endpoint and audit who asked. Operators only.
        """

        if not self.can_operate(user_id=actor_user_id):
            raise PermissionError(
                "Live compute checks require a maintainer, "
                "admin or owner role."
            )

        if not self._relay_url:
            result = {
                "status": "disabled",
                "detail": "No Connector relay URL is configured.",
                "latency_ms": None,
            }
        else:
            raw = self._relay_probe(self._relay_url) or {}
            result = {
                "status": (
                    raw.get("status")
                    if raw.get("status") in {"healthy", "failed"}
                    else "failed"
                ),
                "detail": redact_text(raw.get("detail"), limit=200),
                "latency_ms": raw.get("latency_ms"),
            }

        result["checked_at"] = self._clock()

        self._last_relay_check = result

        self._audit(
            actor_user_id=actor_user_id,
            action="compute_relay_checked",
            metadata={"status": result["status"]},
        )

        return result

    def _audit(
        self,
        *,
        actor_user_id: str,
        action: str,
        metadata: dict,
    ) -> None:

        import secrets

        with self.storage._connect() as connection:
            connection.execute(
                """
                INSERT INTO control_audit_log (
                    id,
                    actor_user_id,
                    target_user_id,
                    action,
                    metadata_json,
                    created_at
                )
                VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (
                    secrets.token_hex(16),
                    actor_user_id,
                    action,
                    json.dumps(metadata, sort_keys=True),
                    self._clock(),
                ),
            )

    # --------------------------------------------------------
    # Cloud
    # --------------------------------------------------------

    def cloud_platform(
        self,
    ) -> dict:

        from cryostack_src.cloud.config import (
            DEFAULT_CLOUD_REGION,
            SUPPORTED_CLOUD_PROVIDERS,
        )
        from cryostack_src.cloud.connect.defaults import RUNS_BUCKET_PREFIX
        from cryostack_src.cloud.connect.onboarding import TEMPLATE_URL_ENV
        from cryostack_src.cloud.connect.principal import (
            PRINCIPAL_ENV,
            is_valid_principal_arn,
        )
        from cryostack_src.cloud.drivers.aws import batch_config as batch
        from cryostack_src.cloud.runtime import SUPPORTED_CLOUD_MODELS

        environ = self._environ

        principal = (environ.get(PRINCIPAL_ENV) or "").strip()
        template_url = (environ.get(TEMPLATE_URL_ENV) or "").strip()
        server_region = (
            environ.get("AWS_REGION")
            or environ.get("AWS_DEFAULT_REGION")
            or ""
        ).strip()

        fargate = batch.DEFAULT_ISSM_JOB_CONFIG

        try:
            batch.validate_fargate_job_config(fargate)
            fargate_valid = True
        except ValueError:
            fargate_valid = False

        ec2 = batch.EC2ComputeConfig()

        models = []

        for model in SUPPORTED_CLOUD_MODELS:
            models.append({
                "model": model,
                "job_definition": batch.job_definition_name(model),
                "job_definition_ec2": batch.job_definition_name(
                    model,
                    batch.COMPUTE_MODE_EC2,
                ),
                "ecr_repository": batch.ECR_REPOSITORY_NAMES.get(
                    model,
                    f"cryostack-{model}",
                ),
                "log_group": batch.log_group_name(model),
            })

        return {
            "providers": list(SUPPORTED_CLOUD_PROVIDERS),
            "default_region": DEFAULT_CLOUD_REGION,
            "server_region": server_region,
            "principal": _principal_view(
                principal,
                valid=is_valid_principal_arn(principal),
                variable=PRINCIPAL_ENV,
            ),
            "template_url": {
                "variable": TEMPLATE_URL_ENV,
                "configured": bool(template_url),
                "host": _host_of(template_url),
            },
            "execution_role_template": execution_role_template_summary(),
            "models": models,
            "compute_modes": [
                {
                    "mode": batch.COMPUTE_MODE_FARGATE,
                    "default": True,
                    "compute_environment": batch.compute_environment_name(
                        batch.COMPUTE_MODE_FARGATE
                    ),
                    "job_queue": batch.job_queue_name(
                        batch.COMPUTE_MODE_FARGATE
                    ),
                },
                {
                    "mode": batch.COMPUTE_MODE_EC2,
                    "default": False,
                    "compute_environment": batch.compute_environment_name(
                        batch.COMPUTE_MODE_EC2
                    ),
                    "job_queue": batch.job_queue_name(
                        batch.COMPUTE_MODE_EC2
                    ),
                    "spot_job_queue": batch.job_queue_name(
                        batch.COMPUTE_MODE_EC2,
                        batch.EC2_CAPACITY_SPOT,
                    ),
                    "capacities": list(batch.SUPPORTED_EC2_CAPACITIES),
                    "accelerators": list(batch.SUPPORTED_EC2_ACCELERATORS),
                    "topologies": list(batch.SUPPORTED_EC2_TOPOLOGIES),
                    "instance_types": list(ec2.instance_types),
                    "allocation_strategy": ec2.allocation_strategy,
                },
            ],
            "fargate_default": {
                "vcpu": fargate.vcpu,
                "memory_mib": int(fargate.memory_mib),
                "ephemeral_gib": int(fargate.ephemeral_gib),
                "timeout_seconds": int(fargate.timeout_seconds),
                "attempts": int(fargate.attempts),
                "platform_version": fargate.platform_version,
                "cpu_architecture": fargate.cpu_architecture,
                "valid": fargate_valid,
            },
            "guardrails": {
                "max_vcpus": batch.DEFAULT_MAX_VCPUS,
                "log_retention_days": batch.LOG_RETENTION_DAYS,
                "log_group_prefix": batch.LOG_GROUP_PREFIX,
                "runs_bucket_pattern": f"{RUNS_BUCKET_PREFIX}-<account-id>",
            },
            "matlab_license": [
                {
                    "resource": resource["name"],
                    "configured": resource["matlab_license"]["configured"],
                    "cloud_requires_tunnel":
                        resource["matlab_license"]["cloud_requires_tunnel"],
                }
                for resource in registered_resources(self._profiles)
            ],
        }

    def cloud_overview(
        self,
    ) -> dict:

        return {
            "platform": self.cloud_platform(),
            "researcher_accounts": {
                "listed": False,
                "detail": (
                    "Researchers connect their own AWS accounts. Each "
                    "connection record (account, role, ExternalId, MATLAB "
                    "license secret) lives in that researcher's workspace "
                    "and is only read by their own sessions, so it is not "
                    "listed here."
                ),
            },
            "configuration_changes": {
                "supported": False,
                "detail": (
                    "Cloud execution settings are deterministic code "
                    "defaults (cryostack_src/cloud) and deployment "
                    "environment variables. There is no stored, editable "
                    "cloud configuration, so the Control Center shows "
                    "them read-only."
                ),
            },
            "executions": self.executions(target="cloud"),
        }

    # --------------------------------------------------------
    # Logs
    # --------------------------------------------------------

    def log_sources(
        self,
    ) -> list[dict]:

        return [
            {
                "key": key,
                "label": spec["label"],
                "available": Path(spec["path"]).is_file(),
            }
            for key, spec in self._log_sources.items()
        ]

    def log_excerpt(
        self,
        *,
        source: str,
        topic: str = "all",
        level: str = "all",
        lines: int = DEFAULT_LOG_LINES,
    ) -> dict:
        """
        The newest ``lines`` lines of one allowlisted log, optionally
        filtered to a compute topic and/or error lines, each redacted and
        length-bounded.
        """

        spec = self._log_sources.get(source)

        if spec is None:
            raise KeyError(source)

        if topic not in {"all", *LOG_TOPICS}:
            raise ValueError("Unknown log topic.")

        if level not in {"all", "errors"}:
            raise ValueError("Unknown log level.")

        count = max(1, min(int(lines), MAX_LOG_LINES))

        path = Path(spec["path"])

        result = {
            "source": source,
            "label": spec["label"],
            "topic": topic,
            "level": level,
            "available": path.is_file(),
            "lines": [],
            "truncated": False,
        }

        if not result["available"]:
            return result

        try:
            raw, truncated = _tail(path, _LOG_TAIL_BYTES)
        except OSError:
            result["available"] = False
            return result

        words = LOG_TOPICS.get(topic, ())

        selected = []

        for line in raw:

            low = line.lower()

            if words and not any(word in low for word in words):
                continue

            if level == "errors" and not any(
                word in low for word in _LOG_ERROR_WORDS
            ):
                continue

            selected.append(line)

        result["truncated"] = truncated or len(selected) > count
        result["lines"] = [
            redact_text(line, limit=_LOG_LINE_LIMIT)
            for line in selected[-count:]
        ]

        return result


def _host_of(
    url: str,
) -> str:

    from urllib.parse import urlsplit

    try:
        return urlsplit(url or "").hostname or ""
    except ValueError:
        return ""


def _principal_view(
    arn: str,
    *,
    valid: bool,
    variable: str,
) -> dict:
    """
    The CryoStack principal ARN appears in every Quick Create template the
    deployment hands out, so it is not secret; the account id is still
    masked to its last four digits.
    """

    view = {
        "variable": variable,
        "configured": bool(arn),
        "valid": bool(valid),
        "display": "",
    }

    if arn and valid:
        view["display"] = redact_text(arn, limit=200)

    return view


def execution_role_template_summary(
    path: Path | None = None,
) -> dict:
    """
    What the checked-in CloudFormation execution role grants (statement
    ids and actions), and whether it still matches the code that renders
    it.
    """

    path = path or (
        REPOSITORY_ROOT
        / "deployment"
        / "cloudformation"
        / "cryostack-execution-role.json"
    )

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False}

    statements = []

    role = (
        (document.get("Resources") or {})
        .get("CryoStackExecutionRole", {})
        .get("Properties", {})
    )

    for policy in role.get("Policies") or []:
        for statement in (policy.get("PolicyDocument") or {}).get("Statement", []):
            actions = statement.get("Action") or []
            if isinstance(actions, str):
                actions = [actions]
            statements.append({
                "sid": statement.get("Sid") or "",
                "effect": statement.get("Effect") or "",
                "actions": sorted(actions),
            })

    try:
        from cryostack_src.cloud.connect.cloudformation import render_template

        in_sync = json.loads(render_template()) == document
    except Exception:
        in_sync = None

    return {
        "available": True,
        "file": "deployment/cloudformation/cryostack-execution-role.json",
        "parameters": sorted((document.get("Parameters") or {}).keys()),
        "max_session_seconds": role.get("MaxSessionDuration"),
        "statements": statements,
        "action_count": sum(len(s["actions"]) for s in statements),
        "in_sync_with_code": in_sync,
    }
