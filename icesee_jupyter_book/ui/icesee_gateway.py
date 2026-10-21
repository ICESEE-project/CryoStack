# icesee_jupyter_book/ui/icesee_gateway.py
from __future__ import annotations

import os
import time as _time
import threading
import uuid
import html as html_lib
import yaml
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
import ipywidgets as W

from IPython.display import display, Image

import zipfile
import shutil
import base64
import tarfile
import tempfile
from IPython.display import HTML, FileLink

from icesee_jupyter_book.core.connector_relay_client import (
    create_session,
    check_status as relay_check_status,
    clear_binding as clear_connector_binding,
    send_command,
)

from icesee_jupyter_book.core import ssh_key_manager
from icesee_jupyter_book.core.example_registry import EXAMPLES, enabled_names, selector_options
from cryostack_src.workspace import resolve_workspace_user, user_run_root, read_manifest
from cryostack_src.resources.profiles import get_compute_profile, initial_remote_fields
from cryostack_src.remote import RemoteBridge
from cryostack_src.remote.access_state import (
    enforce_remote_access,
    verify_remote_identity,
    identity_result_from_output,
    can_reuse_connectivity_identity,
    classify_ssh_failure,
    SSH_KEY_NOT_AUTHORIZED,
)
from icesee_jupyter_book.core.config_io import dump_yaml, load_yaml, with_legacy_parallel_flag
from icesee_jupyter_book.core.example_discovery import (
    find_run_script,
    find_params_template,
    find_report_notebook,
)
from icesee_jupyter_book.core.local_runner import (
    run_dir,
    run_local_example,
    LocalRunResult,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    render_slurm_script,
    ensure_local_ssh_key,
    remote_install_pubkey_with_password,
    explain_ssh_failure_hint,
    remote_test_connection,
    remote_job_status,
    remote_tail_log,
    remote_cancel_job,
    submit_remote_example,
    submit_remote_example_container,
    bootstrap_passwordless_ssh,
    connector_ssh,
    connector_fetch_archive,
    submit_remote_example_via_connector,
    submit_remote_example_container_via_connector,
    connector_get_public_key,
    RemoteSubmitResult,
)
from icesee_jupyter_book.core import run_records
from icesee_jupyter_book.core.runs_manager import IceseeRunsManager
from icesee_jupyter_book.ui.icesee_run_progress import run_progress_html
from icesee_jupyter_book.core.cloud_bridge_adapter import (
    IceseeCloudBridgeConfig,
    build_icesee_cloud_bridge,
    cloud_max_np,
    cloud_runtime_config,
    icesee_cloud_status,
    icesee_cloud_terminate,
    submit_icesee_cloud_run,
    sync_icesee_cloud_results,
)
from cryostack_src.cloud.diagnostics import merge_aws_resources, resources_from_poll
from cryostack_src.frontend.cryolauncher.cloud_experiments import cloud_status_update
from icesee_jupyter_book.core.run_records import da_identity_from_params
from cryostack_src.frontend.cryolauncher.workspace.toolbar import build_workspace_toolbar
from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
    set_cloud_status,
    set_run_estimate_view,
    wire_institutional_connection_widgets,
    wire_matlab_license_widgets,
)
from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities
from cryostack_src.frontend.cryolauncher.cloud_connect_runtime import build_aws_connect_callbacks
from cryostack_src.frontend.cryolauncher.cloud_runtime import build_cloud_environment_ops
from cryostack_src.cloud.review import InfrastructureReadiness
from icesee_jupyter_book.core.cloud_review import (
    build_icesee_cloud_review,
    completed_cloud_minutes,
    icesee_run_estimate,
    render_icesee_review_panel,
)

from icesee_jupyter_book.ui.shared_ssh_widgets import build_ssh_key_manager

from icesee_jupyter_book.ui.application_menus import (
    build_icesee_app_menu,
    load_cryostack_account_assets,
)

from icesee_jupyter_book.ui.shared_app_styles import (
    shared_application_styles,
)
from icesee_jupyter_book.ui.shared_remote_connection_panel import (
    build_remote_connection_panel,
    classify_bootstrap_result,
    connector_diagnostics_html,
    connector_pairing_link_html,
    connector_pairing_status_html,
)
from icesee_jupyter_book.ui.shared_slurm_resources_panel import (
    build_slurm_resources_panel,
)
from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
from icesee_jupyter_book.ui.shared_observer_guard import UIRefreshCoordinator
from cryostack_src import perf

from icesee_jupyter_book.ui.application_menus import (
    build_icesee_app_menu,
    load_cryostack_account_assets,
)

from icesee_jupyter_book.ui.shared_app_styles import (
    shared_application_styles,
)

from icesee_jupyter_book.ui.experiment_bridge import (
    ExperimentBridge,
    load_experiment_bridge,
)

import getpass

from icesee_jupyter_book.ui.workspace_bridge import (
    WorkspaceBridge,
    load_workspace_bridge,
)
from icesee_jupyter_book.ui.workspace_persistence import make_state_io
from cryostack_src.workspace.resource_state import (
    ResourceStateController,
    strip_secrets,
)

from icesee_jupyter_book.core.experiment_status import (
    experiment_update_from_job_status,
)
from icesee_jupyter_book.core import provenance as run_provenance
from icesee_jupyter_book.core import run_launcher
from icesee_jupyter_book.core import run_lifecycle
from icesee_jupyter_book.core.experiment_files import ExperimentFiles, Issue
from icesee_jupyter_book.core.local_jobs import JobMonitor, LocalJob
from icesee_jupyter_book.core.user_plots import PlotWorkspace
from icesee_jupyter_book.ui.icesee_workflow.examples import ExamplePicker
from icesee_jupyter_book.ui.icesee_workflow import (
    LaunchPanel, LocalEnvironmentPanel, ModeSelector, RunWorkspace, Stepper, Ticker, card, field,
    run_js, stylesheet,
)
from icesee_jupyter_book.ui.icesee_workflow.components import callout
from icesee_jupyter_book.core.remote_poll import POLL_SECONDS, RemoteStatusPoller

# ============================================================
# Params widgets factory
# ============================================================
def widget_for(key: str, val):
    if isinstance(val, str):
        if key.lower() == "filter_type":
            opts = ["EnKF", "DEnKF", "EnTKF", "EnRSKF"]
            return W.Dropdown(options=opts, value=val if val in opts else opts[0], layout=W.Layout(width="100%"))
        if key.lower() in {"parallel_flag", "parallel"}:
            opts = ["serial", "MPI", "MPI_model"]
            return W.Dropdown(options=opts, value=val if val in opts else opts[0], layout=W.Layout(width="100%"))
        return W.Text(value=val, layout=W.Layout(width="100%"))

    if isinstance(val, bool):
        return W.Checkbox(value=val)

    if isinstance(val, int) and not isinstance(val, bool):
        return W.IntText(value=val, layout=W.Layout(width="100%"))
    if isinstance(val, float):
        return W.FloatText(value=val, layout=W.Layout(width="100%"))

    if isinstance(val, (list, dict)):
        return W.Textarea(
            value=yaml.safe_dump(val, sort_keys=False).strip(),
            layout=W.Layout(width="100%", height="110px"),
        )

    if val is None:
        # YAML null: an empty field that stays null unless the user types a
        # value (str(None) would come back as the string "None")
        w = W.Text(value="", placeholder="null", layout=W.Layout(width="100%"))
        w._icesee_null = True
        return w

    return W.Text(value=str(val), layout=W.Layout(width="100%"))


def read_widget(w):
    if getattr(w, "_icesee_null", False) and (w.value or "").strip() in ("", "null", "None", "~"):
        return None
    if isinstance(w, W.Textarea):
        try:
            return yaml.safe_load(w.value)
        except Exception:
            return w.value
    if hasattr(w, "value"):
        return w.value
    return None

# ===========================================================
# local reporting helpers (also used by remote when fetching results)
# ===========================================================

def make_zip_from_dir(src_dir: Path, zip_path: Path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(src_dir))

back_link = W.HTML("""
<style>
.icesee-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: #0d6efd;
  text-decoration: none;
  transition: color 0.15s ease, transform 0.15s ease;
}

.icesee-back:hover {
  color: #0b5ed7;
  transform: translateX(-1px);
}

.icesee-back-wrap {
  margin-bottom: 14px;
}
</style>

<div class="icesee-back-wrap">
  <a href="https://cryostack.eas.gatech.edu/index.html#" class="icesee-back">
    ← Back to CryoStack Home
  </a>
</div>
""")

app_menu = build_icesee_app_menu()
shared_styles = shared_application_styles()

