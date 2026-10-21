"""Read-only ICESEE run-progress report: assimilation step, ensemble size,
checkpoints / resume capability and per-phase timings, built ONLY from files
an ICESEE run already writes (or that Remote/Cloud sync copied back) under a
run directory.

What ICESEE actually writes (pinned ``external/ICESEE``, see the sprint
report for line references):

- ``<data_path>/_checkpoints/icesee_ckpt.json`` -- full-parallel driver only
  (``src/run_model_da/icesee_da_full_parallel.py``): ``last_done_k``, ``km``,
  ``nt``, ``nd``, ``nens``, ``timestamp``, ``base_seed`` and, after a crash,
  ``crash_message``.
- ``<data_path>/icesee_enkf_ens_NNNN.h5`` -- the per-step files the
  full-parallel restart logic counts (``src/utils/tools.py``
  ``FNAME_PATTERN``). The I/O class writes ``icesee_enkf_NNNN.h5`` instead;
  those are listed but never counted toward a resume, because ICESEE's own
  resume rule does not count them.
- ``<data_path>/icesee_ensemble_data.h5`` (+ ``ensemble_output_<id>.h5``) --
  the partial-parallel driver's explicit ``resume_from_timestep`` source.
- ``<data_path>/diagnostics/icesee_timing.log`` and stderr -- the
  "Performance Metrics" table (``display_timing_verbose``).
- stdout -- ``[ICESEE] Launching ...``, ``[ICESEE][RESTART] Resuming at
  k=...``, ``Fresh start at k=0 (nt=...)`` and the tqdm
  ``Assimilation progress`` bar.

Rules of this module: nothing is guessed (a value with no source is
reported as :data:`NOT_REPORTED`); every read is size/line bounded; every
path is contained in the run directory (symlinks leaving it are skipped and
listed); nothing is written; no ICESEE code is imported.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path

NOT_REPORTED = "not reported by this run"

#: bounds -- a run directory is user-controlled input
MAX_WALK_DEPTH = 4
MAX_WALK_ENTRIES = 20_000
MAX_CHECKPOINT_BYTES = 64 * 1024
MAX_PARAMS_BYTES = 256 * 1024
MAX_LOG_TAIL_BYTES = 2 * 1024 * 1024
MAX_LOG_LINES = 50_000
MAX_LOG_FILES = 4
MAX_ERROR_LINES = 5
MAX_LISTED_MISSING = 10

CKPT_DIRNAME = "_checkpoints"
CKPT_BASENAME = "icesee_ckpt.json"
TIMING_LOG_NAME = "icesee_timing.log"
ENSEMBLE_HISTORY_NAME = "icesee_ensemble_data.h5"

#: the step files ICESEE's restart logic counts (tools.FNAME_PATTERN)
_RESUME_STEP_RE = re.compile(r"^icesee_enkf_ens_(\d+)\.h5$")
#: the step files EnKF_fully_parallel_IO writes (file_prefix "icesee_enkf")
_IO_STEP_RE = re.compile(r"^icesee_enkf_(\d+)\.h5$")
_MEMBER_RE = re.compile(r"^ensemble_output_(\d+)\.h5$")
_LOG_NAME_RE = re.compile(r"^(run\.log|icesee-enkf-\d+\.out|icesee-enkf-\d+\.err)$")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LAUNCH_RE = re.compile(
    r"\[ICESEE\] Launching (?P<model>\S+) with data assimilation using the "
    r"(?P<filter>\S+) filter across (?P<ranks>\d+) MPI ranks"
)
_RESUME_RE = re.compile(
    r"\[ICESEE\]\[RESTART\] Resuming at k=(?P<k>\d+) \(nt=(?P<nt>\d+)\); km=(?P<km>\d+)"
)
_FRESH_RE = re.compile(r"\[ICESEE\] Fresh start at k=0 \(nt=(?P<nt>\d+)\)")
_PARTIAL_RESUME_RE = re.compile(
    r"\[ICESEE\] Resuming partial run from stored ensemble timestep (?P<k>\d+)"
)
_PROGRESS_RE = re.compile(
    r"Assimilation progress \((?P<ranks>\d+) ranks\):\s*\d+%\|[^|]*\|\s*(?P<n>\d+)/(?P<total>\d+)"
)
_CRASH_CKPT_RE = re.compile(r"\[ICESEE\]\[RESTART\] Checkpoint saved after error")
_ERROR_RE = re.compile(
    r"(\[ICESEE\] An error occurred|\[ICESEE\] Error in \w+ run mode|"
    r"\[ICESEE\]\[(FINALIZE|TIMING)\]|^\w*Error: |MPI_ABORT was invoked)"
)
_TIMING_HEADER_RE = re.compile(r"\[ICESEE\] Performance Metrics \((?P<ranks>\d+) ranks\)")
_TIMING_ROW_RE = re.compile(
    r"^\s*║\s*(?P<label>.+?)\s+(?P<d>\d{2,}):(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\s*║?\s*$"
)

#: the exact row labels of tools.display_timing_verbose, in display order
TIMING_LABELS = (
    "Computational Time (Σ)",
    "Wall-Clock Time (max)",
    "True/Wrong State Time",
    "Ensemble Init Time",
    "Forecast Step Time",
    "Analysis Step Time",
    "Assimilation Time",
    "Init file I/O Time",
    "Forecast File I/O Time",
    "Analysis File I/O Time",
    "Total File I/O Time",
    "Forecast Noise Time",
    "Init Ensemble Mean Computation",
    "Forecast Ensemble Mean Computation",
    "Analysis Ensemble Mean Computation",
)

_DRIVERS = {0: "serial", 1: "partial", 2: "full", 3: "spatial"}

#: execution mode 3 keeps its restart state here (ICESEE mode3_checkpointing)
MODE3_HISTORY = "_mode3_state_history"


# ─────────────────────────────────────────────────────────────────────────────
# data model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FileStat:
    path: str      # relative to the run directory
    size: int
    mtime: float


@dataclass(frozen=True)
class CheckpointInfo:
    file: FileStat
    state: str               # "ok" | "corrupt" | "oversized" | "invalid"
    problem: str = ""
    last_done_k: int | None = None
    km: int | None = None
    nt: int | None = None
    nd: int | None = None
    nens: int | None = None
    timestamp: float | None = None
    crash_message: str = ""


@dataclass(frozen=True)
class StepFile:
    step: int
    file: FileStat


@dataclass(frozen=True)
class DatasetDir:
    """One ICESEE ``data_path`` directory found under the run directory."""

    path: str
    checkpoint: CheckpointInfo | None = None
    resume_steps: tuple = ()        # tuple[StepFile, ...] icesee_enkf_ens_*
    io_steps: tuple = ()            # tuple[StepFile, ...] icesee_enkf_NNNN
    ensemble_history: FileStat | None = None
    ensemble_history_shape: tuple | None = None
    member_files: tuple = ()        # tuple[int, ...] ensemble_output_<id>
    timing_log: FileStat | None = None


@dataclass(frozen=True)
class LogFacts:
    sources: tuple = ()             # tuple[str, ...] relative paths read
    truncated: bool = False
    model: str | None = None
    filter_type: str | None = None
    launch_ranks: int | None = None
    fresh_start_nt: int | None = None
    resumed_k: int | None = None
    resumed_nt: int | None = None
    resumed_km: int | None = None
    partial_resumed_k: int | None = None
    progress_done: int | None = None
    progress_total: int | None = None
    crash_checkpoint_saved: bool = False
    error_lines: tuple = ()


@dataclass(frozen=True)
class PhaseTimings:
    source: str
    reported_ranks: int | None
    phases: tuple                   # tuple[(label, seconds), ...]
    tables_found: int

    def seconds(self, label: str) -> float | None:
        for name, value in self.phases:
            if name == label:
                return value
        return None


@dataclass(frozen=True)
class ResumeAssessment:
    driver: str | None              # "serial" | "partial" | "full" | "spatial" | None
    possible: bool | None           # None = conditional / not determinable
    next_step: int | None
    reason: str
    notes: tuple = ()


@dataclass(frozen=True)
class RunProgressReport:
    run_dir: Path
    dataset_dirs: tuple
    log: LogFacts
    timings: PhaseTimings | None
    resume: ResumeAssessment
    params: dict = field(default_factory=dict)
    skipped: tuple = ()             # paths skipped (outside run dir / bounds)
    walk_truncated: bool = False

    # -- derived facts, each with its own source ------------------------
    def primary_dataset(self) -> DatasetDir | None:
        for d in self.dataset_dirs:
            if d.checkpoint is not None:
                return d
        return self.dataset_dirs[0] if self.dataset_dirs else None

    def assimilation_step(self) -> tuple[str, str]:
        """(value, source) for the current / last assimilation step."""
        primary = self.primary_dataset()
        ckpt = primary.checkpoint if primary else None
        if ckpt and ckpt.state == "ok" and ckpt.last_done_k is not None:
            total = f" of {ckpt.nt}" if ckpt.nt is not None else ""
            done = ckpt.last_done_k + 1
            return (f"{done}{total} steps completed (last_done_k={ckpt.last_done_k})",
                    ckpt.file.path)
        log = self.log
        if log.progress_done is not None:
            return (f"{log.progress_done} of {log.progress_total} steps",
                    "assimilation progress bar in run log")
        if log.resumed_k is not None:
            return (f"resumed at k={log.resumed_k} (nt={log.resumed_nt})", "run log")
        if log.partial_resumed_k is not None:
            return (f"resumed at timestep {log.partial_resumed_k}", "run log")
        if log.fresh_start_nt is not None:
            return (f"started at k=0 (nt={log.fresh_start_nt})", "run log")
        return (NOT_REPORTED, "")

    def ensemble_size(self) -> tuple[str, str]:
        primary = self.primary_dataset()
        ckpt = primary.checkpoint if primary else None
        if ckpt and ckpt.state == "ok" and ckpt.nens is not None:
            return (str(ckpt.nens), ckpt.file.path)
        if primary and primary.ensemble_history_shape and len(primary.ensemble_history_shape) == 3:
            return (str(primary.ensemble_history_shape[1]),
                    f"{primary.ensemble_history.path} (dataset shape)")
        configured = _param(self.params, "Nens")
        if isinstance(configured, int) and not isinstance(configured, bool):
            return (f"{configured} (configured)", "params.yaml")
        return (NOT_REPORTED, "")

    def members_completed(self) -> tuple[str, str]:
        """ICESEE logs no per-member completion; never inferred from files."""
        primary = self.primary_dataset()
        if primary and primary.member_files:
            return (NOT_REPORTED,
                    f"{len(primary.member_files)} member exchange files present "
                    "(presence is not completion)")
        return (NOT_REPORTED, "")

    def checkpoints(self) -> list[CheckpointInfo]:
        return [d.checkpoint for d in self.dataset_dirs if d.checkpoint is not None]

    def summary_rows(self) -> list[tuple[str, str]]:
        step, step_src = self.assimilation_step()
        nens, nens_src = self.ensemble_size()
        members, members_src = self.members_completed()
        driver = self.resume.driver or NOT_REPORTED
        rows = [
            ("Driver", driver),
            ("Assimilation step", _with_source(step, step_src)),
            ("Ensemble size", _with_source(nens, nens_src)),
            ("Members completed", _with_source(members, members_src)),
        ]
        if self.log.model or self.log.filter_type:
            rows.append(("Model / filter", f"{self.log.model or '?'} / {self.log.filter_type or '?'}"))
        if self.log.launch_ranks is not None:
            rows.append(("Ranks (ICESEE-reported)", str(self.log.launch_ranks)))
        possible = {True: "yes", False: "no", None: "conditional"}[self.resume.possible]
        if self.resume.driver is None:
            possible = NOT_REPORTED
        rows.append(("Resume possible", f"{possible} -- {self.resume.reason}"))
        return rows


def _with_source(value: str, source: str) -> str:
    return f"{value} [{source}]" if source else value


# ─────────────────────────────────────────────────────────────────────────────
# bounded, contained filesystem access
# ─────────────────────────────────────────────────────────────────────────────
def _contained(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False


def _stat(root: Path, path: Path) -> FileStat | None:
    try:
        st = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return FileStat(path=str(path.relative_to(root)), size=st.st_size, mtime=st.st_mtime)


def _read_bounded(path: Path, limit: int) -> bytes | None:
    """The whole file if it is at most ``limit`` bytes, else ``None``."""
    try:
        with path.open("rb") as fh:
            data = fh.read(limit + 1)
    except OSError:
        return None
    return None if len(data) > limit else data


def _read_tail(path: Path, limit: int) -> tuple[str, bool]:
    """The last ``limit`` bytes of a text file (and whether it was cut)."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - limit)
            fh.seek(start)
            data = fh.read(limit)
    except OSError:
        return "", False
    text = data.decode("utf-8", errors="replace")
    if start:
        text = text.split("\n", 1)[-1]    # drop the partial first line
    return text, bool(start)


