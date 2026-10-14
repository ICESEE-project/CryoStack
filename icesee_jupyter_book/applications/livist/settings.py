"""Server-side LIVIST settings, all from the environment.

Operators set these; nothing here is editable from the browser:

``CRYOSTACK_LIVIST_ENV``
    the isolated environment built by ``environment/build_env.sh``
    (default ``~/.cryostack-envs/livist``)
``CRYOSTACK_LIVIST_SOURCE``
    the LIVIST checkout (default: the ``external/living-ice-sheet-temperature``
    submodule); only read
``CRYOSTACK_LIVIST_DATABASE``
    job / source / publication-request database (default ``var/livist.db``)
``CRYOSTACK_LIVIST_INPUT_ROOTS``
    ``os.pathsep``-separated directories holding approved local attenuation
    files; maintainers can only pick files inside them
``CRYOSTACK_LIVIST_JOB_TIMEOUT_S``  (default 21600)
``CRYOSTACK_LIVIST_MAX_ACTIVE``     concurrent jobs on this host (default 2)
``CRYOSTACK_LIVIST_JOB_RESERVE_MB``
    free disk space a job needs on the workspace file system before it starts
    (default 2048); a running job is stopped when free space falls below half
    of it, so a generation cannot fill the disk the gateway shares
``CRYOSTACK_LIVIST_PUBLICATION_TARGET``
    the S3 location ``scripts/upload`` writes to
``CRYOSTACK_LIVIST_PUBLICATION_HTTP``
    its public HTTPS mirror, used read-only to detect overwrites
``CRYOSTACK_LIVIST_PUBLICATION_ENABLED``
    ``1`` allows an approved publication request to really upload; off by
    default, so approval only records a dry-run plan
``CRYOSTACK_LIVIST_PUBLICATION_PROFILE``
    optional AWS profile *name* for uploads; credentials themselves come from
    the server's AWS credential chain and are never stored or shown
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_SOURCE = REPO_ROOT / "external" / "living-ice-sheet-temperature"
DEFAULT_DATABASE = REPO_ROOT / "var" / "livist.db"
DEFAULT_ENV = Path.home() / ".cryostack-envs" / "livist"

UPSTREAM_REPOSITORY = "https://github.com/ICESEE-project/living-ice-sheet-temperature"
DEFAULT_PUBLICATION_TARGET = (
    "s3://us-west-2.opendata.source.coop/englacial/ice-sheet-temperature/temperature"
)
DEFAULT_PUBLICATION_HTTP = "https://data.source.coop/englacial/ice-sheet-temperature/temperature"
DEFAULT_TIMEOUT_S = 6 * 3600
DEFAULT_MAX_ACTIVE = 2
DEFAULT_JOB_RESERVE_MB = 2048


def _path(name: str, default: Path) -> Path:
    value = (os.environ.get(name) or "").strip()
    return Path(value).expanduser() if value else default


def _int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int((os.environ.get(name) or "").strip() or default)
    except ValueError:
        return default
    return max(low, min(high, value))


def env_dir() -> Path:
    return _path("CRYOSTACK_LIVIST_ENV", DEFAULT_ENV)


def source_dir() -> Path:
    return _path("CRYOSTACK_LIVIST_SOURCE", DEFAULT_SOURCE)


def database_path() -> Path:
    return _path("CRYOSTACK_LIVIST_DATABASE", DEFAULT_DATABASE)


def input_roots() -> list[Path]:
    raw = os.environ.get("CRYOSTACK_LIVIST_INPUT_ROOTS", "")
    return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]


def job_timeout_s() -> int:
    return _int("CRYOSTACK_LIVIST_JOB_TIMEOUT_S", DEFAULT_TIMEOUT_S, 60, 7 * 24 * 3600)


def max_active_jobs() -> int:
    return _int("CRYOSTACK_LIVIST_MAX_ACTIVE", DEFAULT_MAX_ACTIVE, 1, 16)


def job_reserve_bytes() -> int:
    return _int("CRYOSTACK_LIVIST_JOB_RESERVE_MB", DEFAULT_JOB_RESERVE_MB, 0, 1 << 20) << 20


def publication_target() -> str:
    value = (os.environ.get("CRYOSTACK_LIVIST_PUBLICATION_TARGET") or "").strip()
    return (value or DEFAULT_PUBLICATION_TARGET).rstrip("/")


def publication_http() -> str:
    value = (os.environ.get("CRYOSTACK_LIVIST_PUBLICATION_HTTP") or "").strip()
    return (value or DEFAULT_PUBLICATION_HTTP).rstrip("/")


def publication_enabled() -> bool:
    value = (os.environ.get("CRYOSTACK_LIVIST_PUBLICATION_ENABLED") or "").strip().lower()
    return value in ("1", "true", "yes", "on")


def publication_profile() -> str | None:
    value = (os.environ.get("CRYOSTACK_LIVIST_PUBLICATION_PROFILE") or "").strip()
    return value or None
