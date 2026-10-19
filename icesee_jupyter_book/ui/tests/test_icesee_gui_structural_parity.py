"""Application-shell structure of CryoLauncher and ICESEE.

CryoLauncher keeps its shell (header -> two columns -> LEFT[Run settings
(Run Plan last) + Execution] / RIGHT[one Workspace: Runs/Files/Run Log/
Results]) built from the shared primitives in
cryostack_src/frontend/cryolauncher.

ICESEE has its own production workflow shell (ui/icesee_workflow): LEFT
[Mode, Experiment, Environment & resources, Scientific parameters, Review &
launch] / RIGHT[one Workspace: Run/Files/Editor/Logs/Results following the
selected run]. Both are checked here by widget-hierarchy inspection (class
names, titles, object identity).
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# tree-walking helpers
# ---------------------------------------------------------------------------
def _walk(root):
    yield root
    for child in getattr(root, "children", ()) or ():
        yield from _walk(child)


def _widgets_with_class(root, css_class):
    return [w for w in _walk(root) if css_class in (getattr(w, "_dom_classes", ()) or ())]


def _html_values(root):
    return [w.value or "" for w in _walk(root) if isinstance(w, W.HTML)]


def _count_instances(root, target):
    return sum(1 for w in _walk(root) if w is target)


def _find_run_details_tabs(root):
    """The single Workspace's 4-tab W.Tab (cryostack-workspace-tabs class,
    set by build_run_details -- unambiguous, unlike a bare W.Tab check)."""
    matches = [w for w in _walk(root) if isinstance(w, W.Tab)
               and "cryostack-workspace-tabs" in (getattr(w, "_dom_classes", ()) or ())]
    return matches


def _find_left_column(root):
    matches = _widgets_with_class(root, "icesee-left")
    return matches[0] if matches else None


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _build_icesee(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _build_cryolauncher(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    return build_icesheets_ui()


# ---------------------------------------------------------------------------
# 1. exactly one Workspace, in both applications
# ---------------------------------------------------------------------------
def test_icesee_exposes_exactly_one_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-workspace-count")
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1, f"expected exactly one Workspace, found {len(workspaces)}"


def test_cryolauncher_exposes_exactly_one_workspace(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-cl-workspace-count")
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1, f"expected exactly one Workspace, found {len(workspaces)}"


# ---------------------------------------------------------------------------
# 2. Runs / Files / Run Log / Results, same order, both applications
# ---------------------------------------------------------------------------
def _icesee_workspace_tabs(page):
    bars = _widgets_with_class(page, "icw-tabs")
    assert len(bars) == 1, f"expected one ICESEE workspace tab bar, found {len(bars)}"
    return bars[0].children[0]


def test_icesee_workspace_tabs_are_run_files_editor_logs_results_in_order(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-tabs-icesee")
    tabs = _icesee_workspace_tabs(page)
    assert list(tabs.options) == ["Run", "Files", "Editor", "Logs", "Results"]


def test_cryolauncher_workspace_tabs_are_runs_files_run_log_results_in_order(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-tabs-cl")
    tabs = _find_run_details_tabs(page)
    assert len(tabs) == 1
    tab = tabs[0]
    assert len(tab.children) == 4
    titles = [tab.get_title(i) for i in range(4)]
    assert titles == ["Runs", "Files", "Run Log", "Results"]


# ---------------------------------------------------------------------------
# 3-4. no duplicate standalone Run Log / Results Preview boxes in ICESEE
# ---------------------------------------------------------------------------
def test_icesee_has_no_duplicate_standalone_run_log_heading(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-dup-log")
    values = _html_values(page)
    # the old ICESEE-only heading; the shared Workspace uses a Tab TITLE
    # ("Run log"), not a standalone <div class='icesee-h'>Run log</div> HTML
    # widget outside the Workspace tab system
    assert not any(v.strip() == "<div class='icesee-h'>Run log</div>" for v in values)


def test_icesee_has_no_duplicate_standalone_results_preview_heading(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-dup-results")
    values = _html_values(page)
    assert not any("Results preview" in v for v in values)


def test_icesee_log_out_and_results_out_widgets_appear_exactly_once(monkeypatch, tmp_path):
    """log_out (launcher activity) and results_out (remote fetch / cloud
    sync messages) are each mounted once, inside the single Workspace."""
    page = _build_icesee(monkeypatch, tmp_path, user="parity-single-mount")
    workspace = _widgets_with_class(page, "cryostack-output-workspace")[0]
    assert len(_widgets_with_class(workspace, "icesee-out")) == 2
    all_icesee_out = _widgets_with_class(page, "icesee-out")
    assert len(all_icesee_out) == 2, "log_out/results_out must not be mounted twice"


# ---------------------------------------------------------------------------
# 5. no second Workspace at the bottom of the page (same as #1, stated
#    against the page's top-level children rather than a global class scan)
# ---------------------------------------------------------------------------
def test_icesee_page_top_level_children_contain_no_second_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-bottom-ws")
    # every former standalone/bottom presentation (workspace_box Accordion,
    # actions_card, a second Run Plan mount) is gone from the page's own
    # direct children -- the shell is exactly [styles.., app_menu, header,
    # shell.container, shell.height_sync, back_link]
    accordions_at_top_level = [c for c in page.children if isinstance(c, W.Accordion)]
    assert accordions_at_top_level == []


# ---------------------------------------------------------------------------
# 6. Run Settings / Run Plan / Execution occupy the same shell positions
# ---------------------------------------------------------------------------
def _left_column_headings(page):
    left = _find_left_column(page)
    assert left is not None, "no 'icesee-left' column found (build_workspace_explorer not used?)"
    assert len(left.children) == 2, "LEFT column must be exactly [run_settings, runtime]"
    run_settings, runtime = left.children
    return run_settings, runtime


def test_icesee_left_column_is_mode_first_then_the_workflow(monkeypatch, tmp_path):
    """Mode is the first decision -- before the experiment, the environment,
    the parameters and Review & launch (never buried in run settings)."""
    page = _build_icesee(monkeypatch, tmp_path, user="parity-left-icesee")
    left = _widgets_with_class(page, "icw-col")[0]
    cards = [c for c in left.children if "icw-card" in c._dom_classes]
    titles = []
    for c in cards:
        heads = [v for v in _html_values(c) if "icw-card-title" in v]
        titles.append(heads[0] if heads else "")
    order = ["Mode", "Experiment", "Environment &amp; resources", "Scientific parameters", "Review &amp; launch"]
    assert [next((o for o in order if o in t), "?") for t in titles] == order


def test_cryolauncher_left_column_is_run_settings_then_execution(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-left-cl")
    run_settings, runtime = _left_column_headings(page)

    settings_html = "\n".join(_html_values(run_settings))
    assert "Run settings" in settings_html
    assert "Run Plan" in settings_html

    runtime_html = "\n".join(_html_values(runtime))
    assert "Execution" in runtime_html


def test_icesee_has_no_separate_status_card_outside_execution(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-status-card")
    values = _html_values(page)
    assert not any(v.strip() == "<div class='icesee-h'>Status</div>" for v in values)


# ---------------------------------------------------------------------------
# 7. switching ICESEE scientific controls does not reconstruct the Workspace
# ---------------------------------------------------------------------------
def test_switching_icesee_scientific_controls_does_not_reconstruct_the_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="parity-no-rebuild")
    tabs_before = _icesee_workspace_tabs(page)
    workspace_before = _widgets_with_class(page, "cryostack-output-workspace")[0]
    mode = next(w for w in _walk(page) if isinstance(w, W.ToggleButtons) and "Cloud" in w._options_labels)
    for value in ("cluster", "cloud", "local"):
        mode.value = value
    assert _icesee_workspace_tabs(page) is tabs_before
    assert _widgets_with_class(page, "cryostack-output-workspace")[0] is workspace_before
    assert list(tabs_before.options) == ["Run", "Files", "Editor", "Logs", "Results"]


# ---------------------------------------------------------------------------
# 8. ICESEE Results still uses its DA-aware ResultPackage
# ---------------------------------------------------------------------------
def test_icesee_results_use_icesee_postprocessing_not_the_glaciological_package():
    """ICESEE Results come from ICESEE's own post-processing (the example's
    results contract and read_results views), never from
    cryostack_src/models/*/results.py's single-model ResultPackage."""
    ws = (_REPO / "icesee_jupyter_book/ui/icesee_workflow/workspace.py").read_text()
    svc = (_REPO / "icesee_jupyter_book/core/results_service.py").read_text()
    assert "results_service as rs" in ws and "rs.discover(" in ws and "rs.render(" in ws
    assert "ICESEE.src.postprocessing.render" in svc
    assert "cryostack_src.models" not in ws + svc


# ---------------------------------------------------------------------------
# 9. CryoLauncher behavior is unchanged
# ---------------------------------------------------------------------------
def test_cryolauncher_shell_still_builds_and_keeps_its_own_shape(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="parity-cl-unchanged")
    assert page is not None
    workspaces = _widgets_with_class(page, "cryostack-output-workspace")
    assert len(workspaces) == 1
    left = _find_left_column(page)
    assert left is not None and len(left.children) == 2