def _walk(root: Path, skipped: list[str]) -> tuple[list[Path], list[Path], bool]:
    """Depth/entry-bounded walk that never follows a symlink out of ``root``.
    Returns (directories, files, truncated)."""
    dirs: list[Path] = [root]
    files: list[Path] = []
    seen = 0
    frontier = [(root, 0)]
    while frontier:
        current, depth = frontier.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > MAX_WALK_ENTRIES:
                return dirs, files, True
            path = Path(entry.path)
            try:
                is_link = entry.is_symlink()
                if is_link and not _contained(root, path):
                    skipped.append(str(path.relative_to(root)))
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 <= MAX_WALK_DEPTH:
                        dirs.append(path)
                        frontier.append((path, depth + 1))
                elif entry.is_file(follow_symlinks=True):
                    files.append(path)
            except OSError:
                continue
    return dirs, files, False


# ─────────────────────────────────────────────────────────────────────────────
# parsers
# ─────────────────────────────────────────────────────────────────────────────
def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_checkpoint(root: Path, path: Path) -> CheckpointInfo | None:
    stat_ = _stat(root, path)
    if stat_ is None:
        return None
    raw = _read_bounded(path, MAX_CHECKPOINT_BYTES)
    if raw is None:
        return CheckpointInfo(file=stat_, state="oversized",
                              problem=f"larger than {MAX_CHECKPOINT_BYTES} bytes; not parsed")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return CheckpointInfo(file=stat_, state="corrupt", problem=f"not valid JSON ({type(exc).__name__})")
    if not isinstance(payload, dict):
        return CheckpointInfo(file=stat_, state="corrupt", problem="not a JSON object")
    last = _as_int(payload.get("last_done_k"))
    if last is None:
        return CheckpointInfo(file=stat_, state="invalid", problem="no integer last_done_k")
    ts = payload.get("timestamp")
    crash = payload.get("crash_message")
    return CheckpointInfo(
        file=stat_, state="ok", last_done_k=last,
        km=_as_int(payload.get("km")), nt=_as_int(payload.get("nt")),
        nd=_as_int(payload.get("nd")), nens=_as_int(payload.get("nens")),
        timestamp=float(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None,
        crash_message=str(crash)[:500] if crash else "",
    )


def parse_timing_text(text: str, source: str) -> PhaseTimings | None:
    """The LAST "Performance Metrics" table in ``text`` (the timing log is
    appended to by every run in the same data_path)."""
    tables: list[tuple[int | None, list[tuple[str, float]]]] = []
    current: list[tuple[str, float]] | None = None
    for raw in text.splitlines()[-MAX_LOG_LINES:]:
        line = _ANSI_RE.sub("", raw)
        header = _TIMING_HEADER_RE.search(line)
        if header:
            current = []
            tables.append((int(header.group("ranks")), current))
            continue
        if current is None:
            continue
        row = _TIMING_ROW_RE.match(line)
        if row and row.group("label").strip() in TIMING_LABELS:
            seconds = (int(row.group("d")) * 86400 + int(row.group("h")) * 3600
                       + int(row.group("m")) * 60 + int(row.group("s"))
                       + int(row.group("ms")) / 1000.0)
            current.append((row.group("label").strip(), seconds))
        elif line.strip().startswith("╚"):
            current = None
    complete = [t for t in tables if t[1]]
    if not complete:
        return None
    ranks, phases = complete[-1]
    return PhaseTimings(source=source, reported_ranks=ranks,
                        phases=tuple(phases), tables_found=len(complete))


def parse_log_text(text: str) -> dict:
    facts: dict = {"error_lines": []}
    # tqdm redraws with carriage returns; each redraw is its own record
    for raw in text.replace("\r", "\n").splitlines()[-MAX_LOG_LINES:]:
        line = _ANSI_RE.sub("", raw)
        m = _LAUNCH_RE.search(line)
        if m:
            facts.update(model=m.group("model"), filter_type=m.group("filter"),
                         launch_ranks=int(m.group("ranks")))
            continue
        m = _RESUME_RE.search(line)
        if m:
            facts.update(resumed_k=int(m.group("k")), resumed_nt=int(m.group("nt")),
                         resumed_km=int(m.group("km")))
            continue
        m = _FRESH_RE.search(line)
        if m:
            facts.update(fresh_start_nt=int(m.group("nt")))
            continue
        m = _PARTIAL_RESUME_RE.search(line)
        if m:
            facts.update(partial_resumed_k=int(m.group("k")))
            continue
        m = _PROGRESS_RE.search(line)
        if m:
            facts.update(progress_done=int(m.group("n")), progress_total=int(m.group("total")))
            continue
        if _CRASH_CKPT_RE.search(line):
            facts["crash_checkpoint_saved"] = True
            continue
        if _ERROR_RE.search(line.strip()):
            facts["error_lines"].append(line.strip()[:300])
    facts["error_lines"] = tuple(facts["error_lines"][-MAX_ERROR_LINES:])
    return facts


def _load_params(root: Path, files: list[Path]) -> dict:
    import yaml

    candidates = [p for p in files if p.name == "params.yaml"]
    candidates.sort(key=lambda p: len(p.relative_to(root).parts))
    for path in candidates[:1]:
        raw = _read_bounded(path, MAX_PARAMS_BYTES)
        if raw is None:
            return {}
        try:
            data = yaml.safe_load(raw.decode("utf-8", errors="replace"))
        except yaml.YAMLError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _param(params: dict, key: str):
    """``key`` from the top level or any section of an ICESEE params.yaml
    (ICESEE flattens every section into one kwargs namespace)."""
    if key in params:
        return params[key]
    for section in params.values():
        if isinstance(section, dict) and key in section:
            return section[key]
    return None


def _h5_shape(path: Path, dataset: str) -> tuple | None:
    """Header-only shape of one dataset; ``None`` if h5py is unavailable or
    the file cannot be opened."""
    try:
        import h5py
    except ImportError:
        return None
    try:
        with h5py.File(path, "r") as f:
            if dataset not in f:
                return None
            return tuple(int(n) for n in f[dataset].shape)
    except Exception:  # noqa: BLE001 - a corrupt file is "not determinable"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# resume rules (mirrors ICESEE's own decision, never a new rule)
# ─────────────────────────────────────────────────────────────────────────────
def _flag(params: dict, key: str, default: bool) -> bool:
    value = _param(params, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return default


def _assess_full(primary: DatasetDir | None, params: dict) -> ResumeAssessment:
    notes = ()
    if not _flag(params, "restart_enabled", True):
        return ResumeAssessment("full", False, None, "restart_enabled is false in params.yaml", notes)
    if _flag(params, "force_fresh_start", False):
        return ResumeAssessment("full", False, None, "force_fresh_start is true in params.yaml", notes)
    if primary is None:
        return ResumeAssessment("full", False, None, "no ICESEE data directory in this run", notes)
    ckpt = primary.checkpoint
    nt = ckpt.nt if ckpt and ckpt.state == "ok" else None
    override = _as_int(_param(params, "k_start_override"))
    if override is not None:
        k_start, basis = override, "k_start_override in params.yaml"
    elif ckpt and ckpt.state == "ok":
        k_start, basis = ckpt.last_done_k + 1, f"checkpoint last_done_k={ckpt.last_done_k}"
    elif ckpt and ckpt.state == "corrupt":
        return ResumeAssessment("full", False, None,
                                f"checkpoint corrupt ({ckpt.problem}); ICESEE's load_checkpoint would fail",
                                notes)
    elif ckpt and ckpt.state == "oversized":
        return ResumeAssessment("full", None, None, f"checkpoint {ckpt.problem}", notes)
    elif primary.resume_steps:
        last = max(s.step for s in primary.resume_steps)
        k_start, basis = last + 1, f"last step file icesee_enkf_ens_{last:04d}.h5"
    else:
        return ResumeAssessment("full", False, 0,
                                "no checkpoint and no icesee_enkf_ens_* step files: ICESEE would start at k=0",
                                notes)
    k_start = max(0, k_start if nt is None else min(k_start, nt))
    if nt is not None and k_start >= nt:
        return ResumeAssessment("full", False, None, f"all {nt} steps completed ({basis}); nothing to resume", notes)
    if k_start == 0:
        return ResumeAssessment("full", False, 0, f"ICESEE would start at k=0 ({basis})", notes)
    if _flag(params, "enforce_contiguous_history", True):
        present = {s.step for s in primary.resume_steps}
        missing = [k for k in range(k_start) if k not in present]
        if missing:
            listed = ", ".join(str(k) for k in missing[:MAX_LISTED_MISSING])
            more = " ..." if len(missing) > MAX_LISTED_MISSING else ""
            return ResumeAssessment(
                "full", False, k_start,
                f"{basis}, but ICESEE requires step files 0..{k_start - 1}; missing {listed}{more}",
                notes,
            )
    return ResumeAssessment("full", True, k_start, f"ICESEE would resume at k={k_start} ({basis})", notes)


def _assess_partial(primary: DatasetDir | None, params: dict) -> ResumeAssessment:
    base = "explicit resume_from_timestep only (requires default_run)"
    if primary is None or primary.ensemble_history is None:
        return ResumeAssessment("partial", False, None, f"{base}; {ENSEMBLE_HISTORY_NAME} not present")
    shape = primary.ensemble_history_shape
    if not shape or len(shape) != 3:
        return ResumeAssessment("partial", None, None,
                                f"{base}; ensemble dataset shape not readable here")
    slices, nens = shape[2], shape[1]
    members = set(primary.member_files)
    zero_based = 0 in members
    expected = set(range(nens)) if zero_based else set(range(1, nens + 1))
    missing = sorted(expected - members)
    if missing:
        listed = ", ".join(str(m) for m in missing[:MAX_LISTED_MISSING])
        return ResumeAssessment("partial", False, None,
                                f"{base}; ensemble_output files missing for members {listed}")
    if slices < 2:
        return ResumeAssessment("partial", False, None, f"{base}; no positive timestep slice stored")
    return ResumeAssessment(
        "partial", None, None,
        f"{base}; slices 1..{slices - 1} are selectable, but the history is "
        "preallocated, so which slices hold completed steps is not recorded "
        "(ICESEE checks finiteness at resume time)",
    )


def _assess_spatial(root: Path | None, primary: DatasetDir | None, params: dict) -> ResumeAssessment:
    """Mode 3 restores the newest complete ``steps/checkpoint_<k>`` and
    continues with cycle ``k + 1`` when resume_from_checkpoint is set."""
    how = "with resume_from_checkpoint: true"
    if root is None or primary is None:
        return ResumeAssessment("spatial", False, None, "no ICESEE data directory in this run")
    steps = []
    for d in (root / primary.path / MODE3_HISTORY / "steps").glob("checkpoint_*"):
        try:
            manifest = json.loads((d / "manifest.json").read_text())
            if manifest.get("complete"):
                steps.append(int(d.name.split("_")[-1]))
        except (OSError, ValueError):
            continue
    if not steps:
        return ResumeAssessment("spatial", False, 0, f"no complete {MODE3_HISTORY} step checkpoint: "
                                "ICESEE would start at step 0")
    k = max(steps) + 1
    truth = _h5_shape(root / primary.path / "true_nurged_states.h5", "true_state")
    nt = truth[1] - 1 if truth and len(truth) == 2 else _as_int(_param(params, "nt"))
    if nt is not None and k >= nt:
        return ResumeAssessment("spatial", False, None, f"all {nt} steps completed; nothing to resume")
    return ResumeAssessment("spatial", True, k, f"ICESEE would resume at step {k} {how} "
                            f"(newest checkpoint_{k - 1:08d})")


def assess_resume(primary: DatasetDir | None, params: dict, root: Path | None = None) -> ResumeAssessment:
    mode = _as_int(_param(params, "execution_mode"))
    driver = _DRIVERS.get(mode) if mode is not None else None
    if driver is None and params:
        driver = "partial"      # ICESEE's own default (_utility_imports: execution_mode=1)
    if driver is None and primary is not None and primary.checkpoint is not None:
        driver = "full"         # only the full-parallel driver writes icesee_ckpt.json
    if driver == "serial":
        return ResumeAssessment("serial", False, None, "ICESEE's serial driver has no restart support")
    if driver == "full":
        return _assess_full(primary, params)
    if driver == "partial":
        return _assess_partial(primary, params)
    if driver == "spatial":
        return _assess_spatial(root, primary, params)
    return ResumeAssessment(None, None, None, "driver not determinable (no params.yaml or checkpoint)")


# ─────────────────────────────────────────────────────────────────────────────
# entry point
# ─────────────────────────────────────────────────────────────────────────────
def _dataset_dir(root: Path, directory: Path, files_here: list[Path], ckpt_file: Path | None,
                 timing_file: Path | None) -> DatasetDir:
    resume_steps, io_steps, members = [], [], []
    history = None
    for path in files_here:
        name = path.name
        m = _RESUME_STEP_RE.match(name)
        if m:
            st = _stat(root, path)
            if st:
                resume_steps.append(StepFile(int(m.group(1)), st))
            continue
        m = _IO_STEP_RE.match(name)
        if m:
            st = _stat(root, path)
            if st:
                io_steps.append(StepFile(int(m.group(1)), st))
            continue
        m = _MEMBER_RE.match(name)
        if m:
            members.append(int(m.group(1)))
            continue
        if name == ENSEMBLE_HISTORY_NAME:
            history = path
    history_stat = _stat(root, history) if history else None
    return DatasetDir(
        path=str(directory.relative_to(root)) or ".",
        checkpoint=parse_checkpoint(root, ckpt_file) if ckpt_file else None,
        resume_steps=tuple(sorted(resume_steps, key=lambda s: s.step)),
        io_steps=tuple(sorted(io_steps, key=lambda s: s.step)),
        ensemble_history=history_stat,
        ensemble_history_shape=_h5_shape(history, "ensemble") if history_stat else None,
        member_files=tuple(sorted(members)),
        timing_log=_stat(root, timing_file) if timing_file else None,
    )


def inspect_run_progress(run_dir: "Path | str") -> RunProgressReport:
    """Build a :class:`RunProgressReport` from what is ACTUALLY under
    ``run_dir`` (a local run, a Remote fetch, or a Cloud sync target)."""
    root = Path(run_dir).resolve()
    skipped: list[str] = []
    if not root.is_dir():
        return RunProgressReport(
            run_dir=root, dataset_dirs=(), log=LogFacts(), timings=None,
            resume=ResumeAssessment(None, None, None, "run directory not found"),
        )
    _dirs, files, truncated = _walk(root, skipped)

    by_dir: dict[Path, list[Path]] = {}
    for path in files:
        by_dir.setdefault(path.parent, []).append(path)

    dataset_dirs = []
    for directory, here in sorted(by_dir.items()):
        if directory.name in (CKPT_DIRNAME, "diagnostics"):
            continue
        ckpt = directory / CKPT_DIRNAME / CKPT_BASENAME
        timing = directory / "diagnostics" / TIMING_LOG_NAME
        ckpt_file = ckpt if ckpt in by_dir.get(ckpt.parent, ()) else None
        timing_file = timing if timing in by_dir.get(timing.parent, ()) else None
        names = {p.name for p in here}
        icesee_like = (
            ckpt_file or timing_file or ENSEMBLE_HISTORY_NAME in names
            or any(_RESUME_STEP_RE.match(n) or _IO_STEP_RE.match(n) for n in names)
            or (directory / MODE3_HISTORY).is_dir()
        )
        if icesee_like:
            dataset_dirs.append(_dataset_dir(root, directory, here, ckpt_file, timing_file))
    # a data dir holding only _checkpoints/ or diagnostics/ has no own files
    known = {root / d.path for d in dataset_dirs}
    for directory in sorted({p.parent.parent for p in files if p.parent.name in (CKPT_DIRNAME, "diagnostics")}):
        if directory in known:
            continue
        ckpt = directory / CKPT_DIRNAME / CKPT_BASENAME
        timing = directory / "diagnostics" / TIMING_LOG_NAME
        ckpt_file = ckpt if ckpt in by_dir.get(ckpt.parent, ()) else None
        timing_file = timing if timing in by_dir.get(timing.parent, ()) else None
        if ckpt_file or timing_file:
            dataset_dirs.append(_dataset_dir(root, directory, by_dir.get(directory, []), ckpt_file, timing_file))

    # logs: the local run.log and any synced Slurm output, shallowest first
    logs = sorted((p for p in files if _LOG_NAME_RE.match(p.name)),
                  key=lambda p: (len(p.relative_to(root).parts), p.name))[:MAX_LOG_FILES]
    facts: dict = {"error_lines": ()}
    sources, log_cut, timings = [], False, None
    for path in logs:
        text, cut = _read_tail(path, MAX_LOG_TAIL_BYTES)
        sources.append(str(path.relative_to(root)))
        log_cut = log_cut or cut
        parsed = parse_log_text(text)
        errors = facts["error_lines"] + parsed.pop("error_lines")
        facts.update({k: v for k, v in parsed.items() if v is not None})
        facts["error_lines"] = errors[-MAX_ERROR_LINES:]
        timings = parse_timing_text(text, sources[-1]) or timings
    log = LogFacts(sources=tuple(sources), truncated=log_cut, **facts)

    # the run's own log is per-run; diagnostics/icesee_timing.log is appended
    # to by every run sharing a data_path, so it is only the fallback
    if timings is None:
        for d in dataset_dirs:
            if d.timing_log is not None:
                text, _cut = _read_tail(root / d.timing_log.path, MAX_LOG_TAIL_BYTES)
                timings = parse_timing_text(text, d.timing_log.path)
                if timings is not None:
                    break

    params = _load_params(root, files)
    report = RunProgressReport(
        run_dir=root, dataset_dirs=tuple(dataset_dirs), log=log, timings=timings,
        resume=ResumeAssessment(None, None, None, ""), params=params,
        skipped=tuple(skipped), walk_truncated=truncated,
    )
    return replace(report, resume=assess_resume(report.primary_dataset(), params, root))
