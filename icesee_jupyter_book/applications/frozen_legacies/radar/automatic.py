"""Automatic picking (URSA) jobs on radar assets.

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

Operational availability says nothing about the science: URSA's results have
not been validated against reference picks, so every automatic result is
labelled ``scientifically unvalidated`` (``SCIENTIFIC_STATUS``) and only ASTRA
manual results can be submitted for review and publication.

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

* ``CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT``   -- URSA source directory
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON`` -- Python with URSA's dependencies
  (default: the server's Python)
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT`` -- seconds per job (default 3600)
* ``CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY`` -- concurrent jobs (default 1)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
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
WORK_DIRNAME = ".automatic-work"
LOG_TAIL_LINES = 40

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


# ── availability ─────────────────────────────────────────────────────
def ursa_root() -> Path:
    configured = (os.environ.get(ROOT_ENV) or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_URSA_ROOT


def ursa_python() -> str:
    return (os.environ.get(PYTHON_ENV) or "").strip() or sys.executable


_availability_cache: dict = {}


def availability(*, refresh: bool = False) -> dict:
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
        "message", "log_tail", "summary", "warnings")}
    if isinstance(doc.get("provenance"), dict):
        public["provenance"] = doc["provenance"]
    public["scientific_status"] = SCIENTIFIC_STATUS
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


def warnings_for(filename: str, has_nav: bool) -> list[str]:
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


def frame_diagnostics(workspace, manifest: dict, listed: list[dict], sources: dict) -> dict | None:
    """Per-frame view of the automatic result: URSA's values as-is, the frame
    QC flags with their reasons, and the frame's URSA diagnostic images."""
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


class AutomaticRunner:
    """Runs URSA jobs as subprocesses, off the event loop; one per asset."""

    def __init__(self):
        self.tasks: dict[str, asyncio.Task] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
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
            try:
                limit = max(1, int(os.environ.get(CONCURRENCY_ENV, "1")))
            except ValueError:
                limit = 1
            self._semaphore = asyncio.Semaphore(limit)
        return self._semaphore

    @staticmethod
    def key(workspace, asset_id) -> str:
        return f"{workspace.root}/{asset_id}"

    def active(self, workspace, asset_id) -> bool:
        task = self.tasks.get(self.key(workspace, asset_id))
        return task is not None and not task.done()

    def current(self, workspace, asset_id) -> dict | None:
        """The job document, marking orphaned active jobs as interrupted."""
        doc = read_job(workspace, asset_id)
        if doc and doc["status"] in ACTIVE and not self.active(workspace, asset_id):
            doc["status"] = "interrupted"
            doc["finished_at"] = time.time()
            doc["message"] = ("The server restarted while this job was running. "
                              "Run automatic picking again.")
            self._write(workspace, asset_id, doc)
        return doc

    def start(self, workspace, asset_id: str, *, tiff: Path, nav: Path | None,
              filename: str) -> dict:
        doc = {
            "schema": JOB_SCHEMA, "version": JOB_VERSION, "asset_id": asset_id,
            "job_id": products.new_product_id("ursa"), "picker": "ursa",
            "status": "queued", "created_at": time.time(), "started_at": None,
            "finished_at": None, "message": "Waiting to start.", "log_tail": [],
            "summary": {}, "warnings": warnings_for(filename, nav is not None),
        }
        self._write(workspace, asset_id, doc)
        task = asyncio.get_running_loop().create_task(
            self._leased_run(workspace, asset_id, doc, tiff=tiff, nav=nav, filename=filename))
        self.tasks[self.key(workspace, asset_id)] = task
        return doc

    async def cancel(self, workspace, asset_id: str) -> None:
        key = self.key(workspace, asset_id)
        process = self.processes.get(key)
        task = self.tasks.get(key)
        if process is not None and process.returncode is None:
            process.terminate()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _leased_run(self, workspace, asset_id, doc, *, tiff, nav, filename):
        """Run with the radar's working copy kept from cache eviction."""
        from .working_cache import working_cache

        with working_cache().lease(tiff):
            await self._run(workspace, asset_id, doc, tiff=tiff, nav=nav, filename=filename)

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
                    try:
                        timeout = float(os.environ.get(TIMEOUT_ENV, "3600"))
                    except ValueError:
                        timeout = 3600.0
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
            if process is not None and process.returncode is None:
                process.kill()
            doc.update(status="cancelled", finished_at=time.time(),
                       message="Automatic picking was cancelled.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
            raise
        except Exception as error:   # report, never leave a job "running"
            doc.update(status="failed", finished_at=time.time(),
                       message=f"Automatic picking failed: {type(error).__name__}.",
                       log_tail=_log_tail(log, secrets))
            self._write(workspace, asset_id, doc)
        finally:
            self.processes.pop(key, None)
            if work.exists():
                shutil.rmtree(work, ignore_errors=True)
