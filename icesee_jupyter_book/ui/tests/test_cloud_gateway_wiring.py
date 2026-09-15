"""Cloud Commit 4/5 -- the IceSheets gateway wires the real Cloud path and
leaves the Local / Remote paths untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import ipywidgets as W

_ICESHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_cloud_placeholder_submission_is_gone():
    src = _ICESHEETS.read_text()
    assert "Placeholder for AWS Batch submission" not in src
    assert "adapt submit_cloud_example for model-only workflows" not in src


def test_cloud_branch_validates_and_preflights_before_submit():
    src = _ICESHEETS.read_text()
    assert "resolve_cloud_config(" in src
    assert "validate_cloud_config(" in src
    assert "cloud_run_preflight(" in src
    assert "_submit_cloud_run(" in src
    # the real bridge submit signature (staged tree + model + bucket)
    assert "staged_source=" in src and "matlab_license_configured=" in src


def test_cloud_run_is_registered_with_backend_aws_and_a_real_job_id():
    src = _ICESHEETS.read_text()
    assert 'backend="aws"' in src
    assert 'execution_mode="cloud"' in src
    # registration now happens in _register_cloud_run, called by the
    # CloudRunController only after it has a real job id + S3 run
    assert "_register_cloud_run" in src
    assert "CloudRunController(" in src

    from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
        CloudRunController,
    )
    calls = []

    class _Bridge:
        def submit(self, **kw):
            class _R:
                job_id = None            # no job id -> must NOT register
                metadata = {}
                working_directory = None
                messages = []
            return _R()

    ctl = CloudRunController(
        bridge_factory=_Bridge,
        register_run=lambda **kw: calls.append(kw),
        sync_results=lambda **kw: "/x",
        on_state=lambda s: None,
        on_log=lambda m: None,
        poll_interval=0.0,
    )
    import asyncio
    asyncio.run(ctl.run_once(staged_source="/x", model="issm",
                             run_target="runme.m", bucket="b"))
    assert calls == []                     # no job id -> no registration
    assert ctl.state == "failed"


def test_cloud_state_chip_covers_the_documented_states():
    src = _ICESHEETS.read_text()
    for state in ("not_configured", "checking", "ready", "staging", "submitting",
                  "queued", "running", "completed", "failed", "cancelled"):
        assert f'"{state}"' in src


def test_local_and_remote_paths_are_unchanged():
    src = _ICESHEETS.read_text()
    # Remote: the B3 identity gate + real submitters still present
    assert "enforce_remote_access(" in src
    assert "submit_remote_icesheets" in src
    assert "verify_remote_identity(" in src
    # Local: the local runner path
    assert "run_example_local" in src or "local" in src.lower()
    # cloud staging reuses the SAME working-copy helper as Remote
    assert "stage_example_for_run(" in src


def test_no_developer_or_personal_cloud_defaults():
    src = _ICESHEETS.read_text()
    for bad in ("us-east-1", "arobel3", "bankyanjo", "1711@matlablic"):
        assert bad not in src, bad
    assert "DEFAULT_CLOUD_REGION" in src  # region comes from the shared constant


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_still_builds_with_the_cloud_wiring(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-wire-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Not configured" in blob


# -- C7 live-acceptance: a failed AWS connection is not "Not configured" ---
def test_recovery_actions_and_new_chip_states_are_wired():
    src = _ICESHEETS.read_text()
    assert "connection_issue" in src and "Connection issue" in src
    assert "connection_required" in src and "Connection required" in src
    assert "aws_connect.retry" in src
    assert "aws_connect.change_account" in src
    assert "retry_button.on_click(aws_connect.retry)" in src
    assert "change_account_button.on_click(aws_connect.change_account)" in src
    # Change AWS account is staged: the replacement's own verify/cancel are
    # wired too, distinct from the active connection's verify/disconnect.
    assert "change_verify_button.on_click(aws_connect.change_verify)" in src
    assert "change_cancel_button.on_click(aws_connect.change_cancel)" in src


def test_a_stranded_aws_connection_shows_connection_issue_not_not_configured(monkeypatch, tmp_path):
    """The exact live-acceptance bug: a previously-attempted-but-failed AWS
    connection must render as "Cloud: Connection issue", never silently
    fall back to the first-time "Cloud: Not configured" label."""
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "cloud-recovery-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")

    from cryostack_src.cloud.connect import AWSConnectionStore
    from cryostack_src.workspace.identity import WorkspaceUser

    user = WorkspaceUser(user_id="cloud-recovery-user", source="env-override")
    store = AWSConnectionStore(user=user, workspace_root=tmp_path)
    conn = store.create(region="us-east-2").with_role(
        "arn:aws:iam::713938953301:role/CryoStackExecutionRole"
    ).mark_error("AWS denied the role assumption.")
    store.save(conn)

    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()
    html = []

    def walk(w):
        if isinstance(w, W.HTML):
            html.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    blob = "\n".join(html)
    assert "Cloud: Connection issue" in blob
    assert "Cloud: Not configured" not in blob
    # the Role ARN this user already saved must still be on disk, untouched
    assert store.load().role_arn == "arn:aws:iam::713938953301:role/CryoStackExecutionRole"


# -- Icepack Cloud Execution checkpoint -----------------------------------
def test_canonical_cloud_config_derives_the_selected_model():
    """The functions that build the Review card / drift digest / launch gate
    no longer hardcode model="issm" -- they read model_dd.value. (The
    ISSM-only scientific_overrides conditional is intentional and untouched.)"""
    src = _ICESHEETS.read_text()
    assert 'model=(model_dd.value or "issm").strip().lower()' in src
    # the old hardcoded-issm-only comment on _resolve_cloud_execution is gone
    assert 'model="issm",           # cloud execution is ISSM-only for now' not in src


def test_cloud_run_history_and_execution_follow_the_selected_model():
    src = _ICESHEETS.read_text()
    assert '(run.model or "").lower() != _model' in src
    assert "region_hint=aws_region.value.strip() or DEFAULT_CLOUD_REGION" in src
    # the ISSM-only note is gone from _resolve_cloud_execution
    assert "cloud execution is ISSM-only for now" not in src


def test_gateway_builds_with_icepack_selectable_and_cloud_supported():
    """Icepack Cloud Execution checkpoint: the model dropdown includes
    Icepack, and the capabilities registry (which the gateway/agent both
    read) now agrees Icepack is cloud-capable."""
    from cryostack_src.models.capabilities import get_model_capabilities

    cap = get_model_capabilities("icepack")
    assert cap.cloud_supported is True
    assert "cloud" in cap.execution_modes
    assert cap.requires_matlab is False

    issm_cap = get_model_capabilities("issm")
    assert issm_cap.cloud_supported is True
    assert issm_cap.requires_matlab is True             # ISSM behaviour unchanged


# ── Launch cloud run must never reach Remote/HPC validation ───────────────
# Live-acceptance bug at commit 5c7f0d10: Launch cloud run (Icepack, Review
# passed) produced "[remote][ERROR] Host and User are required." -- the
# button's callback fell through into on_run()'s Remote/HPC dispatch instead
# of the cloud/AWS controller. Root cause: (1) on_run()'s Host/User check was
# unconditional (fired for every execution mode, not just "remote"), and
# (2) nothing set mode_dd back to "cloud" for a user who never touched the
# main Execution Mode dropdown and drove the run entirely from the Cloud
# Environment panel, so on_run() read the stale default ("remote").
#
# Fix: Launch cloud run's callback (_launch_cloud_run) is wired directly as
# cloud_review_runtime's launch_handler -- it never calls on_run() at all,
# so it structurally cannot reach the Remote/HPC checks, regardless of
# mode_dd's value. on_run()'s own Host/User check is also now correctly
# gated on mode == "remote" (defence in depth for the generic Run button).


def _freevar(fn, name):
    """Extract one captured (closure) variable from a nested function by
    name -- the only way to reach icesheets_gateway.py's internals, which
    are deliberately not module-level (every existing test in this file
    verifies this legacy gateway's wiring the same way: build the real
    gateway, then inspect it)."""
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _find_launch_review(page):
    """Return (launch_handler, review_launch) -- ``review_launch`` is
    ``cloud_review_runtime.launch``, ``launch_handler`` is
    ``_launch_cloud_run`` -- for an already-built page."""
    launch_button = None

    def walk(w):
        nonlocal launch_button
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Launch cloud run":
            launch_button = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert launch_button is not None, "Launch cloud run button not found in the built page"
    assert launch_button._click_handlers.callbacks, "Launch cloud run has no click handler"

    review_launch = launch_button._click_handlers.callbacks[0]   # cloud_review_runtime.launch
    launch_handler = _freevar(review_launch, "launch_handler")   # _launch_cloud_run
    return launch_handler, review_launch


def _build_gateway_and_launch_handler(monkeypatch, tmp_path, *, user):
    page = _build_gateway_page(monkeypatch, tmp_path, user=user)
    launch_handler, _ = _find_launch_review(page)
    return launch_handler


def _gateway_state(monkeypatch, tmp_path, *, user):
    """Build one real gateway page and return every widget/closure needed to
    drive Basic/Advanced + compute-mode state through Run Plan, Review &
    Launch, cost estimate and submission -- all from the SAME page, so the
    state is genuinely shared exactly as it is live."""
    page = _build_gateway_page(monkeypatch, tmp_path, user=user)

    launch_handler, review_launch = _find_launch_review(page)
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")
    _run = _freevar(review_launch, "_run")
    build_review = _freevar(_run, "review_builder")

    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    update_summary = _freevar(update_visibility, "update_summary")

    return {
        "page": page,
        "submit_fn": submit_fn,
        "build_review": build_review,
        "update_visibility": update_visibility,
        "update_summary": update_summary,
        "summary_html": _freevar(update_summary, "summary_html"),
        "model_dd": _freevar(submit_fn, "model_dd"),
        "mode_dd": _freevar(update_summary, "mode_dd"),
        "ui_mode_dd": _freevar(update_visibility, "ui_mode_dd"),
        "cloud_environment": _freevar(submit_fn, "cloud_environment"),
        "example_dir": _freevar(submit_fn, "example_dir"),
        "run_target": _freevar(submit_fn, "run_target"),
        "aws_region": _freevar(submit_fn, "aws_region"),
        "cloud_bucket": _freevar(submit_fn, "cloud_bucket"),
        "batch_job_queue": _freevar(submit_fn, "batch_job_queue"),
        "batch_job_def": _freevar(submit_fn, "batch_job_def"),
        "_cloud": _freevar(submit_fn, "_cloud"),
    }


@pytest.mark.parametrize("model", ["icepack", "issm"])
def test_launch_cloud_run_never_reaches_remote_host_user_validation(
    monkeypatch, tmp_path, capsys, model
):
    """The exact live path: build the real gateway, select the model, invoke
    the REAL function object wired as Launch cloud run's callback -- proving
    it (a) is not on_run, (b) cannot call on_run (not even in its closure),
    and (c) running it never produces the Remote/HPC Host/User message,
    for BOTH Icepack and ISSM."""
    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user=f"cloud-launch-{model}")

    # (a)/(b): structurally cannot reach on_run -- it is not even a captured
    # free variable of the Launch cloud run callback.
    assert "on_run" not in launch_handler.__code__.co_freevars

    prepare = _freevar(launch_handler, "_prepare_effective_example")
    example_dir_w = _freevar(prepare, "example_dir")
    model_dd_w = _freevar(prepare, "model_dd")

    example = tmp_path / "SmallestExample"
    example.mkdir()
    (example / "run.py").write_text("print('hello')\n")
    (example / "runme.m").write_text("% issm entry\n")

    model_dd_w.value = model
    example_dir_w.value = str(example)

    # deliberately leave cluster_host/cluster_user at their untouched
    # defaults -- exactly the live report's state (the user never touched
    # the Remote HPC connection fields; only the Cloud Environment panel).
    capsys.readouterr()   # drop anything printed during gateway construction
    # (c): the callback runs to whatever conclusion it reaches offline (no
    # AWS configured -> a clean [cloud] config/preflight message), but it
    # NEVER emits the Remote/HPC Host/User error.
    launch_handler(None)

    printed = capsys.readouterr().out
    assert "[remote][ERROR] Host and User are required." not in printed
    assert "cluster" not in printed.lower()


def test_launch_cloud_run_callback_is_not_on_run_itself():
    """Static, non-behavioural confirmation of the wiring: the source no
    longer connects Launch cloud run to on_run through the old
    pending_review + on_run(None) lambda."""
    src = _ICESHEETS.read_text()
    assert "launch_handler=_launch_cloud_run" in src
    assert 'launch_handler=lambda review: (\n                _cloud.__setitem__' not in src
    # _launch_cloud_run's own CODE (docstring excluded -- it explains the
    # invariant in prose, which legitimately names the very things the code
    # must not touch) never references Remote/HPC state.
    start = src.index("def _launch_cloud_run(")
    end = src.index("\n        def on_run(", start)
    definition = src[start:end]
    docstring_end = definition.index('"""', definition.index('"""') + 3) + 3
    code = definition[docstring_end:]
    for forbidden in ("cluster_host", "cluster_user", "enforce_remote_access",
                      "on_run(", "mode_dd"):
        assert forbidden not in code, forbidden


# ── Icepack notebook staging: Advanced Editor shows the runnable script ────
def _find_widget_by_observer(page, handler_name: str):
    found = {}

    def walk(w):
        if handler_name not in found:
            notifiers = getattr(w, "_trait_notifiers", None)
            if notifiers and "value" in notifiers:
                for handlers in notifiers["value"].values():
                    for h in handlers:
                        if getattr(h, "__name__", "") == handler_name:
                            found[handler_name] = (w, h)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found.get(handler_name)


def test_selecting_an_icepack_notebook_example_materializes_run_py_for_the_editor(
    monkeypatch, tmp_path
):
    """Root cause + item 5: selecting a canonical Icepack tutorial (a bare
    .ipynb file -- the exact discovery shape that produced "Example
    directory not found") must leave example_dir pointing at a real
    directory containing the deterministic run.py, so the Advanced Editor
    shows/edits the runnable Python representation, not raw notebook JSON --
    and every downstream consumer (staging) sees an ordinary directory.
    Skips when this machine has no local Icepack checkout to discover."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    example_dir = freevar(handler, "example_dir")
    run_target = freevar(handler, "run_target")
    editor_panel = freevar(handler, "editor_panel")

    model_dd.value = "icepack"          # repopulates the picker via refresh_example_picker
    target = str(notebook.resolve())
    assert target in [v for _l, v in picker.options]

    picker.value = target               # fires apply_selected_example (real handler)

    staged = Path(example_dir.value)
    assert staged.is_dir(), "example_dir must be a directory, never the bare .ipynb"
    assert (staged / "run.py").is_file()
    assert (staged / notebook.name).is_file()          # the source notebook is kept too
    assert "import" in (staged / "run.py").read_text()

    # item 10: the actual Advanced Editor file-selection callback/state --
    # not just the filesystem it reads from.
    ctl = editor_panel.controller
    assert run_target.value == "run.py"
    assert Path(ctl.file_picker.value).name == "run.py"          # active editor file
    assert ctl.editor.value == (staged / "run.py").read_text()  # generated Python...
    assert not ctl.editor.value.lstrip().startswith("{")         # ...never notebook JSON
    assert ctl.editor.disabled is False                          # run.py is editable


def test_deliberately_selecting_the_notebook_keeps_it_readonly_raw(monkeypatch, tmp_path):
    """Item 6: the .ipynb stays reachable and, once explicitly picked, stays
    read-only raw JSON -- we are not rendering notebooks in this checkpoint."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user2")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    editor_panel = freevar(handler, "editor_panel")
    model_dd.value = "icepack"
    picker.value = str(notebook.resolve())
    ctl = editor_panel.controller

    # the default is run.py (proven above) -- now deliberately switch to .ipynb
    nb_option = next(v for _l, v in ctl.file_picker.options if v.endswith(".ipynb"))
    ctl.file_picker.value = nb_option
    assert ctl.editor.disabled is True
    assert ctl.editor.value.lstrip().startswith("{")   # raw notebook JSON, unrendered


def test_refresh_never_reverts_an_open_run_py_back_to_the_notebook(monkeypatch, tmp_path):
    """Item 7: Refresh must not switch the active file away from run.py."""
    from icesee_jupyter_book.core.icesheet_examples import resolve_icepack_root

    root = resolve_icepack_root()
    if root is None:
        pytest.skip("no local Icepack checkout on this machine")
    notebook = root / "notebooks" / "tutorials" / "00-meshes-functions.ipynb"
    if not notebook.is_file():
        pytest.skip("00-meshes-functions.ipynb not present in this Icepack checkout")

    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "editor-notebook-user3")
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    page = build_icesheets_ui()

    picker, handler = _find_widget_by_observer(page, "apply_selected_example")

    def freevar(fn, name):
        idx = fn.__code__.co_freevars.index(name)
        return fn.__closure__[idx].cell_contents

    model_dd = freevar(handler, "model_dd")
    editor_panel = freevar(handler, "editor_panel")
    model_dd.value = "icepack"
    picker.value = str(notebook.resolve())
    ctl = editor_panel.controller
    assert Path(ctl.file_picker.value).name == "run.py"

    ctl.refresh()                                       # the editor's own Refresh button
    assert Path(ctl.file_picker.value).name == "run.py", (
        "Refresh must not silently switch the active file back to the notebook"
    )


# ── C7.5 live-acceptance: CLOUD RUN card must be the single run-control ───
# surface for cloud mode. Live finding on job ec56a332-7832-4933-936d-
# e98f236d0e37: while a cloud run was active, the page rendered BOTH the
# CLOUD RUN card (View log / View results / Terminate, wired through the
# account-aware CloudRunController) and the older generic Execution panel
# below it (state + "Submit job" + its own "Terminate") -- a second,
# non-account-bound path to the same job. For execution_mode == "cloud" the
# generic panel's Submit job / Terminate must be hidden; Remote is
# unaffected (this gateway's Execution Mode dropdown only ever offers
# "Remote" / "Cloud" -- there is no separate "Local" mode to toggle here).
def _build_gateway_page(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", "cloud-wire-service")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.delenv("CRYOSTACK_AWS_PRINCIPAL_ARN", raising=False)
    monkeypatch.delenv("CRYOSTACK_CF_TEMPLATE_URL", raising=False)
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    return build_icesheets_ui()


def test_cloud_mode_hides_the_duplicate_generic_submit_and_terminate_controls(
    monkeypatch, tmp_path
):
    """Cloud mode: the generic Execution panel's "Submit job" (run_btn) and
    its own Terminate (cloud_terminate_btn) are both hidden -- the CLOUD RUN
    card (a structurally distinct widget, built in cloud_environment.py) is
    the only reachable run-control surface. Remote mode -- the only other
    execution_mode this gateway offers -- renders exactly as it always has:
    run_btn visible, the remote Terminate button visible, cloud_terminate_btn
    still hidden (it always was, outside cloud mode)."""
    page = _build_gateway_page(monkeypatch, tmp_path, user="cloud-ui-hide-user")

    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    mode_dd = _freevar(update_visibility, "mode_dd")
    ui_mode_dd = _freevar(update_visibility, "ui_mode_dd")
    run_btn = _freevar(update_visibility, "run_btn")
    cloud_terminate_btn = _freevar(update_visibility, "cloud_terminate_btn")
    terminate_btn = _freevar(update_visibility, "terminate_btn")

    assert ui_mode_dd.value != "agent"          # the manual Basic/Advanced surface

    # -- Cloud mode: the CLOUD RUN card alone controls a run --------------
    mode_dd.value = "cloud"
    assert run_btn.layout.display == "none", "generic Submit job must be hidden in cloud mode"
    assert cloud_terminate_btn.layout.display == "none", (
        "generic Terminate must be hidden in cloud mode -- CLOUD RUN's own "
        "Terminate (a separate widget) is the only run-control surface"
    )

    # -- Remote mode (this gateway's only other execution_mode): unchanged -
    mode_dd.value = "remote"
    assert run_btn.layout.display == "", "Remote must keep Submit job visible, unchanged"
    assert terminate_btn.layout.display == "", "Remote's own Terminate stays visible, unchanged"
    assert cloud_terminate_btn.layout.display == "none", (
        "cloud_terminate_btn was already hidden outside cloud mode before this fix"
    )


def test_cloud_run_card_terminate_is_a_structurally_distinct_widget_from_the_generic_one(
    monkeypatch, tmp_path
):
    """The CLOUD RUN card's Terminate button (wired to CloudRunController via
    on_cloud_terminate_confirm) is a DIFFERENT Button object than the generic
    Execution panel's cloud_terminate_btn -- hiding the latter cannot also
    remove the former, and the former's own visibility is driven independently
    (cloud_active_run_runtime / set_active_run_view), not by update_visibility."""
    page = _build_gateway_page(monkeypatch, tmp_path, user="cloud-ui-distinct-user")

    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    cloud_terminate_btn = _freevar(update_visibility, "cloud_terminate_btn")

    terminate_buttons = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == "Terminate":
            terminate_buttons.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert len(terminate_buttons) == 2, "expected exactly the generic + CLOUD RUN terminate buttons"
    assert cloud_terminate_btn in terminate_buttons
    active_run_terminate = next(b for b in terminate_buttons if b is not cloud_terminate_btn)
    assert active_run_terminate is not cloud_terminate_btn


# ── C7.5 live-acceptance: "Container Overrides length must be at most 8192" ─
# Live finding: SubmitJob/staging succeeded for account 774888247882, but the
# job then failed with this exact AWS message -- traced to the Icepack output
# collector being embedded VERBATIM into the Batch job definition's command
# (cryostack_src/cloud/runtime.py), which AWS forwards through an ECS RunTask
# override on every launch, capped at 8192 characters. The fix stages the
# collector as an ordinary file alongside run.py
# (cryostack_src.cloud.runtime.icepack_postprocess_extra_files) instead --
# this test proves the ACTUAL wired gateway code path
# (_submit_cloud_run's own "cloud always uploads a user-owned working copy"
# staging call) passes that exact extra_files entry to
# WorkspaceManager.stage_example_for_run for an Icepack cloud run, without
# contacting AWS.
def test_icepack_cloud_submit_stages_the_postprocess_helper_alongside_run_py(
    monkeypatch, tmp_path
):
    from cryostack_src.cloud.runtime import (
        ICEPACK_POSTPROCESS_FILENAME,
        icepack_postprocess_extra_files,
    )

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="icepack-8192-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    workspace_manager = _freevar(submit_fn, "workspace_manager")

    example = tmp_path / "IcepackExample"
    example.mkdir()
    (example / "run.py").write_text("print('hello icepack')\n")

    model_dd.value = "icepack"
    example_dir.value = str(example)
    run_target.value = "run.py"
    # enough to pass validate_cloud_config/cloud_run_preflight's pure string
    # checks -- no AWS is ever contacted by those, or by this test.
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    batch_job_queue.value = "cryostack-queue"
    batch_job_def.value = "cryostack-icepack"

    captured = {}

    def fake_stage_example_for_run(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before any AWS contact -- staging kwargs already captured")

    monkeypatch.setattr(workspace_manager, "stage_example_for_run", fake_stage_example_for_run)

    # _submit_cloud_run(staged_dir, md_provenance, review=None) -- staged_dir
    # equal to example_dir.value is exactly what triggers its own "cloud
    # always uploads a user-owned working copy" staging fallback (the path
    # a plain Advanced-mode Icepack run with no Basic-mode overrides takes --
    # the live failing job's own shape).
    submit_fn(example_dir.value, {}, review=None)

    assert "extra_files" in captured, "the staging call never ran (still blocked earlier)"
    extra = captured["extra_files"]
    assert extra is not None and ICEPACK_POSTPROCESS_FILENAME in extra
    assert extra[ICEPACK_POSTPROCESS_FILENAME] == icepack_postprocess_extra_files()[
        ICEPACK_POSTPROCESS_FILENAME]


def test_issm_cloud_submit_never_gets_the_icepack_extra_file(monkeypatch, tmp_path):
    """ISSM behaviour is untouched apart from the license tunnel client fix:
    its own staging call never carries the Icepack-only extra_files entry,
    but DOES carry the license tunnel client helper (staged as an ordinary
    file, never `python3 -m cryostack_src...` inside the Batch container)."""
    from cryostack_src.cloud.runtime import (
        ICEPACK_POSTPROCESS_FILENAME,
        LICENSE_TUNNEL_CLIENT_FILENAME,
    )

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="issm-8192-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    workspace_manager = _freevar(submit_fn, "workspace_manager")

    example = tmp_path / "SquareIceShelf"
    example.mkdir()
    (example / "runme.m").write_text("md=solve(md,'Stressbalance');\n")

    model_dd.value = "issm"
    example_dir.value = str(example)
    run_target.value = "runme.m"
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    batch_job_queue.value = "cryostack-queue"
    batch_job_def.value = "cryostack-issm"

    # ISSM's own preflight gate (a cloud MATLAB license -- an AWS Secrets
    # Manager ARN on the connection) is unrelated to this checkpoint; stub
    # the gateway's preflight so the test reaches the staging call at all.
    import icesee_jupyter_book.ui.icesheets_gateway as _gw
    monkeypatch.setattr(_gw, "cloud_run_preflight", lambda **kw: [])

    captured = {}

    def fake_stage_example_for_run(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before any AWS contact -- staging kwargs already captured")

    monkeypatch.setattr(workspace_manager, "stage_example_for_run", fake_stage_example_for_run)
    submit_fn(example_dir.value, {}, review=None)

    assert "extra_files" in captured, "the staging call never ran (still blocked earlier)"
    assert captured["extra_files"]
    assert ICEPACK_POSTPROCESS_FILENAME not in captured["extra_files"]
    assert LICENSE_TUNNEL_CLIENT_FILENAME in captured["extra_files"]
    _staged_src = captured["extra_files"][LICENSE_TUNNEL_CLIENT_FILENAME]
    assert "import cryostack_src" not in _staged_src
    assert "from cryostack_src" not in _staged_src
    assert "import websockets" in _staged_src


# ── compute-mode selection must reach actual submission resources ────────
# Live bug: Prepare Cloud correctly created ec2_compute_environment /
# ec2_job_queue / icepack_job_definition_ec2, but Review & Launch / submit
# still resolved to the Fargate queue + job definition because
# resolve_job_definition() (Fargate-only allow_list, compute-mode-blind)
# always won over resolve_cloud_config()'s compute-mode-aware fallback. This
# traces the SAME path Review & Launch/direct-submit use, all the way to the
# kwargs handed to CloudRunController.submit() -- the actual submission
# resource resolution, not just a displayed label.
def _submit_and_capture(monkeypatch, tmp_path, *, user, model="icepack",
                         compute_mode="fargate", capacity="on_demand"):
    launch_handler = _build_gateway_and_launch_handler(monkeypatch, tmp_path, user=user)
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    cloud_environment = _freevar(submit_fn, "cloud_environment")
    _cloud = _freevar(submit_fn, "_cloud")

    model_dd.value = model
    example_dir.value = str(tmp_path / "Example")
    run_target.value = "run.py" if model == "icepack" else "runme.m"
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    # the documented Advanced Cloud Settings contract: blank -> CryoStack
    # derives the resource names from the selected compute mode.
    batch_job_queue.value = ""
    batch_job_def.value = ""
    cloud_environment.compute_mode.value = compute_mode
    cloud_environment.ec2_capacity.value = capacity

    import icesee_jupyter_book.ui.icesheets_gateway as _gw
    monkeypatch.setattr(_gw, "cloud_run_preflight", lambda **kw: [])

    captured = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(_cloud["controller"], "submit", fake_submit)

    # staged_dir deliberately != example_dir.value -- skips the local
    # staging branch (irrelevant here) and goes straight to submit().
    submit_fn(str(tmp_path / "already-staged"), {}, review=None)
    assert captured, "submit() was never reached"
    return captured


def test_ec2_on_demand_selection_submits_to_the_ec2_queue_and_job_definition(
    monkeypatch, tmp_path
):
    captured = _submit_and_capture(
        monkeypatch, tmp_path, user="ec2-ondemand-submit-user",
        compute_mode="ec2", capacity="on_demand",
    )
    assert captured["compute_mode"] == "ec2"
    assert captured["job_queue"] == "cryostack-ec2-queue"
    assert captured["job_definition"] == "cryostack-icepack-ec2"
    # the exact regression: must NOT resolve to Fargate
    assert captured["job_queue"] != "cryostack-queue"
    assert captured["job_definition"] != "cryostack-icepack"
    assert captured["compute_mode"] != "fargate"


def test_fargate_selection_still_submits_to_the_fargate_queue_and_job_definition(
    monkeypatch, tmp_path
):
    """The working Fargate path is unaffected by the EC2 fix."""
    captured = _submit_and_capture(
        monkeypatch, tmp_path, user="fargate-submit-user", compute_mode="fargate",
    )
    assert captured["compute_mode"] == "fargate"
    assert captured["job_queue"] == "cryostack-queue"
    assert captured["job_definition"] == "cryostack-icepack"


def test_ec2_spot_selection_submits_to_the_spot_queue_and_ec2_job_definition(
    monkeypatch, tmp_path
):
    captured = _submit_and_capture(
        monkeypatch, tmp_path, user="ec2-spot-submit-user",
        compute_mode="ec2", capacity="spot",
    )
    assert captured["compute_mode"] == "ec2"
    assert captured["job_queue"] == "cryostack-ec2-spot-queue"
    # capacity never changes the job definition -- On-Demand and Spot share it
    assert captured["job_definition"] == "cryostack-icepack-ec2"


def test_gpu_and_multinode_stay_guarded_by_the_existing_qualification_flags(
    monkeypatch, tmp_path
):
    """This fix only corrects NAME resolution -- it must never loosen the
    existing GPU/multi-node submission gate (unqualified image / unsupported
    distributed runtime). Both stay blocked before submit() is ever reached."""
    from cryostack_src.cloud.drivers.aws.batch_config import EC2ComputeConfig

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="gpu-mnp-guard-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")

    model_dd = _freevar(submit_fn, "model_dd")
    example_dir = _freevar(submit_fn, "example_dir")
    run_target = _freevar(submit_fn, "run_target")
    aws_region = _freevar(submit_fn, "aws_region")
    cloud_bucket = _freevar(submit_fn, "cloud_bucket")
    aws_profile = _freevar(submit_fn, "aws_profile")
    batch_job_queue = _freevar(submit_fn, "batch_job_queue")
    batch_job_def = _freevar(submit_fn, "batch_job_def")
    cloud_environment = _freevar(submit_fn, "cloud_environment")
    _cloud = _freevar(submit_fn, "_cloud")

    model_dd.value = "icepack"
    example_dir.value = str(tmp_path / "Example")
    run_target.value = "run.py"
    aws_region.value = "us-east-2"
    cloud_bucket.value = "cryostack-runs-774888247882"
    aws_profile.value = ""
    batch_job_queue.value = ""
    batch_job_def.value = ""
    cloud_environment.compute_mode.value = "ec2"

    submitted = {"called": False}
    monkeypatch.setattr(
        _cloud["controller"], "submit",
        lambda **kw: submitted.__setitem__("called", True))

    for accelerator, topology in (("gpu", "single_node"), ("none", "multi_node")):
        submitted["called"] = False
        cloud_environment.ec2_accelerator.value = accelerator
        cloud_environment.ec2_topology.value = topology
        submit_fn(str(tmp_path / "already-staged"), {}, review=None)
        assert not submitted["called"], (
            f"accelerator={accelerator!r} topology={topology!r} must stay "
            "blocked by the existing qualification flags"
        )


# ── Basic/Advanced mode must drive the ACTUAL resolved execution config,
# not just widget visibility -- live bug: switching Compute to EC2 never
# re-rendered Run Plan (no observer was wired on compute_mode at all), and
# Basic mode never forced the active compute_mode back to Fargate even
# though its own Advanced Cloud Settings were supposed to be irrelevant.
def _setup_common(state, *, model="icepack"):
    state["model_dd"].value = model
    state["mode_dd"].value = "cloud"
    state["example_dir"].value = str(Path("/tmp") / "GatewayStateExample")
    state["run_target"].value = "run.py" if model != "issm" else "runme.m"
    state["aws_region"].value = "us-east-2"
    state["cloud_bucket"].value = "cryostack-runs-774888247882"
    state["batch_job_queue"].value = ""
    state["batch_job_def"].value = ""


def _capture_submit(state, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        state["_cloud"]["controller"], "submit",
        lambda **kw: captured.update(kw))
    state["submit_fn"](
        str(Path("/tmp") / "already-staged"), {}, review=None)
    assert captured, "submit() was never reached"
    return captured


def test_basic_mode_hides_advanced_settings_and_stays_on_fargate(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="basic-icepack-user")
    _setup_common(state)
    state["ui_mode_dd"].value = "basic"

    ce = state["cloud_environment"]
    assert ce.advanced.layout.display == "none"
    assert ce.compute_mode.value == "fargate"

    html = state["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (Fargate)" in html
    assert "AWS Batch (EC2)" not in html

    captured = _capture_submit(state, monkeypatch)
    assert captured["compute_mode"] == "fargate"
    assert captured["job_queue"] == "cryostack-queue"
    assert captured["job_definition"] == "cryostack-icepack"


def test_advanced_mode_ec2_selection_flows_end_to_end(monkeypatch, tmp_path):
    """The success criterion: Run Plan, Review & Launch's resolved config,
    its cost basis, and the final submit kwargs all agree on EC2 -- from
    ONE widget change, with no manual re-render needed (the fix for the
    live staleness bug)."""
    state = _gateway_state(monkeypatch, tmp_path, user="advanced-ec2-user")
    _setup_common(state)
    state["ui_mode_dd"].value = "advanced"

    ce = state["cloud_environment"]
    assert ce.advanced.layout.display == ""

    ce.compute_mode.value = "ec2"
    ce.ec2_capacity.value = "on_demand"
    ce.ec2_instance_types.value = "optimal"
    ce.ec2_topology.value = "single_node"

    # Run Plan updated itself -- no manual update_summary() call here.
    html = state["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (EC2)" in html
    assert "AWS Batch (Fargate)" not in html
    assert "Capacity:</span> On-Demand" in html

    review = state["build_review"]()
    assert review.config.compute_mode == "ec2"
    assert review.config.job_queue == "cryostack-ec2-queue"
    assert review.config.job_definition == "cryostack-icepack-ec2"
    basis = " ".join(review.estimate_basis_lines())
    assert "EC2 cost estimate unavailable" in basis
    assert "AWS Fargate pricing" not in basis

    captured = _capture_submit(state, monkeypatch)
    assert captured["compute_mode"] == "ec2"
    assert captured["job_queue"] == "cryostack-ec2-queue"
    assert captured["job_definition"] == "cryostack-icepack-ec2"


def test_advanced_to_basic_reverts_the_active_backend_to_fargate(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="advanced-to-basic-user")
    _setup_common(state)
    ce = state["cloud_environment"]

    state["ui_mode_dd"].value = "advanced"
    ce.compute_mode.value = "ec2"
    ce.ec2_capacity.value = "spot"

    state["ui_mode_dd"].value = "basic"
    assert ce.compute_mode.value == "fargate"
    assert ce.advanced.layout.display == "none"

    html = state["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (Fargate)" in html

    captured = _capture_submit(state, monkeypatch)
    assert captured["compute_mode"] == "fargate"
    assert captured["job_queue"] == "cryostack-queue"
    assert captured["job_definition"] == "cryostack-icepack"


def test_basic_to_advanced_restores_the_prior_ec2_selection(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="basic-to-advanced-user")
    _setup_common(state)
    ce = state["cloud_environment"]

    state["ui_mode_dd"].value = "advanced"
    ce.compute_mode.value = "ec2"
    ce.ec2_capacity.value = "spot"
    ce.ec2_instance_types.value = "c5,m5"

    state["ui_mode_dd"].value = "basic"
    assert ce.compute_mode.value == "fargate"          # reverted

    state["ui_mode_dd"].value = "advanced"
    assert ce.compute_mode.value == "ec2"              # restored
    assert ce.ec2_capacity.value == "spot"
    assert ce.ec2_instance_types.value == "c5,m5"

    html = state["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (EC2)" in html
    assert "Capacity:</span> Spot" in html


# ── MATLAB license visibility: driven by workflow capability, never
# Basic/Advanced mode alone ──────────────────────────────────────────────
def test_issm_shows_matlab_license_in_basic_and_advanced(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="issm-matlab-basic-user")
    _setup_common(state, model="issm")

    state["ui_mode_dd"].value = "basic"
    assert state["cloud_environment"].matlab_license_box.layout.display == ""

    state["ui_mode_dd"].value = "advanced"
    assert state["cloud_environment"].matlab_license_box.layout.display == ""


def test_icepack_hides_matlab_license(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="icepack-matlab-hide-user")
    _setup_common(state, model="icepack")
    assert state["cloud_environment"].matlab_license_box.layout.display == "none"


def test_matlab_license_value_survives_being_hidden(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="matlab-preserve-user")
    ce = state["cloud_environment"]
    _setup_common(state, model="issm")
    assert ce.matlab_license_box.layout.display == ""

    arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:cryostack/issm-matlab-Ab1"
    ce.matlab_license_arn.value = arn

    state["model_dd"].value = "icepack"
    assert ce.matlab_license_box.layout.display == "none"
    assert ce.matlab_license_arn.value == arn          # never cleared

    state["model_dd"].value = "issm"
    assert ce.matlab_license_box.layout.display == ""
    assert ce.matlab_license_arn.value == arn


def test_fargate_review_cost_basis_says_fargate_pricing(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="fargate-cost-basis-user")
    _setup_common(state)
    state["ui_mode_dd"].value = "basic"
    review = state["build_review"]()
    basis = " ".join(review.estimate_basis_lines())
    assert "AWS Fargate pricing" in basis
    assert "EC2" not in basis


# ── checkpoint: container provenance + execution-summary semantics ───────
def _summary_internals(monkeypatch, tmp_path, *, user):
    page = _build_gateway_page(monkeypatch, tmp_path, user=user)
    _, update_visibility = _find_widget_by_observer(page, "update_visibility")
    update_summary = _freevar(update_visibility, "update_summary")
    return {
        "page": page,
        "update_visibility": update_visibility,
        "update_summary": update_summary,
        "summary_html": _freevar(update_summary, "summary_html"),
        "mode_dd": _freevar(update_summary, "mode_dd"),
        "model_dd": _freevar(update_summary, "model_dd"),
        "backend_dd": _freevar(update_summary, "backend_dd"),
        "command_preview": _freevar(update_summary, "command_preview"),
        "run_target": _freevar(update_summary, "run_target"),
        "STATUS": _freevar(update_summary, "STATUS"),
        "md_config_panel": _freevar(update_visibility, "md_config_panel"),
        "icepack_config_panel": _freevar(update_visibility, "icepack_config_panel"),
        "cloud_environment": _freevar(update_summary, "cloud_environment"),
    }


def test_execution_summary_has_an_explicit_cloud_branch(monkeypatch, tmp_path):
    """A cloud run must not read backend_dd (still 'spack' by default) -- it
    shows the AWS Batch compute substrate, the container model environment,
    and the exact tested image tag + digest."""
    from cryostack_src.models.stack import default_tested_image_for_model

    g = _summary_internals(monkeypatch, tmp_path, user="cloud-summary-user")
    g["model_dd"].value = "icepack"
    g["backend_dd"].value = "spack"          # deliberately the stale default
    g["mode_dd"].value = "cloud"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Execution mode:</span> Cloud" in html
    assert "Cloud backend:</span> AWS Batch (Fargate)" in html
    assert "Model environment:</span> ICESEE-Container (Spack-built stack)" in html
    assert "Model:</span> ICEPACK" in html
    assert "ICESEE-Spack" not in html                 # the old wrong label is gone
    img = default_tested_image_for_model("icepack")
    assert img.reference in html
    assert img.digest[:22] in html
    # command preview no longer shows a spack / apptainer command
    cmd = g["command_preview"].value
    assert "aws batch submit-job" in cmd
    assert "apptainer" not in cmd and "spack" not in cmd.lower()


def test_execution_summary_shows_ec2_backend_when_ec2_is_selected(monkeypatch, tmp_path):
    """Regression: the Run Plan / Execution summary used to hardcode
    'Cloud backend: AWS Batch (Fargate)' for every cloud run, regardless of
    the Advanced Cloud Settings Compute selection. Selecting EC2 must change
    the displayed backend, capacity and instance types -- not just leave the
    Fargate label standing while EC2 is what actually gets provisioned/
    submitted."""
    g = _summary_internals(monkeypatch, tmp_path, user="cloud-summary-ec2-user")
    g["model_dd"].value = "icepack"
    g["mode_dd"].value = "cloud"
    ce = g["cloud_environment"]
    ce.compute_mode.value = "ec2"
    ce.ec2_capacity.value = "on_demand"
    ce.ec2_instance_types.value = "optimal"
    ce.ec2_topology.value = "single_node"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (EC2)" in html
    assert "AWS Batch (Fargate)" not in html            # the exact regression
    assert "Capacity:</span> On-Demand" in html
    assert "Instance types:</span> optimal" in html
    assert "Single node" in html

    # Spot capacity is reflected too
    ce.ec2_capacity.value = "spot"
    g["update_summary"]()
    assert "Capacity:</span> Spot" in g["summary_html"].value

    # switching back to Fargate restores the original label
    ce.compute_mode.value = "fargate"
    g["update_summary"]()
    html_back = g["summary_html"].value
    assert "Cloud backend:</span> AWS Batch (Fargate)" in html_back
    assert "Capacity:</span>" not in html_back


def test_execution_summary_remote_spack_and_container_unchanged(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="remote-summary-user")
    g["model_dd"].value = "issm"
    g["mode_dd"].value = "remote"

    g["backend_dd"].value = "spack"
    g["update_summary"]()
    html_spack = g["summary_html"].value
    assert "Backend:</span> ICESEE-Spack" in html_spack
    assert "Cloud backend:" not in html_spack

    g["backend_dd"].value = "container"
    g["update_summary"]()
    html_container = g["summary_html"].value
    assert "Backend:</span> ICESEE-Container" in html_container
    assert "Cloud backend:" not in html_container


def test_cloud_submit_freezes_the_container_image_into_run_provenance(monkeypatch, tmp_path):
    """_register_cloud_run must persist the exact tested image tag + digest
    AND a container/software provenance block (the SAME manifest schema the
    Remote container path uses) so a historical run never drifts when the
    default image changes."""
    from cryostack_src.models.stack import default_tested_image_for_model

    launch_handler = _build_gateway_and_launch_handler(
        monkeypatch, tmp_path, user="cloud-prov-user")
    submit_fn = _freevar(launch_handler, "_submit_cloud_run")
    _cloud = _freevar(submit_fn, "_cloud")
    reg = _cloud["controller"]._register_run          # == _register_cloud_run
    workspace_bridge = _freevar(reg, "workspace_bridge")

    started = {}

    def fake_start_run(**kw):
        started.update(kw)

    monkeypatch.setattr(workspace_bridge, "start_run", fake_start_run)

    img = default_tested_image_for_model("icepack")

    class _Handle:
        model = "icepack"
        job_id = "job-xyz"
        run_id = "run-xyz"
        s3_run = "s3://cryostack-runs-774888247882/runs/u/run-xyz"
        region = "us-east-2"
        account_id = "774888247882"
        example = "00-meshes-functions"
        run_target = "run.py"
        source = "00-meshes-functions.ipynb"
        vcpu = 2
        memory_gib = 8
        expected_runtime_minutes = 5
        cost_public = {}
        metadata = {}
        image_key = img.key
        image_label = img.label
        image_reference = img.reference
        image_digest = img.digest

    class _Result:
        metadata = {"job_queue": "q", "job_definition": "cryostack-icepack"}

    reg(handle=_Handle(), result=_Result())

    md = started["metadata"]
    assert md["image_reference"] == img.reference
    assert md["image_digest"] == img.digest
    assert md["image_key"] == img.key
    # experiment identity persisted distinctly: example / source / run target
    assert md["example"] == "00-meshes-functions"
    assert md["source"] == "00-meshes-functions.ipynb"    # the .ipynb, not run.py
    assert md["run_target"] == "run.py"                   # what AWS Batch executed
    # reused container/software provenance schema (not a cloud-only format)
    container = started["container"]
    assert container["source"] == "docker"
    assert container["digest"] == img.digest
    assert img.reference in container["reference"]
    assert container["build_provenance"]["tested_image"] == img.key
    assert started["software"]                      # per-component provenance present
    assert started["backend"] == "aws"
    assert started["execution_mode"] == "cloud"


# ── UI-semantic cleanup: Basic-mode config title, cloud Run Plan source ──
def test_basic_config_accordion_follows_the_selected_model(monkeypatch, tmp_path):
    """Switching model must retitle the Basic-mode configuration accordion:
    Icepack selected -> the Icepack panel is shown, the ISSM panel hidden
    (and vice versa). Regression: update_visibility was not re-run on a
    model switch, so 'ISSM configuration (Basic)' stayed visible for
    Icepack."""
    g = _summary_internals(monkeypatch, tmp_path, user="basic-title-user")
    md, ip = g["md_config_panel"], g["icepack_config_panel"]

    g["model_dd"].value = "icepack"
    assert ip.layout.display == "" and md.layout.display == "none"
    assert ip.get_title(0) == "⚙️ Icepack configuration (Basic)"

    g["model_dd"].value = "issm"                      # ISSM behaviour preserved
    assert md.layout.display == "" and ip.layout.display == "none"
    assert md.get_title(0) == "⚙️ ISSM configuration (Basic)"


def test_cloud_run_plan_distinguishes_notebook_source_from_run_py(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="runplan-nb-user")
    g["model_dd"].value = "icepack"
    g["mode_dd"].value = "cloud"
    g["STATUS"]["selected_example_path"] = (
        "/home/u/icepack/notebooks/tutorials/00-meshes-functions.ipynb")
    g["run_target"].value = "run.py"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Example:</span> 00-meshes-functions" in html
    assert "Source:</span> <code>00-meshes-functions.ipynb</code>" in html
    assert "converted to <code>run.py</code> before staging" in html
    assert "Run target:</span> <code>run.py</code>" in html
    # never implies AWS runs the .ipynb
    assert ">00-meshes-functions.ipynb</code> <span class='icesee-subtle'>(executed on AWS Batch)" not in html
    assert "Selected example:" not in html            # the vague old line is gone


def test_cloud_run_plan_stays_truthful_for_an_issm_example(monkeypatch, tmp_path):
    g = _summary_internals(monkeypatch, tmp_path, user="runplan-issm-user")
    g["model_dd"].value = "issm"
    g["mode_dd"].value = "cloud"
    g["STATUS"]["selected_example_path"] = "/home/u/ISSM/examples/SquareIceShelf"
    g["run_target"].value = "runme.m"
    g["update_summary"]()

    html = g["summary_html"].value
    assert "Example:</span> SquareIceShelf" in html
    assert "Run target:</span> <code>runme.m</code>" in html
    # a directory example has no separate "Source:" file -- not fabricated
    assert "Source:</span>" not in html
    assert "converted to" not in html                 # no notebook language for ISSM


def test_advanced_cloud_settings_helper_states_the_blank_equals_prepared_contract(
    monkeypatch, tmp_path
):
    page = _build_gateway_page(monkeypatch, tmp_path, user="adv-helper-user")
    htmls = []

    def walk(w):
        if isinstance(w, W.HTML):
            htmls.append(w.value)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    caption = next((h for h in htmls if "Leave these fields blank" in h), "")
    assert caption, "advanced-cloud-settings helper text not found"
    assert "CryoStack-prepared resources for the connected AWS account" in caption
    assert "override that specific resource" in caption
    assert "Developer / override settings." not in "\n".join(htmls)   # old text gone


# ── matlab_license_requires_tunnel propagation: one resolved
# CloudMatlabLicense (CloudExecution.matlab_license) is the SOURCE of both
# matlab_license_configured and matlab_license_requires_tunnel handed to
# the real .submit(...) call -- no new resolution/profile logic, no
# Fargate/EC2 branching. ─────────────────────────────────────────────────
def _patch_matlab_license(monkeypatch, *, configured, requires_tunnel):
    """Patch CloudExecution.matlab_license itself (not
    resolve_cloud_matlab_license) -- in developer mode (no BYO connection,
    the test environment here) CloudExecution.matlab_license short-circuits
    on ``self.connection is None`` before ever calling the resolver, so the
    property itself is the only seam that reaches every caller."""
    import cryostack_src.cloud.matlab_license as ml
    from cryostack_src.cloud.connect.execution import CloudExecution

    fake = ml.CloudMatlabLicense(
        configured=configured,
        mechanism="secrets-manager" if configured else "none",
        secret_arn=("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
                    "cryostack/issm-matlab-Ab1" if configured else ""),
        requires_tunnel=requires_tunnel,
    )
    monkeypatch.setattr(CloudExecution, "matlab_license", property(lambda self: fake))
    return fake


def _connect_connector(state, monkeypatch):
    """Mark THIS test's kernel Connector session as paired/online --
    reuses the same SESSION/relay_check_status seam _connector_is_online
    reads, so a run that requires the Connector (matlab_license_requires_
    tunnel=True) can actually reach .submit(...) in tests that are not
    themselves about the Connector-pairing preflight gate."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )
    connector_is_online = _freevar(state["submit_fn"], "_connector_is_online")
    SESSION = _freevar(connector_is_online, "SESSION")
    SESSION["id"] = "sess-test"


def test_issm_pace_cloud_submission_passes_matlab_license_requires_tunnel_true(
    monkeypatch, tmp_path,
):
    """The exact live-acceptance scenario the trace identified: a connected
    account with a Georgia Tech/PACE MATLAB license configured
    (ComputeProfile.matlab_license_cloud_requires_tunnel == True for PACE)
    must reach AWSDriver.submit() -- here, the gateway's own .submit(...)
    call -- with matlab_license_requires_tunnel=True, not the previous
    always-False default. The Connector is paired here (via
    _connect_connector) because that is now also a fail-closed
    prerequisite -- the Connector-pairing gate itself is covered by
    test_preflight_blocks_launch_when_connector_required_but_not_paired."""
    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=True)
    state = _gateway_state(monkeypatch, tmp_path, user="issm-pace-tunnel-user")
    _setup_common(state, model="issm")
    _connect_connector(state, monkeypatch)

    captured = _capture_submit(state, monkeypatch)
    assert captured["matlab_license_configured"] is True
    assert captured["matlab_license_requires_tunnel"] is True


def test_icepack_non_matlab_workflow_does_not_require_the_tunnel(monkeypatch, tmp_path):
    """No MATLAB license configured on the connection (the ordinary Icepack
    user) -- matlab_license_requires_tunnel must stay False, never
    incorrectly True."""
    state = _gateway_state(monkeypatch, tmp_path, user="icepack-no-tunnel-user")
    _setup_common(state, model="icepack")

    captured = _capture_submit(state, monkeypatch)
    assert captured["matlab_license_configured"] is False
    assert captured["matlab_license_requires_tunnel"] is False


def test_matlab_license_configured_flag_is_unchanged_by_the_tunnel_propagation(
    monkeypatch, tmp_path,
):
    """matlab_license_configured must keep reflecting ONLY whether a license
    secret is configured -- independent of requires_tunnel -- proving the
    two fields are read from the same resolved object without coupling
    one's value to the other."""
    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=False)
    state = _gateway_state(monkeypatch, tmp_path, user="matlab-configured-only-user")
    _setup_common(state, model="issm")

    captured = _capture_submit(state, monkeypatch)
    assert captured["matlab_license_configured"] is True
    assert captured["matlab_license_requires_tunnel"] is False


def test_fargate_and_ec2_receive_the_same_tunnel_requirement_no_backend_branching(
    monkeypatch, tmp_path,
):
    """The tunnel requirement is backend-neutral: Fargate and EC2 must both
    receive the identical matlab_license_requires_tunnel value with no
    compute-mode-specific logic added at the gateway."""
    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=True)

    fargate = _submit_and_capture(
        monkeypatch, tmp_path, user="tunnel-fargate-user", model="issm",
        compute_mode="fargate",
    )
    ec2 = _submit_and_capture(
        monkeypatch, tmp_path, user="tunnel-ec2-user", model="issm",
        compute_mode="ec2",
    )
    assert fargate["matlab_license_requires_tunnel"] is True
    assert ec2["matlab_license_requires_tunnel"] is True
    assert fargate["matlab_license_configured"] is True
    assert ec2["matlab_license_configured"] is True
    # the compute-mode fields themselves still diverge normally -- only the
    # tunnel requirement is backend-neutral
    assert fargate["compute_mode"] != ec2["compute_mode"]


