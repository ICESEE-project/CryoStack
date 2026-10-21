"""Results of a selected ICESEE run, for the launcher's Results view.

Finds the run's outputs and its example's results contract, asks ICESEE's
post-processing which views the run supports, and draws them. Loading and
drawing happen in a separate process (``python -m
ICESEE.src.postprocessing.render``) with a time and memory limit, so a large
ensemble or a damaged file can never stall or crash the user's session, and
the figure code is exactly the code the example notebooks run. Drawn figures
are cached in the run directory, keyed by the view, its options and the
output files' timestamps.

A user's own plotting code (:mod:`user_plots`) is drawn the same way, but
only inside a bubblewrap sandbox: no network, the run's outputs and the
code read-only, and the user's figure cache
(``<run>/.icesee-results/user/<fingerprint>``) the only writable directory.
Without bubblewrap the user's code is not run at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .example_registry import EXAMPLES
from .paths import REPO

CACHE_DIR = ".icesee-results"
USER_CACHE = "user"
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
    plots: object = None        # user_plots.PlotWorkspace when drawn from the user's own code

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
    customized: bool = False
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


class SandboxUnavailable(RuntimeError):
    pass


def sandbox_available() -> bool:
    return bool(shutil.which("bwrap"))


def _sandboxed(argv: list[str], *, read_only: list[Path], writable: list[Path]) -> tuple[list[str], dict]:
    """``argv`` inside bubblewrap: the system and Python read-only, ICESEE's
    post-processing read-only, ``read_only`` (outputs, user code) read-only,
    only ``writable`` writable, no network, nothing else of the host."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable("bubblewrap (bwrap) is not installed on this server, so your own "
                                 "plotting code cannot be run safely here")
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc"]
    for link in ("bin", "lib", "lib64", "sbin"):
        target = Path("/") / link
        if target.is_symlink():
            args += ["--symlink", os.readlink(target), str(target)]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run"]
    if Path("/etc/cryostack").exists():
        args += ["--tmpfs", "/etc/cryostack"]
    prefixes = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    for prefix in sorted(prefixes):
        args += ["--ro-bind", str(prefix), str(prefix)]
    args += ["--ro-bind", str(_EXTERNAL), str(_EXTERNAL)]
    for path in read_only:
        args += ["--ro-bind", str(path), str(path)]
    for path in writable:
        path.mkdir(parents=True, exist_ok=True)
        args += ["--bind", str(path), str(path)]
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_EXTERNAL), "MPLBACKEND": "Agg",
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp",
           "MPLCONFIGDIR": "/tmp/matplotlib", "LANG": "C.UTF-8", "TMPDIR": "/tmp"}
    return [*args, "--chdir", str(_EXTERNAL), "--", *argv], env


