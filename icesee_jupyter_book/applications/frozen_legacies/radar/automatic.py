"""Automatic picking jobs on radar assets: LYRA, with URSA as the rollback.

The picker is chosen by ``CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER``:
``lyra`` (default) or ``ursa`` (temporary rollback). A job records the picker
it ran with, so earlier URSA results stay readable after the switch.

LYRA -- Layered-echo Yield from Radiometric Archives
(``Pickers/Automatic_picker/LYRA``) -- runs unmodified in a subprocess
(``pickers/lyra_runner.py``), phase by phase exactly as its guide describes:
frame detection and CBD recognition (phase 1), then, only when the user has
uploaded LYRA's own calibration guidance (``lyra-guidance``, the picks file of
LYRA's desktop picker), per-frame calibration (phase 3) and echo extraction
(phase 4). LYRA's phase 3 refuses to run without a human reference-line pick;
CryoStack never supplies one in its place. LYRA needs the TIFF under its
canonical reel name (``<reel>_<start>_<end>-reel_begin_end.tiff``): taken from
the file name, or from a LYRA rename log (``*_rename_log*.txt``) whose entry
for the same segment agrees with the asset's flight -- otherwise LYRA is not
offered for that asset. LYRA's results carry no positions (its navigation
alignment needs reference files that are not part of LYRA's handoff).

URSA -- the automatic A-scope processor in the FrozenLegacies tools
(``external/FrozenLegacies/Frozen Legacy Tools/Unsupervised Retrieval of
Signal for A-scopes (U.R.S.A.)``) -- runs unmodified in a subprocess
(``pickers/ursa_runner.py``). A job belongs to one asset of one user and is
recorded in ``radar/<asset_id>/automatic.json``.

Lifecycle: ``queued`` -> ``running`` -> ``completed`` | ``failed`` |
``cancelled``. A job left ``queued``/``running`` by a previous server
process is reported as ``interrupted``.

Availability is checked, not assumed: URSA's source tree must be present,
the URSA Python must import its dependencies (OpenCV and scikit-image in
particular), and the runner's health check (``ursa_runner.py --check``) must
import URSA itself in the environment jobs run with. When it cannot, the job
API reports ``available: false`` with the reason, and no results are
produced.

Operational availability says nothing about the science: neither LYRA's nor
URSA's results have been validated against reference picks, so every automatic
result is labelled ``scientifically unvalidated`` (``SCIENTIFIC_STATUS``) and
only ASTRA manual results can be submitted for review and publication.

URSA also writes its own diagnostic images (a picks plot per frame and the
reference-line QA images in ``ref_line_qa/``). They are kept as
``ursa-diagnostic`` products -- regular PNG files copied into the asset's
``outputs/``, bounded in number and size, each with its frame and SHA-256 --
so a scientist can inspect what URSA did on each frame. They are labelled
``URSA diagnostic (unvalidated)`` and are never results. Each completed job
records its provenance (URSA commit when the source is a git checkout, a
digest of URSA's source and configuration, the parameters used, input and
output hashes) in ``automatic.json``.

Configuration (environment):

* ``CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER`` -- ``lyra`` (default) | ``ursa``
* ``CRYOSTACK_FROZEN_LEGACIES_LYRA_ROOT``   -- LYRA directory (holds ``codes/``)
* ``CRYOSTACK_FROZEN_LEGACIES_LYRA_PYTHON`` -- Python with LYRA's dependencies
  (default: the server's Python)
* ``CRYOSTACK_FROZEN_LEGACIES_LYRA_RENAME_LOGS`` -- extra directory of LYRA
  rename logs (``<LYRA root>/rename_logs`` is always read)
* ``CRYOSTACK_FROZEN_LEGACIES_LYRA_TIMEOUT`` -- seconds per job (default 3600)
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT``   -- URSA source directory
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON`` -- Python with URSA's dependencies
  (default: the server's Python)
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT`` -- seconds per job (default 3600)
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY`` -- concurrent automatic jobs, LYRA and URSA
  together (default 1; a LYRA phase-1 run on a ~117 MB strip peaks near 2.6 GB)
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from ..workspace import ASSET_AUTOMATIC, FrozenLegaciesWorkspace
from . import manual, products


JOB_SCHEMA = "cryostack.frozen_legacies.automatic_job"
JOB_VERSION = 1
ACTIVE = ("queued", "running")
FINAL = ("completed", "failed", "cancelled", "interrupted")

ROOT_ENV = "CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT"
PYTHON_ENV = "CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON"
TIMEOUT_ENV = "CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT"
CONCURRENCY_ENV = "CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY"

_REPO = Path(__file__).resolve().parents[4]
DEFAULT_URSA_ROOT = (
    _REPO / "external" / "FrozenLegacies" / "Frozen Legacy Tools"
    / "Unsupervised Retrieval of Signal for A-scopes (U.R.S.A.)"
)
RUNNER = Path(__file__).resolve().parent.parent / "pickers" / "ursa_runner.py"

PICKER_ENV = "CRYOSTACK_FROZEN_LEGACIES_AUTOMATIC_PICKER"
PICKERS = ("lyra", "ursa")
DEFAULT_PICKER = "lyra"
LABELS = {"lyra": "LYRA", "ursa": "URSA"}
WORKFLOWS = {"lyra": "lyra-automatic", "ursa": "ursa-automatic"}
LYRA_ROOT_ENV = "CRYOSTACK_FROZEN_LEGACIES_LYRA_ROOT"
LYRA_PYTHON_ENV = "CRYOSTACK_FROZEN_LEGACIES_LYRA_PYTHON"
LYRA_RENAME_LOGS_ENV = "CRYOSTACK_FROZEN_LEGACIES_LYRA_RENAME_LOGS"
LYRA_TIMEOUT_ENV = "CRYOSTACK_FROZEN_LEGACIES_LYRA_TIMEOUT"
DEFAULT_LYRA_ROOT = (Path(__file__).resolve().parent.parent / "Pickers" / "Automatic_picker"
                     / "LYRA")
LYRA_RUNNER = Path(__file__).resolve().parent.parent / "pickers" / "lyra_runner.py"
WORK_DIRNAME = ".automatic-work"
LOG_TAIL_LINES = 40
MAX_PROGRESS_BYTES = 16 * 1024
MIN_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 24 * 60 * 60.0
MAX_CONCURRENT_JOBS = 4
_LOG = logging.getLogger(__name__)


class AutomaticJobBusy(RuntimeError):
    """Another gateway worker owns this asset's automatic job."""


