"""Results of a selected ICESEE run, for the launcher's Results view.

Finds the run's outputs and its example's results contract, asks ICESEE's
post-processing which views the run supports, and draws them. Loading and
drawing happen in a separate process (``python -m
ICESEE.src.postprocessing.render``) with a time and memory limit, so a large
ensemble or a damaged file can never stall or crash the user's session, and
the figure code is exactly the code the example notebooks run. Drawn figures
are cached in the run directory, keyed by the view, its options and the
output files' timestamps.
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .example_registry import EXAMPLES
from .paths import REPO

CACHE_DIR = ".icesee-results"
RENDER_TIMEOUT_S = 240
MEMORY_LIMIT_BYTES = 6 * 1024 ** 3
_EXTERNAL = REPO / "external"

#: results states shown to the user
READY, PARTIAL, PENDING, NO_OUTPUTS, UNSUPPORTED, ERROR = (
    "ready", "partial", "pending", "no_outputs", "unsupported", "error")


@dataclass
class RunResults:
    status: str
    message: str = ""
    data_dir: Path | None = None
    contract_dir: Path | None = None
    params: Path | None = None
    views: list = field(default_factory=list)
    run: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    not_reproduced: list = field(default_factory=list)
    notebook: str = ""

    def view(self, view_id: str) -> dict | None:
        return next((v for v in self.views if v["id"] == view_id), None)


@dataclass
class RenderOutcome:
    ok: bool
    view: str
    title: str = ""
    png: Path | None = None
    table: dict | None = None
    notes: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
    source: str = ""
    kind: str = ""
    message: str = ""
    supplementary: bool = False
    cached: bool = False


def _example_dir(run) -> Path | None:
    """The example the run executed: its staged copy in the run directory
    (exactly the files that ran, contract included) or the shipped one."""
    run_dir = Path(run.workspace_directory)
    staged = sorted(p for p in (run_dir / "example").glob("*") if p.is_dir()) if (run_dir / "example").is_dir() else []
    for candidate in staged:
        if (candidate / "results.yaml").is_file():
            return candidate
    example = (run.metadata or {}).get("example")
    cfg = EXAMPLES.get(example or "")
    if cfg and (Path(cfg["base"]) / "results.yaml").is_file():
        return Path(cfg["base"])
    return staged[0] if staged else (Path(cfg["base"]) if cfg else None)


def _limits():  # pragma: no cover -- runs in the child
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ValueError, OSError):
        pass
    os.nice(5)


def _run_renderer(args: list[str], out_json: Path, timeout: int = RENDER_TIMEOUT_S) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env["PYTHONPATH"] = f"{_EXTERNAL}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["MPLBACKEND"] = "Agg"
    env["PYTHONNOUSERSITE"] = "1"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.unlink(missing_ok=True)
    try:
        proc = subprocess.run([sys.executable, "-m", "ICESEE.src.postprocessing.render", *args,
                               "--json", str(out_json)],
                              capture_output=True, text=True, timeout=timeout, env=env,
                              cwd=str(_EXTERNAL), preexec_fn=_limits)
    except subprocess.TimeoutExpired:
        return {"ok": False, "kind": "error", "message": f"drawing took longer than {timeout} s and was stopped"}
    try:
        return json.loads(out_json.read_text())
    except (OSError, ValueError):
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["no output"]
        kind = "error"
        if proc.returncode in (-9, 137) or "MemoryError" in (proc.stderr or ""):
            tail = ["the outputs needed more memory than a results view may use"]
        return {"ok": False, "kind": kind, "message": tail[0][:300]}


def _fingerprint(data_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(data_dir.glob("*.h5")):
        st = p.stat()
        h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def _output_dirs(run_dir: Path) -> list[Path]:
    return [run_dir / "_modelrun_datasets", run_dir / "outputs" / "_modelrun_datasets",
            *sorted(run_dir.glob("example/*/_modelrun_datasets")),
            run_dir / "_remote_fetch" / "outputs" / "_modelrun_datasets"]


def _run_fingerprint(run_dir: Path) -> str:
    h = hashlib.sha256()
    for d in _output_dirs(run_dir):
        if d.is_dir():
            h.update(str(d).encode())
            h.update(_fingerprint(d).encode())
    return h.hexdigest()[:16]


def discover(run, *, lifecycle_state: str | None = None) -> RunResults:
    """What the Results view can show for ``run`` (a RunInfo). The example's
    contract is read and the outputs are found by ICESEE's post-processing
    in a child process (the launcher's own ICESEE checkout)."""
    if run is None or not run.workspace_directory:
        return RunResults(NO_OUTPUTS, "Select a run to see its results.")
    run_dir = Path(run.workspace_directory)
    example_dir = _example_dir(run)
    if example_dir is None:
        return RunResults(UNSUPPORTED, "This run's example is not known to the launcher.")
    if not (example_dir / "results.yaml").is_file():
        return RunResults(UNSUPPORTED, "This example does not declare result views (no results.yaml).",
                          contract_dir=example_dir)
    params = run_dir / "params.yaml"
    out_json = run_dir / CACHE_DIR / f"describe-{_run_fingerprint(run_dir)}.json"
    described = None
    if out_json.is_file():
        try:
            described = json.loads(out_json.read_text())
        except ValueError:
            described = None
    if described is None:
        described = _run_renderer(["--run-dir", str(run_dir), "--contract", str(example_dir),
                                   *(["--params", str(params)] if params.is_file() else []), "--describe"],
                                  out_json, timeout=120)
    active = lifecycle_state in ("preparing", "submitted", "queued", "running")
    if not described.get("ok"):
        out_json.unlink(missing_ok=True)
        kind, msg = described.get("kind"), described.get("message", "")
        if kind == "unsupported":
            return RunResults(UNSUPPORTED, msg, contract_dir=example_dir)
        if kind in ("no_outputs", "missing", "incomplete") and active:
            return RunResults(PENDING, "The run has not finished writing its outputs.", contract_dir=example_dir)
        if kind == "no_outputs":
            if lifecycle_state == "failed":
                msg = "The run failed before writing its outputs. See Logs."
            elif run.execution_mode in ("remote", "cloud"):
                msg = "The outputs have not been fetched to the launcher yet."
            else:
                msg = f"No outputs were found ({msg})."
            return RunResults(NO_OUTPUTS, msg, contract_dir=example_dir)
        label = {"missing": "Some outputs are missing", "incomplete": "The outputs are incomplete",
                 "corrupt": "An output file is damaged"}.get(kind, "The outputs could not be read")
        return RunResults(NO_OUTPUTS if kind in ("missing", "incomplete") else ERROR, f"{label}: {msg}",
                          contract_dir=example_dir)
    views = described.get("views") or []
    status = READY if all(v["available"] for v in views) and not described.get("warnings") else PARTIAL
    if active:
        status = PENDING
    return RunResults(status, "", data_dir=Path(described["data_dir"]), contract_dir=example_dir,
                      params=params if params.is_file() else None, views=views,
                      run=described.get("run") or {}, warnings=described.get("warnings") or [],
                      not_reproduced=described.get("not_reproduced") or [],
                      notebook=described.get("notebook") or "")


def render(results: RunResults, view_id: str, options: dict | None = None) -> RenderOutcome:
    view = results.view(view_id)
    if view is None:
        return RenderOutcome(False, view_id, message="This view is not offered for this run.")
    if not view["available"]:
        return RenderOutcome(False, view_id, title=view["title"], message=view["reason"])
    options = {k: v for k, v in (options or {}).items() if v is not None}
    key = hashlib.sha256(json.dumps([view_id, options, _fingerprint(results.data_dir)],
                                    sort_keys=True, default=str).encode()).hexdigest()[:20]
    run_cache = _cache_dir(results)
    png, out_json = run_cache / f"{key}.png", run_cache / f"{key}.json"
    cached = out_json.is_file() and (png.is_file() or view["kind"] == "table")
    if cached:
        try:
            data = json.loads(out_json.read_text())
        except ValueError:
            data, cached = None, False
    if not cached:
        args = ["--data-dir", str(results.data_dir), "--contract", str(results.contract_dir),
                "--view", view_id, "--options", json.dumps(options), "--png", str(png)]
        if results.params:
            args += ["--params", str(results.params)]
        data = _run_renderer(args, out_json)
    if not data.get("ok"):
        out_json.unlink(missing_ok=True)
        return RenderOutcome(False, view_id, title=view["title"], kind=view["kind"],
                             message=data.get("message") or "the view could not be drawn")
    return RenderOutcome(True, view_id, title=data.get("title", view["title"]),
                         png=Path(data["png"]) if data.get("png") else None, table=data.get("table"),
                         notes=data.get("notes") or [], options=data.get("options") or {},
                         source=data.get("source", ""), kind=view["kind"],
                         supplementary=bool(data.get("supplementary")), cached=cached)


def _cache_dir(results: RunResults) -> Path:
    """``<run>/.icesee-results`` -- the run directory is the data directory's
    nearest ancestor holding the run manifest."""
    from .run_records import MANIFEST_NAME

    for parent in [results.data_dir, *results.data_dir.parents]:
        if (parent / MANIFEST_NAME).is_file():
            return parent / CACHE_DIR
    return results.data_dir / CACHE_DIR