# ============================================================
# UI builder (single entry point)
# ============================================================
def build_icesee_ui():
    _perf_t0 = _time.perf_counter()
    try:
        load_cryostack_account_assets()
        load_experiment_bridge()
        load_workspace_bridge()

        shared_styles = shared_application_styles()

        experiment_bridge = ExperimentBridge()
        workspace_bridge = WorkspaceBridge()

        # -----------------------------
        # UI state containers
        # -----------------------------
        STATUS = {"mode": "idle", "remote_dir": None, "jobid": None, "batch_job_id": None, "s3_run": None}

        SESSION = {
            "id": None,
            "ws_url": None,
        }

        #: late-bound hooks into the workflow UI (built at the end of this function)
        _WF: dict = {}

        def set_status(state: str):
            cls = {"idle": "icesee-idle", "running": "icesee-running", "done": "icesee-done", "fail": "icesee-fail"}[state]
            label = {"idle": "Idle", "running": "Running…", "done": "Done", "fail": "Failed"}[state]
            status_chip.value = f"<span class='icesee-status {cls}'>{label}</span>"
            if "activity" in _WF:
                _WF["activity"](state)

        # -----------------------------
        # Top controls
        # -----------------------------
        # every example key (the visible Application/Example pickers follow it,
        # see icesee_workflow/examples.py); legacy keys resolve on selection
        example_dd = W.Dropdown(options=selector_options(), value=enabled_names()[0], layout=W.Layout(width="320px"))
        preset_dd = W.Dropdown(options=["Default"], value="Default", layout=W.Layout(width="320px"))

        filter_alg_dd = W.Dropdown(
            options=[("EnKF", "EnKF"), ("DEnKF", "DEnKF"), ("EnTKF", "EnTKF"), ("EnRSKF", "EnRSKF")],
            value="EnKF",
            layout=W.Layout(width="320px"),
        )

        output_label_dd = W.Dropdown(
            options=[("true-wrong (demo output)", "true-wrong"), ("EnKF (output name)", "enkf")],
            value="true-wrong",
            layout=W.Layout(width="320px"),
        )

        ens_sl = W.IntSlider(min=1, max=200, value=30, layout=W.Layout(width="320px"), continuous_update=False)
        seed_in = W.IntText(value=1, layout=W.Layout(width="320px"))

        gen_report = W.Checkbox(value=True, description="Generate report (read_results.ipynb)")
        open_latest = W.Checkbox(value=False, description="After run: open latest run folder")

        # run_btn = W.Button(description="Run", button_style="success", icon="play")
        action_btn = W.Button(description="Run", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", button_style="", icon="trash")
        

        status_chip = W.HTML("<span class='icesee-status icesee-idle'>Idle</span>")
        log_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.12)",
            padding="10px",
            height="360px",
            overflow="auto",
            width="100%"
        ))

        results_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.12)",
            padding="10px",
            height="620px",
            overflow="auto",
            width="100%"
        ))

        # -----------------------------
        # Mode Tabs
        # -----------------------------
        MODE_LOCAL, MODE_REMOTE, MODE_CLOUD = "local", "cluster", "cloud"
        # The environment panel of the selected mode (Local / Remote / Cloud);
        # the Mode selector above Run settings drives selected_index.
        mode_tabs = W.Stack()
        mode_tabs.layout = W.Layout(width="100%")
        mode_tabs.layout.flex = "1 1 auto"
        mode_tabs.layout.min_width = "0"

        def get_mode():
            return {0: MODE_LOCAL, 1: MODE_REMOTE, 2: MODE_CLOUD}.get(mode_tabs.selected_index, MODE_LOCAL)
        
        def update_action_button():
            mode = get_mode()
            if mode == MODE_LOCAL:
                action_btn.description = "Run"
                action_btn.icon = "play"
                action_btn.button_style = "success"
            elif mode == MODE_REMOTE:
                action_btn.description = "Submit (Remote)"
                action_btn.icon = "server"
                action_btn.button_style = "warning"
            else:
                action_btn.description = "Submit (Cloud)"
                action_btn.icon = "cloud-upload"
                action_btn.button_style = "warning"

        def on_action_click(_=None):
            # simple anti-double-submit (optional but recommended)
            if STATUS.get("_busy"):
                with log_out:
                    print("[ui] Busy — ignoring extra click.")
                return

            STATUS["_busy"] = True
            action_btn.disabled = True
            try:
                mode = get_mode()
                if mode == MODE_LOCAL:
                    return run_example_local()
                elif mode == MODE_REMOTE:
                    return run_example_remote_submit()
                else:
                    return run_example_cloud_submit()
            finally:
                action_btn.disabled = False
                STATUS["_busy"] = False

        # =========================================================
        # Params UI (auto from template)
        # =========================================================
        params_holder = W.VBox([])
        params_accordion = None
        PARAMS0 = {}
        WIDGETS = {}
        EXTRA_YAML = {}
        RUN_SCRIPT = None
        TEMPLATE = None
        REPORT_NB = None

        _TEMPLATE = {"data": {}}     # the example's own params.yaml (validation reference)

        def build_params_ui(template_path):
            """The full-configuration form from the example's params.yaml
            (a path) or from a configuration mapping (Editor -> Apply)."""
            nonlocal params_accordion, PARAMS0, WIDGETS, EXTRA_YAML
            PARAMS0 = dict(template_path) if isinstance(template_path, dict) else load_yaml(template_path)
            WIDGETS = {}
            EXTRA_YAML = {}

            children, titles = [], []

            for sec, sec_dict in (PARAMS0 or {}).items():
                titles.append(sec)
                sec_widgets = {}
                rows = []

                if isinstance(sec_dict, dict):
                    for k, v in sec_dict.items():
                        w = widget_for(k, v)
                        sec_widgets[k] = w
                        rows.append(
                            W.HBox(
                                [W.HTML(f"<div class='icesee-k'>{k}</div>"), w],
                                layout=W.Layout(gap="12px"),
                            )
                        )

                    extra = W.Textarea(
                        value="# Add future keys here (YAML)\n",
                        layout=W.Layout(width="100%", height="90px"),
                    )
                    EXTRA_YAML[sec] = extra
                    rows.append(W.HTML("<div class='icesee-subtle' style='margin-top:6px'>Extra keys (optional)</div>"))
                    rows.append(extra)
                else:
                    w = W.Textarea(
                        value=yaml.safe_dump(sec_dict, sort_keys=False).strip(),
                        layout=W.Layout(width="100%", height="140px"),
                    )
                    sec_widgets["__raw__"] = w
                    rows.append(w)

                WIDGETS[sec] = sec_widgets
                children.append(W.VBox(rows, layout=W.Layout(gap="8px")))

            params_accordion = W.Accordion(children=children)
            for i, t in enumerate(titles):
                params_accordion.set_title(i, t)

        def sync_quick_into_widgets():
            sec = None
            for candidate in ["enkf-parameters", "enkf_parameters", "enkf"]:
                if candidate in WIDGETS:
                    sec = candidate
                    break
            if not sec:
                return

            if "Nens" in WIDGETS[sec]:
                WIDGETS[sec]["Nens"].value = int(ens_sl.value)
            if "seed" in WIDGETS[sec]:
                WIDGETS[sec]["seed"].value = int(seed_in.value)
            if "filter_type" in WIDGETS[sec]:
                WIDGETS[sec]["filter_type"].value = str(filter_alg_dd.value)

        def build_config_from_widgets() -> dict:
            cfg = {}
            for sec, sw in WIDGETS.items():
                if "__raw__" in sw:
                    cfg[sec] = yaml.safe_load(sw["__raw__"].value)
                    continue

                cfg[sec] = {}
                for k, w in sw.items():
                    if k == "__raw__":
                        continue
                    cfg[sec][k] = read_widget(w)

                extra = EXTRA_YAML.get(sec)
                if extra:
                    txt = extra.value.strip()
                    if txt and not txt.startswith("#"):
                        extra_obj = yaml.safe_load(txt) or {}
                        if isinstance(extra_obj, dict):
                            cfg[sec].update(extra_obj)
                        else:
                            cfg[sec]["__extra__"] = extra_obj
            return cfg

        # -----------------------------
        # Rebuild on example change
        # -----------------------------
        def rebuild_for_example(_=None):
            nonlocal RUN_SCRIPT, TEMPLATE, REPORT_NB
            cfg = EXAMPLES[example_dd.value]
            RUN_SCRIPT = find_run_script(cfg)
            TEMPLATE = find_params_template(cfg)
            REPORT_NB = find_report_notebook(cfg)

            _TEMPLATE["data"] = load_yaml(TEMPLATE)
            build_params_ui(TEMPLATE)
            params_holder.children = (params_accordion,)
            if "example_changed" in _WF:
                _WF["example_changed"]()

            with log_out:
                print("[Loaded]")
                print("Template:", TEMPLATE)
                print("Runner  :", RUN_SCRIPT)
                print("Report  :", REPORT_NB if REPORT_NB else "(none)")

        example_dd.observe(rebuild_for_example, names="value")

        # =========================================================
        # Remote panel widgets
        #
        # Ownership: RESOURCE facts (host, port, partition, wall time) come from
        # the ComputeProfile; USER x RESOURCE / USER fields (HPC username, remote
        # directory, Slurm account, notification email) are BLANK until B2 and
        # are never taken from the Voila service account's environment.
        # =========================================================
        _INITIAL_CLUSTER = "pace"
        _rf = initial_remote_fields(_INITIAL_CLUSTER)

        cluster_name_for_keys = W.Text(
            value=_INITIAL_CLUSTER, placeholder="e.g. pace, ub-ccr, frontera",
            continuous_update=False,   # resource switch on commit, not per keystroke
            layout=W.Layout(width="320px"),
        )
        cluster_host = W.Text(value=_rf["login_host"], placeholder="resource login host", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=_rf["hpc_username"], placeholder=_rf["username_hint"], layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=_rf["ssh_port"], layout=W.Layout(width="120px"))

        auth_mode = W.ToggleButtons(
        options=[("Key-only", "key"), ("Bootstrap with password (one-time)", "bootstrap")],
        value="key",
        layout=W.Layout(width="auto", max_width="100%")
        )

        cluster_password = W.Password(
            value="",
            placeholder="One-time password (not stored)",
            layout=W.Layout(width="320px")
        )

        bootstrap_btn = W.Button(
            description="Enable passwordless SSH",
            icon="key",
            button_style="warning"
        )

        remote_base_dir = W.Text(value=_rf["remote_directory"], placeholder="your remote working directory (required)", layout=W.Layout(width="320px"))
        remote_tag = W.Text(value="icesee", layout=W.Layout(width="220px"))

        exec_backend_choice = W.Dropdown(
            options=[("ICESEE-Spack", "spack"), ("ICESEE-Container", "container")],
            value="spack",
            layout=W.Layout(width="320px"),
        )

        container_source = W.Dropdown(
            options=[("Docker Hub", "docker"), ("AWS Registry", "aws")],
            value="docker",
            layout=W.Layout(width="220px"),
        )

        access_mode_dd = W.Dropdown(
            options=[
                ("CryoStack Connector (recommended)", "connector"),
                ("Direct SSH from server (shared-trust / developer)", "direct"),
                ("Auto", "auto"),
            ],
            value="connector",
            layout=W.Layout(width="320px"),
        )

        relay_status = W.HTML("")
        connector_setup_link = W.HTML("")
        connector_diagnostics = W.HTML("")

        start_connector_session_btn = W.Button(
            description="Create connector session",
            icon="plug",
            button_style="info",
        )
        disconnect_connector_btn = W.Button(
            description="Disconnect",
            icon="unlink",
            button_style="",
            layout=W.Layout(display="none"),
        )

        container_image_uri = W.Text(
            value="icesee/combined-container:latest",
            layout=W.Layout(width="520px"),
        )

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        submit_btn = W.Button(description="Submit job", icon="server", button_style="warning")
        status_btn = W.Button(description="Check status", icon="tasks", button_style="")
        tail_btn = W.Button(description="Tail log", icon="file-text", button_style="")
        terminate_btn = W.Button(description="Terminate job",icon="stop",button_style="danger")

        preview_results_btn = W.Button(
            description="Preview results",
            icon="eye",
            button_style="info",
        )

        results_download_btn = W.Button(
            description="Download results",
            icon="download",
            button_style="success",
        )

        slurm_job_name = W.Text(value="ICESEE", layout=W.Layout(width="100%"))              # RUN
        slurm_time = W.Text(value=_rf["wall_time"], layout=W.Layout(width="100%"))           # RESOURCE default

        slurm_nodes = W.IntText(value=2, layout=W.Layout(width="100%"))                      # RUN
        slurm_ntasks = W.IntText(value=24, layout=W.Layout(width="100%"))                    # RUN
        slurm_tpn = W.IntText(value=24, layout=W.Layout(width="100%"))                       # RUN

        slurm_part = W.Text(value=_rf["partition"], layout=W.Layout(width="100%"))           # RESOURCE default
        slurm_mem = W.Text(value="256G", layout=W.Layout(width="100%"))                             # RUN
        slurm_account = W.Text(                                                                     # USER x RESOURCE -- blank
            value=_rf["slurm_account"],
            placeholder=("Slurm allocation (required for this resource)"
                         if _rf["account_required"] else "Slurm allocation"),
            layout=W.Layout(width="100%"),
        )
        slurm_mail = W.Text(                                                                        # USER -- blank
            value=_rf["notification_email"],
            placeholder="notification email (optional)",
            layout=W.Layout(width="100%"),
        )

        cluster_mpi_np = W.IntText(value=40, layout=W.Layout(width="100%"))
        cluster_model_nprocs = W.IntText(value=4, layout=W.Layout(width="100%"))

        def _icesee_run_dir_base() -> Path:
            """Per-user, per-app run root -- two authenticated CryoStack users
            never share a run directory (the process-global BOOK/icesee_runs/
            did). Falls back to the default location for an unauthenticated
            session."""
            try:
                return user_run_root(app="icesee")
            except Exception:
                return None   # local_runner.run_dir() then uses its default

        def _new_icesee_run_id() -> str:
            return datetime.now().strftime("%Y%m%d_%H%M%S") + "-" + uuid.uuid4().hex[:6]

        def _record_icesee_run(
            *, run_dir, run_id, params, example, execution_mode, backend,
            source="", run_target="", model_environment="", status="running",
            jobid=None, remote_directory=None, extra_metadata=None,
        ):
            """Write a local .cryostack-run.json manifest for this ICESEE run
            (run_records.record_run) without ever letting a manifest failure
            interrupt the real run -- a warning in the log is the worst case."""
            state = run_lifecycle.normalize(status) or status
            extra_metadata = {**(extra_metadata or {}), "lifecycle": [
                {"state": state, "at": datetime.now().isoformat(timespec="seconds"), "detail": ""}]}
            status = state
            try:
                return run_records.record_run(
                    run_dir=run_dir, run_id=run_id,
                    name=f"ICESEE {example} ({execution_mode})",
                    params=params, example=example, execution_mode=execution_mode,
                    backend=backend, source=source, run_target=run_target,
                    model_environment=model_environment, status=status,
                    jobid=jobid, remote_directory=remote_directory,
                    extra_metadata=extra_metadata,
                )
            except Exception as _e:
                with log_out:
                    print("[history][WARN] could not record run:", type(_e).__name__, _e)
                return None

        def _update_icesee_run(run_dir, **kwargs):
            """Update a previously recorded ICESEE run manifest. Same
            never-break-the-run contract as _record_icesee_run. A status goes
            through the run lifecycle (backend words normalised; stale or
            backwards reports ignored)."""
            try:
                status = kwargs.pop("status", None)
                info = None
                if status is not None:
                    info = run_lifecycle.apply_backend_status(run_dir, status)
                if kwargs:
                    info = run_records.update_run(run_dir, **kwargs)
                return info
            except Exception as _e:
                with log_out:
                    print("[history][WARN] could not update run history:", type(_e).__name__, _e)
                return None

        def _merge_icesee_aws_resources(run_dir_path, updates: dict) -> None:
            """Merge ``updates`` into this run's persisted metadata['aws_resources']
            (cryostack_src.cloud.diagnostics.merge_aws_resources: non-secret keys
            only, never overwrites a known value with an empty one) so the
            reused Workspace history panel's AWS-diagnostics console links work
            for ICESEE cloud runs too -- the same pure snapshot mechanism
            CryoLauncher's cloud runs already use."""
            try:
                manifest = Path(run_dir_path) / run_records.MANIFEST_NAME
                existing = read_manifest(manifest).metadata.get("aws_resources") if manifest.is_file() else None
            except Exception:
                existing = None
            merged = merge_aws_resources(existing, updates)
            _update_icesee_run(run_dir_path, extra_metadata={"aws_resources": merged})

        def local_remote_cache_dir() -> Path:
            rd = run_dir(_icesee_run_dir_base(), _new_icesee_run_id())
            return rd / "_remote_fetch"


        def fetch_remote_outputs_to_local(target_dir: Path | None = None) -> Path | None:
            """Copy the remote job's outputs/ to ``target_dir`` (default: a
            fresh cache folder)."""
            rdir = STATUS.get("remote_dir")
            if not rdir:
                with results_out:
                    print("[results] No remote run directory found. Submit a job first.")
                return None

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            outputs_dir = Path(target_dir) if target_dir is not None else local_remote_cache_dir() / "outputs"

            if outputs_dir.exists():
                shutil.rmtree(outputs_dir)
            outputs_dir.mkdir(parents=True, exist_ok=True)

            remote_outputs = f"{str(rdir).rstrip('/')}/outputs"

            if access_mode_dd.value == "connector":
                if not SESSION.get("id"):
                    create_or_refresh_connector_session()

                result = connector_fetch_archive(
                    SESSION["id"],
                    host,
                    user,
                    port,
                    f"{remote_outputs.rstrip('/')}/",
                    timeout=600,
                )

                if not result.get("ok"):
                    with results_out:
                        print("[results][ERROR] Could not fetch remote outputs through connector.")
                        print("Remote source:", remote_outputs)
                        print(result)
                    return None

                archive_b64 = result.get("archive_b64")
                if not archive_b64:
                    with results_out:
                        print("[results][ERROR] Connector response did not include archive_b64.")
                    return None

                with tempfile.TemporaryDirectory() as td:
                    archive_path = Path(td) / "outputs.tar.gz"
                    archive_path.write_bytes(base64.b64decode(archive_b64))

                    with tarfile.open(archive_path, "r:gz") as tar:
                        tar.extractall(outputs_dir)

                return outputs_dir

            rsync_cmd = [
                "rsync",
                "-az",
                "-e",
                f"ssh -p {port}",
                f"{user}@{host}:{remote_outputs.rstrip('/')}/",
                f"{outputs_dir}/",
            ]

            rs = subprocess.run(rsync_cmd, capture_output=True, text=True)

            if rs.returncode != 0:
                with results_out:
                    print("[results][ERROR] Could not fetch remote outputs.")
                    print("Remote source:", remote_outputs)
                    print("--- stdout ---")
                    print(rs.stdout)
                    print("--- stderr ---")
                    print(rs.stderr)
                return None

            return outputs_dir
        

        def preview_remote_results(_=None):
            results_out.clear_output()

            outputs_dir = fetch_remote_outputs_to_local()
            if outputs_dir is None:
                return

            pngs = sorted(outputs_dir.rglob("*.png"))
            h5s = sorted(outputs_dir.rglob("*.h5"))
            all_files = sorted([p for p in outputs_dir.rglob("*") if p.is_file()])

            with results_out:
                print("Fetched outputs:", outputs_dir)
                print(f"H5 files: {len(h5s)}")
                print(f"PNG figures: {len(pngs)}\n")

                if all_files:
                    print("Output tree:")
                    for p in all_files[:50]:
                        print(" -", p.relative_to(outputs_dir))
                    print()

                if pngs:
                    print("Preview figures:")
                    for p in pngs[:8]:
                        print("\n", p.name)
                        display(Image(filename=str(p)))
                else:
                    print("No PNG figures found.")

                display(HTML(run_progress_html(outputs_dir)))


        def download_results_bundle(_=None):
            results_out.clear_output()

            outputs_dir = fetch_remote_outputs_to_local()
            if outputs_dir is None:
                return

            zip_path = local_remote_cache_dir() / "results_bundle.zip"

            if zip_path.exists():
                zip_path.unlink()

            make_zip_from_dir(outputs_dir, zip_path)

            with results_out:
                print("Results bundle ready:")
                display(FileLink(str(zip_path)))
            

        def form_pair(label: str, widget, label_width: str = "80px", widget_width: str = "1fr"):
            lbl = W.HTML(f"<div class='icesee-lbl-sm'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            widget.layout = W.Layout(width="100%")
            box = W.HBox([lbl, widget], layout=W.Layout(align_items="center", gap="8px", width="100%"))
            return box

        # minimal module/export lines (you can expand later)
        remote_module_lines = W.Textarea(
            value="# module load ...\n",
            layout=W.Layout(width="100%", height="80px"),
        )
        remote_export_lines = W.Textarea(
            value="# export ISSM_DIR=...\n",
            layout=W.Layout(width="100%", height="80px"),
        )

        remote_backend = W.ToggleButtons(
            options=[("SSH (Slurm)", "ssh"), ("HTTPS (Webhook)", "https")],
            value="ssh",
            layout=W.Layout(width="320px")
        )

        https_base = W.Text(value="", placeholder="https://your-service.example.com", layout=W.Layout(width="520px"))
        https_submit_path = W.Text(value="/submit", layout=W.Layout(width="260px"))
        https_status_path = W.Text(value="/status", layout=W.Layout(width="260px"))  # will call /status/<run_id>
        https_tail_path   = W.Text(value="/tail", layout=W.Layout(width="260px"))    # will call /tail/<run_id>?n=120
        https_health_path = W.Text(value="/health", layout=W.Layout(width="260px"))

        https_token = W.Password(value="", placeholder="optional bearer token", layout=W.Layout(width="320px"))
        https_headers = W.Textarea(
            value="# optional extra headers (YAML dict)\n# X-API-Key: abc\n",
            layout=W.Layout(width="100%", height="80px")
        )

        https_webhook_box = W.VBox([
        W.HTML("<div class='icesee-subtle'>HTTPS backend (user-provided webhook/service)</div>"),
        W.HBox([W.HTML("<div class='icesee-lbl'>Base URL:</div>"), https_base], layout=W.Layout(gap="12px")),
        W.HBox([W.HTML("<div class='icesee-lbl'>Paths:</div>"),
                https_submit_path, https_status_path, https_tail_path, https_health_path],
            layout=W.Layout(gap="8px")),
        W.HBox([W.HTML("<div class='icesee-lbl'>Token:</div>"), https_token], layout=W.Layout(gap="12px")),
        W.HTML("<div class='icesee-subtle'>Extra headers (YAML)</div>"),
        https_headers,
        ], layout=W.Layout(gap="8px"))

        ood_cluster = W.Dropdown(
            options=[
                ("Phoenix OnDemand", "https://ondemand-phoenix.pace.gatech.edu/pun/sys/dashboard/"),
                ("Hive OnDemand",    "https://ondemand-hive.pace.gatech.edu/pun/sys/dashboard/"),
                ("ICE OnDemand",     "https://ondemand-ice.pace.gatech.edu/pun/sys/dashboard/"),
            ],
            value="https://ondemand-phoenix.pace.gatech.edu/pun/sys/dashboard/",
            layout=W.Layout(width="520px")
        )

        open_ood_btn = W.Button(description="Open OnDemand", icon="external-link", button_style="info")

        # --- ICESEE-Spack bootstrap ---
        spack_enable = W.Checkbox(value=True, description="Use ICESEE-Spack on Remote")
        spack_repo_url = W.Text(
            value="https://github.com/ICESEE-project/ICESEE-Spack.git",
            layout=W.Layout(width="520px"),
        )
        spack_dirname = W.Text(value="ICESEE-Spack", layout=W.Layout(width="220px"))

        spack_install_if_needed = W.Checkbox(value=False, description="Run install.sh if not installed")
        spack_install_mode = W.Dropdown(
            options=[
                ("Default", ""),
                ("With ISSM", "--with-issm"),
                ("With Firedrake", "--with-firedrake"),
                ("With Icepack", "--with-icepack"),
            ],
            value="--with-issm",
            layout=W.Layout(width="220px"),
        )

        # README mentions SLURM_DIR + PMIX_DIR for install.sh
        spack_slurm_dir = W.Text(value="", placeholder="e.g. /opt/slurm/current", layout=W.Layout(width="320px"))
        spack_pmix_dir  = W.Text(value="", placeholder="e.g. /opt/pmix/5.0.1", layout=W.Layout(width="320px"))

        # Optional: use an existing sbatch from the repo if present
        spack_use_existing_sbatch = W.Checkbox(
            value=True,
            description="If run_job_spack.sbatch exists for this example, submit it",
        )

        ssh_box = W.VBox([
        # existing SSH fields: host/user/port/auth/... and buttons
        ])

        ondemand_box = W.VBox([
            W.HTML("<div class='icesee-subtle'>OnDemand (web portal)</div>"),
            W.HBox([W.HTML("<div class='icesee-lbl'>Portal:</div>"), ood_cluster], layout=W.Layout(gap="12px")),
            W.HBox([open_ood_btn], layout=W.Layout(gap="10px")),
            W.HTML("<div class='icesee-subtle'>Tip: You may need GT VPN to access OnDemand.</div>"),
        ])

        # Reassigned below, once the Cloud panel's INSTITUTIONAL CONNECTION
        # box is wired (wire_institutional_connection_widgets) -- a no-op
        # until then so Remote's own connector handlers (defined here,
        # called from buttons that exist immediately) never fail if
        # clicked before Cloud finishes building.
        _refresh_institutional_connection = lambda: None  # noqa: E731

        def _connector_is_online() -> bool:
            """Whether THIS kernel's Connector session/binding is currently
            paired -- the SAME fact Cloud reads (institutional_connection_
            box). No new resolution: reuses the existing SESSION/relay
            status check Remote already performs."""
            if not SESSION.get("id"):
                return False
            try:
                return bool(relay_check_status(SESSION["id"]).get("online"))
            except Exception:
                return False

        def create_or_refresh_connector_session(_=None):
            log_out.clear_output()

            try:
                if SESSION.get("id"):
                    prior = relay_check_status(SESSION["id"], force=True)
                    if prior.get("state") in {"unknown", "expired", "superseded"}:
                        SESSION.clear()

                if SESSION.get("id") is None:
                    owner = resolve_workspace_user(require_authenticated=True)
                    sess = create_session(owner_user_id=owner.user_id)
                    SESSION["id"] = sess["session_id"]
                    SESSION["ws_url"] = sess["ws_url"]
                    SESSION["pairing_code"] = sess["pairing_code"]

                st = relay_check_status(SESSION["id"])
                online = bool(st.get("online"))

                # Minimum pairing information/action only, in the existing
                # Remote visual language -- never a second boxed
                # "CRYOSTACK CONNECTOR" card duplicating the real Open
                # Connector.../Disconnect actions above. Session id / ws
                # path / relay state stay out of this compact line -- see
                # connector_diagnostics below (rendered only in Advanced).
                connector_setup_link.value = (
                    "" if online else connector_pairing_link_html(
                        session_id=SESSION.get("id"), app="icesee")
                )
                relay_status.value = connector_pairing_status_html(
                    session_id=SESSION.get("id"),
                    pairing_code=SESSION.get("pairing_code"),
                    online=online,
                )
                connector_diagnostics.value = connector_diagnostics_html(
                    session_id=SESSION.get("id"), ws_url=SESSION.get("ws_url"),
                    relay_state=st.get("state"),
                )
                # A session exists (paired or still waiting) -> Disconnect
                # is reachable either way, matching Cloud's own pairing
                # flow (never only once fully online).
                disconnect_connector_btn.layout.display = (
                    "inline-flex" if SESSION.get("id") else "none")

                with log_out:
                    print("[connector] pairing code:", SESSION.get("pairing_code"))
                    print("[connector] relay state:", st.get("state"))

            except Exception as e:
                relay_status.value = ""
                with log_out:
                    print("[connector][ERROR]", type(e).__name__, e)
            finally:
                # Cloud reads the SAME Connector binding/session -- reflect
                # every Remote-side change there too, never a second
                # Connector state that could drift out of sync.
                _refresh_institutional_connection()

        def disconnect_connector(_=None) -> None:
            """Disconnect the paired CryoStack Connector -- reuses the
            existing relay-client binding revocation (clear_binding());
            never a second Connector state. Cloud reads the SAME binding,
            so this is immediately reflected there too."""
            log_out.clear_output()
            SESSION.clear()
            clear_connector_binding()
            relay_status.value = ""
            connector_setup_link.value = ""
            connector_diagnostics.value = ""
            disconnect_connector_btn.layout.display = "none"
            with log_out:
                print("[connector] Disconnected.")
            _refresh_institutional_connection()

        def _toggle_remote_backend(_=None):
            is_ssh = (remote_backend.value == "ssh")
            ssh_box.layout.display = "block" if is_ssh else "none"
            ondemand_box.layout.display = "none" if is_ssh else "block"

        remote_backend.observe(_toggle_remote_backend, names="value")

        def _sync_resource_facts(_=None):
            # RESOURCE facts follow the selected resource; personal fields
            # (username, remote dir, account, email) are never touched here.
            rf = initial_remote_fields(cluster_name_for_keys.value)
            cluster_host.value = rf["login_host"]
            cluster_port.value = rf["ssh_port"]
            cluster_user.placeholder = rf["username_hint"]
            slurm_part.value = rf["partition"]
            slurm_time.value = rf["wall_time"]
            # B4: resource-aware auth options + manual key-registration checklist.
            try:
                remote_conn_panel.apply_profile(
                    get_compute_profile(cluster_name_for_keys.value or "")
                )
            except NameError:
                pass

        # --- B2: authenticated user x resource personal-settings persistence ---
        def _b2_read_personal() -> dict:
            return {
                "hpc_username": cluster_user.value,
                "remote_directory": remote_base_dir.value,
                "account": slurm_account.value,
                "email": slurm_mail.value,
                "access_mode": access_mode_dd.value,
                "auth_mode": auth_mode.value,
            }

        def _b2_apply_personal(s: dict) -> None:
            cluster_user.value = s.get("hpc_username", "") or ""
            remote_base_dir.value = s.get("remote_directory", "") or ""
            slurm_account.value = s.get("account", "") or ""
            slurm_mail.value = s.get("email", "") or ""
            if s.get("access_mode") in {"auto", "direct", "connector"}:
                access_mode_dd.value = s["access_mode"]
            _saved_auth = s.get("auth_mode")
            if _saved_auth in {t for _, t in auth_mode.options}:
                auth_mode.value = _saved_auth

        _b2_load, _b2_save = make_state_io(
            workspace_bridge, "icesee",
            resolve_workspace_user(require_authenticated=False).user_id,
        )
        resource_state = ResourceStateController(
            load_state=_b2_load, save_state=_b2_save,
            read_personal=_b2_read_personal, apply_personal=_b2_apply_personal,
            resource_name=lambda: cluster_name_for_keys.value,
            set_resource_name=lambda n: setattr(cluster_name_for_keys, "value", n),
            service_username=(os.environ.get("USER") or getpass.getuser() or ""),
        )

        # shared observer-suppression primitive: a resource switch / B2
        # hydration is one batch of programmatic .value = ... assignments, not
        # a dozen independent observer fan-outs.
        ui_refresh = UIRefreshCoordinator()

        def _on_resource_changed(change):
            with ui_refresh.batch():
                resource_state.switch_resource(change.get("old"), change.get("new"))
                _sync_resource_facts()

        cluster_name_for_keys.observe(_on_resource_changed, names="value")
        _toggle_remote_backend()
        W.HBox([W.HTML("<div class='icesee-lbl'>Backend:</div>"), remote_backend], layout=W.Layout(gap="12px")),
        ssh_box,
        ondemand_box,

        def on_test_remote(_=None):
            log_out.clear_output()
            set_status("running")

            if remote_backend.value == "https":
                with log_out:
                    print("[remote:https] OnDemand portal:", ood_cluster.value)
                    print("Open it in a browser tab (VPN may be required).")
                set_status("done")
                return

            # else: your SSH test (with timeout) as you already fixed
            return run_example_remote_test()
        # connect_btn.on_click(on_test_remote)

        def submit_remote(_=None):
            log_out.clear_output()
            set_status("running")

            if remote_backend.value == "ssh":
                run_example_remote_submit()
                return

            # HTTPS assisted mode
            example_cfg = EXAMPLES[example_dd.value]
            sync_quick_into_widgets()
            cfg_yaml = build_config_from_widgets()

            rd = run_dir(_icesee_run_dir_base(), _new_icesee_run_id())
            dump_yaml(cfg_yaml, rd / "params.yaml")

            # write slurm script locally so user can upload via OnDemand Files
            slurm_text = render_slurm_script({...})  # same as SSH branch
            (rd / "slurm_run.sh").write_text(slurm_text)
            if "{{" in slurm_text or "}}" in slurm_text:
                raise RuntimeError("SLURM_TEMPLATE render left unresolved placeholders. Check keys passed to render_slurm_script().")

            with log_out:
                print("[remote:https] Prepared files in:", rd)
                print(" - params.yaml")
                print(" - slurm_run.sh")
                print("\nNext (OnDemand):")
                print(" 1) Open OnDemand portal:", ood_cluster.value)
                print(" 2) Go to Files -> Home (or project dir) and upload these files")
                print(" 3) Open a Shell and run:")
                print("     sbatch slurm_run.sh")
                print("\nTip: OnDemand access may require GT VPN.")

            set_status("done")
        # submit_btn.on_click(submit_remote)

        def _toggle_auth_widgets(_=None):
            show = (auth_mode.value == "bootstrap")
            cluster_password.layout.display = "block" if show else "none"
            bootstrap_btn.layout.display = "block" if show else "none"

        auth_mode.observe(_toggle_auth_widgets, names="value")
        _toggle_auth_widgets()

        connect_btn.icon = "terminal"
        submit_btn.icon  = "server"
        status_btn.icon  = "tasks"
        tail_btn.icon    = "file-text"

        def _https_url(path_widget: W.Text, run_id: str | None = None, query: dict | None = None) -> str:
            base = https_base.value.strip().rstrip("/")
            path = path_widget.value.strip()
            if not path.startswith("/"):
                path = "/" + path
            url = base + path
            if run_id is not None:
                url = url.rstrip("/") + "/" + run_id
            if query:
                url = url + "?" + urlencode(query)
            return url

        def _extra_headers() -> dict:
            h = {}
            # bearer token
            if https_token.value.strip():
                h["Authorization"] = "Bearer " + https_token.value.strip()
            # yaml headers
            txt = https_headers.value.strip()
            if txt and not txt.startswith("#"):
                try:
                    y = yaml.safe_load(txt) or {}
                    if isinstance(y, dict):
                        h.update({str(k): str(v) for k, v in y.items()})
                except Exception:
                    pass
            return h
        
        def should_use_connector() -> bool:
            mode = access_mode_dd.value

            if mode == "connector":
                return True

            if mode == "direct":
                return False

            # auto mode: use connector only if direct SSH fails
            try:
                result = remote_test_connection(
                    cluster_host.value.strip(),
                    cluster_user.value.strip(),
                    int(cluster_port.value),
                )
                return not result.get("ok", False)
            except Exception:
                return True
    
        def show_connector_public_key_help():
            if not SESSION.get("id"):
                create_or_refresh_connector_session()

            result = connector_get_public_key(
                SESSION["id"],
                cluster_name=cluster_name_for_keys.value or "pace",
                hpc_username=cluster_user.value.strip(),
                host=cluster_host.value.strip(),
            )

            with log_out:
                print()
                print("[ssh] Automatic key installation did not complete.")
                print("[ssh] Some clusters require SSH keys to be added through a web portal.")
                print()
                print("[ssh] Copy this public key and add it to the cluster SSH key portal:")
                print()
                print(result.get("public_key_text", "").strip())
                print()
                print("[ssh] After adding the key, return here and click Test SSH.")
                print("[ssh] Then continue using Key-only mode.")

            return result

        def _bootstrap_panel(state, detail=""):
            try:
                remote_conn_panel.set_bootstrap_state(state, detail)
            except (NameError, AttributeError):
                pass

        def on_bootstrap_keys(_=None):
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)
            password = cluster_password.value

            if not host or not user:
                set_status("fail")
                _bootstrap_panel("connector_failed", "Provide Host + HPC username first.")
                return
            if not password:
                set_status("fail")
                _bootstrap_panel("password_failed", "Enter your HPC password (used once, never stored).")
                return

            bootstrap_btn.disabled = True
            _bootstrap_panel("registering")

            try:
                use_connector = should_use_connector()
                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()
                    st = relay_check_status(SESSION["id"], force=True)
                    if not st.get("online"):
                        set_status("fail")
                        _bootstrap_panel("connector_failed",
                                         "The CryoStack Connector is not connected. "
                                         "Pair it, then try again.")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                        return

                result = bootstrap_passwordless_ssh(
                    host=host,
                    user=user,
                    port=port,
                    password=password,
                    access_mode="connector" if use_connector else "direct",
                    session_id=SESSION.get("id"),
                    cluster_name=cluster_name_for_keys.value or "pace",
                )
                cluster_password.value = ""

                with log_out:
                    for msg in result.get("messages", []):
                        print(msg)
                    if (result.get("stdout") or "").strip():
                        print("--- stdout ---"); print(result["stdout"].strip())
                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---"); print(result["stderr"].strip())

                verdict = classify_bootstrap_result(result)
                if verdict == "installed":
                    set_status("done")
                    auth_mode.value = "key"
                    _bootstrap_panel("verifying")
                    with log_out:
                        print("[auth] Public key installed on the resource — verifying access…")
                    try:
                        run_example_remote_test()
                    except Exception as _e:
                        _bootstrap_panel("connector_failed")
                        with log_out:
                            print("[auth] re-check skipped:", type(_e).__name__, _e)
                else:
                    set_status("fail")
                    _bootstrap_panel(verdict)
                    with log_out:
                        print(f"[auth] bootstrap did not complete (reason: "
                              f"{result.get('reason') or verdict}).")

            except Exception as e:
                cluster_password.value = ""
                set_status("fail")
                _bootstrap_panel("timed_out" if "timeout" in type(e).__name__.lower()
                                 else "connector_failed")
                with log_out:
                    print("[auth][ERROR]", type(e).__name__, e)
            finally:
                bootstrap_btn.disabled = False
                cluster_password.value = ""     # never persisted/logged

        # =========================================================
        # Cloud panel -- the SAME shared Cloud Environment component
        # CryoLauncher uses (Provider/Region, AWS ACCOUNT, INFRASTRUCTURE,
        # Prepare Cloud, RUN ESTIMATE, Review & Launch, Advanced cloud
        # settings), not an ICESEE imitation of it. Region/profile/bucket/
        # queue/job-definition/job-name are ITS widgets (aliased below for
        # the existing submit/status/terminate handlers, unchanged) -- the
        # raw fields now live only under its own Advanced cloud settings
        # disclosure, never as the primary Cloud UI.
        # =========================================================
        icesee_cloud_environment = build_cloud_environment_card(
            region="us-east-1", profile="", s3_prefix="",
            job_queue="", job_definition="", job_name="icesee",
        )
        aws_region = icesee_cloud_environment.region
        aws_profile = icesee_cloud_environment.profile
        cloud_bucket = icesee_cloud_environment.s3_prefix
        batch_job_queue = icesee_cloud_environment.job_queue
        batch_job_def = icesee_cloud_environment.job_definition
        batch_job_name = icesee_cloud_environment.job_name

        # Status/Logs/Terminate for an in-flight job remain standalone --
        # they live in the Workspace Run Log toolbar and the Execution
        # panel (unchanged from the prior checkpoint), never inside the
        # Cloud Environment card itself. There is no standalone cloud
        # submit button any more: submission only happens through the
        # shared card's own Review & Launch.
        cloud_status_btn = W.Button(description="Check status", icon="search", button_style="")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text", button_style="")
        cloud_terminate_btn = W.Button(description="Terminate cloud job", icon="stop", button_style="danger")

        # =========================================================
        # Actions: Local / Remote / Cloud
        # =========================================================
        def run_example_local():
            """Start a local run as a background job (run_launcher); the page
            stays responsive and the workspace follows it. Returns
            ``(ok, message, run_id)``."""
            example_cfg = EXAMPLES[example_dd.value]
            sync_quick_into_widgets()
            cfg = build_config_from_widgets()
            local = _WF.get("local_env")
            req = run_launcher.LaunchRequest(
                example=example_dd.value, example_cfg=example_cfg, config=cfg,
                environment=local.env.value if local else "native",
                np=int(local.np.value) if local else 1,
                model_nprocs=int(local.model_nprocs.value) if local else 0,
                generate_report=bool(local.report.value) if local else bool(gen_report.value),
                run_root=_icesee_run_dir_base(),
                drafts=_WF["experiment_files"]().drafts_in_use() if "experiment_files" in _WF else {},
                user_id=resolve_workspace_user(require_authenticated=False).user_id,
            )
            errors = [i for i in run_launcher.validate_launch(req) if i.level == "error"]
            if errors:
                return False, "; ".join(i.message for i in errors), None
            set_status("running")
            try:
                prepared = run_launcher.prepare_local_run(req)
                job = run_launcher.start_local_run(prepared)
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[local][ERROR]", type(e).__name__, e)
                return False, f"The run could not start: {e}", None
            set_status("done")
            with log_out:
                print(f"[local] Started run {prepared.run_id} ({prepared.backend})")
                print("[local] Example :", example_dd.value)
                print("[local] Command :", " ".join(prepared.command))
                print("[local] Folder  :", prepared.run_dir)
            if "watch" in _WF:
                _WF["watch"](prepared.run_id, job, example_cfg.get("model_name", ""))
            return True, f"Run {prepared.run_id} started.", prepared.run_id

        def run_example_remote_submit():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            with log_out:
                print("[remote] Submit job")
                print("  host:", host)
                print("  user:", user)
                print("  port:", port)
                print("  example:", example_dd.value)
                print("-" * 70)

            try:

                use_connector = access_mode_dd.value == "connector"

                if access_mode_dd.value == "auto":
                    direct = remote_test_connection(host, user, port)
                    use_connector = not direct.get("ok", False)

                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"], force=True)
                    if not st.get("online"):
                        set_status("fail")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                        return

                # B3: remote-access identity gate -- verify the real remote
                # identity vs the configured HPC username; block Run on mismatch.
                _resolved = "connector" if use_connector else "direct"
                _gate = enforce_remote_access(
                    RemoteBridge(
                        mode=_resolved, host=host, user=user, port=port,
                        session_id=SESSION.get("id"),
                        cluster_name=cluster_name_for_keys.value or "pace",
                    ),
                    profile=get_compute_profile(cluster_name_for_keys.value or "pace"),
                    access_mode=access_mode_dd.value,
                    resolved_mode=_resolved,
                    hpc_username=user,
                    remote_directory=remote_base_dir.value.strip(),
                    connector_online=(
                        relay_check_status(SESSION["id"]).get("online")
                        if _resolved == "connector" and SESSION.get("id") else None
                    ),
                )
                for _w in _gate.warnings:
                    with log_out:
                        print(_w)
                try:
                    remote_conn_panel.set_status_from_access(_gate.state)
                except NameError:
                    pass
                if not _gate.ok:
                    set_status("fail")
                    with log_out:
                        for _m in _gate.messages:
                            print(_m)
                    return

                # B4: pre-submit Slurm resource validation (internal consistency
                # + syntax only; no invented site limits).
                _slurm_errors = validate_slurm_resources(
                    nodes=slurm_nodes.value,
                    tasks=slurm_ntasks.value,
                    tasks_per_node=slurm_tpn.value,
                    wall_time=slurm_time.value,
                    memory=slurm_mem.value,
                    account=slurm_account.value,
                    account_required=get_compute_profile(
                        cluster_name_for_keys.value or "pace"
                    ).account_required,
                )
                if _slurm_errors:
                    set_status("fail")
                    with log_out:
                        print("[slurm][ERROR] Fix the job resource request:")
                        for _m in _slurm_errors:
                            print("  -", _m)
                    return

                example_cfg = EXAMPLES[example_dd.value]

                sync_quick_into_widgets()
                cfg_yaml = with_legacy_parallel_flag(build_config_from_widgets())
                params_text = yaml.safe_dump(cfg_yaml, sort_keys=False)

                _run_id = _new_icesee_run_id()
                _rd = run_dir(_icesee_run_dir_base(), _run_id)
                dump_yaml(cfg_yaml, _rd / "params.yaml")

                if exec_backend_choice.value == "spack":
                    if use_connector:
                        result = submit_remote_example_via_connector(
                            session_id=SESSION["id"],
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_enable=spack_enable.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            spack_install_if_needed=spack_install_if_needed.value,
                            spack_install_mode=spack_install_mode.value,
                            spack_slurm_dir=spack_slurm_dir.value,
                            spack_pmix_dir=spack_pmix_dir.value,
                            spack_use_existing_sbatch=spack_use_existing_sbatch.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            cluster_name=cluster_name_for_keys.value,
                        )
                    else:
                        result = submit_remote_example(
                        host=host,
                        user=user,
                        port=port,
                        example_cfg=example_cfg,
                        params_text=params_text,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        spack_enable=spack_enable.value,
                        spack_repo_url=spack_repo_url.value,
                        spack_dirname=spack_dirname.value,
                        spack_install_if_needed=spack_install_if_needed.value,
                        spack_install_mode=spack_install_mode.value,
                        spack_slurm_dir=spack_slurm_dir.value,
                        spack_pmix_dir=spack_pmix_dir.value,
                        spack_use_existing_sbatch=spack_use_existing_sbatch.value,
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        remote_module_lines=remote_module_lines.value,
                        remote_export_lines=remote_export_lines.value,
                        cluster_mpi_np=cluster_mpi_np.value,
                        ens_size=ens_sl.value,
                        cluster_model_nprocs=cluster_model_nprocs.value,
                    )
                else:
                    if use_connector:
                        result = submit_remote_example_container_via_connector(
                            session_id=SESSION["id"],
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            container_source=container_source.value,
                            container_image_uri=container_image_uri.value,
                            cluster_name=cluster_name_for_keys.value,
                        )
                    else:
                        result = submit_remote_example_container(
                            host=host,
                            user=user,
                            port=port,
                            example_cfg=example_cfg,
                            params_text=params_text,
                            remote_base_dir=remote_base_dir.value,
                            remote_tag=remote_tag.value,
                            spack_repo_url=spack_repo_url.value,
                            spack_dirname=spack_dirname.value,
                            slurm_time=slurm_time.value,
                            slurm_job_name=slurm_job_name.value,
                            slurm_nodes=slurm_nodes.value,
                            slurm_ntasks=slurm_ntasks.value,
                            slurm_tpn=slurm_tpn.value,
                            slurm_part=slurm_part.value,
                            slurm_mem=slurm_mem.value,
                            slurm_account=slurm_account.value,
                            slurm_mail=slurm_mail.value,
                            remote_module_lines=remote_module_lines.value,
                            remote_export_lines=remote_export_lines.value,
                            cluster_mpi_np=cluster_mpi_np.value,
                            ens_size=ens_sl.value,
                            cluster_model_nprocs=cluster_model_nprocs.value,
                            container_source=container_source.value,
                            container_image_uri=container_image_uri.value,
                        )

                STATUS["remote_dir"] = result.remote_dir
                STATUS["jobid"] = result.jobid
                STATUS["local_run_dir"] = str(_rd)

                _record_icesee_run(
                    run_dir=_rd, run_id=_run_id, params=cfg_yaml,
                    example=example_dd.value, execution_mode="remote",
                    backend=exec_backend_choice.value,
                    source=example_dd.value,
                    run_target=cluster_name_for_keys.value or host,
                    status="submitted", jobid=result.jobid,
                    remote_directory=result.remote_dir,
                )

                experiment_bridge.create(
                    application="icesee",

                    name=(
                        f"ICESEE "
                        f"{filter_alg_dd.value} run"
                    ),

                    backend=remote_backend.value,

                    status="running",

                    job_id=(
                        str(result.jobid)
                        if result.jobid is not None
                        else None
                    ),

                    cluster=(
                        cluster_name_for_keys.value
                        or cluster_host.value.strip()
                    ),

                    working_directory=result.remote_dir,

                    log_path=getattr(
                        result,
                        "log_file",
                        None,
                    ),

                    configuration=(
                        current_experiment_configuration()
                    ),

                    metadata={
                        "execution_mode": "remote",
                        "access_mode": (
                            access_mode_dd.value
                        ),
                        "backend": (
                            remote_backend.value
                        ),
                        "filter": (
                            filter_alg_dd.value
                        ),
                        "preset": (
                            preset_dd.value
                        ),
                        "example": (
                            example_dd.value
                        ),
                    },
                )

                workspace_bridge.save(
                    application="icesee",
                    state=current_workspace_state(),
                )

                set_status("done")

                with log_out:
                    print(
                        "[experiment] Tracking ICESEE "
                        f"{filter_alg_dd.value} run "
                        f"for job {result.jobid}"
                    )

                    for msg in result.messages:
                        print(msg)

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] SSH/Sbatch step timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_test():
            log_out.clear_output()
            set_status("running")
            try:
                remote_conn_panel.set_status("checking")
            except NameError:
                pass

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            with log_out:
                print("[remote] Test SSH")
                print("  host:", host)
                print("  user:", user)
                print("  port:", port)
                print("  cmd : hostname && whoami && date")
                print("-" * 70)

            if not host or not user:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] Provide Host + User first.")
                return

            def _report_identity(resolved_mode: str, precheck_stdout: str = "") -> None:
                try:
                    _vcmd = get_compute_profile(
                        cluster_name_for_keys.value or "pace").verification_command
                    # The Test SSH probe just ran `hostname && whoami && pwd &&
                    # date`. When identity is just `whoami`, reuse that instead
                    # of a second remote round trip. (The Run gate re-verifies
                    # fresh regardless.)
                    _lines = [ln.strip() for ln in (precheck_stdout or "").splitlines() if ln.strip()]
                    if len(_lines) >= 2 and can_reuse_connectivity_identity(_vcmd):
                        _v = identity_result_from_output(
                            whoami_line=_lines[1], expected_username=user
                        )
                    else:
                        _v = verify_remote_identity(
                            RemoteBridge(mode=resolved_mode, host=host, user=user, port=port,
                                         session_id=SESSION.get("id"),
                                         cluster_name=cluster_name_for_keys.value or "pace"),
                            verification_command=_vcmd,
                            expected_username=user,
                        )
                    with log_out:
                        if _v.ok:
                            print(f"[identity] verified — remote '{_v.remote_identity}' "
                                  "matches the configured HPC username.")
                        elif _v.mismatch:
                            print(f"[identity][MISMATCH] remote '{_v.remote_identity}' != "
                                  f"configured '{_v.expected}'. Run is blocked until this matches.")
                        else:
                            print(f"[identity] could not verify remote identity: {_v.error}")
                    try:
                        remote_conn_panel.set_status(
                            "verified" if _v.ok else "mismatch" if _v.mismatch else "failed"
                        )
                    except NameError:
                        pass
                except Exception as _e:
                    with log_out:
                        print("[identity] verification skipped:", type(_e).__name__, _e)
                    try:
                        remote_conn_panel.set_status("failed")
                    except NameError:
                        pass

            def _classify_and_report_failure(res) -> None:
                """A failed connectivity probe: a public-key rejection is an
                actionable "register your CryoStack key" state (B3 namespaced
                key), everything else stays a generic failure."""
                _kind = classify_ssh_failure(
                    stderr=(res or {}).get("stderr", ""),
                    stdout=(res or {}).get("stdout", ""),
                    returncode=(res or {}).get("returncode"),
                )
                try:
                    _profile = get_compute_profile(cluster_name_for_keys.value or "pace")
                    if _kind == SSH_KEY_NOT_AUTHORIZED:
                        remote_conn_panel.set_key_unregistered(_profile)
                        with log_out:
                            print("[access] SSH key not registered — the Connector "
                                  "reached the resource, but this CryoStack key is "
                                  "not yet authorized for your account. See the "
                                  "Remote connection panel for how to register it.")
                    else:
                        remote_conn_panel.set_status("failed")
                except NameError:
                    pass

            try:

                if access_mode_dd.value == "connector":
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"])
                    if not st.get("online"):
                        set_status("fail")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                            print("Open the connector setup page and start the local connector first.")
                        return

                    cluster_name = cluster_name_for_keys.value or "pace"
                    payload = connector_ssh(
                        SESSION["id"],
                        host,
                        user,
                        port,
                        "hostname && whoami && pwd && date",
                        timeout=300,
                        cluster_name=cluster_name,
                    )

                    with log_out:
                        print("[connector] Test SSH via local connector / VPN bridge")
                        print("ok:", payload.get("ok"))
                        print("returncode:", payload.get("returncode"))
                        if (payload.get("stdout") or "").strip():
                            print("--- stdout ---")
                            print(payload["stdout"].strip())
                        if (payload.get("stderr") or "").strip():
                            print("--- stderr ---")
                            print(payload["stderr"].strip())

                    if payload.get("ok"):
                        _report_identity("connector", payload.get("stdout") or "")
                        set_status("done")
                    else:
                        set_status("fail")
                        _classify_and_report_failure(payload)
                    return
                result = remote_test_connection(host, user, port)

                with log_out:
                    print("returncode:", result["returncode"])

                    if (result["stdout"] or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())

                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                    if result["returncode"] != 0:
                        err = (result["stderr"] or "").lower()

                        if "permission denied" in err:
                            print()
                            print("⚠ SSH authentication failed.")
                            print("Looks like passwordless SSH is not configured.")
                            print()
                            print("➡ Fix:")
                            print("   1) Switch Auth → 'Bootstrap with password'")
                            print("   2) Enter your cluster password")
                            print("   3) Click 'Enable passwordless SSH'")
                            print()
                            print("After that the UI will connect automatically.")

                        elif "timed out" in err or "connection timed out" in err:
                            print()
                            print("⚠ Connection timed out.")
                            print("Check VPN, firewall, or hostname.")

                        elif "could not resolve hostname" in err:
                            print()
                            print("⚠ Hostname not reachable.")
                            print("Check the cluster hostname.")

                if result["ok"]:
                    _report_identity("direct", result.get("stdout") or "")
                    set_status("done")
                else:
                    set_status("fail")
                    _classify_and_report_failure(result)

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] SSH did not respond within 15s.")
                    print("Likely: network/DNS issue, firewall/VPN, or auth prompt prevented non-interactive login.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_status():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Check status")
                print("  host:", host)
                print("  user:", user)
                print("  jobid:", jobid)
                print("-" * 70)

            if not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No JobID yet. Submit first.")
                return

            try:
                result = remote_job_status(
                    host,
                    user,
                    port,
                    jobid,
                )

                experiment_update = (
                    experiment_update_from_job_status(
                        result
                    )
                )

                if experiment_update:
                    experiment_bridge.update_by_job(
                        job_id=str(jobid),
                        **experiment_update,
                    )
                    if STATUS.get("local_run_dir"):
                        _update_icesee_run(
                            Path(STATUS["local_run_dir"]),
                            status=experiment_update.get("status"),
                        )

                with log_out:
                    if result["source"] == "squeue":
                        print("--- squeue ---")
                        print(
                            (result["stdout"] or "").strip()
                        )
                    else:
                        print(
                            "(squeue empty; job likely "
                            "finished or left the queue)"
                        )
                        print("--- sacct ---")
                        print(
                            (result["stdout"] or "").strip()
                            or "(no sacct output)"
                        )

                        if (
                            result["stderr"] or ""
                        ).strip():
                            print("--- stderr ---")
                            print(
                                result["stderr"].strip()
                            )

                    if experiment_update:
                        print()
                        print(
                            "[experiment] CryoStack status:",
                            experiment_update["status"],
                        )

                set_status(
                    "done"
                    if result["returncode"] == 0
                    else "fail"
                )

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] Status check timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_cancel():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Cancel job")
                print("  host:", host)
                print("  user:", user)
                print("  jobid:", jobid)
                print("-" * 70)

            if not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No JobID found.")
                return

            try:
                result = remote_cancel_job(host, user, port, jobid)

                with log_out:
                    print("returncode:", result["returncode"])

                    if (result["stdout"] or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())

                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                    if result["ok"]:
                        print(f"✅ Job {jobid} cancelled.")

                if result["ok"] and STATUS.get("local_run_dir"):
                    _update_icesee_run(Path(STATUS["local_run_dir"]), status="cancelled")

                set_status("done" if result["ok"] else "fail")

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def run_example_remote_tail():
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            rdir = STATUS.get("remote_dir")
            jobid = STATUS.get("jobid")

            with log_out:
                print("[remote] Tail log")
                print("  host:", host)
                print("  user:", user)
                print("  rdir:", rdir)
                print("  jobid:", jobid)
                print("-" * 70)

            if not rdir or not jobid:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR] No remote dir / JobID. Submit first.")
                return

            try:
                result = remote_tail_log(host, user, port, rdir, jobid, n=120)

                with log_out:
                    print("[remote] file:", result["log_file"])
                    print("--- tail ---")
                    print((result["stdout"] or "").rstrip())
                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                set_status("done" if result["returncode"] == 0 else "fail")

            except subprocess.TimeoutExpired:
                set_status("fail")
                with log_out:
                    print("[remote][TIMEOUT] Tail timed out.")
            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def _resolve_icesee_cloud_execution(*, region_override: str | None = None):
            """Fresh per-operation credential resolution -- the SAME shared
            resolver CryoLauncher uses (resolve_cloud_execution), not an
            ICESEE-only credential path. A user who already connected a BYO
            AWS account (through CryoLauncher's existing Connect AWS Account
            UI -- the connection is scoped to the authenticated CryoStack
            user, not the app) gets that same account here automatically, no
            new ICESEE UI required. No connection -> unchanged developer/
            ambient-profile behavior from the live Cloud widgets.

            ``region_override`` lets status/terminate resolve against a
            historical run's OWN persisted region (metadata['aws_resources'])
            rather than whatever the Cloud panel's region field currently
            says -- a later visit must not silently query the wrong region
            just because the live widget has since changed."""
            from cryostack_src.cloud.connect import resolve_cloud_execution

            return resolve_cloud_execution(
                region_hint=(region_override or aws_region.value.strip()),
                profile_hint=(aws_profile.value.strip() or None),
                model="icesee",
            )

        def _icesee_cloud_bridge_config(execution) -> IceseeCloudBridgeConfig:
            return IceseeCloudBridgeConfig(
                region=execution.region,
                profile=execution.profile,
                credentials=execution.credentials,
            )

        def run_example_cloud_submit():
            example_cfg = EXAMPLES[example_dd.value]

            sync_quick_into_widgets()
            cfg_yaml, runtime_changes = cloud_runtime_config(build_config_from_widgets(),
                                                             np=int(cloud_mpi_np.value))

            set_status("running")
            log_out.clear_output()
            with log_out:
                print("[cloud] AWS Batch submit")
                print("example:", example_dd.value)
                print("region :", aws_region.value.strip() or "us-east-1")
                print("profile:", aws_profile.value.strip() or "(default)")
                print("s3     :", cloud_bucket.value.strip())
                for change in runtime_changes:
                    print("[cloud] set for the Cloud image's ICESEE:", change)

            _run_id = _new_icesee_run_id()
            _rd = run_dir(_icesee_run_dir_base(), _run_id)

            try:
                execution = _resolve_icesee_cloud_execution()
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))

                # BYO-AWS: blank fields resolve to the connected account's
                # prepared defaults (same "blank = prepared default" contract
                # CryoLauncher's Cloud Environment uses) -- s3_prefix always
                # carries a 'runs' path segment since aws_batch_submit
                # requires one. Developer mode (no connection) is completely
                # unchanged: every field must still be typed by hand.
                s3_prefix = cloud_bucket.value.strip()
                job_queue = batch_job_queue.value.strip()
                job_definition = batch_job_def.value.strip()
                if execution.is_byo and execution.defaults is not None:
                    s3_prefix = s3_prefix or f"s3://{execution.defaults.bucket}/runs"
                    job_queue = job_queue or execution.defaults.job_queue
                    job_definition = job_definition or execution.defaults.job_definition

                result = submit_icesee_cloud_run(
                    bridge,
                    example_name=example_dd.value,
                    example_cfg=example_cfg,
                    config=cfg_yaml,
                    s3_prefix=s3_prefix,
                    job_queue=job_queue,
                    job_definition=job_definition,
                    job_name=(batch_job_name.value.strip() or "icesee"),
                    # the same NP/Nens/model_nprocs contract Remote's own
                    # SLURM template unconditionally threads into mpirun --
                    # a real ICESEE Batch entrypoint reads these to launch
                    # the identical command (see MAX_SINGLE_TASK_MPI_RANKS).
                    np=int(cloud_mpi_np.value),
                    nens=int(ens_sl.value),
                    model_nprocs=int(cluster_model_nprocs.value),
                    run_dir_base=_icesee_run_dir_base(),
                    run_dir_name=_run_id,
                    # one resolution (the SAME `execution` above), both
                    # fields -- CloudMatlabLicense.configured and
                    # .requires_tunnel (the latter already
                    # capability/profile-derived; never re-derived here).
                    matlab_license_configured=bool(
                        getattr(execution.matlab_license, "configured", False)),
                    matlab_license_requires_tunnel=bool(
                        getattr(execution.matlab_license, "requires_tunnel", False)),
                )

                STATUS["batch_job_id"] = result.job_id
                STATUS["s3_run"] = result.working_directory
                STATUS["local_run_dir"] = str(_rd)
                if not (_rd / "params.yaml").is_file():
                    dump_yaml(cfg_yaml, _rd / "params.yaml")

                _record_icesee_run(
                    run_dir=_rd, run_id=_run_id,
                    params=cfg_yaml, example=example_dd.value,
                    execution_mode="cloud", backend="aws",
                    source=example_dd.value,
                    run_target=job_definition,
                    status="submitted", jobid=result.job_id,
                    remote_directory=result.working_directory,
                    extra_metadata={
                        "cloud_account_mode": execution.mode,
                        "cluster_mpi_np": cluster_mpi_np.value,
                        "cluster_model_nprocs": cluster_model_nprocs.value,
                        "ensemble_size": int(ens_sl.value),
                    },
                )
                _merge_icesee_aws_resources(_rd, {
                    "region": execution.region,
                    "account_id": execution.account_id,
                    "batch_job_id": result.job_id,
                    "job_queue": job_queue,
                    "job_definition": job_definition,
                    "s3_run": result.working_directory,
                })

                # the shared experiment record (Control Center Cloud and
                # Experiments), as Remote runs already do; no account id or
                # credentials -- the record carries the provider and queue only
                experiment_bridge.create(
                    application="icesee",
                    name=f"ICESEE {filter_alg_dd.value} run",
                    backend="aws",
                    status="queued",
                    job_id=str(result.job_id),
                    cluster="aws-batch",
                    working_directory=result.working_directory,
                    configuration=current_experiment_configuration(),
                    metadata={
                        "execution_mode": "cloud",
                        "provider": "aws",
                        "filter": filter_alg_dd.value,
                        "cloud": {
                            "region": execution.region,
                            "job_queue": job_queue,
                            "job_definition": job_definition,
                        },
                    },
                )
                STATUS["batch_experiment_status"] = "queued"

                set_status("done")
                with log_out:
                    for msg in result.messages:
                        print(msg)

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def _persisted_icesee_cloud_region() -> str | None:
            if not STATUS.get("local_run_dir"):
                return None
            try:
                manifest = Path(STATUS["local_run_dir"]) / run_records.MANIFEST_NAME
                if not manifest.is_file():
                    return None
                return (read_manifest(manifest).metadata.get("aws_resources") or {}).get("region") or None
            except Exception:
                return None

        def run_example_cloud_status():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet. Submit first.")
                return
            try:
                execution = _resolve_icesee_cloud_execution(
                    region_override=_persisted_icesee_cloud_region(),
                )
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))
                st = icesee_cloud_status(bridge, job_id=STATUS["batch_job_id"])
                with log_out:
                    print("[cloud] status:", st.raw_state)
                    if st.reason:
                        print("[cloud] reason:", st.reason)
                if STATUS.get("local_run_dir"):
                    _update_icesee_run(Path(STATUS["local_run_dir"]), status=st.state)
                    _merge_icesee_aws_resources(
                        Path(STATUS["local_run_dir"]), resources_from_poll(st.metadata),
                    )
                # each experiment status once; nothing after a terminal one
                update = cloud_status_update(st.raw_state or st.state, st.reason or "")
                sent = STATUS.get("batch_experiment_status")
                if (update and update["status"] != sent
                        and sent not in ("completed", "failed", "cancelled")):
                    experiment_bridge.update_by_job(job_id=str(STATUS["batch_job_id"]), **update)
                    STATUS["batch_experiment_status"] = update["status"]
            except Exception as e:
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_terminate():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet.")
                return
            try:
                execution = _resolve_icesee_cloud_execution(
                    region_override=_persisted_icesee_cloud_region(),
                )
                bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))
                result = icesee_cloud_terminate(bridge, job_id=STATUS["batch_job_id"])
                with log_out:
                    print("[cloud]", result.get("message")
                          or f"job {result.get('action', 'terminated')}")
                if STATUS.get("local_run_dir"):
                    _update_icesee_run(Path(STATUS["local_run_dir"]), status="cancelled")
            except Exception as e:
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_logs_hint():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet.")
                return
            with log_out:
                print("[cloud] Logs depend on your job definition (awslogs driver).")
                print("Open the AWS Console -> Batch -> Job -> Logs")
                print("JobID:", STATUS["batch_job_id"])
                if STATUS.get("s3_run"):
                    print("S3 run prefix:", STATUS["s3_run"])

        def current_execution_mode() -> str:
            """
            Return the active ICESEE execution mode.

            mode_tabs:
                0 -> Local
                1 -> Remote
                2 -> Cloud
            """
            index = mode_tabs.selected_index

            return {
                0: "local",
                1: "remote",
                2: "cloud",
            }.get(index, "local")


        def current_experiment_configuration() -> dict:
            """
            Snapshot the scientific and execution configuration used
            for an ICESEE experiment.

            Do not store passwords, SSH keys, connector secrets,
            AWS credentials, or other authentication material.
            """

            execution_mode = current_execution_mode()

            config = {
                "execution_mode": execution_mode,

                "example": example_dd.value or "",

                "preset": preset_dd.value or "",

                "filter": filter_alg_dd.value or "",

                "ensemble_size": int(ens_sl.value),

                "output": output_label_dd.value or "",

                "report_generation": bool(
                    gen_report.value
                ),
            }

            # -------------------------------------------------
            # Remote / HPC configuration
            # -------------------------------------------------
            if execution_mode == "remote":

                config["remote"] = {
                    "access_mode": (
                        access_mode_dd.value
                    ),

                    "backend": (
                        remote_backend.value
                    ),

                    "cluster": (
                        cluster_name_for_keys.value
                        if "cluster_name_for_keys" in locals()
                        else ""
                    ),

                    "host": (
                        cluster_host.value.strip()
                    ),

                    "port": int(
                        cluster_port.value
                    ),

                    "remote_base_dir": (
                        remote_base_dir.value.strip()
                    ),

                    "remote_tag": (
                        remote_tag.value.strip()
                    ),
                }

                config["slurm"] = {
                    "job_name": (
                        slurm_job_name.value
                    ),

                    "time": (
                        slurm_time.value
                    ),

                    "nodes": int(
                        slurm_nodes.value
                    ),

                    "tasks": int(
                        slurm_ntasks.value
                    ),

                    "tasks_per_node": int(
                        slurm_tpn.value
                    ),

                    "partition": (
                        slurm_part.value
                    ),

                    "memory": (
                        slurm_mem.value
                    ),

                    "account": (
                        slurm_account.value
                    ),
                }

            # -------------------------------------------------
            # Cloud configuration
            # -------------------------------------------------
            elif execution_mode == "cloud":

                config["cloud"] = {
                    "region": (
                        aws_region.value.strip()
                    ),

                    "job_queue": (
                        batch_job_queue.value.strip()
                    ),

                    "job_definition": (
                        batch_job_def.value.strip()
                    ),

                    "job_name": (
                        batch_job_name.value.strip()
                    ),

                    "s3_prefix": (
                        cloud_bucket.value.strip()
                    ),
                }

            return config


        def current_workspace_state() -> dict:
            """
            Save enough ICESEE UI state to support future workspace
            restoration.

            This intentionally excludes credentials and secrets.
            """

            execution_mode = current_execution_mode()

            state = {
                "execution_mode": execution_mode,

                "example": example_dd.value or "",

                "preset": preset_dd.value or "",

                "filter": filter_alg_dd.value or "",

                "ensemble_size": int(ens_sl.value),

                "output": output_label_dd.value or "",

                "report_generation": bool(
                    gen_report.value
                ),

                "job": {
                    "job_id": (
                        STATUS.get("jobid")
                    ),

                    "remote_directory": (
                        STATUS.get("remote_dir")
                    ),

                    "batch_job_id": (
                        STATUS.get("batch_job_id")
                    ),

                    "s3_run": (
                        STATUS.get("s3_run")
                    ),
                },
            }

            # -------------------------------------------------
            # Remote workspace
            # -------------------------------------------------
            if execution_mode == "remote":

                state["remote"] = {
                    "access_mode": (
                        access_mode_dd.value
                    ),

                    "backend": (
                        remote_backend.value
                    ),

                    "cluster": (
                        cluster_name_for_keys.value
                        if "cluster_name_for_keys" in locals()
                        else ""
                    ),

                    "host": (
                        cluster_host.value.strip()
                    ),

                    "port": int(
                        cluster_port.value
                    ),

                    "remote_base_dir": (
                        remote_base_dir.value.strip()
                    ),

                    "remote_tag": (
                        remote_tag.value.strip()
                    ),
                }

                state["slurm"] = {
                    "job_name": (
                        slurm_job_name.value
                    ),

                    "time": (
                        slurm_time.value
                    ),

                    "nodes": int(
                        slurm_nodes.value
                    ),

                    "tasks": int(
                        slurm_ntasks.value
                    ),

                    "tasks_per_node": int(
                        slurm_tpn.value
                    ),

                    "partition": (
                        slurm_part.value
                    ),

                    "memory": (
                        slurm_mem.value
                    ),
                }

            # -------------------------------------------------
            # Cloud workspace
            # -------------------------------------------------
            elif execution_mode == "cloud":

                state["cloud"] = {
                    "region": (
                        aws_region.value.strip()
                    ),

                    "job_queue": (
                        batch_job_queue.value.strip()
                    ),

                    "job_definition": (
                        batch_job_def.value.strip()
                    ),

                    "job_name": (
                        batch_job_name.value.strip()
                    ),

                    "s3_prefix": (
                        cloud_bucket.value.strip()
                    ),
                }

            # B2: fold in the authenticated user x resource personal settings
            # (v2 shape). RESOURCE facts are NOT persisted; nothing secret.
            merged = resource_state.capture()
            merged["run"] = state
            return strip_secrets(merged)

        # master run
        def run_example():
            mode = get_mode()
            if mode == MODE_REMOTE:
                return run_example_remote_submit()
            if mode == MODE_CLOUD:
                return run_example_cloud_submit()
            return run_example_local()

        # =========================================================
        # Wire buttons
        # =========================================================
        # run_btn.on_click(lambda b: run_example())
        action_btn.on_click(on_action_click)
        clear_btn.on_click(lambda b: (log_out.clear_output(), results_out.clear_output(), set_status("idle")))

        def _on_check_ssh(_b=None):
            # immediate feedback + no re-entry while the check runs
            connect_btn.disabled = True
            try:
                remote_conn_panel.set_status("checking")
            except NameError:
                pass
            try:
                run_example_remote_test()
            finally:
                connect_btn.disabled = False

        connect_btn.on_click(_on_check_ssh)

        def _after_status_check():
            if "workspace" in _WF:
                _WF["workspace"].reload_selected()
        submit_btn.on_click(lambda b: run_example_remote_submit())
        status_btn.on_click(lambda b: run_example_remote_status())
        tail_btn.on_click(lambda b: run_example_remote_tail())
        terminate_btn.on_click(lambda b: run_example_remote_cancel())

        cloud_status_btn.on_click(lambda b: run_example_cloud_status())
        status_btn.on_click(lambda b: _after_status_check())        # the workspace shows the new state
        cloud_status_btn.on_click(lambda b: _after_status_check())
        cloud_logs_btn.on_click(lambda b: run_example_cloud_logs_hint())
        cloud_terminate_btn.on_click(lambda b: run_example_cloud_terminate())
        
        start_connector_session_btn.on_click(create_or_refresh_connector_session)
        # (removed: auto connector-session creation on access-mode change --
        #  the session is created lazily at Check SSH / Run / the explicit
        #  "Open Connector Setup" button, keeping the relay off the
        #  initial-load and resource-switch paths.)
        preview_results_btn.on_click(preview_remote_results)
        results_download_btn.on_click(download_results_bundle)

        # keep template in sync with quick knobs
        def _sync_knobs(_=None):
            sync_quick_into_widgets()

        filter_alg_dd.observe(_sync_knobs, names="value")
        ens_sl.observe(_sync_knobs, names="value")
        seed_in.observe(_sync_knobs, names="value")

        bootstrap_btn.on_click(on_bootstrap_keys)

    # =========================================================
        # UX CSS
        # =========================================================
        css = """
        <style>
        /* --- your existing styles --- */
        .icesee-wrap { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; }
        .icesee-title { font-size: 18px; font-weight: 700; margin: 6px 0 4px; }
        .icesee-subtitle { color: rgba(0,0,0,.65); margin-bottom: 14px; }
        .icesee-card { border: 1px solid rgba(0,0,0,.10); border-radius: 12px; padding: 14px; background: #fff; }
        .icesee-h { font-size: 18px; font-weight: 800; margin: 2px 0 10px; }
        .icesee-lbl { min-width: 80px; font-weight: 650; }
        .icesee-lbl-wide { min-width: 120px; font-weight: 650; }
        .icesee-lbl-sm { min-width: 56px; font-weight: 650; }
        .icesee-k { min-width: 180px; font-weight: 650; color: rgba(0,0,0,.78); }
        .icesee-subtle { color: rgba(0,0,0,.60); font-size: 12px; }
        .icesee-status { display:inline-block; padding: 8px 14px; border-radius: 999px; font-weight: 700; border: 1px solid rgba(0,0,0,.10); }
        .icesee-idle { background: rgba(0,0,0,.04); }
        .icesee-running { background: rgba(16, 122, 255, .12); }
        .icesee-done { background: rgba(30, 170, 80, .14); }
        .icesee-fail { background: rgba(220, 60, 60, .14); }

        /* --- make notebook/page use full width (JLab/classic) --- */
        .jp-NotebookPanel, .jp-Notebook, .jp-Cell, .jp-OutputArea { max-width: 100% !important; }
        .icesee-page { width: 100% !important; }

        /* --- stretch left/right columns properly --- */
        .icesee-row { display: flex; gap: 26px; width: 100%; align-items: stretch; }
        .icesee-col { flex: 1 1 0; min-width: 0; }  /* min-width:0 is KEY */

        /* --- outputs: full width + readable long lines --- */
        .icesee-out { width: 100% !important; }
        .icesee-out .output_area pre {
        white-space: pre;      /* keep formatting */
        overflow-x: auto;      /* horizontal scroll for long lines */
        }

        /* Optional: if you're in Jupyter Book and it's still constrained, uncomment:
        .bd-main .bd-content, .bd-container, .container-xl, .container-lg { max-width: 100% !important; }
        */
        </style>
        """
        # display(W.HTML(css))
        display(shared_styles)

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML(
            "<div class='icesee-wrap'>"
            "<div class='icesee-title'>Ice-Sheet Modeling with Data Assimilation</div>"
            "<div class='icesee-subtitle'>Outputs and reports are saved and previewed on the right.</div>"
            "</div>"
        )

        # Local tab content
        local_tab_card = W.VBox([W.HTML("<div class='icesee-subtle'>Local mode runs directly in this notebook.</div>")])
        local_tab_card.add_class("icesee-card")

        ssh_key_manager = build_ssh_key_manager(
            cluster_name_widget=cluster_name_for_keys,
            host_widget=cluster_host,
            user_widget=cluster_user,
            defer_probe=True,   # ssh-add subprocesses off the construction path
            )
        exec_backend_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Exec backend:</div>"), exec_backend_choice],
            layout=W.Layout(gap="12px"),
        )

        container_source_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Source:</div>"), container_source],
            layout=W.Layout(gap="12px"),
        )

        container_image_row = W.HBox(
            [W.HTML("<div class='icesee-lbl'>Image:</div>"), container_image_uri],
            layout=W.Layout(gap="12px"),
        )
        

        def _toggle_exec_backend_ui(_=None):
            is_container = (exec_backend_choice.value == "container")

            container_source_row.layout.display = "flex" if is_container else "none"
            container_image_row.layout.display = "flex" if is_container else "none"

            spack_display = "none" if is_container else "flex"
            spack_block_display = "none" if is_container else "block"

            spack_section_title.layout.display = spack_block_display
            spack_enable_row.layout.display = spack_block_display
            spack_repo_row.layout.display = spack_display
            spack_dir_row.layout.display = spack_display
            spack_install_if_needed_row.layout.display = spack_block_display
            spack_install_mode_row.layout.display = spack_display
            spack_slurm_dir_row.layout.display = spack_display
            spack_pmix_dir_row.layout.display = spack_display
            spack_existing_sbatch_row.layout.display = spack_block_display

            if is_container:
                spack_enable.value = False

        spack_section_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>ICESEE-Spack</div>")
        spack_enable_row = W.Box([spack_enable], layout=W.Layout(margin="0 0 0 120px"))
        spack_repo_row = W.HBox([W.HTML("<div class='icesee-lbl'>Repo:</div>"), spack_repo_url], layout=W.Layout(gap="12px"))
        spack_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>Dir name:</div>"), spack_dirname], layout=W.Layout(gap="12px"))
        spack_install_if_needed_row = W.Box([spack_install_if_needed], layout=W.Layout(margin="0 0 0 120px"))
        spack_install_mode_row = W.HBox([W.HTML("<div class='icesee-lbl'>Install:</div>"), spack_install_mode], layout=W.Layout(gap="12px"))
        spack_slurm_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>SLURM_DIR:</div>"), spack_slurm_dir], layout=W.Layout(gap="12px"))
        spack_pmix_dir_row = W.HBox([W.HTML("<div class='icesee-lbl'>PMIX_DIR:</div>"), spack_pmix_dir], layout=W.Layout(gap="12px"))
        spack_existing_sbatch_row = W.Box([spack_use_existing_sbatch], layout=W.Layout(margin="0 0 0 120px"))

        # B4: Job settings / Compute resources / Allocation are arranged by
        # build_slurm_resources_panel; only ICESEE's MPI + module/export rows
        # are laid out here and handed to the panel as extra_children.
        mpi_model_row = W.HBox(
            [form_pair("MPI np:", cluster_mpi_np), form_pair("Model nprocs:", cluster_model_nprocs, label_width="120px")],
            layout=W.Layout(gap="8px", width="100%"),
        )

        modules_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Modules</div>")
        exports_title = W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Exports</div>")
        ssh_key_title = W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>SSH key manager</div>")

        download_buttons_row = W.HBox(
            [preview_results_btn, results_download_btn],
            layout=W.Layout(
                gap="10px",
                justify_content="flex-end",
                align_items="center",
                width="100%",
                margin="10px 0 0 0",
            ),
        )


        # B4: user-workflow-oriented Remote Connection panel (Compute resource /
        # Your HPC identity / Access / Status), connector + session internals
        # behind Diagnostics. Transport, B3 AccessState, identity verification
        # and the Run gate are unchanged.
        connect_btn.description = "Check SSH Access"
        start_connector_session_btn.description = "Open Connector..."
        start_connector_session_btn.icon = "external-link"
        disconnect_connector_btn.on_click(disconnect_connector)

        remote_tag_row = form_pair("Tag:", remote_tag, label_width="56px")
        remote_conn_panel = build_remote_connection_panel(
            resource=cluster_name_for_keys,
            host=cluster_host,
            port=cluster_port,
            hpc_username=cluster_user,
            remote_directory=remote_base_dir,
            connection_method=access_mode_dd,
            auth_method=auth_mode,
            check_ssh_button=connect_btn,
            open_connector_button=start_connector_session_btn,
            connector_card=relay_status,
            connector_setup_link=connector_setup_link,
            disconnect_button=disconnect_connector_btn,
            profile=get_compute_profile(cluster_name_for_keys.value or "pace"),
            auth_extra_children=[cluster_password, bootstrap_btn],
            advanced_children=[remote_tag_row, connector_diagnostics],
        )
        remote_conn_inner = remote_conn_panel.container


        exec_backend_inner = W.VBox([
            exec_backend_row,
            container_source_row,
            container_image_row,
            spack_enable_row,
            spack_repo_row,
            spack_dir_row,
            spack_install_if_needed_row,
            spack_install_mode_row,
            spack_slurm_dir_row,
            spack_pmix_dir_row,
            spack_existing_sbatch_row,
        ], layout=W.Layout(gap="8px"))


        slurm_inner = build_slurm_resources_panel(
            job_name=slurm_job_name,
            wall_time=slurm_time,
            nodes=slurm_nodes,
            tasks=slurm_ntasks,
            tasks_per_node=slurm_tpn,
            partition=slurm_part,
            memory=slurm_mem,
            account=slurm_account,
            email=slurm_mail,
            extra_children=[
                mpi_model_row,
                modules_title,
                remote_module_lines,
                exports_title,
                remote_export_lines,
            ],
        ).container

        remote_conn_box = W.Accordion(children=[remote_conn_inner])
        remote_conn_box.set_title(0, "🔌 Remote connection")
        remote_conn_box.selected_index = None

        exec_backend_box = W.Accordion(children=[exec_backend_inner])
        exec_backend_box.set_title(0, "⚙️ Execution backend")
        exec_backend_box.selected_index = None

        slurm_box = W.Accordion(children=[slurm_inner])
        slurm_box.set_title(0, "📊 Slurm resources")
        slurm_box.selected_index = None

        server_key_note = W.HTML("""
        <div class='icesee-subtle' style='line-height:1.5; margin-bottom:8px;'>
        This manages SSH keys on the web server side for direct SSH.
        For Local Connector / VPN bridge mode, the connector creates the key on your workstation.
        </div>
        """)

        ssh_key_manager_box = W.Accordion(
            children=[
                W.VBox([
                    server_key_note,
                    ssh_key_manager,
                ], layout=W.Layout(gap="8px"))
            ]
        )

        ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        ssh_key_manager_box.selected_index = None

        def _probe_ssh_key_manager(change):
            if change.get("new") is not None:
                probe = getattr(ssh_key_manager, "_cryostack_probe", None)
                if probe is not None:
                    probe()
        ssh_key_manager_box.observe(_probe_ssh_key_manager, names="selected_index")

        # =========================================================
        # Workspace (Runs / Files) -- the same structural language as
        # CryoLauncher's Workspace shell, reusing its shared history panel
        # verbatim over an ICESEE-native manager (run_records.py-backed).
        # Results reuse the existing local figures/H5 preview; the DA-aware
        # ResultPackage (ensemble/analysis/RMSE) is a separate, larger port.
        # =========================================================
        icesee_runs_manager = IceseeRunsManager(root=_icesee_run_dir_base())

        def _sync_icesee_cloud_run_results(run) -> None:
            """Best-effort S3 -> local sync before showing Results for a
            selected CLOUD run -- resolved from the run's OWN persisted
            identity (metadata['aws_resources']), never the live Cloud panel
            widgets, so a later visit stays correct regardless of what has
            since changed there. Never breaks the Results view: a sync
            failure (unreachable AWS, no S3 identity yet, ...) just leaves
            whatever is already local in place."""
            if run.execution_mode != "cloud" or not run.jobid:
                return
            resources = (run.metadata or {}).get("aws_resources") or {}
            s3_run = resources.get("s3_run") or (
                str(run.remote_directory) if run.remote_directory else ""
            )
            if not s3_run:
                return
            try:
                execution = _resolve_icesee_cloud_execution(
                    region_override=resources.get("region"),
                )
                sync_icesee_cloud_results(
                    IceseeCloudBridgeConfig(
                        region=execution.region, profile=execution.profile,
                        credentials=execution.credentials,
                    ),
                    s3_run=s3_run, local_dir=run.workspace_directory,
                )
            except Exception as _e:
                with results_out:
                    print(f"[cloud] result sync skipped: {type(_e).__name__}: {_e}")

        # =========================================================
        # Run plan rows -- execution semantics (mode / compute backend /
        # model environment) plus ICESEE's DA identity
        # (DAIdentity.summary_rows()), shown in Review & launch. Computing
        # them also drives the MATLAB-licence and institutional-connection
        # visibility of the Cloud card.
        # =========================================================
        def _update_icesee_run_plan_summary(_=None):
            mode = get_mode()
            mode_label = {
                MODE_LOCAL: "Local", MODE_REMOTE: "Remote", MODE_CLOUD: "Cloud",
            }.get(mode, mode)
            backend_label = {
                MODE_LOCAL: "Local",
                MODE_REMOTE: {"spack": "ICESEE-Spack", "container": "ICESEE-Container"}
                    .get(exec_backend_choice.value, exec_backend_choice.value),
                MODE_CLOUD: "AWS Batch",
            }.get(mode, mode)
            model_environment = {
                MODE_LOCAL: "ICESEE (native Python)",
                MODE_REMOTE: backend_label,
                MODE_CLOUD: "AWS Batch container",
            }.get(mode, "")
            rows = [
                ("Execution mode", mode_label),
                ("Compute backend", backend_label),
                ("Model environment", model_environment),
            ]
            _icesee_forecast_model = example_dd.value
            try:
                identity = da_identity_from_params(build_config_from_widgets())
                rows += identity.summary_rows()
                _icesee_forecast_model = (
                    identity.forecast_model or identity.example_name
                    or example_dd.value)
            except Exception:
                pass    # a mid-edit params.yaml must never break the summary

            # MATLAB license visibility is driven EXCLUSIVELY by the single
            # workflow-capability resolver -- never a duplicated
            # "model == issm" check -- so an ICESEE run whose forecast model
            # is ISSM (alone or coupled with Icepack) shows the same field a
            # direct ISSM run does. Independent of Basic/Advanced mode;
            # hiding it never clears the value (see wire_matlab_license_
            # widgets). Reuses the SAME identity this Run Plan row already
            # computed above -- no second parse of the params.
            _icesee_capabilities = resolve_workflow_capabilities(
                model="icesee", forecast_model=_icesee_forecast_model)
            icesee_cloud_environment.matlab_license_box.layout.display = (
                "" if _icesee_capabilities.requires_matlab_license else "none")

            # INSTITUTIONAL CONNECTION: shown only when this ICESEE
            # workflow needs MATLAB AND this site's CloudMatlabLicense.
            # requires_tunnel is True -- never a generic "Cloud uses
            # Connector" requirement. Uses the cheap, config-independent
            # site fact (site_requires_cloud_license_tunnel) rather than a
            # full execution.matlab_license resolution here: this summary
            # re-renders on every widget change and must never trigger a
            # fresh AWS sts:AssumeRole just to decide visibility. The
            # actual submit call and Review & Launch still read the one
            # real, configuration-aware CloudMatlabLicense object.
            from cryostack_src.cloud.matlab_license import (
                site_requires_cloud_license_tunnel,
            )

            _icesee_requires_connector = bool(
                _icesee_capabilities.requires_matlab_license
                and site_requires_cloud_license_tunnel())
            icesee_cloud_environment.institutional_connection_box.layout.display = (
                "" if _icesee_requires_connector else "none")
            if _icesee_requires_connector:
                _refresh_institutional_connection()

            _WF["plan_rows"] = rows
            if "summary" in _WF:
                _WF["summary"](rows)

        mode_tabs.observe(_update_icesee_run_plan_summary, names="selected_index")
        exec_backend_choice.observe(_update_icesee_run_plan_summary, names="value")
        example_dd.observe(_update_icesee_run_plan_summary, names="value")
        filter_alg_dd.observe(_update_icesee_run_plan_summary, names="value")
        ens_sl.observe(_update_icesee_run_plan_summary, names="value")

        # ssh_key_manager_box = W.Accordion(children=[ssh_key_manager])
        # # ssh_key_manager_box.set_title(0, "🔐 SSH Key Manager")
        # ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        # ssh_key_manager_box.selected_index = None

        # Remote panel. Authentication + the connector card + "Open Connector
        # Setup" now live inside the Remote connection panel (B4). "Check SSH
        # Access" is the panel's primary action. Status / Tail / Terminate are
        # NOT duplicated here -- Status/Tail live in the Workspace Run Log
        # toolbar and Terminate lives in the Execution panel, matching
        # CryoLauncher's own placement exactly (only "Check SSH"-style connect
        # actions are ever duplicated, into the Workspace toolbar).
        remote_box = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Remote</div>"),
                remote_conn_box,
                exec_backend_box,
                slurm_box,
                ssh_key_manager_box,
            ],
            layout=W.Layout(gap="8px"),
        )
        remote_box.add_class("cryostack-remote-config")

        # Cloud panel -- the shared Cloud Environment card itself. Status/
        # Logs live in the Workspace Run Log toolbar; Terminate lives in the
        # Execution panel; Submit only happens through its own Review &
        # Launch (wired below) -- neither is duplicated here.
        cloud_panel = icesee_cloud_environment.container
        # Cloud's own MPI processes -- never the Remote tab's Slurm value: the
        # cloud task has cloud_max_np() vCPUs
        cloud_mpi_np = W.BoundedIntText(value=1, min=1, max=cloud_max_np(), layout=W.Layout(width="90px"))

        def _cloud_np_default(_=None):
            model = (EXAMPLES[example_dd.value].get("model_name") or "").lower()
            cloud_mpi_np.value = min(cloud_max_np(), 2 if model == "icepack" else 1)

        example_dd.observe(_cloud_np_default, names="value")
        _cloud_np_default()
        _cloud_body = icesee_cloud_environment.container.children[0]
        _cloud_body.children = (*_cloud_body.children[:3], W.HBox(
            [W.HTML("<div style='font-size:12px;color:#66758d;width:110px'>MPI processes:</div>"), cloud_mpi_np,
             W.HTML(f"<div class='cryostack-help' style='margin-left:8px'>1-{cloud_max_np()} "
                    "(the cloud task's vCPUs)</div>")],
            layout=W.Layout(align_items="center", gap="6px")), *_cloud_body.children[3:])
        cloud_panel.add_class("cryostack-cloud-config")

        # =========================================================
        # AWS ACCOUNT -- the SAME generic onboarding callbacks CryoLauncher
        # uses (connect / verify / re-check / disconnect / retry / change
        # account), scoped to whichever CryoStack user is authenticated,
        # not an ICESEE-only credential path.
        # =========================================================
        def _icesee_aws_onboarding_factory():
            from cryostack_src.cloud.connect import AWSOnboarding
            return AWSOnboarding(
                user=resolve_workspace_user(require_authenticated=False),
                region=(icesee_cloud_environment.region.value or "us-east-1").strip(),
            )

        icesee_aws_connect = build_aws_connect_callbacks(
            widgets=icesee_cloud_environment,
            onboarding_factory=_icesee_aws_onboarding_factory,
            log_output=log_out,
        )
        icesee_cloud_environment.connect_button.on_click(icesee_aws_connect.connect)
        icesee_cloud_environment.verify_button.on_click(icesee_aws_connect.verify)
        icesee_cloud_environment.recheck_button.on_click(icesee_aws_connect.recheck)
        icesee_cloud_environment.disconnect_button.on_click(icesee_aws_connect.disconnect)
        icesee_cloud_environment.update_role_button.on_click(icesee_aws_connect.update_role)
        icesee_cloud_environment.retry_button.on_click(icesee_aws_connect.retry)
        icesee_cloud_environment.change_account_button.on_click(icesee_aws_connect.change_account)
        icesee_cloud_environment.change_verify_button.on_click(icesee_aws_connect.change_verify)
        icesee_cloud_environment.change_cancel_button.on_click(icesee_aws_connect.change_cancel)
        icesee_aws_connect.refresh()

        # -- MATLAB license: the SAME shared field/save behavior
        # CryoLauncher's own Cloud panel uses (cloud_environment.
        # wire_matlab_license_widgets) -- one implementation, so a direct
        # ISSM run and an ICESEE run using ISSM configure/save the license
        # identically. Visibility is wired below in
        # _update_icesee_run_plan_summary, driven exclusively by
        # resolve_workflow_capabilities(...).requires_matlab_license.
        wire_matlab_license_widgets(
            icesee_cloud_environment,
            owner=resolve_workspace_user(require_authenticated=False),
            log_output=log_out,
        )

        # -- INSTITUTIONAL CONNECTION: Cloud reads the SAME Connector
        # binding/session Remote uses (_connector_is_online/create_or_
        # refresh_connector_session/disconnect_connector, defined above) --
        # never a second Connector implementation, pairing, identity, or
        # session. Pairing (or disconnecting) here is exactly the same
        # action as doing so in Remote.
        _refresh_institutional_connection = wire_institutional_connection_widgets(
            icesee_cloud_environment,
            check_connected=_connector_is_online,
            session_state=lambda: SESSION,
            open_connector=create_or_refresh_connector_session,
            disconnect=disconnect_connector,
            app="icesee",
            log_output=log_out,
        )

        # =========================================================
        # INFRASTRUCTURE readiness + Prepare Cloud -- the SAME generic,
        # non-blocking coordinator CryoLauncher uses
        # (build_cloud_environment_ops); Test/Prepare never depend on a
        # model, only on the connected account's own AWS capabilities.
        # =========================================================
        def _icesee_update_infrastructure_rows(capabilities):
            rows = {
                "account": icesee_cloud_environment.account_status,
                "storage": icesee_cloud_environment.storage_status,
                "registry": icesee_cloud_environment.registry_status,
                "compute": icesee_cloud_environment.compute_status,
            }
            for key, ready, ready_label, missing_label in (
                ("account", getattr(capabilities, "authenticated", False), "Connected", "Not connected"),
                ("storage", getattr(capabilities, "storage_ready", False), "Ready", "Not prepared"),
                ("registry", getattr(capabilities, "registry_ready", False), "Ready", "Not prepared"),
                ("compute", getattr(capabilities, "batch_ready", False), "Ready", "Not prepared"),
            ):
                # amber = something to do (connect / Prepare cloud); red is
                # kept for operations that actually failed
                set_cloud_status(rows[key], state="done" if ready else "warning",
                                 label=ready_label if ready else missing_label)
            _icesee_refresh_estimate(all(getattr(capabilities, attr, False) for attr in (
                "authenticated", "storage_ready", "registry_ready", "batch_ready")))

        def _icesee_cloud_check_worker():
            execution = _resolve_icesee_cloud_execution()
            bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))
            return bridge.check_environment()

        def _icesee_cloud_check_success(capabilities):
            _icesee_update_infrastructure_rows(capabilities)
            with log_out:
                print("[cloud] Environment check")
                for m in (getattr(capabilities, "messages", None) or []):
                    print(" ", m)

        def _icesee_cloud_prepare_worker():
            execution = _resolve_icesee_cloud_execution()
            bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))
            bucket = execution.defaults.bucket if (execution.is_byo and execution.defaults) else None
            return bridge.prepare_environment(bucket=bucket)

        def _icesee_cloud_prepare_success(result):
            with log_out:
                print("[cloud] Prepare cloud")
                for m in ((result or {}).get("messages") if isinstance(result, dict) else None) or []:
                    print(" ", m)
            # re-check to reflect the REAL post-prepare state -- never
            # hardcode Ready just because Prepare ran without raising.
            try:
                _icesee_update_infrastructure_rows(_icesee_cloud_check_worker())
            except Exception as _err:
                # never leave the rows on "Preparing…": say the state is unknown
                for _row in (icesee_cloud_environment.account_status, icesee_cloud_environment.storage_status,
                             icesee_cloud_environment.registry_status, icesee_cloud_environment.compute_status):
                    set_cloud_status(_row, state="warning", label="Not verified")
                _icesee_refresh_estimate(False)
                with log_out:
                    print("[cloud][WARN] could not re-check the environment after Prepare:",
                          type(_err).__name__, _err)

        icesee_cloud_ops = build_cloud_environment_ops(
            buttons={"test": icesee_cloud_environment.test_button,
                     "prepare": icesee_cloud_environment.prepare_button},
            rows={"account": icesee_cloud_environment.account_status,
                  "storage": icesee_cloud_environment.storage_status,
                  "registry": icesee_cloud_environment.registry_status,
                  "compute": icesee_cloud_environment.compute_status},
            set_row=set_cloud_status,
            set_chip=lambda _k: None,
            log_output=log_out,
        )
        icesee_cloud_environment.test_button.on_click(
            lambda _=None: icesee_cloud_ops.test_connection(
                _icesee_cloud_check_worker, _icesee_cloud_check_success))
        icesee_cloud_environment.prepare_button.on_click(
            lambda _=None: icesee_cloud_ops.prepare_cloud(
                _icesee_cloud_prepare_worker, _icesee_cloud_prepare_success))

        # =========================================================
        # RUN ESTIMATE / Review & Launch -- ICESEE's OWN DA-aware review
        # (icesee_jupyter_book/core/cloud_review.py), rendered into the SAME
        # shared review_body/launch_button widgets, never CryoLauncher's
        # model/example/run_target review schema. As in CryoLauncher the
        # estimate and Review & Launch appear once Test connection / Prepare
        # cloud report every row Ready; Launch stays gated inside the review.
        # =========================================================
        _icesee_estimate_state = {"seq": 0}

        def _icesee_refresh_estimate(ready: bool) -> None:
            _icesee_estimate_state["seq"] += 1
            seq = _icesee_estimate_state["seq"]
            if not ready:
                set_run_estimate_view(icesee_cloud_environment, visible=False)
                return
            set_run_estimate_view(icesee_cloud_environment, visible=True)
            icesee_cloud_environment.run_estimate_line.value = (
                "<div class='cryostack-estimate-pending'>Cloud environment is ready. "
                "Preparing your run estimate…</div>")
            region = aws_region.value.strip() or "us-east-1"
            compute_mode = getattr(icesee_cloud_environment.compute_mode, "value", "fargate")
            example = example_dd.value

            def worker():
                from cryostack_src.cloud.estimate.pricing import resolve_fargate_prices

                try:
                    durations = completed_cloud_minutes(run_records.discover_runs(_icesee_run_dir_base()),
                                                        example=example)
                except Exception:  # noqa: BLE001 - history is best-effort
                    durations = []
                prices = None if compute_mode == "ec2" else resolve_fargate_prices(region)
                estimate = icesee_run_estimate(region=region, compute_mode=compute_mode,
                                               durations_minutes=durations, prices=prices)
                if seq == _icesee_estimate_state["seq"]:      # a newer refresh wins
                    set_run_estimate_view(icesee_cloud_environment, visible=True, **estimate)

            threading.Thread(target=worker, daemon=True).start()

        set_run_estimate_view(icesee_cloud_environment, visible=False)

        _icesee_review_state = {"review": None}

        def _icesee_build_review():
            sync_quick_into_widgets()
            cfg_yaml = build_config_from_widgets()
            identity = da_identity_from_params(cfg_yaml)

            execution = _resolve_icesee_cloud_execution()
            bridge = build_icesee_cloud_bridge(_icesee_cloud_bridge_config(execution))
            try:
                caps = bridge.check_environment()
            except Exception:
                caps = None
            infra = InfrastructureReadiness(
                account=bool(getattr(caps, "authenticated", False)) and execution.is_byo,
                storage=bool(getattr(caps, "storage_ready", False)),
                container=bool(getattr(caps, "registry_ready", False)),
                compute=bool(getattr(caps, "batch_ready", False)),
            )
            return build_icesee_cloud_review(
                forecast_model=(identity.forecast_model or identity.example_name
                                or example_dd.value),
                filter_alg=identity.assimilation_filter or filter_alg_dd.value,
                ensemble_size=int(identity.ensemble_size or ens_sl.value),
                parallel_processes=int(cloud_mpi_np.value),
                account_id=execution.account_id, region=execution.region,
                infrastructure=infra, account_freshly_verified=execution.is_byo,
                # the example's own folder name (e.g. "synthetic_ice_stream"),
                # never the menu label -- the cloud runtime is keyed by it
                example_name=Path(EXAMPLES[example_dd.value]["base"]).name,
                matlab_license_configured=bool(
                    getattr(execution.matlab_license, "configured", False)),
                matlab_license_requires_tunnel=bool(
                    getattr(execution.matlab_license, "requires_tunnel", False)),
                connector_connected=_connector_is_online(),
                compute_mode=getattr(
                    icesee_cloud_environment.compute_mode, "value", "fargate"),
            )

        def _on_icesee_review_click(_=None):
            try:
                review = _icesee_build_review()
            except Exception as e:
                with log_out:
                    print("[cloud][ERROR] could not build the review:", type(e).__name__, e)
                return
            _icesee_review_state["review"] = review
            render_icesee_review_panel(icesee_cloud_environment, review)
            icesee_cloud_environment.review_panel.layout.display = "flex"

        def _on_icesee_review_back(_=None):
            icesee_cloud_environment.review_panel.layout.display = "none"

        def _on_icesee_launch_click(_=None):
            review = _icesee_review_state.get("review")
            if review is None or not review.can_launch:
                return
            icesee_cloud_environment.review_panel.layout.display = "none"
            before = STATUS.get("batch_job_id")
            run_example_cloud_submit()
            if STATUS.get("batch_job_id") and STATUS.get("batch_job_id") != before and "after_submit" in _WF:
                _WF["after_submit"]("cloud")

        icesee_cloud_environment.review_button.on_click(_on_icesee_review_click)
        icesee_cloud_environment.review_back_button.on_click(_on_icesee_review_back)
        icesee_cloud_environment.launch_button.on_click(_on_icesee_launch_click)

        mode_tabs.children = [local_tab_card, remote_box, cloud_panel]
        mode_tabs.selected_index = 0

        local_tab_card.layout = W.Layout(width="100%")
        remote_box.layout   = W.Layout(width="100%")
        cloud_panel.layout     = W.Layout(width="100%")

        # Workspace Run Log toolbar: swapped by execution mode, exactly the
        # CryoLauncher pattern (log_runtime_controls in icesheets_gateway.py)
        # -- status/tail/connect-type diagnostics live here, never in the
        # scientific config panel, and never a second time in Execution.
        log_runtime_controls = build_workspace_toolbar([])

        def _toggle_panels_from_tabs(_=None):
            mode = get_mode()

            is_remote = (mode == MODE_REMOTE)
            connect_btn.disabled = not is_remote
            submit_btn.disabled = not is_remote
            tail_btn.disabled = not is_remote
            terminate_btn.disabled = not is_remote
            terminate_btn.layout.display = "" if is_remote else "none"

            is_cloud = (mode == MODE_CLOUD)
            cloud_logs_btn.disabled = not is_cloud
            cloud_terminate_btn.disabled = not is_cloud
            cloud_terminate_btn.layout.display = "" if is_cloud else "none"

            # Cloud submission only happens through Review & Launch (inside
            # the Cloud Environment card) -- the generic Execution Run
            # button is hidden for Cloud, the same rule CryoLauncher's
            # run_btn follows for its own cloud path (a lesson from a real
            # live-acceptance bug: two submit surfaces for the same job).
            action_btn.layout.display = "none" if is_cloud else ""

            if is_remote:
                log_runtime_controls.children = (connect_btn, tail_btn, clear_btn)
            elif is_cloud:
                log_runtime_controls.children = (cloud_logs_btn, clear_btn)
            else:
                log_runtime_controls.children = (clear_btn,)

            update_action_button()

        mode_tabs.observe(_toggle_panels_from_tabs, names="selected_index")
        _toggle_panels_from_tabs()

        exec_backend_choice.observe(_toggle_exec_backend_ui, names="value")
        _toggle_exec_backend_ui()

        log_out.add_class("icesee-out")
        results_out.add_class("icesee-out")

        # =========================================================
        # Workflow UI (ui/icesee_workflow): Mode first -> experiment ->
        # environment & resources -> scientific parameters -> Review &
        # launch (which becomes the active run) on the left; the workspace
        # (Run / Files / Editor / Logs / Results) on the right follows the
        # selected run. Every Remote/Cloud widget and handler above is
        # reused as is -- this block only arranges and connects them.
        # =========================================================
        stepper = Stepper()
        _MODE_INDEX = {"local": 0, "cluster": 1, "cloud": 2}
        _MODE_TITLE = {"local": "Local", "cluster": "Remote HPC", "cloud": "Cloud"}
        _drafts_base = _icesee_run_dir_base()
        _drafts_root = (Path(_drafts_base).parent / "icesee_drafts") if _drafts_base else (Path(__file__).resolve().parents[1] / "icesee_drafts")

        def _experiment_files() -> ExperimentFiles:
            return ExperimentFiles(EXAMPLES[example_dd.value]["base"], _drafts_root, example_key=example_dd.value)

        # the user's own plotting code, next to their drafts (core/user_plots.py)
        _plots_root = _drafts_root.parent / "icesee_plots"

        def _plot_workspace(example_key: str, contract_dir=None) -> PlotWorkspace:
            if contract_dir is None:
                contract_dir = EXAMPLES[example_key]["base"]
            return PlotWorkspace(_plots_root, example_key, contract_dir)

        _WF["experiment_files"] = _experiment_files

        # ── 1. Mode ────────────────────────────────────────────────────────
        mode_selector = ModeSelector(initial=get_mode())
        local_env = LocalEnvironmentPanel()
        _WF["local_env"] = local_env
        local_tab_card.children = (local_env.container,)
        local_tab_card.remove_class("icesee-card")

        def _on_mode_selected(change):
            idx = _MODE_INDEX[change["new"]]
            if mode_tabs.selected_index != idx:
                mode_tabs.selected_index = idx

        mode_selector.toggle.observe(_on_mode_selected, names="value")

        # ── 2. Experiment ──────────────────────────────────────────────────
        example_status = W.HTML()
        example_picker = ExamplePicker(example_dd)
        for _w in (example_dd, preset_dd, filter_alg_dd, seed_in):
            _w.layout = W.Layout(width="100%")
        example_dd.layout.display = "none"      # the pickers above are its visible face
        ens_sl.layout = W.Layout(width="100%")
        ens_sl.tooltip = "Number of ensemble members (enkf-parameters.Nens)"
        filter_alg_dd.tooltip = "Assimilation filter (enkf-parameters.filter_type)"
        seed_in.tooltip = "Random seed (enkf-parameters.seed)"
        experiment_card = card(
            [field("Application", example_picker.application), field("Example", example_picker.example),
             example_picker.note, example_status, example_dd,
             W.VBox([field("Filter", filter_alg_dd),
                     field("Ensemble size", ens_sl, "members"),
                     field("Seed", seed_in),
                     field("Preset", preset_dd)], layout=W.Layout(gap="8px"))],
            title="Experiment", number=2, subtitle="The ICESEE example and its data-assimilation set-up.",
            css="icw-anchor-experiment")

        # ── 3. Environment & resources ─────────────────────────────────────
        env_subtitle = W.HTML()
        for _child in (local_tab_card, remote_box, cloud_panel):
            _child.add_class("icw-pane")
        environment_card = card([env_subtitle, mode_tabs], title="Environment & resources", number=3,
                                css="icw-anchor-environment")

        # ── 4. Scientific parameters ───────────────────────────────────────
        open_params_btn = W.Button(description="Edit params.yaml", icon="pencil",
                                   tooltip="Open the full configuration in the Editor (validated, applied to this form)")
        open_params_btn.add_class("icw-btn-secondary")
        params_note = W.HTML("<div class='icw-card-sub'>Every key of the example's <code>params.yaml</code>. "
                             "Filter, ensemble size and seed above take precedence.</div>")
        params_disclosure = W.Accordion(children=[W.VBox([params_note, params_holder], layout=W.Layout(gap="8px"))],
                                        selected_index=None)
        params_disclosure.set_title(0, "All parameters")
        parameters_card = card([params_disclosure], title="Scientific parameters", number=4,
                               subtitle="Physical, modelling and assimilation settings.", right=open_params_btn,
                               css="icw-anchor-parameters")

        # ── workspace (right) and Review & launch (left) ───────────────────
        _active = {"run_id": None, "monitors": {}}

        def _current_config() -> dict:
            sync_quick_into_widgets()
            return build_config_from_widgets()

        def _apply_config(data: dict) -> None:
            if not isinstance(data, dict):
                raise ValueError("params.yaml must be a mapping of sections")
            enkf = data.get("enkf-parameters") or {}
            if enkf.get("filter_type") in [v for _l, v in filter_alg_dd.options]:
                filter_alg_dd.value = enkf["filter_type"]
            if isinstance(enkf.get("Nens"), int) and enkf["Nens"] >= 1:
                ens_sl.max = max(ens_sl.max, enkf["Nens"])
                ens_sl.value = enkf["Nens"]
            if isinstance(enkf.get("seed"), int):
                seed_in.value = enkf["seed"]
            build_params_ui(data)
            params_holder.children = (params_accordion,)
            _workflow_refresh()

        def _load_run(run_id):
            icesee_runs_manager.refresh()
            return icesee_runs_manager.select_run(run_id) if run_id else None

        def _show_active(run_id, status=None):
            run = run_records.load_run(_icesee_run_dir_base(), run_id) if run_id else None
            if run is None:
                return
            if _active["run_id"] == run_id:
                launch_panel.show_run(run, status=status)
                stepper.set_live(launch_panel.live_html)
            if workspace.selected is not None and workspace.selected.id == run_id:
                if status is None:
                    workspace.reload_selected()
                elif workspace.tabs.value == "Logs":
                    workspace.refresh_log()
            _update_stepper()

        def _watch(run_id, job, model):
            if run_id in _active["monitors"]:
                return
            _last = {"log": 0.0}

            def on_update(status):
                _show_active(run_id, status)
                if (workspace.selected is not None and workspace.selected.id == run_id
                        and workspace.tabs.value == "Logs" and _time.time() - _last["log"] > 2):
                    _last["log"] = _time.time()
                    workspace.refresh_log()

            def on_finish(status):
                run_launcher.finalize_local_run(job.run_dir, status)
                _active["monitors"].pop(run_id, None)
                with log_out:
                    print(f"[local] Run {run_id}: {status.state}" + (f" — {status.detail}" if status.detail else ""))
                workspace.refresh_runs(select=workspace.selected.id if workspace.selected else run_id)
                _show_active(run_id)
                if workspace.selected is not None and workspace.selected.id == run_id:
                    workspace._results = None
                    if workspace.tabs.value in ("Results", "Logs"):
                        workspace._refresh_visible()

            _active["monitors"][run_id] = JobMonitor(job, on_update=on_update, on_finish=on_finish,
                                                     model_name=model).start()
            _active["run_id"] = run_id
            workspace.refresh_runs(select=run_id)
            _show_active(run_id)

        _WF["watch"] = _watch

        def _after_submit(mode):
            rd = STATUS.get("local_run_dir")
            if not rd:
                return None
            run_id = Path(rd).name
            try:
                cfg_resources = {"mode": mode}
                if mode == "remote":
                    cfg_resources.update({"cluster": cluster_name_for_keys.value, "backend": exec_backend_choice.value,
                                          "nodes": slurm_nodes.value, "tasks": slurm_ntasks.value,
                                          "tasks_per_node": slurm_tpn.value, "partition": slurm_part.value,
                                          "wall_time": slurm_time.value, "memory": slurm_mem.value,
                                          "mpi_np": cluster_mpi_np.value, "model_nprocs": cluster_model_nprocs.value})
                else:
                    cfg_resources.update({"region": aws_region.value.strip(), "mpi_np": cloud_mpi_np.value,
                                          "model_nprocs": cluster_model_nprocs.value})
                record = run_provenance.collect(
                    run_id=run_id, run_dir=Path(rd), example=example_dd.value, example_cfg=EXAMPLES[example_dd.value],
                    mode=mode, backend=exec_backend_choice.value if mode == "remote" else "aws-batch",
                    params_file=Path(rd) / "params.yaml",
                    environment={"environment": exec_backend_choice.value if mode == "remote" else "aws-batch",
                                 "image": container_image_uri.value if (mode == "remote" and exec_backend_choice.value
                                                                        == "container") else None},
                    resources=cfg_resources, user_id=resolve_workspace_user(require_authenticated=False).user_id)
                _update_icesee_run(Path(rd), extra_metadata={"provenance": run_provenance.summary(record)})
            except Exception as _e:
                with log_out:
                    print("[history][WARN] provenance not recorded:", type(_e).__name__, _e)
            _active["run_id"] = run_id
            workspace.refresh_runs(select=run_id)
            _show_active(run_id)
            return run_id

        _WF["after_submit"] = _after_submit

        class _Host:
            runs_manager = icesee_runs_manager
            activity_output = log_out

            def example_key(self):
                return example_dd.value

            def experiment_files(self):
                return _experiment_files()

            def plot_workspace(self, example_key, contract_dir=None):
                return _plot_workspace(example_key, contract_dir)

            def current_config(self):
                return _current_config()

            def apply_config(self, data):
                _apply_config(data)

            def template(self):
                return dict(_TEMPLATE["data"])

            def reconcile(self, run):
                state, job = run_launcher.reconcile_local_run(run)
                if job is not None:
                    _watch(run.id, job, (run.metadata or {}).get("forecast_model", ""))

            def on_run_selected(self, run):
                remote_fetch_row.layout.display = "" if (run is not None and run.execution_mode == "remote") else "none"
                status_btn.layout.display = "" if (run is not None and run.execution_mode == "remote") else "none"
                cloud_status_btn.layout.display = "" if (run is not None and run.execution_mode == "cloud") else "none"
                if run is not None and run.execution_mode == "remote":
                    STATUS.update(jobid=run.jobid, remote_dir=str(run.remote_directory or "") or None,
                                  local_run_dir=str(run.workspace_directory))
                elif run is not None and run.execution_mode == "cloud":
                    STATUS.update(batch_job_id=run.jobid, local_run_dir=str(run.workspace_directory),
                                  s3_run=str(run.remote_directory or "") or None)

                    def _sync_then_refresh(run=run):
                        _sync_icesee_cloud_run_results(run)
                        if workspace.selected is not None and workspace.selected.id == run.id:
                            workspace._results = None
                            if workspace.tabs.value == "Results":
                                workspace.refresh_results(force=True)
                    workspace._threaded(_sync_then_refresh)
                _update_stepper()

            def run_extra_html(self, run):
                """ICESEE's checkpoint/progress panel for the selected run."""
                try:
                    return run_progress_html(run.workspace_directory)
                except Exception:
                    return ""

            def on_workspace_tab(self, tab):
                _update_stepper()

            def cancel_run(self, run):
                state = run_lifecycle.current_state(run)
                if state not in run_lifecycle.ACTIVE:
                    return False, "This run is not active."
                if run.execution_mode == "local":
                    job = LocalJob(run.workspace_directory)
                    if not job.exists:
                        run_lifecycle.transition(run.workspace_directory, run_lifecycle.CANCELLED,
                                                 detail="cancelled before it started")
                        return True, "Cancelled."
                    job.cancel()
                    return True, "Cancel requested — the run stops within a few seconds."
                self.on_run_selected(run)
                if run.execution_mode == "remote":
                    run_example_remote_cancel()
                else:
                    run_example_cloud_terminate()
                workspace.reload_selected()
                ok = run_lifecycle.current_state(_load_run(run.id)) == run_lifecycle.CANCELLED
                return ok, ("Cancelled." if ok else "The cancellation did not go through. See Logs › Launcher activity.")

            def reuse_configuration(self, run):
                if run is None:
                    return
                params_file = Path(run.workspace_directory) / "params.yaml"
                example = (run.metadata or {}).get("example")
                if example in EXAMPLES and example_dd.value != EXAMPLES.canonical(example):
                    example_dd.value = EXAMPLES.canonical(example)
                mode = {"local": "local", "remote": "cluster", "cloud": "cloud"}.get(run.execution_mode, "local")
                mode_selector.toggle.value = mode
                if params_file.is_file():
                    _apply_config(load_yaml(params_file))
                launch_panel.show_review()
                launch_panel.message.value = (
                    f"<div class='icw-callout info' role='status'><span class='ico'>ℹ</span><div>Loaded the "
                    f"configuration of run <code>{html_lib.escape(run.id)}</code>. Review it and launch.</div></div>")
                _update_stepper()

            def on_drafts_changed(self):
                _workflow_refresh()

        workspace = RunWorkspace(_Host())
        _WF["workspace"] = workspace

        # Remote runs: fetch the job's outputs into the run folder so Results
        # can read them (Cloud runs sync from S3 when Results opens).
        def _fetch_selected_remote(_=None):
            run = workspace.selected
            if run is None or run.execution_mode != "remote":
                return
            _host_obj = workspace.host
            _host_obj.on_run_selected(run)
            target = Path(run.workspace_directory) / "outputs"
            fetched = fetch_remote_outputs_to_local(target_dir=target)
            with log_out:
                print("[results] fetched to", fetched if fetched else "(nothing fetched)")
            workspace.refresh_results(force=True)

        fetch_remote_btn = W.Button(description="Fetch outputs from cluster", icon="cloud-download",
                                    tooltip="Copy this job's outputs into the run folder (rsync or the Connector)")
        fetch_remote_btn.add_class("icw-btn-secondary")
        fetch_remote_btn.on_click(lambda _b: workspace._threaded(_fetch_selected_remote))
        remote_fetch_row = W.HBox([fetch_remote_btn])
        remote_fetch_row.add_class("icw-actions")
        remote_fetch_row.layout.display = "none"
        # messages of the Remote fetch / Cloud S3 sync, next to the results they concern
        results_out.layout = W.Layout(width="100%", max_height="220px", overflow="auto")
        workspace.results_pane.children = (remote_fetch_row, results_out, *workspace.results_pane.children)
        workspace.log_controls_extra.children = (log_runtime_controls,)
        status_btn.tooltip = "Ask the cluster for this job's state (squeue / sacct)"
        cloud_status_btn.tooltip = "Ask AWS Batch for this job's state"
        workspace.backend_actions.children = (status_btn, cloud_status_btn)
        # the gateway's Remote/Cloud log tools, in the workflow's button hierarchy;
        # "Clear" is the workspace's own (Logs › Launcher activity)
        for _b in (connect_btn, status_btn, tail_btn, cloud_status_btn, cloud_logs_btn,
                   preview_results_btn, results_download_btn):
            _b.add_class("icw-btn-secondary")
        clear_btn.layout.display = "none"
        open_params_btn.on_click(lambda _b: workspace.open_in_editor("params.yaml"))

        # ── 5. Review & launch ─────────────────────────────────────────────
        def _workflow_validate():
            mode = get_mode()
            example_cfg = EXAMPLES[example_dd.value]
            req = run_launcher.LaunchRequest(
                example=example_dd.value, example_cfg=example_cfg, config=_current_config(),
                environment=local_env.env.value, np=int(local_env.np.value),
                model_nprocs=int(local_env.model_nprocs.value),
                drafts=_experiment_files().drafts_in_use())
            if mode == MODE_LOCAL:
                return run_launcher.validate_launch(req)
            issues = run_launcher.validate_launch(req, mode="remote" if mode == MODE_REMOTE else "cloud")
            if mode == MODE_REMOTE:
                if not cluster_host.value.strip():
                    issues.append(Issue("error", "Remote connection: the login host is empty"))
                if not cluster_user.value.strip():
                    issues.append(Issue("error", "Remote connection: enter your HPC username"))
                if not remote_base_dir.value.strip():
                    issues.append(Issue("error", "Remote connection: enter your remote working directory"))
                for _m in validate_slurm_resources(
                        nodes=slurm_nodes.value, tasks=slurm_ntasks.value, tasks_per_node=slurm_tpn.value,
                        wall_time=slurm_time.value, memory=slurm_mem.value, account=slurm_account.value,
                        account_required=get_compute_profile(cluster_name_for_keys.value or "pace").account_required):
                    issues.append(Issue("error", f"Slurm resources: {_m}"))
            else:
                identity = da_identity_from_params(req.config)
                if (identity.example_name or "") != "lorenz96":
                    issues.append(Issue("warning", "Cloud execution has been verified for the Lorenz-96 example "
                                                   "only; the cloud review will tell you if this one is refused"))
            return issues

        def _workflow_launch():
            mode = get_mode()
            if mode == MODE_LOCAL:
                ok, message, run_id = run_example_local()
                if ok:
                    workspace.show("Run")
                return ok, message, run_id
            if mode == MODE_REMOTE:
                before = STATUS.get("jobid")
                run_example_remote_submit()
                if STATUS.get("jobid") and STATUS.get("jobid") != before:
                    run_id = _after_submit("remote")
                    workspace.show("Run")
                    return True, f"Submitted Slurm job {STATUS['jobid']}.", run_id
                workspace.show_activity()
                return False, "The job was not submitted. Details are in Logs › Launcher activity.", None
            _on_icesee_review_click()
            if icesee_cloud_environment.review_panel.layout.display == "none":
                workspace.show_activity()
                return False, "The cloud review could not be prepared. See Logs › Launcher activity.", None
            run_js(_js_out, "var e=document.querySelector('.cryostack-cloud-config');"
                            "if(e){e.scrollIntoView({behavior:'smooth',block:'center'});}")
            return True, "Review the launch in the Cloud panel above, then press Launch there.", None

        def _cancel_active(run):
            return workspace.host.cancel_run(run)

        launch_panel = LaunchPanel(
            on_launch=_workflow_launch, on_validate=_workflow_validate, on_cancel=_cancel_active,
            on_open_logs=lambda: workspace.focus(_active["run_id"], "Logs"),
            on_open_results=lambda: workspace.focus(_active["run_id"], "Results"))
        _WF["activity"] = lambda state: launch_panel.set_activity(state)
        # Cloud submits only through the cloud card's own gated Launch. Its
        # Review & Launch (shown with the estimate once the environment is
        # Ready) and step 5's button both open that same review.

        def _summary_rows(rows):
            mode = get_mode()
            env_rows = []
            if mode == MODE_LOCAL:
                env_rows = [("Runs in", {v: l for l, v in local_env.env.options}.get(local_env.env.value,
                                                                                     local_env.env.value))]
                if local_env.env.value == "container":
                    env_rows.append(("MPI processes", str(local_env.np.value)))
            elif mode == MODE_REMOTE:
                env_rows = [("Resource", cluster_name_for_keys.value or cluster_host.value),
                            ("Slurm", f"{slurm_nodes.value} node(s) · {slurm_ntasks.value} tasks · {slurm_time.value}"),
                            ("MPI", f"np {cluster_mpi_np.value} · model {cluster_model_nprocs.value}")]
            else:
                env_rows = [("Region", aws_region.value.strip() or "us-east-1"),
                            ("Compute", getattr(icesee_cloud_environment.compute_mode, "value", "fargate")),
                            ("MPI processes", str(cloud_mpi_np.value))]
            drafts = sorted(_experiment_files().drafts_in_use())
            out = [("Mode", html_lib.escape(_MODE_TITLE[mode])),
                   ("Experiment", html_lib.escape(example_dd.value))]
            out += [(k, html_lib.escape(str(v))) for k, v in rows if k not in ("Execution mode",)]
            out += [(k, html_lib.escape(str(v))) for k, v in env_rows if v]
            if drafts:
                out.append(("Edited inputs", html_lib.escape(", ".join(drafts))
                            + (" <span class='icw-badge warn'>Local only</span>" if mode != MODE_LOCAL else "")))
            launch_panel.set_summary(out)

        _WF["summary"] = _summary_rows

        def _update_stepper():
            issues = launch_panel._issues or []
            errors = [i for i in issues if i.level == "error"]
            env_words = ("environment", "Docker", "MPI processes", "Remote connection", "Slurm", "cannot run")
            env_err = any(any(w in i.message for w in env_words) for i in errors)
            param_err = any(not any(w in i.message for w in env_words) for i in errors)
            active = _load_run(_active["run_id"]) if _active["run_id"] else None
            if workspace.selected is not None:
                icesee_runs_manager.select_run(workspace.selected.id)
            active_state = run_lifecycle.current_state(active)
            sel = workspace.selected
            states = {"Mode": "done", "Experiment": "done",
                      "Environment": "attention" if env_err else "done",
                      "Parameters": "attention" if param_err else "done",
                      "Review & launch": "attention" if errors else ("done" if active_state else "current")}
            if active_state in run_lifecycle.ACTIVE:
                states["Monitor"] = "current active"
            elif active_state:
                states["Monitor"] = "done"
            if sel is not None and run_lifecycle.current_state(sel) == run_lifecycle.COMPLETED:
                states["Results"] = "current" if workspace.tabs.value == "Results" else "done"
            stepper.update(states)

        def _workflow_refresh(_=None):
            mode = get_mode()
            env_subtitle.value = ("<div class='icw-card-sub'>" + {
                MODE_LOCAL: "This server's resources: the launcher's Python or the ICESEE container.",
                MODE_REMOTE: "Your cluster account, connection and Slurm request.",
                MODE_CLOUD: "Your AWS account, its prepared infrastructure, and the run estimate."}[mode] + "</div>")
            launch_panel.set_mode(mode)
            model = EXAMPLES[example_dd.value].get("model_name", "")
            local_env.set_model(model)
            try:
                _update_icesee_run_plan_summary()
            except Exception:
                pass
            from icesee_jupyter_book.core.local_jobs import environments as _envs
            if mode == MODE_LOCAL:
                envs = [e for e in _envs(model) if e.available]
                example_status.value = (
                    f"<div class='icw-badges'><span class='icw-badge ok'><span class='dot'></span>Runs here</span>"
                    f"<span class='icw-card-sub' style='margin:0'>{html_lib.escape(', '.join(e.label for e in envs))}</span></div>"
                    if envs else
                    "<div class='icw-badges'><span class='icw-badge bad'><span class='dot'></span>Not runnable on this "
                    "server</span><span class='icw-card-sub' style='margin:0'>Choose Remote HPC or Cloud.</span></div>")
            elif mode == MODE_REMOTE:
                example_status.value = ("<div class='icw-badges'><span class='icw-badge info'><span class='dot'></span>"
                                        "Submits to your cluster</span></div>")
            else:
                example_status.value = ("<div class='icw-badges'><span class='icw-badge info'><span class='dot'></span>"
                                        "AWS Batch</span><span class='icw-card-sub' style='margin:0'>Verified for "
                                        "Lorenz-96</span></div>")
            launch_panel.revalidate()
            _update_stepper()
            workspace.editor_sync_from_form()

        def _on_mode_index(_change=None):
            mode = get_mode()
            if mode_selector.toggle.value != mode:
                mode_selector.toggle.value = mode
            _workflow_refresh()

        mode_tabs.observe(_on_mode_index, names="selected_index")
        for _w in (filter_alg_dd, ens_sl, seed_in, exec_backend_choice, cluster_host, cluster_user,
                   remote_base_dir, slurm_account, slurm_time, slurm_nodes, slurm_ntasks, slurm_tpn, slurm_mem):
            _w.observe(_workflow_refresh, names="value")
        for _w in (local_env.env, local_env.np, local_env.model_nprocs):
            _w.observe(_workflow_refresh, names="value")
        def _example_changed():
            """A new example: its own filter, ensemble size and seed become the
            form's values (the quick controls must never silently override
            the example's defaults), then everything depending on it updates."""
            enkf = (_TEMPLATE["data"] or {}).get("enkf-parameters") or {}
            with ui_refresh.batch():
                if enkf.get("filter_type") in [v for _l, v in filter_alg_dd.options]:
                    filter_alg_dd.value = enkf["filter_type"]
                if isinstance(enkf.get("Nens"), int) and enkf["Nens"] >= 1:
                    ens_sl.max = max(200, enkf["Nens"])
                    ens_sl.value = enkf["Nens"]
                if isinstance(enkf.get("seed"), int):
                    seed_in.value = enkf["seed"]
            if workspace.tabs.value == "Editor":
                workspace.editor_refresh_list()
            _workflow_refresh()

        _WF["example_changed"] = _example_changed

        # ── page ───────────────────────────────────────────────────────────
        hero = W.HTML(
            "<div class='icw-hero'><div><h1>Ice-Sheet Modeling with Data Assimilation</h1>"
            "<p>Configure an ICESEE ensemble data-assimilation experiment, run it locally, on your cluster or in "
            "the cloud, and inspect its scientific results here.</p></div></div>")
        if os.environ.get("CRYOSTACK_AGENT_PANEL", "").strip().lower() in ("1", "true", "on", "yes"):
            from icesee_jupyter_book.ui.configuration_agent import build_icesee_configuration_agent

            def _agent_cloud_validate():
                return list(_icesee_build_review().blocked_reasons)

            icesee_agent = build_icesee_configuration_agent(
                fields=dict(profile=cluster_name_for_keys, nodes=slurm_nodes,
                            cpus=slurm_ntasks, tasks_per_node=slurm_tpn,
                            wall_time=slurm_time, memory=slurm_mem, account=slurm_account,
                            user=cluster_user, directory=remote_base_dir,
                            parallel_processes=cluster_mpi_np, model_processes=cluster_model_nprocs),
                example=example_dd, mode_tabs=mode_tabs, filter_widget=filter_alg_dd,
                ensemble=ens_sl, params_snapshot=build_config_from_widgets,
                sync_quick=sync_quick_into_widgets, cloud_validate=_agent_cloud_validate)
            agent_acc = W.Accordion(children=[icesee_agent.container], selected_index=None)
            agent_acc.set_title(0, "Auto-config · Beta")
            mode_selector.attach_assistant(agent_acc)

        _js_out = W.Output(layout=W.Layout(height="0px", overflow="hidden"))
        left = W.VBox([mode_selector.container, experiment_card, environment_card, parameters_card,
                       launch_panel.container], layout=W.Layout(width="100%"))
        left.add_class("icw-col")
        left.add_class("cryostack-left-workspace")
        right = W.VBox([workspace.container], layout=W.Layout(width="100%"))
        right.add_class("icw-col")
        right.add_class("cryostack-right-workspace")
        icesee_shell = W.HBox([left, right], layout=W.Layout(width="100%"))
        icesee_shell.add_class("icw-shell")

        log_out.add_class("icesee-out")
        results_out.add_class("icesee-out")
        page = W.VBox(
            [
                shared_styles,
                W.HTML(css),
                stylesheet(),
                W.HTML("<script>document.title = 'ICESEE';</script>"),

                experiment_bridge.widget(),
                workspace_bridge.widget(),

                app_menu,
                hero,
                stepper.html,
                icesee_shell,
                _js_out,
                back_link,
            ],
            layout=W.Layout(width="100%"),
        )
        page.add_class("icesee-page")
        page.add_class("icw")

        def _workflow_start():
            _example_changed()
            try:
                workspace.refresh_runs()
            except Exception as _e:
                with log_out:
                    print("[workspace] run history unavailable:", type(_e).__name__, _e)
            if workspace.selected is not None and run_lifecycle.current_state(workspace.selected) in run_lifecycle.ACTIVE:
                _active["run_id"] = workspace.selected.id
                _show_active(workspace.selected.id)
            # elapsed time of an active Remote/Cloud run ticks without polling the backend
            def _tick():
                run_id = _active["run_id"]
                if run_id and run_id not in _active["monitors"]:
                    run = run_records.load_run(_icesee_run_dir_base(), run_id)
                    if run is not None and run_lifecycle.current_state(run) in run_lifecycle.ACTIVE:
                        launch_panel.show_run(run)
                        stepper.set_live(launch_panel.live_html)
            _active["ticker"] = Ticker(_tick, interval=5.0)

            # the selected Remote run's scheduler state is checked quietly every
            # minute while it is active (remote_poll.py); Check status resumes
            # checks paused after repeated failures
            def _apply_remote_update(run, update):
                experiment_bridge.update_by_job(job_id=str(run.jobid), **update)
                _update_icesee_run(Path(run.workspace_directory), status=update.get("status"))
                if workspace.selected is not None and workspace.selected.id == run.id:
                    workspace.reload_selected()
                _show_active(run.id)

            def _remote_notice(text, kind):
                workspace.run_msg.value = callout(text, kind)

            remote_poller = RemoteStatusPoller(
                selected=lambda: workspace.selected if cluster_host.value.strip() else None,
                check=lambda jobid: remote_job_status(cluster_host.value.strip(), cluster_user.value.strip(),
                                                      int(cluster_port.value), jobid),
                apply=_apply_remote_update, notify=_remote_notice)
            status_btn.on_click(lambda _b: remote_poller.resume())
            _active["remote_poll"] = Ticker(remote_poller.tick, interval=POLL_SECONDS)

        set_status("idle")
        rebuild_for_example()
        _update_icesee_run_plan_summary()
        _workflow_start()

        # B2: restore this user's saved per-resource settings, last of all.
        try:
            with perf.span("workspace hydrate"), ui_refresh.batch():
                _b2_warnings = resource_state.hydrate()
                _sync_resource_facts()
            for _w in _b2_warnings:
                with log_out:
                    print("[settings]", _w)
        except Exception as _b2_err:
            with log_out:
                print("[settings] restore skipped:", type(_b2_err).__name__, _b2_err)

        perf.mark("gateway total (icesee)", _time.perf_counter() - _perf_t0)
        return page
    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise

