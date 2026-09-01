from __future__ import annotations

import os
import io
import html
import json
import yaml
import subprocess
from pathlib import Path

from tornado.ioloop import PeriodicCallback

from IPython.display import HTML
import base64

import ipywidgets as W
from IPython.display import display

from icesee_jupyter_book.core.icesheet_examples import (
    merged_examples_for_model,
    example_summary_text,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    slurm_optional_lines,
    resolve_remote_abs_path,
    remote_stage_and_submit,
    sanitize_multiline,
    bootstrap_passwordless_ssh,
    connector_ssh,
    connector_fetch_archive,
    connector_stage_archive,
    connector_slurm_submit,
    connector_get_public_key,
)
from cryostack_src.cloud.bridge import CloudBridge

from icesee_jupyter_book.core.local_connector import build_connector_panel
from icesee_jupyter_book.ui.shared_ssh_widgets import build_ssh_key_manager
from icesee_jupyter_book.core.connector_relay_client import (
    create_session,
    check_status as relay_check_status,
    send_command,
)

from icesee_jupyter_book.ui.application_menus import (
    build_icesheets_app_menu,
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
    WorkspaceBridge as WorkspacePersistenceBridge,
    load_workspace_bridge,
)
from icesee_jupyter_book.ui.workspace_persistence import make_state_io

from cryostack_src.workspace import (
    WorkspaceBridge,
    WorkspaceManager,
    build_workspace_logs,
    resolve_workspace_user,
)
from cryostack_src.workspace.resource_state import (
    ResourceStateController,
    strip_secrets,
)

from icesee_jupyter_book.core.experiment_status import (
    experiment_update_from_job_status,
)


from cryostack_src.frontend.shared import (
    CRYOSTACK_FRONTEND_CSS,
    status_badge as status_badge_html,
)

from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
    set_cloud_status,
)
from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    build_cloud_runtime_callbacks,
)
from cryostack_src.frontend.cryolauncher.remote_runtime import (
    build_remote_runtime_callbacks,
)
from cryostack_src.remote import RemoteBridge, expand_remote_home, normalize_remote_path
from cryostack_src.remote.access_state import enforce_remote_access, verify_remote_identity
from cryostack_src.remote.spack_env import SetupSlurmOpts
from cryostack_src.frontend.cryolauncher.spack_runtime import build_spack_runtime_callbacks
from cryostack_src.models import get_model_adapter
from cryostack_src.models.issm.md_config import (
    build_md_override_script,
    inject_override_step,
)
from cryostack_src.models.stack import (
    ComponentResolutionError,
    ContainerIdentityError,
    StackCompatError,
    StackRuntimeError,
    resolve_stack,
    stack_log_line,
)
from cryostack_src.models.submission import (
    submit_remote_icesheets,
    submit_remote_icesheets_via_connector,
)
from cryostack_src.resources.profiles import get_compute_profile, initial_remote_fields
from cryostack_src.frontend.cryolauncher.software_stack import build_software_stack_panel
from cryostack_src.frontend.cryolauncher.container_image import build_container_image_panel
from cryostack_src.frontend.cryolauncher.issm_md_panel import build_issm_md_panel

from cryostack_src.frontend.cryolauncher.panels import (
    build_logs_panel,
    build_results_panel,
    build_run_settings_panel,
    build_status_panel,
    build_runtime_panel,
    build_run_plan_panel,

)

from cryostack_src.frontend.cryolauncher.workspace import (
    build_dataset_panel,
    build_editor_panel,
    build_run_details,
    build_visualization_panel,
    build_workspace_explorer,
    build_workspace_toolbar,
    build_workspace_history_panel,
)

from cryostack_src.frontend.cryolauncher.run_settings_state import (
    build_run_settings_state,
)

from cryostack_src.frontend.cryolauncher.runtime_state import (
    build_runtime_state,
    status_html,
)

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

    return W.Text(value=str(val), layout=W.Layout(width="100%"))


def read_widget(w):
    if isinstance(w, W.Textarea):
        try:
            return yaml.safe_load(w.value)
        except Exception:
            return w.value
    if hasattr(w, "value"):
        return w.value
    return None

def build_sidebar():
    sidebar_html = """
    <style>
    .icesee-shell {
      width: 100%;
      display: flex;
      min-height: 100vh;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }

    .icesee-sidebar {
      width: 260px;
      min-width: 260px;
      background: #f8f9fb;
      border-right: 1px solid rgba(0,0,0,.08);
      padding: 18px 14px;
      box-sizing: border-box;
    }

    .icesee-sidebar h2 {
      font-size: 18px;
      margin: 0 0 16px 0;
      font-weight: 800;
    }

    .icesee-nav-group {
      margin: 18px 0 8px 0;
      font-size: 13px;
      font-weight: 800;
      color: rgba(0,0,0,.75);
      text-transform: uppercase;
    }

    .icesee-nav a {
      display: block;
      padding: 8px 10px;
      margin: 2px 0;
      border-radius: 8px;
      color: #1f3b64;
      text-decoration: none;
      font-weight: 500;
    }

    .icesee-nav a:hover {
      background: rgba(13,110,253,.08);
    }

    .icesee-nav a.active {
      background: rgba(13,110,253,.12);
      color: #0d6efd;
      font-weight: 700;
    }

    .icesee-main {
      flex: 1 1 auto;
      min-width: 0;
      padding: 18px;
      box-sizing: border-box;
    }
    </style>

    <div class="icesee-sidebar">
      <h2>ICESEE</h2>

      <div class="icesee-nav">
        <a href="/index.html">Home</a>

        <div class="icesee-nav-group">Getting Started</div>
        <a href="/intro.html">ICESEE on GHUB</a>
        <a href="/quickstart.html">Quickstart</a>
        <a href="/icesee_workflow.html">ICESEE Workflow Overview</a>

        <div class="icesee-nav-group">ICESEE-OnLINE</div>
        <a class="active" href="/voila/render/icesee_jupyter_notebooks/icesee_app.ipynb">ICESEE GUI</a>
        <a href="/icesee_jupyter_notebooks/icesheet_models.html">CryoLauncher</a>

        <div class="icesee-nav-group">Tutorials</div>
        <a href="/icesee_jupyter_notebooks/run_lorenz96_da.html">Tutorial: Lorenz-96</a>

        <div class="icesee-nav-group">Deployment Notes</div>
        <a href="/running_with_containers.html">Running with Containers</a>
        <a href="/icesee_hpc_coupling.html">ICESEE-HPC Coupling</a>
        <a href="/user_manual.html">User Manual</a>
      </div>
    </div>
    """
    return W.HTML(sidebar_html)

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

session_bridge = W.HTML("""
<script>
(async () => {
    try {
        const response = await fetch("/api/v1/me", {
            credentials: "same-origin",
            cache: "no-store"
        });

        if (!response.ok) {
            return;
        }

        /*
         * We cannot read the HttpOnly session cookie from JavaScript.
         * Therefore this bridge intentionally does not expose credentials.
         */
    } catch (error) {
        console.error("CryoStack session bridge failed:", error);
    }
})();
</script>
""")

app_menu = build_icesheets_app_menu()
shared_styles = shared_application_styles()

def build_backend_check_cmd(backend: str, model: str, remote_base: str, remote_tag: str) -> str:
    root = f"{remote_base.rstrip('/')}/{remote_tag}"
    spack_path = f"{remote_base.rstrip('/')}/ICESEE-Spack"
    container_dir = f"{root}/ICESEE-Containers/spack-managed/combined-container"
    sif_path = f"{container_dir}/combined-env.sif"

    return get_model_adapter(model).build_environment_check(
        spack_path=spack_path,
        sif_path=sif_path,
        backend=backend,
    )