# ── INSTITUTIONAL CONNECTION: Cloud reuses the SAME Connector Remote uses ──
def _all_widgets(widget):
    out = [widget]

    def walk(w):
        for c in getattr(w, "children", ()):
            out.append(c)
            walk(c)

    walk(widget)
    return out


def _remote_open_connector_handler(page, cloud_environment):
    """The real "Open Connector..." button Remote renders -- distinct from
    Cloud's own institutional_connection_open_button (same label, a
    different widget) -- and its click handler (create_or_refresh_
    connector_session), by walking the built page."""
    candidates = [
        w for w in _all_widgets(page)
        if isinstance(w, W.Button) and w.description == "Open Connector..."
        and w is not cloud_environment.institutional_connection_open_button
    ]
    assert len(candidates) == 1, "expected exactly one Remote Open Connector... button"
    btn = candidates[0]
    return btn, btn._click_handlers.callbacks[0]


def _remote_disconnect_handler(page, cloud_environment):
    candidates = [
        w for w in _all_widgets(page)
        if isinstance(w, W.Button) and w.description == "Disconnect"
        and w is not cloud_environment.institutional_connection_disconnect_button
        and w is not cloud_environment.disconnect_button
    ]
    assert len(candidates) == 1, "expected exactly one Remote Disconnect button"
    btn = candidates[0]
    return btn, btn._click_handlers.callbacks[0]


def test_institutional_connection_hidden_for_icepack_only_workflow(monkeypatch, tmp_path):
    """Must remain hidden for Icepack-only / other workflows that do not
    require private institutional license connectivity."""
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-icepack-user")
    _setup_common(state, model="icepack")
    assert (state["cloud_environment"].institutional_connection_box
            .layout.display == "none")


def test_institutional_connection_shown_for_issm_pace_workflow(monkeypatch, tmp_path):
    """Shown only when the resolved workflow/license capability requires
    it -- ISSM at a site whose CloudMatlabLicense.requires_tunnel is True
    (PACE)."""
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-issm-user")
    _setup_common(state, model="issm")
    assert state["cloud_environment"].institutional_connection_box.layout.display == ""


def test_institutional_connection_starts_not_connected(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-initial-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]
    assert "not connected" in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_open_button.layout.display != "none"
    assert ce.institutional_connection_recheck_button.layout.display == "none"
    assert ce.institutional_connection_disconnect_button.layout.display == "none"


def test_remote_and_cloud_open_connector_share_the_exact_same_handler(monkeypatch, tmp_path):
    """No second Connector implementation, pairing, identity, or session:
    Cloud's Open Connector... action is literally the SAME function object
    Remote's own button calls."""
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-shared-open-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    _remote_btn, remote_handler = _remote_open_connector_handler(state["page"], ce)
    cloud_open_click = ce.institutional_connection_open_button._click_handlers.callbacks[0]
    cloud_open_connector_fn = _freevar(cloud_open_click, "open_connector")
    assert cloud_open_connector_fn is remote_handler


def test_remote_and_cloud_disconnect_share_the_exact_same_handler(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-shared-disc-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    _remote_btn, remote_handler = _remote_disconnect_handler(state["page"], ce)
    cloud_disc_click = ce.institutional_connection_disconnect_button._click_handlers.callbacks[0]
    cloud_disconnect_fn = _freevar(cloud_disc_click, "disconnect")
    assert cloud_disconnect_fn is remote_handler


def test_pairing_in_remote_is_immediately_reflected_in_cloud(monkeypatch, tmp_path):
    """pair in Remote -> Cloud immediately recognizes the same Connector."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-pair-remote-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, _handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()

    assert "connected" in ce.institutional_connection_status.value.lower()
    assert "not connected" not in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_open_button.layout.display == "none"
    assert ce.institutional_connection_disconnect_button.layout.display != "none"


def test_disconnect_in_cloud_is_immediately_reflected_in_remote(monkeypatch, tmp_path):
    """disconnecting/revoking the Connector updates both views consistently."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )
    cleared = {"called": False}
    monkeypatch.setattr(
        gw, "clear_connector_binding", lambda: cleared.__setitem__("called", True))

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-disc-cloud-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, remote_handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()
    assert "connected" in ce.institutional_connection_status.value.lower()

    SESSION = _freevar(remote_handler, "SESSION")
    relay_status = _freevar(remote_handler, "relay_status")
    disconnect_connector_btn = _freevar(remote_handler, "disconnect_connector_btn")
    assert SESSION.get("id") == "sess-1"

    ce.institutional_connection_disconnect_button.click()

    assert cleared["called"] is True
    assert SESSION.get("id") is None
    assert relay_status.value == ""
    assert disconnect_connector_btn.layout.display == "none"
    assert "not connected" in ce.institutional_connection_status.value.lower()


def test_no_duplicate_pairing_session_is_created(monkeypatch, tmp_path):
    """Clicking Open Connector... from Cloud after Remote already paired
    must not mint a second relay session -- there is exactly ONE Connector
    session, reused by both views."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-no-dup-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, _handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()
    ce.institutional_connection_open_button.click()   # already hidden, but even if invoked...
    ce.institutional_connection_recheck_button.click()

    assert calls["n"] == 1


def test_institutional_connection_never_leaks_implementation_details(monkeypatch, tmp_path):
    """The scientist only needs to know CryoStack needs the Connector to
    reach their institution -- Basic mode must not show tunnel/relay/
    WebSocket/session id/tunnel token/FlexNet/vendor daemon/host-port/
    MLM_LICENSE_FILE/Secrets Manager implementation details."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-abc123", "ws_url": "/connector/ws/sess-abc123",
            "pairing_code": "XZ99"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-no-leak-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, _handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()

    blob = "\n".join([
        ce.institutional_connection_status.value,
        "\n".join(w.value for w in _all_widgets(ce.institutional_connection_box)
                   if isinstance(w, W.HTML)),
    ]).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "session id", "token", "flexnet",
        "vendor", "mlm_license_file", "secrets manager",
    ):
        assert forbidden not in blob, forbidden
    # Cloud never renders the technical diagnostics (session id / ws path)
    # at all -- those stay confined to Remote's own Advanced accordion.
    # (The pairing-page link's href necessarily carries the opaque session
    # id as a URL parameter -- the same accepted, already-tested Remote
    # behaviour -- that is a navigation target, never a readable label.)
    assert "/connector/ws" not in blob


def test_existing_remote_controls_are_preserved(monkeypatch, tmp_path):
    """Restore the Remote Connector UI: the established compact controls
    (Connection method, Status, Check SSH Access, Open Connector..., and
    the existing Advanced section) remain present and reachable."""
    page = _build_gateway_page(monkeypatch, tmp_path, user="inst-conn-preserve-user")
    html = "\n".join(
        w.value for w in _all_widgets(page) if isinstance(w, W.HTML))
    assert "Compute resource" in html
    assert "Your HPC identity" in html
    assert "Access" in html
    assert "Status" in html

    buttons = [w for w in _all_widgets(page) if isinstance(w, W.Button)]
    assert any(b.description == "Check SSH Access" for b in buttons)
    assert any(b.description == "Open Connector..." for b in buttons)

    accordions = [w for w in _all_widgets(page) if isinstance(w, W.Accordion)]
    titles = [
        t for acc in accordions
        for t in (acc.titles if getattr(acc, "titles", None)
                   else [acc.get_title(i) for i in range(len(acc.children))])
    ]
    assert "Advanced" in titles
    assert "🔌 Remote connection" in titles


def test_preflight_blocks_launch_when_connector_required_but_not_paired(monkeypatch, tmp_path):
    """If institutional connectivity is required and no Connector is
    currently paired, Cloud launch must remain blocked before AWS
    submission -- the existing fail-closed cloud_run_preflight gate,
    reached before _cloud["controller"].submit(...) is ever called."""
    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=True)
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-preflight-block-user")
    _setup_common(state, model="issm")

    submitted = {"called": False}
    monkeypatch.setattr(
        state["_cloud"]["controller"], "submit",
        lambda **kw: submitted.__setitem__("called", True))

    state["submit_fn"](str(tmp_path / "already-staged"), {}, review=None)

    assert submitted["called"] is False