def _bounded_float_env(name: str, default: float, low: float, high: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    if not (low <= value <= high):
        _LOG.warning("Ignoring out-of-range %s=%r; using %s.", name, raw, default)
        return default
    return value


def _bounded_int_env(name: str, default: int, low: int, high: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    if not low <= value <= high:
        _LOG.warning("Ignoring out-of-range %s=%r; using %s.", name, raw, default)
        return default
    return value

#: URSA's CBD parser (``AScope._extract_cbd_sequence_from_filename``)
URSA_CBD_PATTERN = re.compile(r"C(\d+)_C(\d+)")

URSA_DEPENDENCIES = ("cv2", "numpy", "scipy", "pandas", "matplotlib", "skimage")

#: URSA's own diagnostic images kept per job (``ursa-diagnostic`` products):
#: ``<stem>_frameNN_<what>.png`` in its output directory, its ``ref_line_qa/``
#: and (for plots it saves relative to its working directory) ``output/``
DIAGNOSTIC_DIRS = ("out", "out/ref_line_qa", "output", "output/ref_line_qa")
_DIAGNOSTIC_SUFFIX = re.compile(r"_frame(\d{1,3})_([A-Za-z0-9_]{1,40})\.png")
DIAGNOSTIC_LABELS = {
    "picked": "picks plot",
    "01_search_region": "reference line: search region",
    "02_blackhat": "reference line: black-hat filter",
    "03_threshold_raw": "reference line: threshold",
    "04_threshold_filtered": "reference line: filtered threshold",
    "05_projection": "reference line: projection",
    "grid_QA": "grid detection QA",
}
MAX_DIAGNOSTIC_FILES = 400
MAX_DIAGNOSTIC_FILE_BYTES = 16 * 1024 * 1024
MAX_DIAGNOSTIC_TOTAL_BYTES = 128 * 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: provenance keeps at most this much of URSA's configuration
MAX_CONFIG_BYTES = 256 * 1024

#: scientific status of every URSA result (API, UI, product provenance)
SCIENTIFIC_STATUS = "unvalidated"
SCIENTIFIC_NOTE = ("Automatic (URSA) results are scientifically unvalidated: they have not "
                   "been compared with reference picks and cannot be submitted for review "
                   "or publication.")
LYRA_SCIENTIFIC_NOTE = (
    "Automatic (LYRA) results are scientifically unvalidated: they have not been compared "
    "with independently verified observations and cannot be submitted for review or "
    "publication. LYRA's status labels (good, weak_bed, no_bed, no_surface) and its CBD "
    "sequence are LYRA's own heuristics, not validation.")


def configured_picker() -> str:
    """The picker new jobs use: ``lyra`` unless ``ursa`` is configured. An
    unrecognised setting is logged (once per value), never silently honoured."""
    value = (os.environ.get(PICKER_ENV) or "").strip().lower()
    if value in PICKERS:
        return value
    if value and value not in _reported_pickers:
        _reported_pickers.add(value)
        logging.getLogger(__name__).warning(
            "%s=%r is not one of %s; new automatic jobs use %s.",
            PICKER_ENV, value, "/".join(PICKERS), DEFAULT_PICKER)
    return DEFAULT_PICKER


_reported_pickers: set[str] = set()


def picker_identity(picker: str) -> dict:
    """Which picker, and which version of its code, a job runs with (recorded
    when the job is created, so failed and interrupted jobs carry it too)."""
    try:
        if picker == "lyra":
            identity = lyra_identity(lyra_root())
            return {"picker": "lyra", "source_sha256": identity["source_sha256"],
                    "source_files": identity["source_files"], "commit": None}
        identity = ursa_identity(ursa_root())
        return {"picker": "ursa", "source_sha256": identity["source_sha256"],
                "source_files": identity["source_files"], "commit": identity["commit"]}
    except OSError:
        return {"picker": picker, "source_sha256": None, "source_files": 0, "commit": None}


def scientific_note(picker: str | None = None) -> str:
    return SCIENTIFIC_NOTE if (picker or configured_picker()) == "ursa" else LYRA_SCIENTIFIC_NOTE


# ── availability ─────────────────────────────────────────────────────
def ursa_root() -> Path:
    configured = (os.environ.get(ROOT_ENV) or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_URSA_ROOT


def ursa_python() -> str:
    return (os.environ.get(PYTHON_ENV) or "").strip() or sys.executable


_availability_cache: dict = {}


def availability(*, refresh: bool = False, picker: str | None = None) -> dict:
    """Whether the configured picker can run here; the reason when it cannot."""
    if (picker or configured_picker()) == "lyra":
        return lyra_availability(refresh=refresh)
    return _ursa_availability(refresh=refresh)


def _ursa_availability(*, refresh: bool = False) -> dict:
    """Whether URSA can run here; the reason when it cannot (cached 5 min)."""
    root, python = ursa_root(), ursa_python()
    key = (str(root), python)
    cached = _availability_cache.get(key)
    if cached and not refresh and time.time() - cached[0] < 300:
        return cached[1]
    result = {"available": True, "picker": "URSA", "reason": None}
    missing = [n for n in ("ascope_processor.py", "main.py", "config/default_config.json")
               if not (root / n).is_file()]
    if missing:
        result = {"available": False, "picker": "URSA",
                  "reason": "The URSA automatic picker is not installed on this server."}
    else:
        probe = "import importlib, sys\n" + "".join(
            f"importlib.import_module({name!r})\n" for name in URSA_DEPENDENCIES)
        try:
            completed = subprocess.run([python, "-c", probe], capture_output=True,
                                       text=True, timeout=120)
            if completed.returncode != 0:
                lines = (completed.stderr or "").strip().splitlines()
                detail = lines[-1] if lines else "import failed"
                name = re.search(r"No module named '([^']+)'", detail)
                what = f"the Python package '{name.group(1)}'" if name else "a required package"
                result = {"available": False, "picker": "URSA",
                          "reason": f"URSA needs {what}, which is not installed in the "
                                    "automatic-picking environment on this server."}
        except (OSError, subprocess.TimeoutExpired):
            result = {"available": False, "picker": "URSA",
                      "reason": "The automatic-picking Python environment could not be started."}
        if result["available"]:
            result = _health_check(python, root)
    _availability_cache[key] = (time.time(), result)
    return result


def _health_check(python: str, root: Path) -> dict:
    """Run the runner's ``--check`` exactly as a job runs URSA."""
    unavailable = {"available": False, "picker": "URSA",
                   "reason": "URSA could not be imported in the automatic-picking environment "
                             "on this server."}
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="ursa-check-") as scratch:
            completed = subprocess.run(
                [python, str(RUNNER), "--check", "--ursa-root", str(root)],
                capture_output=True, text=True, timeout=180, env=ursa_environment(),
                cwd=scratch)
    except (OSError, subprocess.TimeoutExpired):
        return unavailable
    lines = (completed.stdout or "").strip().splitlines()
    try:
        report = json.loads(lines[-1]) if completed.returncode == 0 and lines else None
    except ValueError:
        report = None
    if not isinstance(report, dict) or report.get("ursa") != "importable":
        return unavailable
    packages = report.get("packages") if isinstance(report.get("packages"), dict) else {}
    return {"available": True, "picker": "URSA", "reason": None,
            "environment": {"python": str(report.get("python") or "")[:20],
                            "packages": {str(k)[:40]: (str(v)[:40] if v else None)
                                         for k, v in list(packages.items())[:20]}}}


#: variables passed through to the URSA subprocess; everything else in the
#: gateway's environment (sessions, OAuth and cloud credentials) is withheld
_PASSTHROUGH_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
                    "CONDA_PREFIX", "LD_LIBRARY_PATH", "OMP_NUM_THREADS")


def ursa_environment() -> dict:
    """The environment URSA runs with: only what a Python process needs."""
    env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
    # PYTHONNOUSERSITE: the service user's ~/.local packages must not leak
    # into (or shadow packages of) the URSA environment
    env.update(MPLBACKEND="Agg", PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1")
    return env


# ── job document ─────────────────────────────────────────────────────
def _job_path(workspace, asset_id):
    path = workspace.asset_file(asset_id, ASSET_AUTOMATIC)
    if path.is_symlink():
        raise PermissionError("automatic.json may not be a link.")
    return path


def read_job(workspace: FrozenLegaciesWorkspace, asset_id: str) -> dict | None:
    path = _job_path(workspace, asset_id)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict) or doc.get("schema") != JOB_SCHEMA
            or doc.get("asset_id") != asset_id
            or doc.get("status") not in ACTIVE + FINAL):
        return None
    return doc