def _run_renderer(args: list[str], out_json: Path, timeout: int = RENDER_TIMEOUT_S, *,
                  sandbox: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env["PYTHONPATH"] = f"{_EXTERNAL}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["MPLBACKEND"] = "Agg"
    env["PYTHONNOUSERSITE"] = "1"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.unlink(missing_ok=True)
    argv = [sys.executable, "-m", "ICESEE.src.postprocessing.render", *args, "--json", str(out_json)]
    if sandbox is not None:
        try:
            argv, env = _sandboxed(argv, read_only=sandbox["read_only"],
                                   writable=[out_json.parent, *sandbox.get("writable", [])])
        except SandboxUnavailable as exc:
            return {"ok": False, "kind": "sandbox", "message": str(exc)}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
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


def example_dir(run) -> Path | None:
    """The directory holding the results contract the run's views come from."""
    return _example_dir(run) if run is not None and run.workspace_directory else None


def user_cache_dir(run_dir: Path, plots) -> Path:
    return Path(run_dir) / CACHE_DIR / USER_CACHE / plots.fingerprint()


def discover(run, *, lifecycle_state: str | None = None, plots=None) -> RunResults:
    """What the Results view can show for ``run`` (a RunInfo). The example's
    contract is read and the outputs are found by ICESEE's post-processing
    in a child process (the launcher's own ICESEE checkout). With ``plots``
    (a user_plots.PlotWorkspace holding a copy) the user's contract and view
    modules are used instead, in the sandbox."""
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
    sandbox = None
    contract_dir = example_dir
    if plots is not None:
        contract_dir = plots.root
        out_json = user_cache_dir(run_dir, plots) / f"describe-{_run_fingerprint(run_dir)}.json"
        sandbox = {"read_only": [run_dir, plots.root]}
        extra = ["--user-views", str(plots.root)]
    else:
        out_json = run_dir / CACHE_DIR / f"describe-{_run_fingerprint(run_dir)}.json"
        extra = []
    described = None
    if out_json.is_file():
        try:
            described = json.loads(out_json.read_text())
        except ValueError:
            described = None
    if described is None:
        described = _run_renderer(["--run-dir", str(run_dir), "--contract", str(contract_dir),
                                   *(["--params", str(params)] if params.is_file() else []), *extra,
                                   "--describe"],
                                  out_json, timeout=120, sandbox=sandbox)
    active = lifecycle_state in ("preparing", "submitted", "queued", "running")
    if not described.get("ok"):
        out_json.unlink(missing_ok=True)
        kind, msg = described.get("kind"), described.get("message", "")
        if kind in ("user_code", "sandbox"):
            return RunResults(ERROR, msg, contract_dir=contract_dir, plots=plots)
        if kind == "unsupported":
            return RunResults(UNSUPPORTED, msg, contract_dir=contract_dir, plots=plots)
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
    if plots is not None and not _inside(described.get("data_dir"), run_dir):
        # the description came from the user's code: it may only name this run's outputs
        out_json.unlink(missing_ok=True)
        return RunResults(ERROR, "Your plotting code reported outputs outside this run.",
                          contract_dir=contract_dir, plots=plots)
    status = READY if all(v["available"] for v in views) and not described.get("warnings") else PARTIAL
    if active:
        status = PENDING
    return RunResults(status, "", data_dir=Path(described["data_dir"]), contract_dir=contract_dir,
                      params=params if params.is_file() else None, views=views,
                      run=described.get("run") or {}, warnings=described.get("warnings") or [],
                      not_reproduced=described.get("not_reproduced") or [],
                      notebook=described.get("notebook") or "", plots=plots)


def render(results: RunResults, view_id: str, options: dict | None = None) -> RenderOutcome:
    view = results.view(view_id)
    if view is None:
        return RenderOutcome(False, view_id, message="This view is not offered for this run.")
    if not view["available"]:
        return RenderOutcome(False, view_id, title=view["title"], message=view["reason"])
    options = {k: v for k, v in (options or {}).items() if v is not None}
    plots = results.plots
    key = hashlib.sha256(json.dumps([view_id, options, _fingerprint(results.data_dir),
                                     plots.fingerprint() if plots is not None else ""],
                                    sort_keys=True, default=str).encode()).hexdigest()[:20]
    run_cache = _cache_dir(results)
    sandbox = None
    if plots is not None:
        run_cache = run_cache / USER_CACHE / plots.fingerprint()
        read_only = [results.data_dir, plots.root] + ([results.params] if results.params else [])
        sandbox = {"read_only": read_only}
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
        if plots is not None:
            args += ["--user-views", str(plots.root)]
        data = _run_renderer(args, out_json, sandbox=sandbox)
    if data.get("ok") and data.get("png") and not (_inside(data["png"], run_cache) and not Path(data["png"]).is_symlink()):
        data = {"ok": False, "message": "the figure was not written where it was asked to be"}
    if not data.get("ok"):
        out_json.unlink(missing_ok=True)
        return RenderOutcome(False, view_id, title=view["title"], kind=view["kind"],
                             message=data.get("message") or "the view could not be drawn")
    return RenderOutcome(True, view_id, title=data.get("title", view["title"]),
                         png=Path(data["png"]) if data.get("png") else None, table=data.get("table"),
                         notes=data.get("notes") or [], options=data.get("options") or {},
                         source=data.get("source", ""), kind=view["kind"],
                         supplementary=bool(data.get("supplementary")),
                         customized=bool(data.get("customized")), cached=cached)


def _inside(path, root: Path) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _cache_dir(results: RunResults) -> Path:
    """``<run>/.icesee-results`` -- the run directory is the data directory's
    nearest ancestor holding the run manifest."""
    from .run_records import MANIFEST_NAME

    for parent in [results.data_dir, *results.data_dir.parents]:
        if (parent / MANIFEST_NAME).is_file():
            return parent / CACHE_DIR
    return results.data_dir / CACHE_DIR