# ── Cloud completes the ENTIRE compact pairing flow itself (no switching
# to Remote merely to pair) ────────────────────────────────────────────
def test_pairing_initiated_entirely_from_cloud(monkeypatch, tmp_path):
    """A scientist must never have to switch to Remote merely to pair the
    Connector: clicking Cloud's own Open Connector... creates the session
    through the SAME create_or_refresh_connector_session Remote uses."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-cloud-1", "ws_url": "/x", "pairing_code": "QR77"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-pair-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()

    assert calls["n"] == 1
    open_click = ce.institutional_connection_open_button._click_handlers.callbacks[0]
    open_connector_fn = _freevar(open_click, "open_connector")
    SESSION = _freevar(open_connector_fn, "SESSION")
    assert SESSION.get("id") == "sess-cloud-1"


def test_cloud_displays_pairing_code_and_action_while_waiting(monkeypatch, tmp_path):
    """The exact fix for this task: previously Cloud lost the pairing code
    entirely (falling back to "Connector not connected") because refresh()
    only distinguished connected/not-connected. Now a waiting session shows
    the pairing code and the pairing-page action, reusing Remote's own
    presentation helpers."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-wait-1", "ws_url": "/x", "pairing_code": "QR77"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-waiting-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()

    assert "waiting" in ce.institutional_connection_status.value.lower()
    assert "QR77" in ce.institutional_connection_pairing_info.value
    assert "QR77" not in ce.institutional_connection_pairing_link.value  # never in the URL
    assert ce.institutional_connection_pairing_link.value.count("<a ") == 1
    assert "session=sess-wait-1" in ce.institutional_connection_pairing_link.value
    assert "app=icesheets" in ce.institutional_connection_pairing_link.value
    # scientist never needs to reload the page or change execution mode --
    # this is the SAME synchronous click -> refresh already proven above.
    assert ce.institutional_connection_open_button.layout.display == "none"
    assert ce.institutional_connection_recheck_button.layout.display != "none"
    assert ce.institutional_connection_disconnect_button.layout.display != "none"


def test_successful_cloud_pairing_updates_cloud_to_connected(monkeypatch, tmp_path):
    """Waiting -> connected, driven entirely from Cloud's own Re-check."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    online = {"value": False}
    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-succeed-1", "ws_url": "/x", "pairing_code": "QR77"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {
            "online": online["value"],
            "state": "connected" if online["value"] else "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-success-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()
    assert "waiting" in ce.institutional_connection_status.value.lower()

    online["value"] = True
    ce.institutional_connection_recheck_button.click()

    assert "connected" in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_pairing_info.value == ""
    assert ce.institutional_connection_pairing_link.value == ""
    assert ce.institutional_connection_recheck_button.layout.display != "none"
    assert ce.institutional_connection_disconnect_button.layout.display != "none"


def test_cloud_created_pairing_is_immediately_recognized_by_remote(monkeypatch, tmp_path):
    """Cloud -> pair -> Remote already connected (recognizes the SAME
    session/pairing code -- never a second Connector session)."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-cloud-2", "ws_url": "/x", "pairing_code": "MK55"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-to-remote-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()

    remote_btn, remote_handler = _remote_open_connector_handler(state["page"], ce)
    SESSION = _freevar(remote_handler, "SESSION")
    relay_status = _freevar(remote_handler, "relay_status")
    disconnect_connector_btn = _freevar(remote_handler, "disconnect_connector_btn")

    assert SESSION.get("id") == "sess-cloud-2"
    assert "connected" in relay_status.value.lower()
    assert disconnect_connector_btn.layout.display != "none"
    # Remote's own Open Connector... button, when clicked, must reuse the
    # SAME session rather than minting a new one -- proven separately by
    # test_no_duplicate_pairing_session_is_created below.
    assert remote_btn is not ce.institutional_connection_open_button


def test_remote_created_waiting_pairing_is_immediately_recognized_by_cloud(
    monkeypatch, tmp_path,
):
    """Remote -> start pairing (still waiting) -> Cloud shows the SAME
    pairing code/state without switching modes or reloading."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-remote-1", "ws_url": "/x", "pairing_code": "TT21"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-remote-to-cloud-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, _handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()

    assert "waiting" in ce.institutional_connection_status.value.lower()
    assert "TT21" in ce.institutional_connection_pairing_info.value
    assert "session=sess-remote-1" in ce.institutional_connection_pairing_link.value


def test_disconnect_from_remote_updates_cloud_state(monkeypatch, tmp_path):
    """disconnecting/revoking the Connector updates both views consistently
    -- the Remote -> Cloud direction (the Cloud -> Remote direction is
    covered by test_disconnect_in_cloud_is_immediately_reflected_in_remote)."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-rd-1", "ws_url": "/x", "pairing_code": "PP44"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )
    monkeypatch.setattr(gw, "clear_connector_binding", lambda: None)

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-remote-disc-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    remote_btn, remote_handler = _remote_open_connector_handler(state["page"], ce)
    remote_btn.click()
    assert "connected" in ce.institutional_connection_status.value.lower()

    remote_disconnect_btn, _h = _remote_disconnect_handler(state["page"], ce)
    remote_disconnect_btn.click()

    SESSION = _freevar(remote_handler, "SESSION")
    assert SESSION.get("id") is None
    assert "not connected" in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_open_button.layout.display != "none"
    assert ce.institutional_connection_disconnect_button.layout.display == "none"


def test_repeated_open_connector_from_cloud_does_not_create_duplicate_sessions(
    monkeypatch, tmp_path,
):
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-nodup-1", "ws_url": "/x", "pairing_code": "ZZ00"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-nodup-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()
    ce.institutional_connection_recheck_button.click()
    ce.institutional_connection_recheck_button.click()

    assert calls["n"] == 1


def test_cloud_institutional_connection_box_stays_compact(monkeypatch, tmp_path):
    """No duplicate/oversized Connector card in Cloud: the box carries the
    heading, caption, status line, pairing info/link lines and the
    actions row only -- nothing else, and no second "CryoStack Connector"
    heading duplicating the one already in Remote."""
    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-compact-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    children = list(ce.institutional_connection_box.children)
    assert len(children) == 6   # heading, caption, status, pairing info/link, actions
    for expected in (
        ce.institutional_connection_status,
        ce.institutional_connection_pairing_info,
        ce.institutional_connection_pairing_link,
    ):
        assert expected in children

    html = "\n".join(w.value for w in _all_widgets(ce.institutional_connection_box)
                      if isinstance(w, W.HTML))
    assert html.count("INSTITUTIONAL CONNECTION") == 1


def test_cloud_waiting_state_terminology_hygiene(monkeypatch, tmp_path):
    """Basic mode stays free of tunnel/relay/WebSocket/session-ID/token/
    FlexNet/vendor-port/MLM_LICENSE_FILE terminology in the waiting state
    too (not just not-connected/connected, already covered elsewhere)."""
    import icesee_jupyter_book.ui.icesheets_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-hygiene-1", "ws_url": "/connector/ws/sess-hygiene-1",
            "pairing_code": "HY99"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    state = _gateway_state(monkeypatch, tmp_path, user="inst-conn-cloud-hygiene-user")
    _setup_common(state, model="issm")
    ce = state["cloud_environment"]

    ce.institutional_connection_open_button.click()

    blob = "\n".join(w.value for w in _all_widgets(ce.institutional_connection_box)
                      if isinstance(w, W.HTML)).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "session id", "token", "flexnet",
        "vendor", "mlm_license_file", "secrets manager",
    ):
        assert forbidden not in blob, forbidden
    assert "/connector/ws" not in blob
