"""ICESEE Workspace: one workspace over the run_records-backed
IceseeRunsManager; selecting a run makes it the shared context (context bar,
Run details, Files, Logs, Results all follow it).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_backs_the_workspace_with_the_icesee_runs_manager():
    src = _GW.read_text()
    assert "IceseeRunsManager(root=_icesee_run_dir_base())" in src
    assert "runs_manager = icesee_runs_manager" in src
    assert "RunWorkspace(_Host())" in src


def _walk(w):
    yield w
    for c in getattr(w, "children", ()) or ():
        yield from _walk(c)


def _with_class(page, cls):
    return [w for w in _walk(page) if cls in getattr(w, "_dom_classes", ())]


def test_workspace_is_mounted_once_with_its_heading(monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "workspace-shell-user")
    monkeypatch.setenv("USER", "workspace-shell-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui

    page = build_icesee_ui()
    ws = _with_class(page, "cryostack-output-workspace")
    assert len(ws) == 1
    assert any("Workspace" in (w.value or "") for w in _walk(ws[0]) if isinstance(w, W.HTML))


def test_selecting_a_run_makes_it_the_shared_context(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "workspace-preview-user")
    monkeypatch.setenv("USER", "workspace-preview-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    root = user_run_root(app="icesee")
    for rid in ("run-a", "run-b"):
        rr.record_run(run_dir=root / rid, run_id=rid, name=rid, params={}, example="Lorenz-96 (fully runnable locally)",
                      execution_mode="local", backend="local", status="completed")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui

    page = build_icesee_ui()
    runs = _with_class(page, "icw-runlist")[0]
    assert {v for _l, v in runs.options} == {"run-a", "run-b"}
    runs.value = "run-a"
    context = [w for w in _walk(page) if isinstance(w, W.HTML)
               and (w.value or "").startswith('<div class="icw-context"')][0]
    assert "run-a" in context.value and "Completed" in context.value
    details = [w for w in _walk(page) if isinstance(w, W.HTML) and "Output directory" in (w.value or "")][0]
    assert str((root / "run-a").resolve()) in details.value
    runs.value = "run-b"
    assert "run-b" in context.value
    assert str((root / "run-b").resolve()) in details.value
