"""UI cleanup checkpoint: establish the execution environment (Remote/Cloud
connection) before exposing operations against it, and integrate the
Advanced-mode file editor as tab 0 ("Editor") of the EXISTING right-hand
Workspace Tab widget -- Editor, Runs, Files, Run Log, Results in Advanced
mode; Runs, Files, Run Log, Results (unchanged) in Basic mode.

Structural (full-page) checks reuse the SAME widget-hierarchy-inspection
approach test_icesee_gui_structural_parity.py already established: build
the real page (icesheets_gateway.build_icesheets_ui / icesee_gateway.
build_icesee_ui) and walk it -- a passing assertion is a claim about actual
construction, not a hand-built lookalike tree.

The tab-integration mechanism itself (build_run_details's
WorkspaceDetails.set_advanced_mode) is additionally proven at the unit
level -- exact tab order/titles, single Textarea instance, and content
surviving repeated Advanced<->Basic flips -- since that is where the
insert-at-0 index-shift risk (task item 8) actually lives.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_ICESHEETS_GW = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


# ---------------------------------------------------------------------------
# tree-walking helpers (same shape as test_icesee_gui_structural_parity.py)
# ---------------------------------------------------------------------------
def _walk(root):
    yield root
    for child in getattr(root, "children", ()) or ():
        yield from _walk(child)


def _widgets_with_class(root, css_class):
    return [w for w in _walk(root) if css_class in (getattr(w, "_dom_classes", ()) or ())]


def _find_workspace_tabs(root):
    return [w for w in _walk(root) if isinstance(w, W.Tab)
            and "cryostack-workspace-tabs" in (getattr(w, "_dom_classes", ()) or ())]


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


def _build_icesee(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _find_ui_mode_dropdown(page):
    """The 'User mode' Basic/Advanced(/Agent) selector (a ToggleButtons,
    per run_settings_state.py) -- identified by its option VALUES, not
    type/position, so it is robust to unrelated layout changes."""
    for w in _walk(page):
        options = getattr(w, "options", None)
        if not options:
            continue
        try:
            values = {v for _, v in options}
        except (TypeError, ValueError):
            continue
        if {"basic", "advanced"} <= values:
            return w
    return None


# ---------------------------------------------------------------------------
# C/D. Remote/Cloud config precedes the Workspace (unchanged from the prior
# checkpoint -- the editor moving INSIDE the Workspace's own Tab doesn't
# change where the Workspace itself sits relative to Remote/Cloud).
# ---------------------------------------------------------------------------
def test_cryolauncher_remote_config_precedes_workspace(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="order-cl-remote")
    order = list(_walk(page))
    remote = _widgets_with_class(page, "cryostack-remote-config")
    tabs = _find_workspace_tabs(page)
    assert remote and tabs
    assert order.index(remote[0]) < order.index(tabs[0])


def test_cryolauncher_cloud_config_precedes_workspace(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="order-cl-cloud")
    order = list(_walk(page))
    cloud = _widgets_with_class(page, "cryostack-cloud-config")
    tabs = _find_workspace_tabs(page)
    assert cloud and tabs
    assert order.index(cloud[0]) < order.index(tabs[0])


def test_icesee_remote_config_precedes_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="order-ic-remote")
    order = list(_walk(page))
    remote = _widgets_with_class(page, "cryostack-remote-config")
    tabs = _find_workspace_tabs(page)
    assert remote and tabs
    assert order.index(remote[0]) < order.index(tabs[0])


def test_icesee_cloud_config_precedes_workspace(monkeypatch, tmp_path):
    page = _build_icesee(monkeypatch, tmp_path, user="order-ic-cloud")
    order = list(_walk(page))
    cloud = _widgets_with_class(page, "cryostack-cloud-config")
    tabs = _find_workspace_tabs(page)
    assert cloud and tabs
    assert order.index(cloud[0]) < order.index(tabs[0])


# ---------------------------------------------------------------------------
# 1-3. Editor as tab 0 of the RIGHT Workspace, Advanced only -- driven
# through the REAL 'User mode' dropdown (the same observer path the app
# itself uses), not a hand-called internal function.
# ---------------------------------------------------------------------------
def test_basic_mode_tab_order_is_unchanged(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="tabs-basic")
    ui_mode_dd = _find_ui_mode_dropdown(page)
    assert ui_mode_dd is not None
    ui_mode_dd.value = "basic"
    tabs = _find_workspace_tabs(page)[0]
    titles = [tabs.get_title(i) for i in range(len(tabs.children))]
    assert titles == ["Runs", "Files", "Run Log", "Results"]


def test_advanced_mode_puts_editor_first_then_the_original_four_tabs(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="tabs-advanced")
    ui_mode_dd = _find_ui_mode_dropdown(page)
    assert ui_mode_dd is not None
    ui_mode_dd.value = "advanced"
    tabs = _find_workspace_tabs(page)[0]
    titles = [tabs.get_title(i) for i in range(len(tabs.children))]
    assert titles == ["Editor", "Runs", "Files", "Run Log", "Results"]

    # editor is NOT also present in the LEFT configuration column (820px is
    # this editor's distinguishing height -- the left column has unrelated
    # Textareas, e.g. the Agent-mode experiment description field)
    left = _widgets_with_class(page, "icesee-left")[0]
    editor_in_left = [w for w in _walk(left)
                      if isinstance(w, W.Textarea) and str(w.layout.height) == "820px"]
    assert editor_in_left == []


def test_switching_basic_to_advanced_to_basic_restores_exact_tab_orders(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="tabs-round-trip")
    ui_mode_dd = _find_ui_mode_dropdown(page)
    tabs = _find_workspace_tabs(page)[0]

    ui_mode_dd.value = "basic"
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Runs", "Files", "Run Log", "Results"]

    ui_mode_dd.value = "advanced"
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Editor", "Runs", "Files", "Run Log", "Results"]

    ui_mode_dd.value = "basic"
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Runs", "Files", "Run Log", "Results"]


# ---------------------------------------------------------------------------
# 4. exactly one editor Textarea instance in the whole page
# ---------------------------------------------------------------------------
def test_exactly_one_editor_textarea_instance_in_the_whole_page(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="tabs-single-instance")
    ui_mode_dd = _find_ui_mode_dropdown(page)
    ui_mode_dd.value = "advanced"
    # 820px is this editor's distinguishing height (workspace/editor.py);
    # no other Textarea in the page uses it.
    marked = [w for w in _walk(page)
              if isinstance(w, W.Textarea) and str(w.layout.height) == "820px"]
    assert len(marked) == 1


# ---------------------------------------------------------------------------
# 6. Advanced -> Basic -> Advanced preserves editor content (same object,
# same value) through the REAL mode-switch path
# ---------------------------------------------------------------------------
def test_mode_round_trip_preserves_editor_identity_and_unsaved_content(monkeypatch, tmp_path):
    page = _build_cryolauncher(monkeypatch, tmp_path, user="tabs-preserve-content")
    ui_mode_dd = _find_ui_mode_dropdown(page)
    tabs = _find_workspace_tabs(page)[0]

    ui_mode_dd.value = "advanced"
    editor = [w for w in _walk(tabs) if isinstance(w, W.Textarea)][0]
    editor.value = "draft surviving a Basic<->Advanced round trip"
    editor_identity = id(editor)

    ui_mode_dd.value = "basic"      # Editor tab removed from .children...
    ui_mode_dd.value = "advanced"   # ...and reattached, never recreated

    still_there = [w for w in _walk(tabs) if isinstance(w, W.Textarea)][0]
    assert id(still_there) == editor_identity
    assert still_there.value == "draft surviving a Basic<->Advanced round trip"


# ---------------------------------------------------------------------------
# existing Runs/Files/Run Log/Results callbacks still address the correct
# tab after the Editor-at-0 index shift -- the gateway's own
# _switch_workspace_tab must resolve by TITLE, not a stale hardcoded index.
# ---------------------------------------------------------------------------
def test_switch_workspace_tab_is_title_based_not_a_hardcoded_index_map():
    src = _ICESHEETS_GW.read_text()
    assert 'idx = _WS_TAB.get(name)' not in src
    assert '_WS_TAB = {"runs": 0, "files": 1, "log": 2, "results": 3}' not in src
    start = src.index("def _switch_workspace_tab(name):")
    end = src.index("def _runs_tail_log():", start)
    block = src[start:end]
    assert "tab.get_title(index) == title" in block


def test_workspace_editor_is_built_exactly_once_and_never_rebuilt_on_toggle():
    src = _ICESHEETS_GW.read_text()
    assert src.count("build_editor_panel(") == 1
    assert src.count("build_dataset_panel(") == 1
    assert src.count("output_workspace = build_run_details(") == 1
    start = src.index("def update_visibility(_=None):")
    end = src.index("def update_summary(_=None):", start)
    block = src[start:end]
    assert "output_workspace.set_advanced_mode(" in block
    assert "build_editor_panel(" not in block
    assert "build_run_details(" not in block
    assert "W.Textarea(" not in block


# ---------------------------------------------------------------------------
# 5 (existing editor controls still operate on that same editor) + the
# insert-at-0 index-shift mechanics, at the unit level (build_run_details
# in isolation -- no full gateway build).
# ---------------------------------------------------------------------------
def _editor_panel(tmp_path):
    from cryostack_src.frontend.cryolauncher.workspace.editor import build_editor_panel
    from cryostack_src.workspace import WorkspaceManager, WorkspaceUser

    user = WorkspaceUser(user_id="user-reloc", source="cryostack-auth")
    canon = tmp_path / "shipped" / "SquareIceShelf"
    canon.mkdir(parents=True)
    (canon / "runme.m").write_text("md=solve(md,'Stressbalance');\n")

    class _W:
        def __init__(self, value=None):
            self.value = value
            self.options = ()

    example_dir = _W(str(canon))
    mgr = WorkspaceManager(
        owner=user, workspace_root=tmp_path / "ws", status={}, session={"id": "s"},
        example_dir=example_dir, model=_W("issm"), backend=_W("c"),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )
    return build_editor_panel(
        manager=mgr, model_value=lambda: "issm", example_dir_widget=example_dir,
        log_output=[], on_files_changed=lambda: None,
    )


def test_unit_set_advanced_mode_produces_exact_tab_orders_and_reuses_the_editor(tmp_path):
    from cryostack_src.frontend.cryolauncher.workspace.run_details import build_run_details

    panel = _editor_panel(tmp_path)
    details = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML("runs"), files_panel=W.HTML("files"),
        editor_panel=panel.container,
    )
    tabs = details.tabs

    # Basic (default): unchanged
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Runs", "Files", "Run Log", "Results"]

    details.set_advanced_mode(True)
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Editor", "Runs", "Files", "Run Log", "Results"]
    assert tabs.children[0] is panel.container
    found_advanced = [w for w in _walk(details.container) if isinstance(w, W.Textarea)]
    assert len(found_advanced) == 1
    assert found_advanced[0] is panel.controller.editor      # exact same instance

    details.set_advanced_mode(False)
    assert [tabs.get_title(i) for i in range(len(tabs.children))] == \
        ["Runs", "Files", "Run Log", "Results"]
    # the Tab's own children ARE the show/hide mechanism (no wrapper
    # Accordion) -- in Basic mode the editor is fully detached from the
    # tree, not merely display:none, so it is genuinely absent here...
    assert [w for w in _walk(details.container) if isinstance(w, W.Textarea)] == []
    # ...but the Python widget object itself was never destroyed/recreated:
    # the SAME controller still owns the SAME Textarea instance.
    assert panel.controller.editor is found_advanced[0]


def test_unit_editor_controls_still_operate_on_the_relocated_textarea(tmp_path):
    """build_editor_panel's own controller keeps driving the SAME Textarea
    after it becomes tab 0 -- proves this is pure container/tab
    composition, not a second editor/controller."""
    from cryostack_src.frontend.cryolauncher.workspace.run_details import build_run_details

    panel = _editor_panel(tmp_path)
    details = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML("runs"), files_panel=W.HTML("files"),
        editor_panel=panel.container,
    )
    details.set_advanced_mode(True)

    found = [w for w in _walk(details.tabs) if isinstance(w, W.Textarea)][0]
    panel.controller.refresh()
    panel.controller.editor.value = "typed through the relocated widget"
    assert found.value == "typed through the relocated widget"
    assert found is panel.controller.editor


def test_unit_selected_tab_by_title_survives_the_index_shift(tmp_path):
    """The user is on 'Run Log' (index 2 of 4 in Basic); switching to
    Advanced inserts Editor at 0, shifting Run Log to index 3 -- the SAME
    tab (by title) must stay selected, not whatever now sits at the old
    index 2 ('Files')."""
    from cryostack_src.frontend.cryolauncher.workspace.run_details import build_run_details

    panel = _editor_panel(tmp_path)
    details = build_run_details(
        log_output=W.Output(), results_output=W.Output(),
        download_controls=W.HTML(), log_controls=W.HTML(),
        runs_panel=W.HTML("runs"), files_panel=W.HTML("files"),
        editor_panel=panel.container,
    )
    tabs = details.tabs
    tabs.selected_index = 2  # "Run Log" in the Basic 4-tab order
    assert tabs.get_title(tabs.selected_index) == "Run Log"

    details.set_advanced_mode(True)
    assert tabs.get_title(tabs.selected_index) == "Run Log"   # followed, not stuck at index 2

    details.set_advanced_mode(False)
    assert tabs.get_title(tabs.selected_index) == "Run Log"