def build_icesheets_ui():
    try:
        load_cryostack_account_assets()
        load_experiment_bridge()

        shared_styles = (
            shared_application_styles()
        )

        experiment_bridge = ExperimentBridge()

        load_workspace_bridge()

        workspace_bridge = WorkspaceBridge(
            persistence=WorkspacePersistenceBridge(),
        )

        # =========================================================
        # State
        # =========================================================

        runtime_state = build_runtime_state()

        # Compatibility aliases while the gateway is migrated.
        STATUS = runtime_state.status
        SESSION = runtime_state.session
        AUTO_TAIL = runtime_state.auto_tail

        # =========================================================
        # Controls
        # =========================================================

        run_settings = build_run_settings_state()

        ui_mode_dd = run_settings.ui_mode
        mode_dd = run_settings.execution_mode
        backend_dd = run_settings.backend
        model_dd = run_settings.model

        software_panel = build_software_stack_panel()
        image_panel = build_container_image_panel()

        example_picker = run_settings.example_picker
        example_info = run_settings.example_info
        example_dir = run_settings.example_dir
        exec_dir = run_settings.exec_dir

        advanced_action_dd = run_settings.advanced_action

        file_picker = run_settings.file_picker
        file_editor = run_settings.file_editor
        run_target = run_settings.run_target

        new_example_name = run_settings.new_example_name
        dataset_upload = run_settings.dataset_upload

        container_source = run_settings.container_source
        image_uri = run_settings.image_uri

        def _is_oci_source() -> bool:
            return (
                backend_dd.value == "container"
                and container_source.value in ("docker", "oci")
            )

        def effective_image_uri() -> str:
            """The image reference to submit.

            For a Docker/OCI source this is the curated tested-image reference or
            the advanced user's custom URI; for git / local SIF it is the
            gateway's existing free-text field (``.def`` name / SIF path).
            """
            if _is_oci_source():
                return image_panel.selection().image_uri
            return image_uri.value

        def selected_tested_image_key() -> str | None:
            if _is_oci_source():
                sel = image_panel.selection()
                return sel.tested_key if sel.mode == "tested" else None
            return None

        access_mode_dd = W.Dropdown(
            options=[
                ("Auto", "auto"),
                ("Direct SSH from server", "direct"),
                ("Local Connector / VPN bridge", "connector"),
            ],
            value="connector",
            layout=W.Layout(width="100%"),
        )

        results_download_btn = W.Button(
            description="Download results",
            icon="download",
            button_style="success",
        )

        figures_download_btn = W.Button(
            description="Download figures",
            icon="picture-o",
            button_style="success",
        )

        auto_tail_btn = W.ToggleButton(
        value=False,
        description="Auto tail",
        icon="refresh",
        button_style="info",
        )

        connector_panel, refresh_connector = build_connector_panel(mode_dd)
        relay_status = W.HTML("")
        start_connector_session_btn = W.Button(
            description="Create connector session",
            icon="plug",
            button_style="info",
        )

        check_backend_btn = W.Button(
            description="Check backend",
            icon="check-circle",
            button_style="info",
        )

        # -----------------------------
        # Remote controls
        #
        # Ownership:
        #   RESOURCE (from ComputeProfile) : login host, ssh port, partition,
        #                                    wall time -- follow the resource.
        #   USER x RESOURCE / USER         : HPC username, remote directory,
        #                                    Slurm account, notification email --
        #                                    BLANK until B2 persistence. Never
        #                                    inferred from the server $USER.
        #   RUN                            : job name, nodes, tasks, tasks/node,
        #                                    memory, per-run overrides.
        # -----------------------------
        _INITIAL_CLUSTER = "pace"
        _rf = initial_remote_fields(_INITIAL_CLUSTER)

        cluster_name_for_keys = W.Text(value=_INITIAL_CLUSTER, placeholder="e.g. pace, ub-ccr, frontera", layout=W.Layout(width="320px"))
        cluster_host = W.Text(value=_rf["login_host"], placeholder="resource login host", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=_rf["hpc_username"], placeholder=_rf["username_hint"], layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=_rf["ssh_port"], layout=W.Layout(width="120px"))

        remote_base_dir = W.Text(value=_rf["remote_directory"], placeholder="your remote working directory (required)", layout=W.Layout(width="320px"))
        remote_tag = W.Text(value="icesheets", layout=W.Layout(width="220px"))

        auth_mode = W.ToggleButtons(
            options=[("Key-only", "key"), ("Bootstrap with password (one-time)", "bootstrap")],
            value="key",
            layout=W.Layout(width="420px"),
        )

        cluster_password = W.Password(
            value="",
            placeholder="One-time password (not stored)",
            layout=W.Layout(width="320px"),
        )

        bootstrap_btn = W.Button(
            description="Enable passwordless SSH",
            icon="key",
            button_style="warning",
        )

        preview_results_btn = W.Button(
            description="Preview results",
            icon="eye",
            button_style="info",
        )

        slurm_job_name = W.Text(value="ICESHEETS", layout=W.Layout(width="100%"))          # RUN
        slurm_time = W.Text(value=_rf["wall_time"], layout=W.Layout(width="100%"))          # RESOURCE default
        slurm_nodes = W.IntText(value=1, layout=W.Layout(width="100%"))                     # RUN
        slurm_ntasks = W.IntText(value=8, layout=W.Layout(width="100%"))                    # RUN
        slurm_tpn = W.IntText(value=8, layout=W.Layout(width="100%"))                       # RUN
        slurm_part = W.Text(value=_rf["partition"], layout=W.Layout(width="100%"))          # RESOURCE default
        slurm_mem = W.Text(value="64G", layout=W.Layout(width="100%"))                      # RUN
        slurm_account = W.Text(                                                             # USER x RESOURCE -- blank
            value=_rf["slurm_account"],
            placeholder=("Slurm allocation (required for this resource)"
                         if _rf["account_required"] else "Slurm allocation"),
            layout=W.Layout(width="100%"),
        )
        slurm_mail = W.Text(                                                                # USER -- blank
            value=_rf["notification_email"],
            placeholder="notification email (optional)",
            layout=W.Layout(width="100%"),
        )

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        status_btn = W.Button(description="Check status", icon="tasks")
        tail_btn = W.Button(description="Tail log", icon="file-text")
        terminate_btn = W.Button(description="Terminate job", icon="stop", button_style="danger")

        cloud_terminate_btn = W.Button(
            description="Terminate",
            icon="stop",
            button_style="danger",
        )

        # Basic-mode ISSM configuration: a curated, solver-aware, validated panel
        # (replaces the old raw md.<section>.<field> editor).
        md_panel = build_issm_md_panel()

        def current_cloud_bridge():
            selected_run = workspace_manager.selected_run()
            selected_metadata = selected_run.metadata if selected_run and selected_run.execution_mode == "cloud" else {}
            return CloudBridge(
                provider="aws",
                region=(
                    selected_metadata.get("region")
                    or aws_region.value.strip()
                    or "us-east-2"
                ),
                profile=(
                    selected_metadata.get("profile")
                    or aws_profile.value.strip()
                    or None
                ),
                results_sync=workspace_manager.sync_cloud_results,
            )

        def current_remote_bridge(*, mode=None):
            return RemoteBridge(
                mode=mode or access_mode_dd.value,
                host=cluster_host.value.strip(),
                user=cluster_user.value.strip(),
                port=int(cluster_port.value),
                session_id=SESSION.get("id"),
                cluster_name=cluster_name_for_keys.value or "pace",
                direct_submitter=submit_remote_icesheets,
                connector_submitter=submit_remote_icesheets_via_connector,
            )

        def current_experiment_configuration() -> dict:
            return {
                "user_mode": ui_mode_dd.value,
                "execution_mode": mode_dd.value,

                "backend": backend_dd.value,
                "model": model_dd.value,

                "example": (
                    example_picker.value or ""
                ),

                "example_directory": (
                    example_dir.value.strip()
                ),

                "execution_directory": (
                    exec_dir.value.strip()
                ),

                "run_target": (
                    run_target.value or ""
                ),

                "access_mode": (
                    access_mode_dd.value
                ),

                "cluster": {
                    "name": (
                        cluster_name_for_keys.value
                        or ""
                    ),
                    "host": (
                        cluster_host.value.strip()
                    ),
                    "port": int(
                        cluster_port.value
                    ),
                },

                "slurm": {
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
                },

                "issm_md": (
                    md_panel.overrides()
                    if model_dd.value == "issm"
                    else {}
                ),
            }

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
            #     print("[ssh] Automatic key installation did not complete.")
            #     print("[ssh] Some clusters require SSH keys to be added through a web portal.")
            #     print()
            #     print("[ssh] Copy this public key and add it to the cluster SSH key portal:")
            #     print()
            #     print(result.get("public_key_text", "").strip())
            #     print()
            #     print("[ssh] After adding the key, return here and click Test SSH.")
            #     print("[ssh] Then continue using Key-only mode.")

            return result

        def on_bootstrap_keys(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)
            password = cluster_password.value

            if not host or not user:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[auth][ERROR] Provide Host + User first.")
                return

            if not password:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[auth][ERROR] Enter your password. It is used once and not stored.")
                return

            try:
                use_connector = should_use_connector()

                if use_connector:
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    st = relay_check_status(SESSION["id"])
                    if not st.get("online"):
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[connector][ERROR] Connector session is not online.")
                            print("Open the connector setup page and start the local connector first.")
                        return

                result = bootstrap_passwordless_ssh(
                    host=host,
                    user=user,
                    port=port,
                    password=password,
                    access_mode="connector" if access_mode_dd.value == "connector" else "direct",
                    session_id=SESSION.get("id"),
                    cluster_name=cluster_name_for_keys.value or "pace",
                )

                with log_out:
                    for msg in result.get("messages", []):
                        print(msg)

                    if (result.get("stdout") or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())

                    if (result.get("stderr") or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())

                if result.get("ok"):
                    status_chip.value = status_html("done")
                    auth_mode.value = "key"
                    cluster_password.value = ""
                    with log_out:
                        print("[auth] ✅ Passwordless SSH is working.")
                else:
                    status_chip.value = status_html("fail")

                    if should_use_connector():
                        show_connector_public_key_help()
                    else:
                        with log_out:
                            print()
                            print("[ssh] Direct/server-side bootstrap failed.")
                            print("[ssh] Use the SSH Key Manager below only for direct SSH from this server.")

            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[auth][ERROR]", type(e).__name__, e)

        def create_or_refresh_connector_session(_=None):
            log_out.clear_output()

            try:
                # A relay-side session that is gone/expired/superseded must be
                # recreated, not reused -- otherwise commands fail closed later.
                if SESSION.get("id"):
                    prior = relay_check_status(SESSION["id"])
                    if prior.get("state") in {"unknown", "expired", "superseded"}:
                        SESSION.clear()

                if SESSION.get("id") is None:
                    owner = resolve_workspace_user(require_authenticated=True)
                    sess = create_session(owner_user_id=owner.user_id)
                    SESSION["id"] = sess["session_id"]
                    SESSION["ws_url"] = sess["ws_url"]
                    SESSION["pairing_code"] = sess["pairing_code"]

                    connector_setup_link.value = f"""
                    <a href="https://cryostack.eas.gatech.edu/connect/?session={SESSION['id']}&app=icesheets"
                    target="_blank"
                    style="
                        display:inline-block;
                        background:#0d6efd;
                        color:white;
                        padding:8px 12px;
                        border-radius:8px;
                        text-decoration:none;
                        font-weight:700;
                        margin:6px 0;">
                    Open CryoStack Connector Setup
                    </a>
                    """

                st = relay_check_status(SESSION["id"])
                online = bool(st.get("online"))

                relay_status.value = f"""
                <div style="
                    border:1px solid {'rgba(25,135,84,.25)' if online else 'rgba(13,110,253,.18)'};
                    background:{'rgba(25,135,84,.08)' if online else 'rgba(13,110,253,.06)'};
                    border-radius:12px; padding:12px; line-height:1.6; margin:8px 0;
                ">
                  <b>Connector:</b> {'connected ✅' if online else 'waiting for connector'}<br>
                  <b>Pairing code:</b>
                  <code style="font-size:15px;background:#eef1f4;padding:2px 8px;border-radius:6px;">
                  {SESSION.get('pairing_code', '—')}</code><br>
                  <span style="color:#5f6b7a;font-size:13px;">
                  Enter this code in the CryoStack Connector on your workstation
                  (“Pair with CryoStack…”). It is one-time and expires with this session.
                  </span>
                  <details style="margin-top:8px;">
                    <summary style="cursor:pointer;color:#5f6b7a;font-size:13px;">Diagnostics</summary>
                    <div style="font-size:12px;color:#5f6b7a;margin-top:4px;">
                      session id: {SESSION['id']}<br>
                      ws path: {SESSION['ws_url']}<br>
                      relay state: {st.get('state', 'unknown')}
                    </div>
                  </details>
                </div>
                """

                with log_out:
                    print("[connector] pairing code:", SESSION.get("pairing_code"))
                    print("[connector] relay state:", st.get("state"))

            except Exception as e:
                relay_status.value = ""
                with log_out:
                    print("[connector][ERROR]", type(e).__name__, e)

        # Cloud controls
        # -----------------------------
        cloud_environment = build_cloud_environment_card(
            region="us-east-1",
            profile="",
            s3_prefix="",
            job_queue="",
            job_definition="",
            job_name="icesheets",
        )

        cloud_box = cloud_environment.container

        aws_region = cloud_environment.region
        aws_profile = cloud_environment.profile
        cloud_bucket = cloud_environment.s3_prefix
        batch_job_queue = cloud_environment.job_queue
        batch_job_def = cloud_environment.job_definition
        batch_job_name = cloud_environment.job_name

        cloud_status_btn = W.Button(description="Check status", icon="search")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text")

        # =========================================================
        # Outputs
        # =========================================================

        summary_html = W.HTML()

        command_preview = W.Textarea(
            layout=W.Layout(
                width="100%",
                height="130px",
            )
        )

        connector_setup_link = W.HTML("")

        log_out = W.Output(
            layout=W.Layout(
                width="100%",
                min_height="0",
                flex="1 1 0",
                overflow_y="auto",
                overflow_x="auto",
                border="1px solid rgba(0,0,0,.10)",
                padding="10px",
            )
        )

        results_out = W.Output(
            layout=W.Layout(
                width="100%",
                min_height="0",
                flex="1 1 0",
                overflow_y="auto",
                overflow_x="auto",
                border="1px solid rgba(0,0,0,.10)",
                padding="10px",
            )
        )

        log_out.add_class("cryostack-live-log")
        results_out.add_class("cryostack-live-log")

        auto_scroll_script = W.HTML(
            """
            <script>
            (() => {

                function installCryoStackLogScroll() {

                    const root = document.querySelector(
                        ".cryostack-live-log"
                    );

                    if (!root) {
                        setTimeout(
                            installCryoStackLogScroll,
                            250
                        );
                        return;
                    }

                    if (
                        root.dataset.cryoAutoScroll === "1"
                    ) {
                        return;
                    }

                    root.dataset.cryoAutoScroll = "1";

                    const findScroller = () => {
                        return (
                            root.querySelector(
                                ".jupyter-widgets-output-area"
                            )
                            || root
                        );
                    };

                    const scrollToBottom = () => {
                        const scroller = findScroller();

                        requestAnimationFrame(() => {
                            scroller.scrollTop =
                                scroller.scrollHeight;
                        });
                    };

                    const observer = new MutationObserver(
                        scrollToBottom
                    );

                    observer.observe(
                        root,
                        {
                            childList: true,
                            subtree: true,
                            characterData: true
                        }
                    );

                    scrollToBottom();
                }

                installCryoStackLogScroll();

            })();
            </script>
            """
        )

        # =========================================================
        # Helpers
        # =========================================================
        def form_row(label: str, widget):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width="120px", min_width="120px")
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

        def form_pair(label: str, widget, label_width: str = "80px"):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            row = W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))
            row.add_class("cryostack-field-row")
            return row

        def selected_text(dd: W.Dropdown) -> str:
            for label, value in dd.options:
                if value == dd.value:
                    return label
            return str(dd.value)
        
        def _discover_examples():
            model = model_dd.value
            adapter = get_model_adapter(model)
            return merged_examples_for_model(
                model,
                user_examples=workspace_manager.list_user_examples(model),
                runnable_check=getattr(adapter, "example_runnable", None),
            )

        def refresh_example_picker(_=None, *, select: str | None = None):
            examples = _discover_examples()
            opts = [(ex.label, str(ex.path)) for ex in examples]
            if not opts:
                example_picker.options = [("(no examples found)", "")]
                example_picker.value = ""
                example_info.value = "No examples were discovered for this model."
                if ui_mode_dd.value == "basic":
                    example_dir.value = ""
                STATUS["selected_example_path"] = None
                update_summary()
                return

            values = [v for _l, v in opts]
            keep = select if select in values else (
                example_picker.value if example_picker.value in values else values[0]
            )
            example_picker.options = opts
            example_picker.value = keep

        _editor_ctx = {"last_example": "", "last_model": model_dd.value}

        def apply_selected_example(_=None):
            selected = example_picker.value or ""
            if selected == _editor_ctx["last_example"]:
                return
            # never discard unsaved editor work on an example / model switch
            if not editor_panel.controller.guard_context_switch():
                example_picker.value = _editor_ctx["last_example"]
                return
            _editor_ctx["last_example"] = selected

            STATUS["selected_example_path"] = selected or None

            ex = None
            if selected:
                ex = next((e for e in _discover_examples()
                           if str(e.path) == selected), None)
            example_info.value = _example_summary(ex, selected)

            if selected:
                example_dir.value = selected

            editor_panel.controller.refresh()
            refresh_run_target_options()

            # reset auto-target when example changes
            run_target.value = ""
            auto_set_run_target()

            if model_dd.value == "issm":
                md_panel.set_example(example_dir.value)
            update_summary()

        def _example_summary(ex, selected: str) -> str:
            if ex is None:
                return example_summary_text(None)
            lines = [
                f"Model: {ex.model_name.upper()}",
                f"Name: {Path(selected).name}",
                "Access: your workspace (editable)" if ex.owned
                else "Access: application example (read-only)",
                f"Runnable: {'yes' if ex.runnable else 'no — add a run target'}",
                f"Path: {selected}",
            ]
            if ex.description:
                lines.append(ex.description)
            return "\n".join(lines)

        def build_model_command():
            backend = backend_dd.value
            run_file = selected_run_file()
            run_file_name = Path(run_file).name if run_file else ""
            return get_model_adapter(model_dd.value).build_run_command(
                backend=backend,
                target=run_file_name,
                example_dir=example_dir.value,
                exec_dir=exec_dir.value,
                image_uri=effective_image_uri(),
                ntasks=slurm_ntasks.value,
            )
        
        workspace_manager = WorkspaceManager(
            owner=resolve_workspace_user(require_authenticated=True),
            status=STATUS,
            session=SESSION,
            example_dir=example_dir,
            model=model_dd,
            backend=backend_dd,
            file_picker=file_picker,
            file_editor=file_editor,
            log_output=log_out,
            results_output=results_out,
            cluster_host=cluster_host,
            cluster_user=cluster_user,
            cluster_port=cluster_port,
            access_mode=access_mode_dd,
            normalize_remote_path=normalize_remote_path,
            connector_fetch_archive=connector_fetch_archive,
            should_use_connector=lambda: should_use_connector(),
            connector_ssh=connector_ssh,
            ssh_run=ssh_run,
            cluster_name=cluster_name_for_keys,
        )
        workspace_bridge.attach_manager(workspace_manager)

        def list_editable_files(example_path: str) -> list[tuple[str, str]]:
            return workspace_manager.list_editable_files(example_path)

        # Advanced-mode editor: a generic, model-neutral workspace facility.
        editor_panel = build_editor_panel(
            manager=workspace_manager,
            model_value=lambda: model_dd.value,
            example_dir_widget=example_dir,
            log_output=log_out,
            on_files_changed=lambda: refresh_run_target_options(),
            on_clone_created=lambda dest: refresh_example_picker(select=str(dest)),
            on_examples_changed=lambda _action, dest: refresh_example_picker(
                select=str(dest) if dest is not None else None
            ),
            example_template=lambda: (
                getattr(get_model_adapter(model_dd.value), "example_template", lambda: None)()
            ),
        )

        dataset_panel = build_dataset_panel(
            manager=workspace_manager,
            uploader=dataset_upload,
            log_output=log_out,
            current_example_path=lambda: example_dir.value,
        )

        # Deterministic Results visualization (model adapter supplies the
        # renderer; this panel stays a model-neutral selector). ``fetch_results``
        # is late-bound: it dispatches to the backend that produced the run
        # (remote rsync / connector archive / cloud S3 sync) and lands outputs
        # in the one backend-neutral local shape the ResultPackage reads.
        def _visualization_fetch_results():
            return sync_selected_run_results()

        visualization_panel = build_visualization_panel(
            manager=workspace_manager,
            selected_run_id=lambda: (
                workspace_manager.selected_run().id
                if workspace_manager.selected_run() else ""
            ),
            log_output=log_out,
            fetch_results=_visualization_fetch_results,
        )

        def refresh_run_target_options(_=None):
            files = list_editable_files(example_dir.value.strip())
            opts = [Path(v).name for _, v in files if v]
            adapter = get_model_adapter(model_dd.value)
            final_opts = adapter.order_run_targets(opts)
            run_target.options = final_opts

            current = (run_target.value or "").strip()
            if current and current in final_opts:
                return

            run_target.value = adapter.choose_run_target(final_opts)
                
        def auto_set_run_target(_=None):
            current = (run_target.value or "").strip()
            if current:
                return

            opts = list(run_target.options or [])
            if not opts:
                run_target.value = ""
                return

            run_target.value = get_model_adapter(model_dd.value).choose_run_target(opts)

        def selected_run_file() -> str:
            target = (run_target.value or "").strip()
            if not target:
                return ""

            root = current_example_root()
            if root is None:
                return target

            candidate = root / target
            return str(candidate)
        
        def compute_run_target_text() -> str:
            target = (run_target.value or "").strip()
            if not target:
                return "(default environment check)"
            return target

        def current_example_root() -> Path | None:
            return workspace_manager.example_root()

        def on_check_backend(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            cmd = build_backend_check_cmd(
                backend_dd.value,
                model_dd.value,
                remote_base_dir.value,
                remote_tag.value,
            )

            try:
                if should_use_connector():
                    if not SESSION.get("id"):
                        create_or_refresh_connector_session()

                    bridge = current_remote_bridge(mode="connector")
                else:
                    bridge = current_remote_bridge(mode="direct")

                res = bridge.check_backend(command=cmd, timeout=120)
                rc = res.get("returncode", 1)
                out = res.get("stdout", "")
                err = res.get("stderr", "")
                ok = res.get("ok", False)

                with log_out:
                    print("[backend] Check", backend_dd.value, "for", model_dd.value)
                    print("returncode:", rc)
                    if out.strip():
                        print("--- stdout ---")
                        print(out.strip())
                    if err.strip():
                        print("--- stderr ---")
                        print(err.strip())

                status_chip.value = status_html("done" if ok else "fail")

            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[backend][ERROR]", type(e).__name__, e)


        # =========================================================
        # Dynamic logic
        # =========================================================
        def update_visibility(_=None):
            is_container = backend_dd.value == "container"
            is_oci = is_container and container_source.value in ("docker", "oci")

            container_source.layout.display = "" if is_container else "none"
            image_uri.layout.display = "" if (is_container and not is_oci) else "none"
            image_panel.set_visible(is_oci)

            spack_enable.layout.display = "none" if is_container else ""
            spack_repo_url.layout.display = "none" if is_container else ""
            spack_dirname.layout.display = "none" if is_container else ""
            spack_install_if_needed.layout.display = "none" if is_container else ""
            spack_install_mode.layout.display = "none" if is_container else ""
            # spack_slurm_dir.layout.display = "none" if is_container else ""
            # spack_pmix_dir.layout.display = "none" if is_container else ""

            is_remote = mode_dd.value == "remote"
            is_cloud = mode_dd.value == "cloud"
            is_basic = ui_mode_dd.value == "basic"
            is_advanced = ui_mode_dd.value == "advanced"

            container_source_row.layout.display = "" if is_container else "none"
            image_uri_row.layout.display = "" if (is_container and not is_oci) else "none"

            remote_box.layout.display = "" if is_remote else "none"
            cloud_box.layout.display = "" if is_cloud else "none"

            remote_actions.layout.display = "" if is_remote else "none"
            cloud_actions.layout.display = "" if is_cloud else "none"
            # remote_actions = remote_log_controls
            # cloud_actions = cloud_log_controls
            terminate_btn.layout.display = "" if is_remote else "none"
            cloud_terminate_btn.layout.display = "" if is_cloud else "none"

            example_picker_row.layout.display = ""
            example_info_row.layout.display = ""

            example_row.layout.display = "none" if is_basic else ""
            exec_row.layout.display = ""

            advanced_action_row.layout.display = "" if is_advanced else "none"
            editor_panel.container.layout.display = "" if is_advanced else "none"
            run_target_row.layout.display = ""
            dataset_panel.container.layout.display = "" if is_advanced else "none"
            download_buttons_row.layout.display = ""

            md_config_panel.layout.display = "" if model_dd.value == "issm" else "none"

            if is_remote and access_mode_dd.value == "connector" and SESSION.get("id") is None:
                create_or_refresh_connector_session()

            if is_remote:
                log_runtime_controls.children = (
                    connect_btn,
                    status_btn,
                    tail_btn,
                    # auto_tail_btn,
                    clear_btn,
                )

            elif is_cloud:
                log_runtime_controls.children = (
                    cloud_status_btn,
                    cloud_logs_btn,
                    clear_btn,
                )

            else:
                log_runtime_controls.children = (
                    clear_btn,
                )

            update_summary()

        def update_summary(_=None):
            backend = backend_dd.value
            model = model_dd.value
            mode = mode_dd.value
            user_mode = ui_mode_dd.value

            if model == "issm":
                example_dir.placeholder = "~/ISSM/examples/<example_name>"
                exec_dir.placeholder = "~/runs/issm"
            else:
                example_dir.placeholder = "~/icepack/notebooks/tutorials/<example>.ipynb"
                exec_dir.placeholder = "~/runs/icepack"

            selected = STATUS.get("selected_example_path")
            selected_line = ""
            if selected:
                selected_line = f"<div><span class='icesee-summary-k'>Selected example:</span> {selected}</div>"

            if backend == "spack":
                if model == "issm":
                    model_root = "ICESEE-Spack/.icesee-spack/externals/ISSM"
                    exec_note = "Use the native ISSM workflow inside the ICESEE-Spack environment."
                else:
                    model_root = "ICESEE-Spack/icepack"
                    exec_note = "Use the native Icepack workflow inside the ICESEE-Spack environment."

                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                  <div><span class="icesee-summary-k">Backend:</span> ICESEE-Spack</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  <div><span class="icesee-summary-k">Model root:</span> {model_root}</div>
                  {selected_line}
                  <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """
            else:
                source_name = {
                    "docker": "Docker / OCI",
                    "local": "Local SIF",
                }.get(container_source.value, "ICESEE-Containers (git)")
                exec_note = (
                    "Create host-side example and execution folders, then bind them into "
                    "the combined ICESEE container before launching the selected model."
                )

                if container_source.value in ("docker", "oci"):
                    sel = image_panel.selection()
                    ti = sel.tested_image
                    if ti is not None:
                        image_lines = (
                            f"<div><span class='icesee-summary-k'>Container image:</span> "
                            f"{html.escape(ti.label)} — Tested</div>"
                            f"<div><span class='icesee-summary-k'>OCI reference:</span> "
                            f"{html.escape(ti.reference)}</div>"
                            f"<div><span class='icesee-summary-k'>Digest:</span> "
                            f"{html.escape(ti.short_digest)}</div>"
                        )
                    else:
                        custom_uri = (sel.custom_uri or "").strip()
                        image_lines = (
                            "<div><span class='icesee-summary-k'>Container image:</span> Custom</div>"
                            f"<div><span class='icesee-summary-k'>OCI reference:</span> "
                            f"{html.escape(custom_uri) or '<em>not set</em>'}</div>"
                            "<div><span class='icesee-summary-k'>Digest:</span> unresolved</div>"
                        )
                else:
                    image_lines = (
                        f"<div><span class='icesee-summary-k'>Image:</span> "
                        f"{html.escape(image_uri.value) or '<em>default</em>'}</div>"
                    )

                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                  <div><span class="icesee-summary-k">Backend:</span> ICESEE-Container</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  {selected_line}
                  <div><span class="icesee-summary-k">Image source:</span> {source_name}</div>
                  {image_lines}
                  <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """

            # run_target.value = compute_run_target_text()
            command_preview.value = build_model_command()

        def _guard_model_switch(change):
            # never discard unsaved editor work on a model switch
            if change["new"] == _editor_ctx["last_model"]:
                return
            if not editor_panel.controller.guard_context_switch():
                model_dd.value = _editor_ctx["last_model"]   # revert (re-fires, then no-ops)
                return
            _editor_ctx["last_model"] = change["new"]

        backend_dd.observe(update_visibility, names="value")
        model_dd.observe(_guard_model_switch, names="value")   # must precede the reloaders
        model_dd.observe(refresh_example_picker, names="value")
        model_dd.observe(update_summary, names="value")
        model_dd.observe(lambda _c: software_panel.set_model(model_dd.value), names="value")
        model_dd.observe(lambda _c: image_panel.set_model(model_dd.value), names="value")
        software_panel.observe_profile(lambda profile: image_panel.set_profile(profile))
        image_panel.on_change(update_summary)
        mode_dd.observe(update_visibility, names="value")
        ui_mode_dd.observe(update_visibility, names="value")
        container_source.observe(update_summary, names="value")
        image_uri.observe(update_summary, names="value")
        example_dir.observe(update_summary, names="value")
        exec_dir.observe(update_summary, names="value")
        slurm_ntasks.observe(update_summary, names="value")

        def _sync_resource_facts(_=None):
            # RESOURCE facts follow the selected resource. Personal fields
            # (username, remote dir, account, email) are never touched here.
            rf = initial_remote_fields(cluster_name_for_keys.value)
            cluster_host.value = rf["login_host"]
            cluster_port.value = rf["ssh_port"]
            cluster_user.placeholder = rf["username_hint"]
            slurm_part.value = rf["partition"]
            slurm_time.value = rf["wall_time"]

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
            if s.get("auth_mode") in {"key", "bootstrap"}:
                auth_mode.value = s["auth_mode"]

        _b2_load, _b2_save = make_state_io(
            workspace_bridge, "cryolauncher",
            resolve_workspace_user(require_authenticated=False).user_id,
        )
        resource_state = ResourceStateController(
            load_state=_b2_load, save_state=_b2_save,
            read_personal=_b2_read_personal, apply_personal=_b2_apply_personal,
            resource_name=lambda: cluster_name_for_keys.value,
            set_resource_name=lambda n: setattr(cluster_name_for_keys, "value", n),
            service_username=(os.environ.get("USER") or getpass.getuser() or ""),
        )

        def _on_resource_changed(change):
            resource_state.switch_resource(change.get("old"), change.get("new"))
            _sync_resource_facts()

        cluster_name_for_keys.observe(_on_resource_changed, names="value")
        example_picker.observe(apply_selected_example, names="value")
        access_mode_dd.observe(lambda change: create_or_refresh_connector_session() if change["new"] == "connector" else None, names="value")
        

        # =========================================================
        # Actions
        # =========================================================
        run_btn = W.Button(description="Submit job", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", icon="trash")
        status_chip = W.HTML(status_html("idle"))

        def should_use_connector() -> bool:
            return current_remote_bridge().uses_connector()

        def on_run(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            action = advanced_action_dd.value
            mode = mode_dd.value

            # ----------------------------------------
            # DEPLOY  (clone the selected example into the user's workspace)
            # ----------------------------------------
            if ui_mode_dd.value == "advanced" and action == "deploy":
                editor_panel.controller.clone_example()
                status_chip.value = status_html("done")
                return

            # ----------------------------------------
            # TEST (force environment check)
            # ----------------------------------------
            test_mode = (
                ui_mode_dd.value == "advanced"
                and action == "test"
            )

            if mode == "cloud":
                result = current_cloud_bridge().submit(
                    backend=selected_text(backend_dd),
                    model=selected_text(model_dd),
                    display_region=aws_region.value.strip() or "us-east-1",
                    s3_prefix=cloud_bucket.value.strip(),
                    job_queue=batch_job_queue.value.strip(),
                    job_definition=batch_job_def.value.strip(),
                    job_name=batch_job_name.value.strip() or "icesheets",
                )
                with log_out:
                    for message in result.messages:
                        print(message)
                if result.job_id:
                    STATUS["batch_job_id"] = result.job_id
                cloud_run = result.metadata.get("s3_run") or result.working_directory
                if cloud_run:
                    STATUS["cloud_run"] = cloud_run
                if result.job_id or cloud_run:
                    workspace_bridge.start_run(
                        name=str(result.metadata.get("run_id") or result.job_id or "cloud-run"),
                        model=model_dd.value,
                        backend=backend_dd.value,
                        execution_mode="cloud",
                        jobid=result.job_id,
                        remote_directory=Path(str(cloud_run or "cloud")),
                        log_file=None,
                        metadata={"cloud_run": cloud_run, "region": aws_region.value.strip(), "profile": aws_profile.value.strip()},
                    )
                status_chip.value = status_html("done")
                return
            
            if mode == "remote" and access_mode_dd.value == "connector":
                create_or_refresh_connector_session()

                st = relay_check_status(SESSION["id"])
                if not st.get("online"):
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[connector][ERROR] Connector session is not online.")
                        print("[connector] Start the local connector with the session WebSocket URL, then retry.")
                    return

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            if not host or not user:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR] Host and User are required.")
                return

            # B3: remote-access identity gate. Verifies the real remote identity
            # (fresh whoami) against the configured HPC username and blocks Run
            # on mismatch / unverified access / missing prerequisites.
            if mode == "remote":
                _resolved = "connector" if should_use_connector() else "direct"
                _gate = enforce_remote_access(
                    current_remote_bridge(mode=_resolved),
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
                if not _gate.ok:
                    status_chip.value = status_html("fail")
                    with log_out:
                        for _m in _gate.messages:
                            print(_m)
                    return

            if not example_dir.value.strip():

                status_chip.value = status_html("fail")

                with log_out:

                    print("[remote][ERROR] Example path is empty.")

                return
            
            local_example = Path(example_dir.value).expanduser()
            if not local_example.exists():
                status_chip.value = status_html("fail")
                with log_out:
                    print(f"[remote][ERROR] Example path does not exist locally: {local_example}")
                return

            # Stage a user-owned working copy when the run needs one: Basic-mode
            # ISSM md overrides (validated + injected before the first solve),
            # and/or referenced datasets to materialise. The canonical example
            # is never modified.
            effective_example_dir = example_dir.value
            md_run_provenance: dict = {}
            if model_dd.value == "issm" and not test_mode:
                _md_validation = md_panel.validate()
                if not _md_validation.ok:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[md][ERROR] ISSM configuration is not valid:")
                        for _err in _md_validation.errors:
                            print("  -", _err)
                    return
                _has_ds_refs = bool(
                    workspace_manager.example_dataset_references(example_dir.value)
                )
                if _md_validation.normalized or _has_ds_refs:
                    _extra = (
                        {"cryostack_md_overrides.m":
                         build_md_override_script(_md_validation.normalized)}
                        if _md_validation.normalized else None
                    )
                    try:
                        _staged = workspace_manager.stage_example_for_run(
                            source_example=example_dir.value,
                            extra_files=_extra,
                            entrypoint_transform=(
                                inject_override_step if _md_validation.normalized else None
                            ),
                            overrides=_md_validation.normalized or None,
                        )
                    except Exception as _stage_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[stage][ERROR] Could not stage a working copy:",
                                  type(_stage_err).__name__, _stage_err)
                        return
                    effective_example_dir = str(_staged.path)
                    md_run_provenance = {
                        "md_overrides": _md_validation.normalized,
                        "md_working_copy": str(_staged.path),
                        "md_example_source": _staged.source,
                        "md_working_copy_from_canonical": _staged.from_canonical,
                        "staged_datasets": _staged.provenance.get("staged_datasets", []),
                    }
                    with log_out:
                        print(f"[stage] working copy: {_staged.path}")
                        if _md_validation.normalized:
                            print("[stage] md overrides: "
                                  f"{', '.join(sorted(_md_validation.normalized))}")
                        for _d in _staged.provenance.get("staged_datasets", []):
                            print(f"[stage] dataset -> {_d['as']}")

            # ICESEE-Spack scientific runs are blocked unless the live
            # environment probe reports Ready. Never install silently at Run.
            if backend_dd.value == "spack":
                try:
                    _env = current_remote_bridge(
                        mode="connector" if should_use_connector() else "direct"
                    ).environment_status(
                        model=model_dd.value,
                        remote_base=remote_base_dir.value.strip(),
                        spack_dirname=spack_dirname.value.strip() or "ICESEE-Spack",
                    )
                except Exception as _env_err:
                    status_chip.value = status_html("fail")
                    with log_out:
                        print("[spack][ERROR] Could not check the environment:",
                              type(_env_err).__name__, _env_err)
                    return
                if not _env.is_ready:
                    status_chip.value = status_html("fail")
                    spack_env_badge.value = status_badge_html(
                        _env.status.badge_state, label=_env.status.label
                    )
                    with log_out:
                        print(
                            f"ICESEE-Spack is not ready for {model_dd.value.upper()} "
                            "on this resource."
                        )
                        print("Check or prepare the environment before running.")
                        for _m in _env.messages:
                            print(" ", _m)
                    return

            try:
                # Resolve the reproducibility provenance BEFORE any job is
                # submitted or any manifest is written, so a resolution failure
                # cannot leave a half-registered run. Tested = image stack, no
                # network. Custom = resolve each requested ref to an exact SHA
                # now; the job only ever receives resolved SHAs.
                stack_provenance = {}
                stack_line = ""
                if backend_dd.value == "container":
                    _profile = software_panel.profile()
                    _selections = software_panel.selections()
                    if _is_oci_source():
                        _img_err = image_panel.validate()
                        if _img_err:
                            status_chip.value = status_html("fail")
                            with log_out:
                                print("[container][ERROR]", _img_err)
                            return
                    try:
                        stack_provenance = resolve_stack(
                            model=model_dd.value,
                            profile=_profile,
                            selections=_selections,
                            container_source=container_source.value,
                            image_uri=effective_image_uri(),
                            tested_image_key=selected_tested_image_key(),
                            digest_resolver=None,
                        )
                    except (StackCompatError, ComponentResolutionError,
                            StackRuntimeError, ContainerIdentityError) as stack_err:
                        status_chip.value = status_html("fail")
                        with log_out:
                            print("[stack][ERROR]", stack_err)
                        return
                    stack_line = stack_log_line(stack_provenance)
                    with log_out:
                        print(stack_line)

                # Site-specific runtime config (e.g. MATLAB licensing) comes from
                # the compute-resource profile, never the container image.
                _compute_profile = get_compute_profile(cluster_name_for_keys.value or "pace")
                _matlab_license = _compute_profile.matlab_license_config()

                # ISSM runs MATLAB inside the container; fail now (not after a
                # multi-hour allocation blocks on license checkout) if the
                # compute resource has no MATLAB license configured.
                if (
                    backend_dd.value == "container"
                    and model_dd.value == "issm"
                    and _matlab_license is None
                ):
                    status_chip.value = status_html("fail")
                    with log_out:
                        print(
                            "[container][ERROR] MATLAB licensing is not configured "
                            "for this compute resource."
                        )
                    return

                use_connector = should_use_connector()
                if use_connector:
                    execution_result = current_remote_bridge(mode="connector").submit(
                        direct_kwargs={},
                        connector_kwargs=dict(
                        session_id=SESSION["id"],
                        host=host,
                        user=user,
                        port=port,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        backend=backend_dd.value,
                        model=model_dd.value,
                        example_dir=effective_example_dir,
                        exec_dir=exec_dir.value,
                        image_uri=effective_image_uri(),
                        container_source=container_source.value,
                        spack_enable=spack_enable.value,
                        spack_repo_url=spack_repo_url.value,
                        spack_dirname=spack_dirname.value,
                        spack_install_if_needed=spack_install_if_needed.value,
                        spack_install_mode=spack_install_mode.value,
                        spack_slurm_dir=spack_slurm_dir.value,
                        spack_pmix_dir=spack_pmix_dir.value,
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        test_mode=test_mode,
                        run_file=selected_run_file(),
                        cluster_name=cluster_name_for_keys.value or "pace",
                        stack_log_line=stack_line,
                        stack_software=stack_provenance.get("software") or {},
                        matlab_license=_matlab_license,
                        ),
                    )
                else:
                    execution_result = current_remote_bridge(mode="direct").submit(
                        connector_kwargs={},
                        direct_kwargs=dict(
                        host=host,
                        user=user,
                        port=port,
                        remote_base_dir=remote_base_dir.value,
                        remote_tag=remote_tag.value,
                        backend=backend_dd.value,
                        model=model_dd.value,
                        example_dir=effective_example_dir,
                        exec_dir=exec_dir.value,
                        image_uri=effective_image_uri(),
                        container_source=container_source.value,
                        spack_enable=True,
                        spack_repo_url="https://github.com/ICESEE-project/ICESEE-Spack.git",
                        spack_dirname="ICESEE-Spack",
                        spack_install_if_needed=False,
                        spack_install_mode="--with-issm" if model_dd.value == "issm" else "--with-icepack",
                        spack_slurm_dir="",
                        spack_pmix_dir="",
                        slurm_time=slurm_time.value,
                        slurm_job_name=slurm_job_name.value,
                        slurm_nodes=slurm_nodes.value,
                        slurm_ntasks=slurm_ntasks.value,
                        slurm_tpn=slurm_tpn.value,
                        slurm_part=slurm_part.value,
                        slurm_mem=slurm_mem.value,
                        slurm_account=slurm_account.value,
                        slurm_mail=slurm_mail.value,
                        test_mode=test_mode,
                        run_file=selected_run_file(),
                        stack_log_line=stack_line,
                        stack_software=stack_provenance.get("software") or {},
                        matlab_license=_matlab_license,
                        ),
                    )

                result = {
                    "remote_dir": execution_result.working_directory,
                    "jobid": execution_result.job_id,
                    "log_file": execution_result.log_path,
                    "messages": execution_result.messages,
                }

                STATUS["remote_dir"] = result["remote_dir"]
                STATUS["jobid"] = result["jobid"]
                STATUS["log_file"] = result.get("log_file")

                workspace_bridge.start_run(
                    name=Path(STATUS["remote_dir"]).name,
                    model=model_dd.value,
                    backend=backend_dd.value,
                    execution_mode=mode_dd.value,
                    jobid=STATUS["jobid"],
                    remote_directory=Path(STATUS["remote_dir"]),
                    log_file=(
                        Path(STATUS["log_file"])
                        if STATUS.get("log_file")
                        else None
                    ),
                    metadata={
                        "host": cluster_host.value.strip(),
                        "user": cluster_user.value.strip(),
                        "port": int(cluster_port.value),
                        "access_mode": access_mode_dd.value,
                        "cluster_name": cluster_name_for_keys.value or "pace",
                        **md_run_provenance,
                    },
                    container=stack_provenance.get("container") or {},
                    software=stack_provenance.get("software") or {},
                )

                experiment_bridge.create(
                    application="cryolauncher",

                    name=(
                        f"{model_dd.value.upper()} "
                        f"{backend_dd.value} run"
                    ),

                    backend=backend_dd.value,

                    status="running",

                    job_id=str(result["jobid"]),

                    cluster=(
                        cluster_name_for_keys.value
                        or cluster_host.value.strip()
                    ),

                    working_directory=(
                        result["remote_dir"]
                    ),

                    output_directory=(
                        f"{result['remote_dir']}/outputs"
                    ),

                    log_path=result.get("log_file"),

                    configuration=(
                        current_experiment_configuration()
                    ),

                    metadata={
                        "execution_mode": mode_dd.value,
                        "access_mode": access_mode_dd.value,
                        "model": model_dd.value,
                    },
                )

                workspace_bridge.save(
                    application="cryolauncher",
                    state=current_workspace_state(),
                )

                with log_out:
                    for msg in result["messages"]:
                        print(msg)

                status_chip.value = status_html("done")

            except subprocess.TimeoutExpired:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][TIMEOUT] Submission timed out.")
            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_clear(_=None):
            log_out.clear_output()
            results_out.clear_output()
            status_chip.value = status_html("idle")

        remote_runtime = build_remote_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_remote_bridge,
            experiment_bridge=experiment_bridge,
            experiment_update_from_job_status=experiment_update_from_job_status,
            on_status_result=workspace_manager.update_run_status_by_job,
        )
        _remote_check = remote_runtime.check

        def on_test_remote(_=None):
            _remote_check(_)
            if mode_dd.value != "remote":
                return
            try:
                _resolved = "connector" if should_use_connector() else "direct"
                _v = verify_remote_identity(
                    current_remote_bridge(mode=_resolved),
                    verification_command=get_compute_profile(
                        cluster_name_for_keys.value or "pace"
                    ).verification_command,
                    expected_username=cluster_user.value.strip(),
                )
                with log_out:
                    if _v.ok:
                        print(f"[identity] verified — remote whoami '{_v.remote_identity}' "
                              "matches the configured HPC username.")
                    elif _v.mismatch:
                        print(f"[identity][MISMATCH] remote whoami '{_v.remote_identity}' "
                              f"!= configured HPC username '{_v.expected}'. Run is blocked "
                              "until this matches.")
                    else:
                        print(f"[identity] could not verify remote identity: {_v.error}")
            except Exception as _e:
                with log_out:
                    print("[identity] verification skipped:", type(_e).__name__, _e)

        on_status = remote_runtime.status
        on_terminate = remote_runtime.terminate

        workspace_logs = build_workspace_logs(
            status=STATUS,
            session=SESSION,
            auto_tail=AUTO_TAIL,
            log_output=log_out,
            status_widget=status_chip,
            auto_tail_button=auto_tail_btn,
            cluster_host=cluster_host,
            cluster_user=cluster_user,
            cluster_port=cluster_port,
            access_mode=access_mode_dd,
            normalize_remote_path=normalize_remote_path,
            status_html=status_html,
            send_command=send_command,
            ssh_run=ssh_run,
            bridge_factory=current_remote_bridge,
        )
        on_tail = workspace_logs.on_tail
        on_auto_tail_change = workspace_logs.on_auto_tail_change

        cloud_runtime = build_cloud_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_cloud_bridge,
            cloud_environment=cloud_environment,
            set_cloud_status=set_cloud_status,
            bucket_value=lambda: cloud_bucket.value.strip(),
            results_output=results_out,
            on_status_result=workspace_manager.update_run_status_by_job,
        )
        on_cloud_status = cloud_runtime.status
        on_cloud_logs = cloud_runtime.logs
        on_cloud_terminate = cloud_runtime.terminate
        on_cloud_results = cloud_runtime.results

        def tail_selected_workspace_run():
            selected = workspace_manager.selected_run()
            if selected and selected.execution_mode == "cloud":
                return on_cloud_logs()
            return on_tail()

        workspace_manager.set_tail_handler(tail_selected_workspace_run)

        def resolve_workspace_run_status(run):
            if run.execution_mode == "cloud":
                bridge = CloudBridge(
                    provider="aws",
                    region=run.metadata.get("region") or "us-east-2",
                    profile=run.metadata.get("profile") or None,
                )
            else:
                bridge = RemoteBridge(
                    mode=run.metadata.get("access_mode") or "direct",
                    host=run.metadata.get("host") or cluster_host.value.strip(),
                    user=run.metadata.get("user") or cluster_user.value.strip(),
                    port=int(run.metadata.get("port") or cluster_port.value),
                    session_id=SESSION.get("id"),
                    cluster_name=run.metadata.get("cluster_name") or "pace",
                )
            return bridge.status(job_id=str(run.jobid)).state

        workspace_manager.set_status_resolver(resolve_workspace_run_status)

        def active_execution_mode():
            selected = workspace_manager.selected_run()
            return selected.execution_mode if selected else mode_dd.value

        def sync_selected_run_results():
            """Synchronise the selected run's outputs into its local run cache,
            using whichever backend produced it. Returns the local outputs dir
            (or None). Performs no rendering."""
            if active_execution_mode() == "cloud":
                return on_cloud_results()
            return workspace_manager.refresh_results()

        def on_results_preview(_=None):
            # 1. fetch/synchronise outputs + print the run summary, 2. drive the
            # structured visualization panel: re-read the local package, rebuild
            # Solution/Field/Timestep, and render an initial recommended plot.
            if active_execution_mode() == "cloud":
                on_cloud_results()
            else:
                workspace_manager.preview_results()
            visualization_panel.controller.preview()

        def on_results_download(_=None):
            if active_execution_mode() == "cloud":
                on_cloud_results()
            else:
                workspace_manager.download_results()

        def on_figures_download(_=None):
            if active_execution_mode() == "cloud":
                on_cloud_results()
            else:
                workspace_manager.download_figures()

        def current_workspace_state() -> dict:
            # v2 shape: RESOURCE facts are NOT persisted (they live in
            # ComputeProfile); personal settings are folded per-resource by the
            # controller; run settings go under "run"; nothing secret.
            state = resource_state.capture()
            state["run"] = {
                "model": model_dd.value,
                "backend": backend_dd.value,
                "execution_mode": mode_dd.value,
                "user_mode": ui_mode_dd.value,
                "example": example_picker.value or "",
                "example_directory": example_dir.value.strip(),
                "run_target": run_target.value or "",
                "job_name": slurm_job_name.value,
                "nodes": slurm_nodes.value,
                "tasks": slurm_ntasks.value,
                "tasks_per_node": slurm_tpn.value,
                "memory": slurm_mem.value,
                "wall_time_override": slurm_time.value,
                "partition_override": slurm_part.value,
            }
            state["job"] = {
                "job_id": STATUS.get("jobid"),
                "remote_directory": STATUS.get("remote_dir"),
                "log_file": STATUS.get("log_file"),
            }
            return strip_secrets(state)


        run_btn.on_click(on_run)
        clear_btn.on_click(on_clear)
        connect_btn.on_click(on_test_remote)
        status_btn.on_click(on_status)
        tail_btn.on_click(on_tail)
        # auto_tail_btn.on_click(on_auto_tail_click)
        terminate_btn.on_click(on_terminate)
        cloud_status_btn.on_click(on_cloud_status)
        cloud_logs_btn.on_click(on_cloud_logs)
        cloud_terminate_btn.on_click(on_cloud_terminate)
        cloud_environment.test_button.on_click(cloud_runtime.check_environment)
        cloud_environment.prepare_button.on_click(cloud_runtime.prepare_environment)
        results_download_btn.on_click(on_results_download)
        figures_download_btn.on_click(on_figures_download)
        preview_results_btn.on_click(on_results_preview)
        start_connector_session_btn.on_click(create_or_refresh_connector_session)
        bootstrap_btn.on_click(on_bootstrap_keys)
        check_backend_btn.on_click(on_check_backend)

        # =========================================================
        # CSS
        # =========================================================
        css = """
            <style>

            /*
            * CryoLauncher-specific styles remain here.
            * Shared cards, labels, layout, statuses, and typography
            * come from shared_app_styles.py.
            */

            </style>
            """

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML("""
        <div class="icesee-page">
          <div class="icesee-title">Ice-Sheet Modeling</div>
          <div class="icesee-subtitle">
            Launch supported ice-sheet models without the ICESEE data assimilation layer.
            Basic mode helps beginners discover native ISSM and Icepack examples automatically.
            Advanced mode keeps manual control for custom paths, editing, and expert workflows.
          </div>
        </div>
        """)

        ui_mode_row = form_row("User mode:", ui_mode_dd)
        mode_row = form_row("Exec mode:", mode_dd)
        backend_row = form_row("Backend:", backend_dd)
        model_row = form_row("Model:", model_dd)
        example_picker_row = form_row("Examples:", example_picker)
        example_info_row = form_row("Details:", example_info)
        example_row = form_row("Example path:", example_dir)
        exec_row = form_row("Exec dir:", exec_dir)
        advanced_action_row = form_row("Action:", advanced_action_dd)
        run_target_row = form_row("Run target:", run_target)
        md_config_panel = W.Accordion(children=[md_panel.container])
        md_config_panel.set_title(0, "⚙️ ISSM configuration (Basic)")
        # md_config_panel.selected_index = 0  # open by default
        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        cluster_host_row = form_pair("Host:", cluster_host, "90px")
        cluster_user_row = form_pair("User:", cluster_user, "90px")
        cluster_port_row = form_pair("Port:", cluster_port, "90px")
        remote_base_dir_row = form_pair("Remote dir:", remote_base_dir, "90px")
        remote_tag_row = form_pair("Tag:", remote_tag, "90px")

        slurm_job_name_row = form_pair("Job:", slurm_job_name, "90px")
        slurm_time_row = form_pair("Time:", slurm_time, "90px")
        slurm_nodes_row = form_pair("Nodes:", slurm_nodes, "90px")
        slurm_ntasks_row = form_pair("Tasks:", slurm_ntasks, "90px")
        slurm_tpn_row = form_pair("TPN:", slurm_tpn, "90px")
        slurm_part_row = form_pair("Part:", slurm_part, "90px")
        slurm_mem_row = form_pair("Mem:", slurm_mem, "90px")
        slurm_account_row = form_pair("Acct:", slurm_account, "90px")
        slurm_mail_row = form_pair("Mail:", slurm_mail, "90px")

        ssh_key_manager = build_ssh_key_manager(
            cluster_name_widget=cluster_name_for_keys,
            host_widget=cluster_host,
            user_widget=cluster_user,
        )
        server_key_note = W.HTML("""
        <div class='icesee-subtle' style='line-height:1.5; margin-bottom:8px;'>
        This manages SSH keys on the web server/GHUB side for direct SSH.
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

        # ssh_key_manager_box = W.Accordion(children=[ssh_key_manager])
        # # ssh_key_manager_box.set_title(0, "🔐 SSH Key Manager")
        # ssh_key_manager_box.set_title(0, "🔐 Server-side SSH Key Manager")
        # ssh_key_manager_box.selected_index = None

        ssh_key_manager_box.layout = W.Layout(
            width="100%",
            border="1px solid rgba(0,0,0,.08)",
            border_radius="12px",
            margin="8px 0 4px 0"
        )

        # [preview_results_btn, results_download_btn, figures_download_btn],
        download_buttons_row = build_workspace_toolbar(
            [preview_results_btn, results_download_btn],
            justify_content="flex-end",
            margin="10px 0 0 0",
        )

        cluster_name_row = form_pair("Cluster:", cluster_name_for_keys, "90px")
        remote_conn_inner = W.VBox([
            cluster_name_row,
            form_pair("Access:", access_mode_dd, "90px"),
            cluster_host_row,
            W.HBox([cluster_user_row, cluster_port_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([remote_base_dir_row, remote_tag_row], layout=W.Layout(gap="12px", width="100%")),
        ])
        remote_conn_box = W.Accordion(children=[remote_conn_inner])
        remote_conn_box.set_title(0, "🔌 Remote connection")
        # remote_conn_box.selected_index = 0  # open by default

        slurm_inner = W.VBox([
            W.HBox([slurm_job_name_row, slurm_time_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_nodes_row, slurm_ntasks_row, slurm_tpn_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_part_row, slurm_mem_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_account_row, slurm_mail_row], layout=W.Layout(gap="12px", width="100%")),
        ])

        slurm_box = W.Accordion(children=[slurm_inner])
        slurm_box.set_title(0, "📊 Slurm resources")
        slurm_box.selected_index = None

        auth_inner = W.VBox([
            W.HBox(
                [W.HTML("<div class='icesee-lbl'>Method:</div>"), auth_mode],
                layout=W.Layout(gap="10px")
            ),
            cluster_password,
            bootstrap_btn,
        ])

        auth_box = W.Accordion(children=[auth_inner])
        auth_box.set_title(0, "🔒 Authentication")

        exec_backend_choice = W.Dropdown(
            options=[("ICESEE-Spack", "spack"), ("ICESEE-Container", "container")],
            value="spack",
            layout=W.Layout(width="320px"),
        )

        spack_enable = W.Checkbox(value=True, description="Use ICESEE-Spack on Remote")

        spack_repo_url = W.Text(
            value="https://github.com/ICESEE-project/ICESEE-Spack.git",
            layout=W.Layout(width="100%"),
        )

        spack_dirname = W.Text(value="ICESEE-Spack", layout=W.Layout(width="100%"))

        spack_install_if_needed = W.Checkbox(
            value=False,
            description="Run install.sh if not installed",
        )

        spack_install_mode = W.Dropdown(
            options=[
                ("Default", ""),
                ("With ISSM", "--with-issm"),
                ("With Icepack", "--with-icepack"),
                ("With Firedrake", "--with-firedrake"),
            ],
            value="--with-issm",
            layout=W.Layout(width="100%"),
        )

        spack_slurm_dir = W.Text(
            value="",
            placeholder="e.g. /opt/slurm/current",
            layout=W.Layout(width="100%"),
        )

        spack_pmix_dir = W.Text(
            value="",
            placeholder="e.g. /opt/pmix/5.0.1",
            layout=W.Layout(width="100%"),
        )

        # --- Remote + ICESEE-Spack: Environment lifecycle ------------------
        spack_env_badge = W.HTML(status_badge_html("idle", label="Unknown"))
        spack_env_setup_label = W.HTML("")
        spack_check_env_btn = W.Button(
            description="Check environment", icon="search", button_style="info",
        )
        spack_prepare_env_btn = W.Button(
            description="Prepare environment", icon="wrench", button_style="primary",
        )
        spack_setup_log_btn = W.Button(
            description="View setup log", icon="file-text",
            layout=W.Layout(display="none"),
        )
        spack_env_row = W.VBox(
            [
                W.HBox(
                    [W.HTML("<div class='icesee-lbl'>Environment</div>",
                            layout=W.Layout(width="120px", min_width="120px")),
                     spack_env_badge, spack_env_setup_label],
                    layout=W.Layout(align_items="center", gap="10px"),
                ),
                W.HBox(
                    [spack_check_env_btn, spack_prepare_env_btn, spack_setup_log_btn],
                    layout=W.Layout(gap="8px", flex_wrap="wrap", margin="0 0 0 120px"),
                ),
            ],
            layout=W.Layout(width="100%", gap="6px"),
        )

        backend_row = form_row("Backend:", backend_dd)

        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        spack_enable_row = W.Box([spack_enable], layout=W.Layout(margin="0 0 0 120px"))
        spack_repo_row = form_row("Repo:", spack_repo_url)
        spack_dir_row = form_row("Dir name:", spack_dirname)
        spack_install_row = W.Box([spack_install_if_needed], layout=W.Layout(margin="0 0 0 120px"))
        spack_install_mode_row = form_row("Install:", spack_install_mode)
        spack_slurm_row = form_row("SLURM_DIR:", spack_slurm_dir)
        spack_pmix_row = form_row("PMIX_DIR:", spack_pmix_dir)

        exec_backend_inner = W.VBox([
            backend_row,
            container_source_row,
            image_uri_row,
            image_panel.container,
            software_panel.container,
            spack_enable_row,
            spack_repo_row,
            spack_dir_row,
            spack_env_row,
            # spack_slurm_row,
            # spack_pmix_row,
        ], layout=W.Layout(gap="8px"))

        def _toggle_exec_backend_ui(_=None):
            is_container = backend_dd.value == "container"
            is_oci = is_container and container_source.value in ("docker", "oci")

            container_source_row.layout.display = "flex" if is_container else "none"
            image_uri_row.layout.display = (
                "flex" if (is_container and not is_oci) else "none"
            )
            image_panel.set_visible(is_oci)
            software_panel.set_visible(is_container)

            spack_display = "none" if is_container else "flex"
            spack_box_display = "none" if is_container else "block"

            spack_enable_row.layout.display = spack_box_display
            spack_repo_row.layout.display = spack_display
            spack_dir_row.layout.display = spack_display
            spack_env_row.layout.display = spack_box_display
            spack_install_row.layout.display = "none"
            spack_install_mode_row.layout.display = "none"
            spack_slurm_row.layout.display = spack_display
            spack_pmix_row.layout.display = spack_display
        
        backend_dd.observe(_toggle_exec_backend_ui, names="value")
        container_source.observe(_toggle_exec_backend_ui, names="value")
        container_source.observe(update_visibility, names="value")
        _toggle_exec_backend_ui()

        # --- Remote + ICESEE-Spack environment lifecycle callbacks ---------
        def _setup_slurm_opts():
            return SetupSlurmOpts(
                partition=slurm_part.value.strip() or "cpu-small",
                time="08:00:00",
                nodes=1,
                ntasks=int(slurm_ntasks.value or 8),
                mem=slurm_mem.value.strip() or "32G",
                account=slurm_account.value.strip(),
                mail=slurm_mail.value.strip(),
            )

        def _spack_matlab_license(model):
            if model != "issm":
                return None
            return get_compute_profile(
                cluster_name_for_keys.value or "pace"
            ).matlab_license_config()

        spack_runtime = build_spack_runtime_callbacks(
            runtime_status=STATUS,
            log_output=log_out,
            status_widget=status_chip,
            status_html=status_html,
            bridge_factory=current_remote_bridge,
            ensure_connector_session=(
                lambda: (create_or_refresh_connector_session()
                         if should_use_connector() else None)
            ),
            env_badge=spack_env_badge,
            setup_job_label=spack_env_setup_label,
            view_log_button=spack_setup_log_btn,
            model_value=lambda: model_dd.value,
            remote_base_value=lambda: remote_base_dir.value.strip(),
            spack_dirname_value=lambda: spack_dirname.value.strip() or "ICESEE-Spack",
            spack_repo_value=lambda: (
                spack_repo_url.value.strip()
                or "https://github.com/ICESEE-project/ICESEE-Spack.git"
            ),
            setup_slurm_opts=_setup_slurm_opts,
            matlab_license_for=_spack_matlab_license,
        )
        spack_check_env_btn.on_click(spack_runtime.check)
        spack_prepare_env_btn.on_click(spack_runtime.prepare)
        spack_setup_log_btn.on_click(spack_runtime.view_setup_log)

        exec_backend_box = W.Accordion(children=[exec_backend_inner])
        exec_backend_box.set_title(0, "⚙️ Execution backend")
        exec_backend_box.selected_index = None

        remote_box = W.VBox([
            remote_conn_box,
            exec_backend_box,
            auth_box,
            # server_key_note,
            ssh_key_manager_box,
            slurm_box,
            relay_status,
            start_connector_session_btn,
            connector_setup_link,
            # connector_panel,
        ], layout=W.Layout(gap="10px"))

        run_plan = build_run_plan_panel(
            summary_widget=summary_html,
            command_widget=command_preview,
        )

        remote_log_controls = build_workspace_toolbar(
            [
                connect_btn,
                status_btn,
                # auto_tail_btn,
                tail_btn,
                clear_btn,
            ],
        )

        cloud_log_controls = build_workspace_toolbar(
            [
                cloud_status_btn,
                cloud_logs_btn,
                clear_btn,
            ],
        )

        log_runtime_controls = build_workspace_toolbar([])

        run_settings_panel = build_run_settings_panel(
            configuration_rows=[
                ui_mode_row,
                mode_row,
                model_row,
                example_picker_row,
                example_info_row,
                example_row,
                exec_row,
                advanced_action_row,
                editor_panel.container,
                run_target_row,
                md_config_panel,
                dataset_panel.container,
            ],
            remote_panel=remote_box,
            cloud_panel=cloud_box,
            run_plan=run_plan.container,
        )

        runtime_panel = build_runtime_panel(
            status_widget=status_chip,

            run_button=run_btn,
            # clear_button=clear_btn,

            # remote_connect_button=connect_btn,
            # remote_status_button=status_btn,
            # remote_logs_button=tail_btn,
            remote_terminate_button=terminate_btn,

            # cloud_status_button=cloud_status_btn,
            # cloud_logs_button=cloud_logs_btn,
            cloud_terminate_button=cloud_terminate_btn,
        )

        actions_card = runtime_panel.container

        # Compatibility aliases
        # remote_actions = runtime_panel.remote_actions
        # cloud_actions = runtime_panel.cloud_actions
        remote_actions = remote_log_controls
        cloud_actions = cloud_log_controls

        workspace_history_panel = build_workspace_history_panel(
            manager=workspace_manager,
            on_run_selected=lambda _run_id: visualization_panel.controller.refresh(),
        )

        output_workspace = build_run_details(
            log_output=log_out,
            results_output=results_out,
            download_controls=download_buttons_row,
            log_controls=log_runtime_controls,
            runs_panel=workspace_history_panel.runs_panel,
            files_panel=workspace_history_panel.files_panel,
            visualization_panel=visualization_panel.container,
        )

        workspace_ui = build_workspace_explorer(
            run_settings=run_settings_panel,
            runtime=actions_card,
            run_details=output_workspace.container,
        )

        row = workspace_ui.container
        workspace_height_sync = workspace_ui.height_sync

        auto_tail_btn.observe(on_auto_tail_change, names="value")

        def _toggle_auth_widgets(_=None):
            show = (auth_mode.value == "bootstrap")
            cluster_password.layout.display = "block" if show else "none"
            bootstrap_btn.layout.display = "block" if show else "none"

        auth_mode.observe(_toggle_auth_widgets, names="value")

        _toggle_auth_widgets()
        refresh_example_picker()
        apply_selected_example()

        # B2: restore this user's saved per-resource settings. Runs last, after
        # every widget + observer exists; the controller guards persistence so a
        # blank build state can never overwrite stored settings during restore.
        try:
            _b2_warnings = resource_state.hydrate()
            _sync_resource_facts()
            for _w in _b2_warnings:
                with log_out:
                    print("[settings]", _w)
        except Exception as _b2_err:  # never block the gateway on restore
            with log_out:
                print("[settings] restore skipped:", type(_b2_err).__name__, _b2_err)

        page = W.VBox(
            [
                shared_styles,
                # W.HTML(css),
                auto_scroll_script,
                W.HTML(CRYOSTACK_FRONTEND_CSS),

                experiment_bridge.widget(),
                workspace_bridge.widget(),

                app_menu,
                header,
                row,
                workspace_height_sync,
                # actions_card,
                back_link,
            ],
            layout=W.Layout(width="100%"),
        )
        page.add_class("cryostack-application-page")

        image_panel.set_model(model_dd.value)
        image_panel.set_profile(software_panel.profile())
        update_visibility()
        update_summary()

        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise
