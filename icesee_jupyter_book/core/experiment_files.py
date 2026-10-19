"""The files of the selected ICESEE experiment, for the launcher's Editor.

Every file of the example directory gets a role:

* ``config``    -- ``params.yaml``: the run configuration. In the launcher it
  is the same state as the form; editing it there and applying updates the
  form, and launching writes it into the run.
* ``input``     -- other text inputs (YAML/JSON/CSV/TXT/EXP). Editable; an
  edited copy is kept as the user's *draft* and staged into Local runs in
  place of the shipped file.
* ``source``    -- model and driver code (``.py``, ``.m``, ``.sh`` ...).
  Read-only: launched runs execute on shared infrastructure, so the launcher
  never runs code typed into a browser.
* ``reference`` -- notebooks and documentation, read-only.

Run outputs (``_modelrun_datasets``, ``results``, ``figures``), caches and
binary data are not experiment files and are not listed.

Drafts live under the user's own workspace
(``<owner-root>/.cryostack/icesee_drafts/<example>/``); the shipped example is
never written. Every path is resolved and checked to stay inside the example
(reads) or the draft directory (writes).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_NAME = "params.yaml"
INPUT_SUFFIXES = {".yaml", ".yml", ".json", ".csv", ".txt", ".exp"}
SOURCE_SUFFIXES = {".py", ".m", ".sh", ".sbatch", ".par", ".jl", ".toml", ".cfg", ".ini"}
REFERENCE_SUFFIXES = {".md", ".ipynb", ".rst"}
SKIP_DIRS = {"_modelrun_datasets", "results", "figures", "__pycache__", ".ipynb_checkpoints", "_remote_fetch"}
MAX_EDIT_BYTES = 512 * 1024
MAX_VIEW_BYTES = 2 * 1024 * 1024
KNOWN_FILTERS = ("EnKF", "DEnKF", "EnTKF", "EnRSKF")
PARALLEL_FLAGS = ("serial", "mpi", "mpi_model")
READONLY_REASONS = {
    "source": "Model code is read-only in the launcher: runs execute on shared infrastructure.",
    "reference": "Reference material (notebook or documentation), read-only.",
    "too_large": "Too large to open in the editor.",
    "binary": "Binary file; not shown as text.",
}


class ExperimentFileError(Exception):
    pass


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning" | "info"
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"{self.level.upper()}: {where}{self.message}"


@dataclass(frozen=True)
class ExperimentFile:
    path: str           # relative to the example
    role: str           # config | input | source | reference
    editable: bool
    size: int
    drafted: bool = False
    reason: str = ""


@dataclass
class OpenedFile:
    file: ExperimentFile
    text: str
    origin: str         # "draft" | "example"
    issues: list = field(default_factory=list)


def role_of(rel: str) -> str:
    name = Path(rel).name
    suffix = Path(rel).suffix.lower()
    if name == CONFIG_NAME and "/" not in rel.replace(os.sep, "/"):
        return "config"
    if suffix in INPUT_SUFFIXES:
        return "input"
    if suffix in SOURCE_SUFFIXES:
        return "source"
    if suffix in REFERENCE_SUFFIXES:
        return "reference"
    return ""


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-.") or "example"


class ExperimentFiles:
    """The listing / open / save / reset / validate operations behind the
    Editor for one example and one user."""

    def __init__(self, example_dir: Path | str, drafts_root: Path | str, *, example_key: str = ""):
        self.example_dir = Path(example_dir).resolve()
        self.drafts = (Path(drafts_root) / _slug(example_key or self.example_dir.name)).resolve()

    # ── paths ─────────────────────────────────────────────────────────────
    def _rel(self, rel: str) -> str:
        if not rel or not isinstance(rel, str):
            raise ExperimentFileError("no file selected")
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts or rel.startswith(("~", "/")):
            raise ExperimentFileError(f"{rel}: not a path inside the experiment")
        return str(p)

    def _inside(self, base: Path, rel: str) -> Path:
        target = (base / rel).resolve()
        if not target.is_relative_to(base):
            raise ExperimentFileError(f"{rel}: resolves outside the experiment")
        return target

    def example_path(self, rel: str) -> Path:
        return self._inside(self.example_dir, self._rel(rel))

    def draft_path(self, rel: str) -> Path:
        return self._inside(self.drafts, self._rel(rel))

    # ── listing ───────────────────────────────────────────────────────────
    def files(self) -> list[ExperimentFile]:
        out = []
        if not self.example_dir.is_dir():
            return out
        for path in sorted(self.example_dir.rglob("*")):
            rel_parts = path.relative_to(self.example_dir).parts
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts):
                continue
            if not path.is_file() or path.is_symlink():
                continue
            rel = str(path.relative_to(self.example_dir))
            role = role_of(rel)
            if not role:
                continue
            out.append(self._describe(rel, role, path))
        # drafts of files the example does not ship are never listed (no new files)
        return sorted(out, key=lambda f: ({"config": 0, "input": 1, "source": 2, "reference": 3}[f.role], f.path))

    def _describe(self, rel: str, role: str, path: Path) -> ExperimentFile:
        size = path.stat().st_size
        drafted = (self.drafts / rel).is_file()
        if drafted:
            size = (self.drafts / rel).stat().st_size
        editable = role in ("config", "input") and size <= MAX_EDIT_BYTES
        reason = "" if editable else READONLY_REASONS.get(role, "")
        if role in ("config", "input") and size > MAX_EDIT_BYTES:
            reason = READONLY_REASONS["too_large"]
        return ExperimentFile(path=rel, role=role, editable=editable, size=size, drafted=drafted, reason=reason)

    def describe(self, rel: str) -> ExperimentFile:
        rel = self._rel(rel)
        path = self.example_path(rel)
        role = role_of(rel)
        if not path.is_file() or not role:
            raise ExperimentFileError(f"{rel}: not a file of this experiment")
        return self._describe(rel, role, path)

    # ── open / save / reset ───────────────────────────────────────────────
    def open(self, rel: str) -> OpenedFile:
        info = self.describe(rel)
        draft = self.draft_path(info.path)
        path, origin = (draft, "draft") if draft.is_file() else (self.example_path(info.path), "example")
        size = path.stat().st_size
        if size > MAX_VIEW_BYTES:
            return OpenedFile(file=info, origin=origin, issues=[Issue("info", READONLY_REASONS["too_large"])],
                              text=f"({size / 1e6:.1f} MB — too large to display; download the run files instead)")
        raw = path.read_bytes()
        if info.path.endswith(".ipynb"):
            return OpenedFile(file=info, origin=origin, text=_notebook_as_text(raw))
        if b"\x00" in raw[:8192]:
            return OpenedFile(file=ExperimentFile(**{**info.__dict__, "editable": False,
                                                     "reason": READONLY_REASONS["binary"]}),
                              origin=origin, text="(binary file)")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        return OpenedFile(file=info, origin=origin, text=text)

    def save(self, rel: str, text: str, *, template: dict | None = None) -> list[Issue]:
        """Validate and store ``text`` as the user's draft of ``rel``. Nothing
        is written when validation reports an error. Returns the issues."""
        info = self.describe(rel)
        if not info.editable and info.reason != READONLY_REASONS["too_large"]:
            raise ExperimentFileError(f"{info.path}: {info.reason or 'read-only'}")
        if len(text.encode("utf-8")) > MAX_EDIT_BYTES:
            raise ExperimentFileError(f"{info.path}: larger than {MAX_EDIT_BYTES // 1024} KB; not saved")
        issues = validate(info.path, text, template=template)
        if any(i.level == "error" for i in issues):
            return issues
        target = self.draft_path(info.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
        return issues

    def reset(self, rel: str) -> bool:
        """Discard the draft; the experiment's own file is used again."""
        target = self.draft_path(self._rel(rel))
        if target.is_file():
            target.unlink()
            return True
        return False

    def drafts_in_use(self) -> dict[str, Path]:
        """Edited input files (relative path -> draft), excluding the config,
        which reaches a run through the form."""
        out = {}
        for f in self.files():
            if f.drafted and f.role == "input":
                out[f.path] = self.draft_path(f.path)
        return out

    def config_draft(self) -> dict | None:
        draft = self.drafts / CONFIG_NAME
        if not draft.is_file():
            return None
        try:
            data = yaml.safe_load(draft.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            return None
        return data if isinstance(data, dict) else None


def _notebook_as_text(raw: bytes) -> str:
    try:
        nb = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")
    parts = []
    for i, cell in enumerate(nb.get("cells", [])):
        src = "".join(cell.get("source", []))
        tag = "# %%" if cell.get("cell_type") == "code" else "# %% [markdown]"
        parts.append(f"{tag}  (cell {i})\n{src}")
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# validation
# ─────────────────────────────────────────────────────────────────────────────
def _line_of(text: str, key: str) -> int | None:
    m = re.search(rf"^\s*{re.escape(str(key))}\s*:", text, flags=re.MULTILINE)
    return text[: m.start()].count("\n") + 1 if m else None


def validate(rel: str, text: str, *, template: dict | None = None) -> list[Issue]:
    suffix = Path(rel).suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            return [Issue("error", f"YAML syntax: {problem}", mark.line + 1 if mark else None)]
        if role_of(rel) == "config":
            return validate_params(data, text=text, template=template)
        return []
    if suffix == ".json":
        try:
            json.loads(text)
        except ValueError as exc:
            return [Issue("error", f"JSON syntax: {exc.msg}", getattr(exc, "lineno", None))]
        return []
    if suffix == ".csv":
        rows = list(csv.reader(io.StringIO(text)))
        widths = {len(r) for r in rows if r}
        if len(widths) > 1:
            return [Issue("warning", f"rows have different numbers of columns ({sorted(widths)})")]
    return []


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_params(data, *, text: str = "", template: dict | None = None) -> list[Issue]:
    """Checks of an ICESEE ``params.yaml`` against what ICESEE needs and the
    example's own template (types of the template's keys)."""
    issues: list[Issue] = []
    if not isinstance(data, dict):
        return [Issue("error", "params.yaml must be a mapping of sections")]
    template = template or {}
    for section in template:
        if section not in data:
            issues.append(Issue("error", f"section '{section}' is missing", None))
        elif not isinstance(data[section], dict) and isinstance(template[section], dict):
            issues.append(Issue("error", f"section '{section}' must be a mapping", _line_of(text, section)))
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        tsec = template.get(section) if isinstance(template.get(section), dict) else {}
        for key, value in values.items():
            if key not in tsec:
                if template and tsec:
                    issues.append(Issue("info", f"{section}.{key} is not in the example's template",
                                        _line_of(text, key)))
                continue
            ref = tsec[key]
            line = _line_of(text, key)
            if isinstance(ref, bool):
                if not (isinstance(value, bool) or value in (0, 1)):
                    issues.append(Issue("error", f"{section}.{key} must be true/false", line))
            elif _is_number(ref):
                if not _is_number(value):
                    issues.append(Issue("error", f"{section}.{key} must be a number (got {value!r})", line))
            elif isinstance(ref, list) and not isinstance(value, list):
                issues.append(Issue("warning", f"{section}.{key} is a list in the template", line))

    enkf = data.get("enkf-parameters") if isinstance(data.get("enkf-parameters"), dict) else {}
    modeling = data.get("modeling-parameters") if isinstance(data.get("modeling-parameters"), dict) else {}
    if "Nens" in enkf:
        n = enkf["Nens"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            issues.append(Issue("error", "enkf-parameters.Nens must be a whole number ≥ 1", _line_of(text, "Nens")))
        elif n < 2:
            issues.append(Issue("warning", "an ensemble of 1 member has no spread", _line_of(text, "Nens")))
    if "filter_type" in enkf and enkf["filter_type"] not in KNOWN_FILTERS:
        issues.append(Issue("error", f"filter_type must be one of {', '.join(KNOWN_FILTERS)}",
                            _line_of(text, "filter_type")))
    if "parallel_flag" in enkf and str(enkf["parallel_flag"]).lower() not in PARALLEL_FLAGS:
        issues.append(Issue("warning", "parallel_flag is usually serial, MPI or MPI_model",
                            _line_of(text, "parallel_flag")))
    if _is_number(enkf.get("freq_obs")) and enkf["freq_obs"] <= 0:
        issues.append(Issue("error", "freq_obs must be positive", _line_of(text, "freq_obs")))
    if _is_number(enkf.get("obs_start_time")) and _is_number(enkf.get("obs_max_time")) \
            and enkf["obs_start_time"] > enkf["obs_max_time"]:
        issues.append(Issue("error", "obs_start_time is after obs_max_time", _line_of(text, "obs_start_time")))
    vec = enkf.get("vec_inputs")
    observed = enkf.get("observed_vars")
    if isinstance(vec, list) and isinstance(observed, list):
        unknown = [v for v in observed if v not in vec]
        if unknown:
            issues.append(Issue("error", f"observed_vars not in vec_inputs: {', '.join(map(str, unknown))}",
                                _line_of(text, "observed_vars")))
    if isinstance(vec, list) and _is_number(enkf.get("num_state_vars")):
        expected = int(enkf["num_state_vars"]) + int(enkf.get("num_param_vars") or 0) \
            if _is_number(enkf.get("num_param_vars") or 0) else None
        if expected is not None and expected != len(vec):
            issues.append(Issue("warning", f"vec_inputs has {len(vec)} entries; num_state_vars + num_param_vars = "
                                f"{expected}", _line_of(text, "vec_inputs")))
    for key in ("num_years", "timesteps_per_year", "dt"):
        if _is_number(modeling.get(key)) and modeling[key] <= 0:
            issues.append(Issue("error", f"modeling-parameters.{key} must be positive", _line_of(text, key)))
    return issues


def config_text(config: dict) -> str:
    return yaml.safe_dump(config, sort_keys=False, default_flow_style=None)
