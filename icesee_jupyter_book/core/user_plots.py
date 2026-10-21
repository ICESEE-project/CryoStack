"""A user's own copy of an ICESEE example's plotting code.

The Results view draws figures with ICESEE's post-processing views
(``ICESEE/src/postprocessing/views``) as listed by the example's
``results.yaml``. A user who wants different figures copies that code into
their workspace::

    <owner-root>/.cryostack/icesee_plots/<example>/
        results.yaml        which views the Results tab offers
        <model>.py          the example's view module (copy, editable)
        common.py           the shared data-assimilation views (copy, editable)
        README.md

and edits it in the launcher's Editor. A view the copy registers under an
existing id replaces ICESEE's; a new id is a new view once it is listed in
``results.yaml``.

The copy is the user's: the shipped ICESEE code and the example are never
written. It is executed only by :mod:`results_service` inside a sandbox in
which the run's outputs are read-only and the only writable directory is
the user's figure cache, so plotting code can never change a dataset.
Here it is only copied, listed, saved and syntax-checked (``compile``, which
does not execute it).
"""
from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .experiment_files import Issue
from .paths import REPO

VIEWS_DIR = REPO / "external" / "ICESEE" / "src" / "postprocessing" / "views"
CONTRACT = "results.yaml"
README = "README.md"
MAX_BYTES = 256 * 1024
#: copies import ICESEE's post-processing by absolute name (they no longer sit in its package)
_RELATIVE = ((re.compile(r"^from \.\. import ", re.M), "from ICESEE.src.postprocessing import "),
             (re.compile(r"^from \.\.(\w)", re.M), r"from ICESEE.src.postprocessing.\1"),
             (re.compile(r"^from \. import ", re.M), "from ICESEE.src.postprocessing.views import "),
             (re.compile(r"^from \.(\w)", re.M), r"from ICESEE.src.postprocessing.views.\1"))
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}\.(py|yaml|md)$")
_README = """# My plotting code

Your own copy of the plotting code of the **{example}** example. The Results
tab draws your figures from these files when *My plotting code* is selected.

- `results.yaml` lists the views the Results tab offers, in order.
- `{model}.py` and `common.py` are copies of ICESEE's views. Edit a view's
  `build` function to change its figure; `register(ViewSpec(id="my.view", ...))`
  adds a new one (then list `my.view` in `results.yaml`).
- Your code reads the run's outputs; it cannot change them. Figures are kept
  apart from ICESEE's, per run.
- *Reset to ICESEE* in the Editor restores one file; deleting the copy in the
  Results tab removes all of them.
"""


class PlotFileError(Exception):
    pass


@dataclass(frozen=True)
class PlotFile:
    path: str
    kind: str           # "contract" | "views" | "readme"
    size: int
    modified: bool      # differs from the ICESEE original


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-.") or "example"


def absolute_imports(source: str) -> str:
    for pattern, repl in _RELATIVE:
        source = pattern.sub(repl, source)
    return source


class PlotWorkspace:
    """One user's plotting code for one example."""

    def __init__(self, plots_root: Path | str, example_key: str, contract_dir: Path | str):
        self.example_key = example_key
        self.contract_dir = Path(contract_dir)
        self.root = (Path(plots_root) / _slug(example_key)).resolve()

    # ── what the example uses ─────────────────────────────────────────────
    def _contract(self) -> dict:
        path = self.contract_dir / CONTRACT
        if not path.is_file():
            raise PlotFileError("This example declares no result views (no results.yaml).")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PlotFileError("The example's results.yaml is not a mapping.")
        return data

    @property
    def main_module(self) -> str:
        """The example's own view module (``<model>.py``), the one to open first."""
        try:
            model = str(self._contract().get("model_name") or "").strip()
        except PlotFileError:
            return ""
        return f"{model}.py" if model and (VIEWS_DIR / f"{model}.py").is_file() else ""

    def originals(self) -> dict[str, str]:
        """``{file name: ICESEE original text}`` of every file a copy holds."""
        data = self._contract()
        model = str(data.get("model_name") or "").strip()
        files = {CONTRACT: (self.contract_dir / CONTRACT).read_text(encoding="utf-8")}
        for stem in dict.fromkeys([model, "common"]):
            src = VIEWS_DIR / f"{stem}.py"
            if stem and src.is_file():
                files[src.name] = absolute_imports(src.read_text(encoding="utf-8"))
        files[README] = _README.format(example=self.example_key, model=model or "model")
        return files

    # ── the copy ──────────────────────────────────────────────────────────
    @property
    def exists(self) -> bool:
        return (self.root / CONTRACT).is_file()

    def create(self) -> list[PlotFile]:
        if self.exists:
            return self.files()
        originals = self.originals()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, text in originals.items():
            self._write(name, text)
        return self.files()

    def delete(self) -> None:
        if self.root.is_dir():
            shutil.rmtree(self.root)

    def files(self) -> list[PlotFile]:
        if not self.exists:
            return []
        originals = self.originals()
        out = []
        main = self.main_module
        for p in sorted(self.root.iterdir(), key=lambda p: (p.name != CONTRACT, p.name != main, p.suffix != ".py", p.name)):
            if not p.is_file() or not _NAME.match(p.name):
                continue
            kind = "contract" if p.name == CONTRACT else ("views" if p.suffix == ".py" else "readme")
            text = p.read_text(encoding="utf-8", errors="replace")
            out.append(PlotFile(p.name, kind, p.stat().st_size, originals.get(p.name) != text))
        return out

    def _path(self, name: str) -> Path:
        if not isinstance(name, str) or not _NAME.match(name):
            raise PlotFileError(f"{name!r}: plotting files are .py, .yaml or .md files directly in your copy")
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise PlotFileError(f"{name}: not inside your plotting copy")
        return path

    def open(self, name: str) -> str:
        path = self._path(name)
        if not path.is_file():
            raise PlotFileError(f"{name}: no such file in your plotting copy")
        return path.read_text(encoding="utf-8", errors="replace")

    def save(self, name: str, text: str) -> list[Issue]:
        if not self.exists:
            raise PlotFileError("Copy the plotting code to your workspace first.")
        issues = validate(name, text)
        if any(i.level == "error" for i in issues):
            return issues
        self._write(name, text)
        return issues

    def reset(self, name: str) -> None:
        original = self.originals().get(name)
        if original is None:
            self._path(name).unlink(missing_ok=True)
        else:
            self._write(name, original)

    def _write(self, name: str, text: str) -> None:
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise PlotFileError(f"{name}: larger than {MAX_BYTES // 1024} KB")
        path = self._path(name)
        tmp = path.with_name(f".{path.name}.part")
        tmp.write_text(text, encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)

    def fingerprint(self) -> str:
        """Changes whenever any plotting file changes (keys the figure cache)."""
        h = hashlib.sha256()
        for p in sorted(self.root.glob("*")):
            if p.is_file() and p.suffix in (".py", ".yaml"):
                h.update(p.name.encode())
                h.update(p.read_bytes())
        return h.hexdigest()[:16]


def validate(name: str, text: str) -> list[Issue]:
    """Syntax only -- nothing is executed here."""
    issues: list[Issue] = []
    if name.endswith(".py"):
        try:
            compile(text, name, "exec", dont_inherit=True)
        except SyntaxError as exc:
            issues.append(Issue("error", f"SyntaxError: {exc.msg}", exc.lineno))
    elif name.endswith(".yaml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            return [Issue("error", f"not valid YAML: {getattr(exc, 'problem', exc)}",
                          mark.line + 1 if mark else None)]
        if name == CONTRACT:
            if not isinstance(data, dict):
                return [Issue("error", "results.yaml must be a mapping")]
            views = data.get("views")
            if not isinstance(views, list) or not all(isinstance(v, str) for v in views):
                issues.append(Issue("error", "views must be a list of view ids"))
            elif not views:
                issues.append(Issue("warning", "no views listed: the Results tab will have nothing to draw"))
            if not str(data.get("model_name") or "").strip():
                issues.append(Issue("error", "model_name is required"))
    return issues