def write_job(workspace, asset_id: str, doc: dict) -> None:
    path = _job_path(workspace, asset_id)
    text = json.dumps(doc, indent=2, sort_keys=True, allow_nan=False)
    manual._atomic_write(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def public_job(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    public = {k: doc.get(k) for k in (
        "job_id", "picker", "status", "created_at", "started_at", "finished_at",
        "message", "log_tail", "summary", "warnings", "picker_version")}
    if isinstance(doc.get("provenance"), dict):
        public["provenance"] = doc["provenance"]
    if isinstance(doc.get("progress"), dict):
        public["progress"] = doc["progress"]
    public["scientific_status"] = SCIENTIFIC_STATUS
    public["picker_label"] = LABELS.get(doc.get("picker"), str(doc.get("picker") or ""))
    return public


# ── running ──────────────────────────────────────────────────────────
def _sanitize(text: str, secrets: list[str]) -> str:
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "…")
    return text


def _log_tail(path: Path, secrets: list[str]) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [_sanitize(line, secrets)[:300] for line in lines[-LOG_TAIL_LINES:]]


def _read_lyra_progress(path: Path) -> dict | None:
    """Read the runner's bounded, path-free live progress document."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_PROGRESS_BYTES:
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(doc, dict)
            or doc.get("schema") != "cryostack.frozen_legacies.lyra_progress"
            or doc.get("phase") not in ("phase1", "phase3", "phase4")
            or doc.get("status") not in ("running", "completed", "finished")
            or not isinstance(doc.get("updated_at"), (int, float))
            or not isinstance(doc.get("phases"), dict)):
        return None
    phases = {}
    for name, result in doc["phases"].items():
        if name not in ("phase1", "phase3", "phase4") or not isinstance(result, dict):
            continue
        phases[name] = {key: result[key] for key in ("exit", "seconds")
                        if isinstance(result.get(key), (int, float))}
    return {"phase": doc["phase"], "status": doc["status"],
            "updated_at": float(doc["updated_at"]), "phases": phases}


def warnings_for(filename: str, has_nav: bool, *, picker: str | None = None,
                 manifest: dict | None = None) -> list[str]:
    if (picker or configured_picker()) == "lyra":
        return lyra_warnings(manifest or {"filename": filename})
    out = []
    if not URSA_CBD_PATTERN.search(filename or ""):
        out.append("URSA reads CBDs from names like 'F103-C0467_C0479.tiff'; this file name "
                   "has no such range, so URSA will not assign CBDs or positions.")
    if not has_nav:
        out.append("No navigation file: URSA will not assign latitude/longitude.")
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(path: Path | None, name: str | None = None) -> dict | None:
    """Name, size and SHA-256 of a file (never its path)."""
    if path is None or not path.is_file():
        return None
    return {"name": name or path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _git_commit(root: Path) -> str | None:
    """URSA's commit when its source is a git checkout of its own (read-only).

    A checkout that is merely inside the CryoStack repository (a copied
    source tree) has no URSA commit; the source digest identifies it then.
    """
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel", "HEAD"],
            capture_output=True, text=True, timeout=10, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = completed.stdout.strip().splitlines() if completed.returncode == 0 else []
    if len(lines) != 2 or not re.fullmatch(r"[0-9a-f]{40}", lines[1]):
        return None
    try:
        toplevel = Path(lines[0]).resolve()
    except OSError:
        return None
    if toplevel == _REPO or toplevel not in (root, *root.parents):
        return None
    return lines[1]


def ursa_identity(root: Path) -> dict:
    """What identifies the URSA that ran: commit (if determinable), a digest
    of its Python sources and configuration, and the parameters it used."""
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*.py")
                   if "__pycache__" not in p.parts and p.is_file() and not p.is_symlink())
    config = root / "config" / "default_config.json"
    for path in files + ([config] if config.is_file() else []):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    parameters = None
    config_sha = None
    if config.is_file() and not config.is_symlink() and config.stat().st_size <= MAX_CONFIG_BYTES:
        raw = config.read_bytes()
        config_sha = hashlib.sha256(raw).hexdigest()
        try:
            parameters = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            parameters = None
    return {"commit": _git_commit(root), "source_sha256": digest.hexdigest(),
            "source_files": len(files), "configuration": "default_config.json",
            "config_sha256": config_sha, "parameters": parameters}


def _copy_regular(source: Path, target: Path, limit: int) -> tuple[str, int]:
    """Copy a regular file (never through a link) of at most ``limit`` bytes;
    returns ``(sha256, bytes)``."""
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise PermissionError("Diagnostic images must be bounded regular files.")
        if handle.read(len(_PNG_SIGNATURE)) != _PNG_SIGNATURE:
            raise PermissionError("Diagnostic images must be PNG files.")
        handle.seek(0)
        digest, size = hashlib.sha256(), 0
        with target.open("xb") as out:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                if size > limit:
                    raise PermissionError("Diagnostic image grew while being copied.")
                digest.update(chunk)
                out.write(chunk)
    return digest.hexdigest(), size


def _diagnostic_candidates(work: Path, stem: str) -> list[tuple[Path, str, int, str]]:
    """``(source, name relative to the work area, frame, what)`` of URSA's
    diagnostic images: regular files only, in directories inside ``work``."""
    root = work.resolve()
    found: dict[str, tuple[Path, str, int, str]] = {}
    for relative in DIAGNOSTIC_DIRS:
        directory = work / relative
        if directory.is_symlink() or not directory.is_dir():
            continue
        resolved = directory.resolve()
        if root not in (resolved, *resolved.parents):
            continue
        for entry in sorted(os.scandir(directory), key=lambda e: e.name):
            if not entry.name.startswith(stem) or not entry.is_file(follow_symlinks=False):
                continue
            match = _DIAGNOSTIC_SUFFIX.fullmatch(entry.name[len(stem):])
            if not match or entry.name in found:
                continue
            frame = int(match.group(1))
            if frame < 1:
                continue
            shown = relative.split("/", 1)[1] + "/" if "/" in relative else ""
            found[entry.name] = (Path(entry.path), shown + entry.name, frame, match.group(2))
    # every frame's picks plot first, so the size bound never drops the
    # last frames' plots in favour of reference-line QA images
    return sorted(found.values(), key=lambda c: (c[3] != "picked", c[2], c[3]))


def _collect_diagnostics(workspace, asset_id: str, work: Path, stem: str, safe_stem: str,
                         *, now: float, run: dict) -> dict:
    """Keep URSA's diagnostic images as ``ursa-diagnostic`` products
    (replacing a previous run's); returns their provenance."""
    records, kept, skipped, total = [], [], 0, 0
    for source, shown, frame, what in _diagnostic_candidates(work, stem):
        try:
            size = os.lstat(source).st_size
        except OSError:
            continue
        if (len(records) >= MAX_DIAGNOSTIC_FILES or size > MAX_DIAGNOSTIC_FILE_BYTES
                or total + size > MAX_DIAGNOSTIC_TOTAL_BYTES):
            skipped += 1
            continue
        key = re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-")
        product_id = f"ursa-diag-f{frame:02d}-{key}"[:64].rstrip("-")
        name = f"{safe_stem}_ursa_diag_frame{frame:02d}_{what}.png"
        if not products.is_valid_product_id(product_id) or any(
                r["product_id"] == product_id for r in records):
            skipped += 1
            continue
        target = products.stored_file(workspace, asset_id, name)
        copied = {}

        def write(tmp, source=source):
            copied["sha256"], copied["bytes"] = _copy_regular(
                source, tmp, MAX_DIAGNOSTIC_FILE_BYTES)

        try:
            manual._atomic_write(target, write)
        except (OSError, PermissionError):
            skipped += 1
            continue
        total += copied["bytes"]
        label = DIAGNOSTIC_LABELS.get(what, what.replace("_", " "))
        records.append({
            "product_id": product_id, "kind": "ursa-diagnostic",
            "title": f"{products.DIAGNOSTIC_LABEL} · frame {frame}: {label}",
            "file": target.name, "producer": "frozen-legacies", "workflow": "ursa-automatic",
            "mime": "image/png", "created_at": now,
            "provenance": {"picker": "URSA (automatic)", "written_by": "URSA",
                           "source_name": shown, "sha256": copied["sha256"],
                           "scientific_status": SCIENTIFIC_STATUS, **run},
            "summary": {"frame": frame, "label": label, "bytes": copied["bytes"]},
        })
        kept.append({"product_id": product_id, "name": shown, "frame": frame,
                     "bytes": copied["bytes"], "sha256": copied["sha256"]})
    products.replace_kind(workspace, asset_id, "ursa-diagnostic", "ursa-automatic", records)
    return {"label": products.DIAGNOSTIC_LABEL, "images": kept, "count": len(kept),
            "bytes": total, "skipped": skipped,
            "limits": {"files": MAX_DIAGNOSTIC_FILES, "file_bytes": MAX_DIAGNOSTIC_FILE_BYTES,
                       "total_bytes": MAX_DIAGNOSTIC_TOTAL_BYTES}}


def _collect(workspace, asset_id: str, out_dir: Path, stem: str, safe_stem: str, *,
             work: Path | None = None, tiff: Path | None = None, nav: Path | None = None,
             filename: str | None = None, job_id: str | None = None,
             environment: dict | None = None) -> tuple[dict, dict]:
    """Register URSA's outputs as products (replacing a previous run);
    returns ``(CSV summary, provenance)``."""
    now = time.time()
    produced = {}
    identity = ursa_identity(ursa_root())
    inputs = {"tiff": _file_identity(tiff, os.path.basename(filename or f"{stem}.tiff")),
              "navigation": _file_identity(nav, "nav.csv")}
    # recorded on every product of the run (additive provenance fields)
    run = {"job_id": job_id, "ursa_commit": identity["commit"],
           "ursa_source_sha256": identity["source_sha256"],
           "config_sha256": identity["config_sha256"],
           "input_sha256": (inputs["tiff"] or {}).get("sha256")}

    def store(kind, source: Path, name: str):
        target = products.stored_file(workspace, asset_id, name)
        manual._atomic_write(target, lambda tmp: shutil.copyfile(source, tmp))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        record = {
            "product_id": kind, "kind": kind, "title": products.KINDS[kind]["title"],
            "file": target.name, "producer": "frozen-legacies", "workflow": "ursa-automatic",
            "mime": products.KINDS[kind]["mime"], "created_at": now,
            "provenance": {"picker": "URSA (automatic)", "configuration": "URSA default_config.json",
                           "sha256": digest, "scientific_status": SCIENTIFIC_STATUS, **run},
        }
        if kind == "ursa-csv":
            try:
                record["summary"] = products.summarize_csv("ursa-csv", target)
            except products.ProductValidationError:
                record["summary"] = {}
        products.register(workspace, asset_id, record, replace_kinds=(kind,))
        produced[kind] = record

    csv_path = out_dir / f"{stem}_pick.csv"
    store("ursa-csv", csv_path, f"{safe_stem}_pick.csv")
    if (out_dir / f"{stem}_pick.npz").is_file():
        store("ursa-npz", out_dir / f"{stem}_pick.npz", f"{safe_stem}_pick.npz")
    if (out_dir / f"{stem}_frame_verification.png").is_file():
        store("ursa-verification", out_dir / f"{stem}_frame_verification.png",
              f"{safe_stem}_frame_verification.png")
    frames = sorted(out_dir.glob(f"{stem}_frame*_picked.png"))
    if frames:
        bundle = out_dir / f"{safe_stem}_ursa_frames.zip"
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
            for frame in frames:
                archive.write(frame, arcname=frame.name)
        store("ursa-frames", bundle, bundle.name)
    diagnostics = _collect_diagnostics(workspace, asset_id, work or out_dir.parent, stem,
                                       safe_stem, now=now, run=run)
    provenance = {
        "picker": "URSA (automatic)",
        "scientific_status": SCIENTIFIC_STATUS,
        "ursa": {k: identity[k] for k in ("commit", "source_sha256", "source_files",
                                          "configuration", "config_sha256")},
        "parameters": identity["parameters"],
        "runner": {"interactive": False, "defer_frame_plots": False,
                   "navigation": nav is not None},
        "environment": environment,
        "inputs": inputs,
        "outputs": {kind: {"name": record["file"], "sha256": record["provenance"]["sha256"]}
                    for kind, record in produced.items()},
        "diagnostics": diagnostics,
    }
    return produced.get("ursa-csv", {}).get("summary", {}), provenance


FRAME_NOTE = ("Values are URSA's, exactly as written in its CSV. Flags are heuristic "
              "consistency checks against the strip median (transmitter position and power); "
              "they mark frames to inspect and correct nothing. Diagnostic images are URSA's "
              "own and scientifically unvalidated.")


def frame_diagnostics(workspace, manifest: dict, listed: list[dict], sources: dict,
                      picker: str = "ursa") -> dict | None:
    """Per-frame view of the automatic result of ``picker``: its values as-is,
    the frame QC flags with their reasons, and its diagnostic images."""
    if picker == "lyra":
        return _lyra_frame_diagnostics(workspace, manifest, listed, sources)
    csv_product = next((p for p in listed if p["kind"] == "ursa-csv"
                        and p["workflow"] == "ursa-automatic" and p["available"]), None)
    if csv_product is None:
        return None
    try:
        _record, path = products.resolve_product(workspace, manifest, sources, "ursa-csv")
    except (products.AssetNotFoundError, PermissionError):
        return None
    table = products.ursa_frame_table(path)
    if not table:
        return None
    images: dict[int, list[dict]] = {}
    for product in listed:
        if product["kind"] != "ursa-diagnostic" or not product["available"]:
            continue
        frame = (product.get("summary") or {}).get("frame")
        if isinstance(frame, int):
            images.setdefault(frame, []).append({
                "product_id": product["product_id"], "title": product["title"],
                "label": product["summary"].get("label"), "bytes": product["bytes"],
                "sha256": product["provenance"].get("sha256"),
                "preview_url": product["preview_url"], "download_url": product["download_url"]})
    flags = {f["frame"]: f["checks"] for f in table["qc_flags"]}
    position = table["columns"].index("Frame")
    rows = []
    for values in table["rows"]:
        try:
            frame = int(float(values[position]))
        except ValueError:
            frame = None
        rows.append({"frame": frame, "values": values, "flags": flags.get(frame, []),
                     "images": images.get(frame, [])})
    return {"columns": table["columns"], "rows": rows, "truncated": table["truncated"],
            "flagged": len(flags), "diagnostic_images": sum(len(v) for v in images.values()),
            "label": products.DIAGNOSTIC_LABEL, "note": FRAME_NOTE,
            "scientific_status": SCIENTIFIC_STATUS}


# ── LYRA ─────────────────────────────────────────────────────────────
LYRA_DEPENDENCIES = ("numpy", "pandas", "matplotlib", "PIL")
LYRA_SCRIPTS = ("lyra.py", "detect_frames.py", "segment_ocr.py", "build_digit_templates.py",
                "calibrate.py", "echoes.py")
#: LYRA's canonical TIFF name (``lyra._CANONICAL_RE``)
LYRA_CANONICAL = re.compile(r"^(\d+)_(\d+)_(\d+)-reel_begin_end\.tiff$", re.IGNORECASE)
_RENAME_NEW = re.compile(r"^F(\d+)-")
#: LYRA's per-frame figures kept as ``lyra-diagnostic`` products
_LYRA_FRAME_FIGURE = re.compile(
    r"F\d+_\d+_(CBD\d+(?:_f\d+)?|fr\d+)_(cal|echoes|waveform|publication)\.png")
_LYRA_TIFF_FIGURE = re.compile(r"F\d+_\d+_(contact|ocr_diag)\.png")
LYRA_FIGURE_LABELS = {"contact": "contact sheet (frames and CBDs)",
                      "ocr_diag": "CBD OCR diagnostic",
                      "cal": "calibration (main bang, -60 dB reference, grid)",
                      "echoes": "surface and bed echoes",
                      "waveform": "waveform",
                      "publication": "publication figure"}
LYRA_RUN_KINDS = ("lyra-frame-index", "lyra-calibration", "lyra-run-echoes")
LYRA_STOPPED = {
    None: "LYRA finished: frames, CBDs, calibration and echoes.",
    "calibration-guidance-required": (
        "LYRA detected the frames and read their CBDs. Calibration and echo extraction "
        "need LYRA's calibration picks (a human reference-line pick for this TIFF): "
        "upload them as a 'LYRA calibration picks (JSON)' product and run again."),
    "phase3-refused": ("LYRA detected the frames but refused to calibrate them with the "
                       "uploaded calibration picks (see the LYRA log)."),
    "phase4-failed": "LYRA calibrated the frames but echo extraction failed (see the LYRA log).",
}


def lyra_root() -> Path:
    configured = (os.environ.get(LYRA_ROOT_ENV) or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_LYRA_ROOT


def lyra_python() -> str:
    return (os.environ.get(LYRA_PYTHON_ENV) or "").strip() or sys.executable


def lyra_availability(*, refresh: bool = False) -> dict:
    """Whether LYRA can run here; the reason when it cannot (cached 5 min)."""
    root, python = lyra_root(), lyra_python()
    key = ("lyra", str(root), python)
    cached = _availability_cache.get(key)
    if cached and not refresh and time.time() - cached[0] < 300:
        return cached[1]
    unavailable = {"available": False, "picker": "LYRA"}
    if any(not (root / "codes" / name).is_file() for name in LYRA_SCRIPTS):
        result = {**unavailable,
                  "reason": "The LYRA automatic picker is not installed on this server."}
    else:
        result = _lyra_health_check(python, root)
    _availability_cache[key] = (time.time(), result)
    return result


def _lyra_health_check(python: str, root: Path) -> dict:
    import tempfile

    unavailable = {"available": False, "picker": "LYRA",
                   "reason": "LYRA could not be imported in the automatic-picking environment "
                             "on this server."}
    try:
        with tempfile.TemporaryDirectory(prefix="lyra-check-") as scratch:
            completed = subprocess.run(
                [python, str(LYRA_RUNNER), "--check", "--lyra-root", str(root)],
                capture_output=True, text=True, timeout=180, env=ursa_environment(),
                cwd=scratch)
    except (OSError, subprocess.TimeoutExpired):
        return {**unavailable,
                "reason": "The automatic-picking Python environment could not be started."}
    lines = (completed.stdout or "").strip().splitlines()
    if completed.returncode != 0:
        name = re.search(r"No module named '([^']+)'", lines[-1] if lines else "")
        if name:
            return {**unavailable,
                    "reason": f"LYRA needs the Python package '{name.group(1)}', which is not "
                              "installed in the automatic-picking environment on this server."}
        return unavailable
    try:
        report = json.loads(lines[-1]) if lines else None
    except ValueError:
        report = None
    if not isinstance(report, dict) or report.get("lyra") != "importable":
        return unavailable
    packages = report.get("packages") if isinstance(report.get("packages"), dict) else {}
    return {"available": True, "picker": "LYRA", "reason": None,
            "environment": {"python": str(report.get("python") or "")[:20],
                            "packages": {str(k)[:40]: (str(v)[:40] if v else None)
                                         for k, v in list(packages.items())[:20]}}}


def _rename_logs() -> list[Path]:
    directories = [lyra_root() / "rename_logs"]
    extra = (os.environ.get(LYRA_RENAME_LOGS_ENV) or "").strip()
    if extra:
        directories.append(Path(extra).expanduser())
    logs = []
    for directory in directories:
        if directory.is_dir() and not directory.is_symlink():
            logs += sorted(p for p in directory.glob("*_rename_log*.txt")
                           if p.is_file() and not p.is_symlink())
    return logs


def _parse_rename_log(path: Path) -> list[tuple[str, str]]:
    """``(old, new)`` name pairs of a LYRA rename log (``lyra._parse_rename_log``)."""
    pairs, old = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("Old: "):
            old = line[5:].strip()
        elif line.startswith("New: ") and old:
            pairs.append((old, line[5:].strip()))
            old = None
    return pairs


def lyra_inputs(manifest: dict) -> dict:
    """The canonical LYRA name and flight of an asset's TIFF, or the reason
    LYRA cannot be offered for it. Never synthesizes a name."""
    filename = os.path.basename(manifest.get("filename") or "")
    flight = str(manifest.get("flight") or "").strip().lstrip("Ff")
    if LYRA_CANONICAL.fullmatch(filename):
        if not flight.isdigit():
            return {"ok": False, "reason": (
                "LYRA needs the flight number of this radar; it is not recorded for "
                "this asset.")}
        return {"ok": True, "canonical_name": filename, "flight": int(flight),
                "resolved_by": "file name"}
    stem = os.path.splitext(filename)[0]
    matches, conflicts = {}, set()
    for log in _rename_logs():
        try:
            pairs = _parse_rename_log(log)
        except OSError:
            continue
        for old, new in pairs:
            if os.path.splitext(new)[0] != stem:
                continue
            old_stem = re.sub(r"(_QC)?\.[A-Za-z]+$", "", old)
            prefix = _RENAME_NEW.match(new)
            logged_flight = prefix.group(1) if prefix else None
            if flight and logged_flight and logged_flight != flight:
                conflicts.add(f"{log.name}: F{logged_flight}")
                continue
            matches.setdefault(old_stem, set()).add(log.name)
    canonical = [f"{old}.tiff" for old in matches if LYRA_CANONICAL.fullmatch(f"{old}.tiff")]
    if len(canonical) == 1 and flight.isdigit():
        log_names = sorted(matches[canonical[0][:-5]])
        logs = {p.name: p for p in _rename_logs()}
        return {"ok": True, "canonical_name": canonical[0], "flight": int(flight),
                "resolved_by": "rename log", "rename_logs": [
                    _file_identity(logs[name]) for name in log_names if name in logs]}
    if len(canonical) > 1:
        return {"ok": False, "reason": (
            "LYRA's rename logs give more than one original reel name for this file; "
            "LYRA is not run until that is resolved.")}
    reason = ("LYRA reads the TIFF under its original reel name "
              "('<reel>_<start>_<end>-reel_begin_end.tiff'). This file has another name and "
              "no LYRA rename log maps it to its reel name, so LYRA cannot process it.")
    if conflicts:
        reason += (" A rename log names this segment under a different flight ("
                   + ", ".join(sorted(conflicts)) + ") than the asset; that label needs "
                   "checking first.")
    return {"ok": False, "reason": reason}


def lyra_guidance(workspace, asset_id: str) -> dict:
    """The newest uploaded LYRA calibration picks (and derived calibration)."""
    newest: dict[str, dict] = {}
    for record in products.read_records(workspace, asset_id)["products"]:
        if record["kind"] in ("lyra-guidance", "lyra-guidance-derived") \
                and record.get("producer") == "user":
            previous = newest.get(record["kind"])
            if previous is None or (record.get("created_at") or 0) >= (previous.get("created_at") or 0):
                newest[record["kind"]] = record
    out = {}
    for kind, key in (("lyra-guidance", "picks"), ("lyra-guidance-derived", "derived")):
        record = newest.get(kind)
        if record is None:
            continue
        try:
            path = products.stored_file(workspace, asset_id, record["file"])
        except PermissionError:
            continue
        if path.is_file():
            out[key] = {"path": path, "product_id": record["product_id"],
                        "name": record.get("download_name") or record["file"],
                        "sha256": (record.get("provenance") or {}).get("sha256"),
                        "summary": record.get("summary") or {}}
    return out


def lyra_warnings(manifest: dict, guidance: dict | None = None) -> list[str]:
    out = []
    inputs = lyra_inputs(manifest)
    if not inputs["ok"]:
        out.append(inputs["reason"])
    elif inputs["resolved_by"] == "rename log":
        out.append(f"LYRA will read this file as {inputs['canonical_name']} "
                   "(original reel name from a LYRA rename log).")
    if guidance is not None and "picks" not in guidance:
        out.append("No LYRA calibration picks uploaded: LYRA will detect frames and read CBDs "
                   "only. Calibration, echoes and ice thickness need LYRA's calibration picks.")
    out.append("LYRA assigns no latitude/longitude: its navigation alignment is not part of "
               "this installation.")
    return out


def lyra_identity(root: Path) -> dict:
    """A digest of LYRA's code that ran (scripts and digit templates)."""
    digest = hashlib.sha256()
    files = sorted(p for p in (root / "codes").iterdir()
                   if p.suffix in (".py", ".npy") and p.is_file() and not p.is_symlink())
    for path in files:
        digest.update(path.name.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"source_sha256": digest.hexdigest(), "source_files": len(files),
            "ocr_method": "segment"}


def _read_summary(work: Path) -> dict | None:
    path = work / "lyra-run.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == "cryostack.frozen_legacies.lyra_run" else None


def _small_json(path: Path) -> dict | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _collect_lyra(workspace, asset_id: str, work: Path, summary: dict, safe_stem: str, *,
                  tiff: Path, filename: str, inputs: dict, guidance: dict, job_id: str,
                  environment: dict | None) -> tuple[dict, dict]:
    """Register LYRA's outputs as products (replacing a previous LYRA run);
    returns ``(summary, provenance)``."""
    now = time.time()
    flight = int(summary["flight"])
    out = work / "LYRA" / "output" / f"F{flight}"
    identity = lyra_identity(lyra_root())
    tiff_identity = _file_identity(tiff, os.path.basename(filename))
    run = {"job_id": job_id, "lyra_source_sha256": identity["source_sha256"],
           "input_sha256": (tiff_identity or {}).get("sha256"),
           "guidance_sha256": (guidance.get("picks") or {}).get("sha256")}
    produced = {}

    def store(kind: str, source: Path, name: str, extra_summary: dict | None = None):
        if source.is_symlink() or not source.is_file():
            products.replace_kind(workspace, asset_id, kind, "lyra-automatic", [])
            return
        target = products.stored_file(workspace, asset_id, name)
        manual._atomic_write(target, lambda tmp: shutil.copyfile(source, tmp))
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        record = {
            "product_id": kind, "kind": kind, "title": products.KINDS[kind]["title"],
            "file": target.name, "producer": "frozen-legacies", "workflow": "lyra-automatic",
            "mime": products.KINDS[kind]["mime"], "created_at": now,
            "provenance": {"picker": "LYRA (automatic)", "written_by": "LYRA",
                           "source_name": source.relative_to(out).as_posix(), "sha256": digest,
                           "scientific_status": SCIENTIFIC_STATUS, **run},
            "summary": extra_summary or {},
        }
        products.replace_kind(workspace, asset_id, kind, "lyra-automatic", [record])
        produced[kind] = record

    index_csv = out / "phase1" / f"F{flight}_frame_index.csv"
    frames = _lyra_rows(index_csv)
    store("lyra-frame-index", index_csv, f"{safe_stem}_lyra_frame_index.csv",
          {"rows": len(frames), "row_label": "frames",
           "complete": sum(1 for r in frames if r.get("frame_type") == "complete")})
    cal_csv = out / "phase3" / f"F{flight}_cal.csv"
    store("lyra-calibration", cal_csv, f"{safe_stem}_lyra_cal.csv",
          {"rows": len(_lyra_rows(cal_csv)), "row_label": "frames"})
    echoes_csv = out / "phase4" / f"F{flight}_echoes.csv"
    echoes = _lyra_rows(echoes_csv)
    statuses: dict[str, int] = {}
    for row in echoes:
        statuses[row.get("echo_status") or ""] = statuses.get(row.get("echo_status") or "", 0) + 1
    store("lyra-run-echoes", echoes_csv, f"{safe_stem}_lyra_echoes.csv",
          {"rows": len(echoes), "row_label": "frames", "echo_status": statuses})
    diagnostics = _collect_lyra_diagnostics(workspace, asset_id, out, safe_stem, now=now, run=run)
    reviews = {"calibration": _small_json(out / "phase3" / f"F{flight}_cal_review.json"),
               "echoes": _small_json(out / "phase4" / f"F{flight}_echo_review.json")}
    provenance = {
        "picker": "LYRA (automatic)",
        "scientific_status": SCIENTIFIC_STATUS,
        "lyra": identity,
        "phases": {name: {"exit": phase.get("exit"), "seconds": phase.get("seconds")}
                   for name, phase in (summary.get("phases") or {}).items()},
        "stopped": summary.get("stopped"),
        "canonical_name": inputs["canonical_name"], "flight": flight,
        "canonical_name_from": inputs["resolved_by"],
        "rename_logs": inputs.get("rename_logs") or [],
        "environment": environment,
        "inputs": {"tiff": tiff_identity,
                   "calibration_picks": ({k: guidance["picks"][k] for k in ("name", "sha256")}
                                         if guidance.get("picks") else None),
                   "derived_calibration": ({k: guidance["derived"][k] for k in ("name", "sha256")}
                                           if guidance.get("derived") else None)},
        "outputs": {kind: {"name": record["file"], "sha256": record["provenance"]["sha256"]}
                    for kind, record in produced.items()},
        "lyra_reviews": reviews,
        "diagnostics": diagnostics,
    }
    result = {"frames": len(frames),
              "complete_frames": sum(1 for r in frames if r.get("frame_type") == "complete"),
              "echo_rows": len(echoes), "echo_status": statuses,
              "stopped": summary.get("stopped")}
    return result, provenance


def _lyra_rows(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > products.MAX_CSV_BYTES:
        return []
    import csv

    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for _, row in zip(range(products.MAX_FRAME_ROWS * 4),
                                                csv.DictReader(handle))]
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _lyra_diagnostic_candidates(out: Path) -> list[tuple[Path, str, str, str]]:
    """``(source, shown name, frame key, what)`` of LYRA's PNG figures."""
    root = out.resolve()
    found = []
    for relative in ("phase1", "phase1/ocr_diag", "phase3", "phase4"):
        directory = out / relative
        if directory.is_symlink() or not directory.is_dir():
            continue
        resolved = directory.resolve()
        if root not in (resolved, *resolved.parents):
            continue
        for entry in sorted(os.scandir(directory), key=lambda e: e.name):
            if not entry.is_file(follow_symlinks=False):
                continue
            frame = _LYRA_FRAME_FIGURE.fullmatch(entry.name)
            whole = _LYRA_TIFF_FIGURE.fullmatch(entry.name)
            if frame:
                found.append((Path(entry.path), f"{relative}/{entry.name}", frame.group(1),
                              frame.group(2)))
            elif whole:
                found.append((Path(entry.path), f"{relative}/{entry.name}", "", whole.group(1)))
    order = {"contact": 0, "ocr_diag": 1, "echoes": 2, "cal": 3, "waveform": 4, "publication": 5}
    return sorted(found, key=lambda c: (order.get(c[3], 9), c[2]))


def _collect_lyra_diagnostics(workspace, asset_id: str, out: Path, safe_stem: str, *,
                              now: float, run: dict) -> dict:
    records, kept, skipped, total = [], [], 0, 0
    for source, shown, frame, what in _lyra_diagnostic_candidates(out):
        try:
            size = os.lstat(source).st_size
        except OSError:
            continue
        if (len(records) >= MAX_DIAGNOSTIC_FILES or size > MAX_DIAGNOSTIC_FILE_BYTES
                or total + size > MAX_DIAGNOSTIC_TOTAL_BYTES):
            skipped += 1
            continue
        key = re.sub(r"[^a-z0-9]+", "-", f"{frame}-{what}".lower()).strip("-")
        product_id = f"lyra-diag-{key}"[:64].rstrip("-")
        name = f"{safe_stem}_lyra_diag_{key}.png"
        if not products.is_valid_product_id(product_id) or any(
                r["product_id"] == product_id for r in records):
            skipped += 1
            continue
        target = products.stored_file(workspace, asset_id, name)
        copied = {}

        def write(tmp, source=source):
            copied["sha256"], copied["bytes"] = _copy_regular(
                source, tmp, MAX_DIAGNOSTIC_FILE_BYTES)

        try:
            manual._atomic_write(target, write)
        except (OSError, PermissionError):
            skipped += 1
            continue
        total += copied["bytes"]
        label = LYRA_FIGURE_LABELS.get(what, what.replace("_", " "))
        title = f"{products.LYRA_DIAGNOSTIC_LABEL} · " + (f"{frame}: {label}" if frame else label)
        records.append({
            "product_id": product_id, "kind": "lyra-diagnostic", "title": title,
            "file": target.name, "producer": "frozen-legacies", "workflow": "lyra-automatic",
            "mime": "image/png", "created_at": now,
            "provenance": {"picker": "LYRA (automatic)", "written_by": "LYRA",
                           "source_name": shown, "sha256": copied["sha256"],
                           "scientific_status": SCIENTIFIC_STATUS, **run},
            "summary": {"frame_key": frame or None, "label": label, "bytes": copied["bytes"]},
        })
        kept.append({"product_id": product_id, "name": shown, "frame_key": frame or None,
                     "bytes": copied["bytes"], "sha256": copied["sha256"]})
    products.replace_kind(workspace, asset_id, "lyra-diagnostic", "lyra-automatic", records)
    return {"label": products.LYRA_DIAGNOSTIC_LABEL, "images": kept, "count": len(kept),
            "bytes": total, "skipped": skipped,
            "limits": {"files": MAX_DIAGNOSTIC_FILES, "file_bytes": MAX_DIAGNOSTIC_FILE_BYTES,
                       "total_bytes": MAX_DIAGNOSTIC_TOTAL_BYTES}}


LYRA_FRAME_NOTE = (
    "Values are LYRA's, exactly as written in its CSVs. CBDs come from LYRA's OCR plus its "
    "sequence constraint, which assumes no skipped CBD numbers; the OCR column shows what "
    "LYRA actually read. Flags are heuristic consistency checks (OCR disagreement, main-bang "
    "position against the strip median, LYRA's echo status); they mark frames to inspect and "
    "correct nothing.")
LYRA_MB_QC_PX = 100
#: LYRA values shown per frame: (column title, source table, column)
LYRA_FRAME_COLUMNS = [
    ("Frame", "index", "frame_idx"), ("Type", "index", "frame_type"), ("CBD", "index", "cbd"),
    ("OCR read", "index", "ocr_raw"), ("Echo status", "echoes", "echo_status"),
    ("Main bang x (px)", "echoes", "mb_x"), ("Surface TWT (µs)", "echoes", "surface_twt_us"),
    ("Bed TWT (µs)", "echoes", "bed_twt_us"), ("Ice thickness (m)", "echoes", "h_ice_m"),
    ("Bed SNR (dB)", "echoes", "bed_snr_dB"),
]


def _lyra_cbd(row: dict) -> int | None:
    try:
        return int(float((row.get("cbd") or "").strip()))
    except ValueError:
        return None


def _lyra_frame_key(row: dict, duplicates: set[int] = frozenset()) -> str:
    """The frame part of LYRA's figure names (``calibrate.py`` ``file_id``)."""
    cbd = _lyra_cbd(row)
    try:
        frame = int(row["frame_idx"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not cbd:
        return f"fr{frame:02d}"
    return f"CBD{cbd}_f{frame}" if cbd in duplicates else f"CBD{cbd}"


def lyra_frame_table(index_rows: list[dict], echo_rows: list[dict]) -> dict:
    """LYRA's per-frame values (text as written) and display-only QC flags."""
    echoes = {}
    for row in echo_rows:
        echoes[str(row.get("frame_idx", "")).strip()] = row
    mbs = []
    for row in echo_rows:
        try:
            mbs.append(float(row["mb_x"]))
        except (KeyError, TypeError, ValueError):
            pass
    mbs.sort()
    median = (mbs[len(mbs) // 2] if len(mbs) % 2 else (mbs[len(mbs) // 2 - 1] + mbs[len(mbs) // 2]) / 2) \
        if len(mbs) >= 3 else None
    seen: dict[int, int] = {}
    for index in index_rows:
        cbd = _lyra_cbd(index)
        if index.get("frame_type") == "complete" and cbd:
            seen[cbd] = seen.get(cbd, 0) + 1
    duplicates = {cbd for cbd, count in seen.items() if count > 1}
    rows = []
    for index in index_rows[:products.MAX_FRAME_ROWS]:
        frame = str(index.get("frame_idx", "")).strip()
        echo = echoes.get(frame, {})
        tables = {"index": index, "echoes": echo}
        values = [str(tables[t].get(c) or "").strip()[:40] for _, t, c in LYRA_FRAME_COLUMNS]
        flags = []
        cbd, raw = (index.get("cbd") or "").strip(), (index.get("ocr_raw") or "").strip()
        if index.get("frame_type") == "complete":
            if not raw:
                flags.append("CBD inferred from the sequence: OCR read nothing")
            elif cbd and not raw.endswith(cbd.zfill(4)):
                flags.append(f"CBD {cbd} inferred from the sequence: OCR read {raw}")
        try:
            mb = float(echo["mb_x"])
            if median is not None and abs(mb - median) > LYRA_MB_QC_PX:
                flags.append(f"main bang position: {mb:.0f} px vs strip median {median:.0f} px")
        except (KeyError, TypeError, ValueError):
            pass
        status = (echo.get("echo_status") or "").strip()
        if status and status != "good":
            flags.append(f"LYRA echo status: {status}")
        try:
            number = int(frame)
        except ValueError:
            number = None
        rows.append({"frame": number, "frame_key": _lyra_frame_key(index, duplicates), "values": values,
                     "flags": flags})
    return {"columns": [c for c, _, _ in LYRA_FRAME_COLUMNS], "rows": rows,
            "truncated": len(index_rows) > products.MAX_FRAME_ROWS}


def _finite(row: dict, name: str) -> float | None:
    try:
        value = float(row.get(name, ""))
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def lyra_map_observations(workspace, manifest: dict, sources: dict, nav_rows: list[dict]) -> dict:
    """Owner-only map observations from the latest completed LYRA run.

    Coordinates are never inferred from frame order. A frame is positioned
    only by an exact match between LYRA's CBD and the asset navigation CSV.
    """
    job = read_job(workspace, manifest["asset_id"])
    if not job or job.get("picker") != "lyra" or job.get("status") != "completed":
        return {"records": [], "total": 0, "positioned": 0}
    tables = {}
    for kind in ("lyra-frame-index", "lyra-run-echoes"):
        try:
            record, path = products.resolve_product(workspace, manifest, sources, kind)
        except (products.AssetNotFoundError, PermissionError):
            continue
        if record.get("workflow") == "lyra-automatic":
            tables[kind] = _lyra_rows(path)
    indexes = tables.get("lyra-frame-index") or []
    echoes = {str(row.get("frame_idx", "")).strip(): row
              for row in tables.get("lyra-run-echoes") or []}
    navigation = {row["cbd"]: row for row in nav_rows
                  if row.get("lat") is not None and row.get("lon") is not None}
    records = []
    for index in indexes:
        if index.get("frame_type") != "complete":
            continue
        cbd = _lyra_cbd(index)
        try:
            frame = int(index["frame_idx"])
        except (KeyError, TypeError, ValueError):
            continue
        echo = echoes.get(str(frame), {})
        nav = navigation.get(cbd)
        lon = nav.get("lon") if nav else None
        if lon is not None and lon > 180:
            lon -= 360
        raw = str(index.get("ocr_raw") or "").strip()
        records.append({
            "observation_id": f"{manifest['asset_id']}-lyra-f{frame}",
            "asset_id": manifest["asset_id"], "frame": frame, "cbd": cbd,
            "flight": manifest.get("flight"), "dataset_id": manifest.get("dataset_id"),
            "workflow": "lyra-automatic", "status": "completed", "scope": "user",
            "scientific_status": SCIENTIFIC_STATUS,
            "cbd_source": "lyra-ocr" if cbd is not None and raw.endswith(str(cbd).zfill(4))
                          else "lyra-sequence",
            "geolocation_status": "exact-cbd-navigation" if nav else "no-navigation-match",
            "lat": nav.get("lat") if nav else None, "lon": lon,
            "position": [lon, nav["lat"]] if nav else None,
            "echo_status": str(echo.get("echo_status") or "") or None,
            "surface_us": _finite(echo, "surface_twt_us"),
            "bed_us": _finite(echo, "bed_twt_us"),
            "h_ice_m": _finite(echo, "h_ice_m"), "job_id": job.get("job_id"),
        })
    return {"records": records, "total": len(records),
            "positioned": sum(1 for record in records if record["position"] is not None)}


def _lyra_frame_diagnostics(workspace, manifest: dict, listed: list[dict], sources: dict) -> dict | None:
    tables = {}
    for kind in ("lyra-frame-index", "lyra-run-echoes"):
        product = next((p for p in listed if p["kind"] == kind and p["available"]
                        and p["workflow"] == "lyra-automatic"), None)
        if product is None:
            continue
        try:
            _record, path = products.resolve_product(workspace, manifest, sources, kind)
        except (products.AssetNotFoundError, PermissionError):
            continue
        tables[kind] = _lyra_rows(path)
    if not tables.get("lyra-frame-index"):
        return None
    table = lyra_frame_table(tables["lyra-frame-index"], tables.get("lyra-run-echoes") or [])
    images: dict[str, list[dict]] = {}
    for product in listed:
        if product["kind"] != "lyra-diagnostic" or not product["available"]:
            continue
        key = (product.get("summary") or {}).get("frame_key") or ""
        images.setdefault(key, []).append({
            "product_id": product["product_id"], "title": product["title"],
            "label": product["summary"].get("label"), "bytes": product["bytes"],
            "sha256": product["provenance"].get("sha256"),
            "preview_url": product["preview_url"], "download_url": product["download_url"]})
    for row in table["rows"]:
        row["images"] = images.get(row.pop("frame_key"), [])
    return {**table, "flagged": sum(1 for r in table["rows"] if r["flags"]),
            "diagnostic_images": sum(len(v) for v in images.values()),
            "strip_images": images.get("", []),
            "label": products.LYRA_DIAGNOSTIC_LABEL, "note": LYRA_FRAME_NOTE,
            "picker_label": "LYRA", "scientific_status": SCIENTIFIC_STATUS}


class AutomaticRunner:
    """Runs automatic-picking jobs (LYRA, or URSA as the rollback) as
    subprocesses, off the event loop; one per asset."""

    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        #: keys whose process leads its own process group (LYRA: the runner
        #: starts one child per phase, and the whole group is stopped)
        self.groups: set[str] = set()
        self.leases: dict[str, object] = {}
        self._semaphore: asyncio.Semaphore | None = None
        #: called as ``on_change(workspace, asset_id)`` after each status change
        self.on_change = None

    def _write(self, workspace, asset_id, doc) -> None:
        write_job(workspace, asset_id, doc)
        if self.on_change is not None:
            try:
                self.on_change(workspace, asset_id)
            except Exception:
                pass

    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            limit = _bounded_int_env(CONCURRENCY_ENV, 1, 1, MAX_CONCURRENT_JOBS)
            self._semaphore = asyncio.Semaphore(limit)
        return self._semaphore

    @staticmethod
    def key(workspace, asset_id) -> str:
        return f"{workspace.root}/{asset_id}"

    def active(self, workspace, asset_id) -> bool:
        task = self.tasks.get(self.key(workspace, asset_id))
        return task is not None and not task.done()

    def _lease_path(self, workspace, asset_id: str) -> Path:
        return workspace.asset_dir(asset_id) / ".automatic.lock"

    def _acquire_lease(self, workspace, asset_id: str) -> None:
        key = self.key(workspace, asset_id)
        path = self._lease_path(workspace, asset_id)
        if path.is_symlink():
            raise PermissionError("Automatic job lock may not be a link.")
        handle = path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise AutomaticJobBusy("Automatic picking is already running for this asset.")
        self.leases[key] = handle

    def _release_lease(self, key: str) -> None:
        handle = self.leases.pop(key, None)
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _leased_by_another_worker(self, workspace, asset_id: str) -> bool:
        path = self._lease_path(workspace, asset_id)
        if path.is_symlink():
            return False
        handle = path.open("a+b")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False
        finally:
            handle.close()

    def current(self, workspace, asset_id) -> dict | None:
        """The job document, marking orphaned active jobs as interrupted."""
        doc = read_job(workspace, asset_id)
        if (doc and doc["status"] in ACTIVE and not self.active(workspace, asset_id)
                and not self._leased_by_another_worker(workspace, asset_id)):
            doc["status"] = "interrupted"
            doc["finished_at"] = time.time()
            doc["message"] = ("The server restarted while this job was running. "
                              "Run automatic picking again.")
            self._write(workspace, asset_id, doc)
        elif doc and doc.get("picker") == "lyra" and doc["status"] in ACTIVE:
            directory = workspace.asset_dir(asset_id)
            progress = _read_lyra_progress(directory / WORK_DIRNAME / "run" / "lyra-progress.json")
            if progress is not None:
                doc["progress"] = progress
        return doc

    def start(self, workspace, asset_id: str, *, tiff: Path, nav: Path | None,
              filename: str, picker: str = "ursa", lyra: dict | None = None) -> dict:
        if picker == "lyra":
            guidance = lyra_guidance(workspace, asset_id)
            warnings = lyra_warnings({"filename": filename, **(lyra or {}).get("manifest", {})},
                                     guidance)
        else:
            guidance, warnings = None, warnings_for(filename, nav is not None, picker="ursa")
        doc = {
            "schema": JOB_SCHEMA, "version": JOB_VERSION, "asset_id": asset_id,
            "job_id": products.new_product_id(picker), "picker": picker,
            "status": "queued", "created_at": time.time(), "started_at": None,
            "finished_at": None, "message": "Waiting to start.", "log_tail": [],
            "summary": {}, "warnings": warnings,
            "picker_version": picker_identity(picker),
        }
        key = self.key(workspace, asset_id)
        self._acquire_lease(workspace, asset_id)
        try:
            self._write(workspace, asset_id, doc)
            if picker == "lyra":
                run = self._run_lyra(workspace, asset_id, doc, tiff=tiff, filename=filename,
                                     inputs=(lyra or {}).get("inputs") or {}, guidance=guidance)
            else:
                run = self._run(workspace, asset_id, doc, tiff=tiff, nav=nav, filename=filename)
            task = asyncio.get_running_loop().create_task(self._leased(tiff, run))
            self.tasks[key] = task
            task.add_done_callback(lambda finished, job_key=key: self._task_done(job_key, finished))
        except Exception:
            self._release_lease(key)
            raise
        return doc

    def _task_done(self, key: str, task: asyncio.Task) -> None:
        if self.tasks.get(key) is task:
            self.tasks.pop(key, None)
        self._release_lease(key)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            _LOG.error("Automatic job task ended unexpectedly: %s", type(error).__name__,
                       exc_info=(type(error), error, error.__traceback__))

    def _signal(self, key: str, process, sig) -> None:
        """Signal a job's process (its whole group for LYRA)."""
        if process is None or process.returncode is not None:
            return
        try:
            if key in self.groups:
                os.killpg(process.pid, sig)
            else:
                process.send_signal(sig)
        except (ProcessLookupError, PermissionError):
            pass

    async def _kill_and_reap(self, key: str, process) -> None:
        """Stop a child or process group and always collect its exit status."""
        if process is None:
            return
        if process.returncode is None:
            self._signal(key, process, signal.SIGKILL)
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except (asyncio.TimeoutError, ProcessLookupError):
            _LOG.error("Automatic child process did not exit after SIGKILL.")

    async def cancel(self, workspace, asset_id: str) -> None:
        key = self.key(workspace, asset_id)
        process = self.processes.get(key)
        task = self.tasks.get(key)
        if process is not None and process.returncode is None:
            self._signal(key, process, signal.SIGTERM)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _leased(self, tiff, run):
        """Run with the radar's working copy kept from cache eviction."""
        from .working_cache import working_cache

        with working_cache().lease(tiff):
            await run

    async def _leased_run(self, workspace, asset_id, doc, *, tiff, nav, filename):
        await self._leased(tiff, self._run(workspace, asset_id, doc, tiff=tiff, nav=nav,
                                           filename=filename))

    async def _run(self, workspace, asset_id, doc, *, tiff, nav, filename):
        key = self.key(workspace, asset_id)
        directory = workspace.asset_dir(asset_id)
        work = workspace.contain(directory / WORK_DIRNAME)
        stem = os.path.splitext(os.path.basename(filename))[0]
        safe_stem = manual.output_stem(filename)
        secrets = [str(work), str(directory), str(tiff), str(nav or ""), str(ursa_root()),
                   str(workspace.root)]
        log = work / "ursa.log"
        try:
            async with self.semaphore():
                availability_now = availability()
                if not availability_now["available"]:
                    doc.update(status="failed", finished_at=time.time(),
                               message=availability_now["reason"])
                    self._write(workspace, asset_id, doc)
                    return
                if work.exists():
                    shutil.rmtree(work)
                (work / "input").mkdir(parents=True)
                # URSA reads flight/CBDs from the file name: present the TIFF
                # under its original name without copying it.
                link = work / "input" / os.path.basename(filename)
                link.symlink_to(tiff)
                out = work / "out"
                command = [ursa_python(), str(RUNNER), "--ursa-root", str(ursa_root()),
                           "--tiff", str(link), "--output", str(out)]
                if nav is not None:
                    command += ["--nav", str(nav)]
                doc.update(status="running", started_at=time.time(),
                           message="URSA is processing the radar TIFF.")
                self._write(workspace, asset_id, doc)
                env = ursa_environment()
                with log.open("wb") as handle:
                    process = await asyncio.create_subprocess_exec(
                        *command, cwd=str(work), stdout=handle, stderr=subprocess.STDOUT,
                        env=env)
                    self.processes[key] = process
                    timeout = _bounded_float_env(
                        TIMEOUT_ENV, 3600.0, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
                    try:
                        code = await asyncio.wait_for(process.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                        doc.update(status="failed", finished_at=time.time(),
                                   message=f"URSA did not finish within {int(timeout)} s.",
                                   log_tail=_log_tail(log, secrets))
                        self._write(workspace, asset_id, doc)
                        return
                tail = _log_tail(log, secrets)
                # URSA saves its frame-verification plot relative to its working
                # directory ("output/"), not to the output directory it was given
                stray = work / "output" / f"{stem}_frame_verification.png"
                if stray.is_file() and not (out / stray.name).exists():
                    out.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(stray), str(out / stray.name))
                if code == 0 and (out / f"{stem}_pick.csv").is_file():
                    summary, provenance = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: _collect(
                            workspace, asset_id, out, stem, safe_stem, work=work, tiff=tiff,
                            nav=nav, filename=filename, job_id=doc["job_id"],
                            environment=availability_now.get("environment")))
                    doc.update(status="completed", finished_at=time.time(), summary=summary,
                               message="URSA finished.", log_tail=tail, provenance=provenance)
                else:
                    reason = {3: "URSA finished without producing picks.",
                              4: "URSA could not be started in this environment."}.get(
                        code, f"URSA stopped with exit status {code}.")
                    doc.update(status="failed", finished_at=time.time(), message=reason,
                               log_tail=tail)
                self._write(workspace, asset_id, doc)
        except asyncio.CancelledError:
            process = self.processes.get(key)
            await self._kill_and_reap(key, process)
            doc.update(status="cancelled", finished_at=time.time(),
                       message="Automatic picking was cancelled.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
            raise
        except Exception as error:   # report, never leave a job "running"
            _LOG.exception("URSA automatic job %s failed (%s).", doc.get("job_id"), asset_id)
            await self._kill_and_reap(key, self.processes.get(key))
            doc.update(status="failed", finished_at=time.time(),
                       message=f"Automatic picking failed: {type(error).__name__}.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
        finally:
            self.processes.pop(key, None)
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)

    async def _run_lyra(self, workspace, asset_id, doc, *, tiff, filename, inputs, guidance):
        key = self.key(workspace, asset_id)
        directory = workspace.asset_dir(asset_id)
        work = workspace.contain(directory / WORK_DIRNAME)
        safe_stem = manual.output_stem(filename)
        secrets = [str(work), str(directory), str(tiff), str(lyra_root()), str(workspace.root)]
        secrets += [str(g["path"]) for g in (guidance or {}).values()]
        log = work / "lyra.log"
        try:
            async with self.semaphore():
                availability_now = lyra_availability()
                if not availability_now["available"]:
                    doc.update(status="failed", finished_at=time.time(),
                               message=availability_now["reason"])
                    self._write(workspace, asset_id, doc)
                    return
                if not inputs.get("ok"):
                    doc.update(status="failed", finished_at=time.time(),
                               message=inputs.get("reason") or "LYRA cannot process this file.")
                    self._write(workspace, asset_id, doc)
                    return
                if work.exists():
                    shutil.rmtree(work)
                work.mkdir(parents=True)
                command = [lyra_python(), str(LYRA_RUNNER), "--lyra-root", str(lyra_root()),
                           "--tiff", str(tiff), "--canonical-name", inputs["canonical_name"],
                           "--flight", str(inputs["flight"]), "--work", str(work / "run")]
                if guidance.get("picks"):
                    command += ["--picks", str(guidance["picks"]["path"])]
                if guidance.get("derived"):
                    command += ["--derived", str(guidance["derived"]["path"])]
                doc.update(status="running", started_at=time.time(),
                           message="LYRA is processing the radar TIFF.")
                self._write(workspace, asset_id, doc)
                with log.open("wb") as handle:
                    process = await asyncio.create_subprocess_exec(
                        *command, cwd=str(work), stdout=handle, stderr=subprocess.STDOUT,
                        env=ursa_environment(), start_new_session=True)
                    self.groups.add(key)
                    self.processes[key] = process
                    timeout = _bounded_float_env(
                        LYRA_TIMEOUT_ENV, 3600.0, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
                    try:
                        code = await asyncio.wait_for(process.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        self._signal(key, process, signal.SIGKILL)
                        await process.wait()
                        doc.update(status="failed", finished_at=time.time(),
                                   message=f"LYRA did not finish within {int(timeout)} s.",
                                   log_tail=_log_tail(log, secrets))
                        self._write(workspace, asset_id, doc)
                        return
                tail = _log_tail(log, secrets)
                summary = _read_summary(work / "run") if code == 0 else None
                if summary is not None and summary.get("stopped") != "phase1-failed":
                    result, provenance = await asyncio.get_running_loop().run_in_executor(
                        None, lambda: _collect_lyra(
                            workspace, asset_id, work / "run", summary, safe_stem, tiff=tiff,
                            filename=filename, inputs=inputs, guidance=guidance,
                            job_id=doc["job_id"],
                            environment=availability_now.get("environment")))
                    doc.update(status="completed", finished_at=time.time(), summary=result,
                               message=LYRA_STOPPED.get(summary.get("stopped"),
                                                        LYRA_STOPPED[None]),
                               log_tail=tail, provenance=provenance)
                else:
                    reason = {2: "LYRA rejected its inputs (see the LYRA log).",
                              3: "LYRA finished without detecting frames.",
                              4: "LYRA could not be started in this environment."}.get(
                        code, f"LYRA stopped with exit status {code}.")
                    doc.update(status="failed", finished_at=time.time(), message=reason,
                               log_tail=tail)
                self._write(workspace, asset_id, doc)
        except asyncio.CancelledError:
            await self._kill_and_reap(key, self.processes.get(key))
            doc.update(status="cancelled", finished_at=time.time(),
                       message="Automatic picking was cancelled.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
            raise
        except Exception as error:   # report, never leave a job "running"
            _LOG.exception("LYRA automatic job %s failed (%s).", doc.get("job_id"), asset_id)
            await self._kill_and_reap(key, self.processes.get(key))
            doc.update(status="failed", finished_at=time.time(),
                       message=f"Automatic picking failed: {type(error).__name__}.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
        finally:
            self.processes.pop(key, None)
            self.groups.discard(key)
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)
