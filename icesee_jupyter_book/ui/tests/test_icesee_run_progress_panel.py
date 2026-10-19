"""Results-tab DA progress panel (icesee_run_progress.py) and its wiring into
the ICESEE gateway: selecting a run in the Workspace and previewing fetched
Remote outputs both render the run-progress report; values are escaped and
"not reported" is shown instead of a guess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.run_monitor import NOT_REPORTED
from icesee_jupyter_book.ui import icesee_run_progress as panel

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def _run_with_checkpoint(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    ckpt_dir = run / "_modelrun_datasets" / "_checkpoints"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "icesee_ckpt.json").write_text(json.dumps({
        "last_done_k": 2, "nt": 8, "nens": 6, "timestamp": 1_760_000_000.0,
        "crash_message": "<script>alert(1)</script>",
    }))
    for k in range(3):
        (run / "_modelrun_datasets" / f"icesee_enkf_ens_{k:04d}.h5").write_bytes(b"\0")
    return run


def test_panel_renders_checkpoint_and_escapes_values(tmp_path):
    html = panel.run_progress_html(_run_with_checkpoint(tmp_path))
    assert "Data assimilation progress" in html
    assert "3 of 8 steps completed (last_done_k=2)" in html
    assert "_modelrun_datasets/_checkpoints/icesee_ckpt.json" in html
    assert "3 files, steps 0..2" in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert f"Phase timings: {NOT_REPORTED}." in html


def test_panel_for_an_empty_run_reports_nothing(tmp_path):
    html = panel.run_progress_html(tmp_path)
    assert f"No ICESEE checkpoint: {NOT_REPORTED}." in html
    assert f"Phase timings: {NOT_REPORTED}." in html
    assert "ICESEE data directories" not in html


def test_panel_never_raises(monkeypatch, tmp_path):
    def boom(_run_dir):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(panel, "inspect_run_progress", boom)
    html = panel.run_progress_html(tmp_path)
    assert "unavailable: RuntimeError" in html
    assert "secret detail" not in html


def test_gateway_renders_the_panel_for_selected_runs_and_remote_previews():
    src = _GW.read_text()
    assert "from icesee_jupyter_book.ui.icesee_run_progress import run_progress_html" in src
    assert "return run_progress_html(run.workspace_directory)" in src
    assert "display(HTML(run_progress_html(outputs_dir)))" in src


def test_selecting_a_run_renders_its_progress_panel(monkeypatch, tmp_path):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "run-progress-wiring-user")
    monkeypatch.setenv("USER", "run-progress-wiring-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.workspace import user_run_root
    from icesee_jupyter_book.core import run_records as rr

    run_dir = user_run_root(app="icesee") / "progress-check"
    run_dir.mkdir(parents=True, exist_ok=True)
    rr.record_run(
        run_dir=run_dir, run_id="progress-check", name="progress check",
        params={}, example="lorenz96", execution_mode="local",
        backend="local", status="done",
    )

    import icesee_jupyter_book.ui.icesee_gateway as gw

    rendered = []
    monkeypatch.setattr(gw, "run_progress_html",
                        lambda path: rendered.append(Path(path)) or "<div>progress</div>")
    page = gw.build_icesee_ui()

    found = {}

    def walk(w):
        if "icw-runlist" in getattr(w, "_dom_classes", ()):
            found["select"] = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert "select" in found, "run history list not found"
    found["select"].value = "progress-check"   # the only run: selected as soon as the page loads
    assert run_dir.resolve() in rendered
