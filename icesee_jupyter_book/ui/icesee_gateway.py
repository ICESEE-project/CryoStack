# icesee_jupyter_book/ui/icesee_gateway.py
from __future__ import annotations

import os
import yaml
import subprocess
from pathlib import Path
from urllib.parse import urlencode
import ipywidgets as W

from IPython.display import display, Image

from icesee_jupyter_book.core.example_registry import EXAMPLES, enabled_names
from icesee_jupyter_book.core.config_io import load_yaml, dump_yaml
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
    RemoteSubmitResult,
)
from icesee_jupyter_book.core.cloud_runner import (
    AWSBatchConfig,
    aws_batch_status,
    submit_cloud_example,
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

# ===========================================================
# local reporting helpers (also used by remote when fetching results)
# ===========================================================

def refresh_results_preview(rd: Path, results_out: W.Output):
    results_out.clear_output()
    with results_out:
        fig_dir = rd / "figures"
        pngs = sorted(fig_dir.glob("*.png"))
        if not pngs:
            pngs = sorted((rd / "results").glob("*.png"))
        h5s = sorted((rd / "results").glob("*.h5"))

        print("Run folder:", rd)
        print(f"Results: {len(h5s)} H5, {len(pngs)} PNG\n")
        for p in h5s[:10]:
            print(" -", p.name)

        if pngs:
            print("\nFigures:")
            for p in pngs[:6]:
                display(Image(filename=str(p)))
        else:
            print("\nNo figures found yet.")

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
        <a href="http://127.0.0.1:8080/index.html">Home</a>

        <div class="icesee-nav-group">Getting Started</div>
        <a href="http://127.0.0.1:8080/intro.html">ICESEE on GHUB</a>
        <a href="http://127.0.0.1:8080/quickstart.html">Quickstart</a>
        <a href="http://127.0.0.1:8080/icesee_workflow.html">ICESEE Workflow Overview</a>

        <div class="icesee-nav-group">ICESEE-OnLINE</div>
        <a class="active" href="http://127.0.0.1:8866/">ICESEE GUI</a>
        <a href="http://127.0.0.1:8080/icesee_jupyter_notebooks/icesheet_models.html">ICE-Sheet Modeling</a>

        <div class="icesee-nav-group">Tutorials</div>
        <a href="http://127.0.0.1:8080/icesee_jupyter_notebooks/run_lorenz96_da.html">Tutorial: Lorenz-96</a>

        <div class="icesee-nav-group">Deployment Notes</div>
        <a href="http://127.0.0.1:8080/running_with_containers.html">Running with Containers</a>
        <a href="http://127.0.0.1:8080/icesee_hpc_coupling.html">ICESEE-HPC Coupling</a>
        <a href="http://127.0.0.1:8080/user_manual.html">User Manual</a>
      </div>
    </div>
    """
    return W.HTML(sidebar_html)

# back_link = W.HTML(
#     '<div style="margin-bottom:12px;">'
#     '<a href="http://127.0.0.1:8080/" style="font-weight:700; text-decoration:none;">'
#     '← Back to ICESEE Book'
#     '</a>'
#     '</div>'
# )
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
  <a href="http://127.0.0.1:8080/icesee_jupyter_notebooks/run_center.html" class="icesee-back">
    ← Back to ICESEE Run Center
  </a>
</div>
""")

# ============================================================
# UI builder (single entry point)
# ============================================================
def build_icesee_ui():
    # print("STEP 1: start UI")
    import traceback
    try:
        # -----------------------------
        # UI state containers
        # -----------------------------
        STATUS = {"mode": "idle", "remote_dir": None, "jobid": None, "batch_job_id": None, "s3_run": None}

        def set_status(state: str):
            cls = {"idle": "icesee-idle", "running": "icesee-running", "done": "icesee-done", "fail": "icesee-fail"}[state]
            label = {"idle": "Idle", "running": "Running…", "done": "Done", "fail": "Failed"}[state]
            status_chip.value = f"<span class='icesee-status {cls}'>{label}</span>"

        # -----------------------------
        # Top controls
        # -----------------------------
        example_dd = W.Dropdown(options=enabled_names(), value=enabled_names()[0], layout=W.Layout(width="320px"))
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
        mode_tabs = W.Tab()
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

        def build_params_ui(template_path: Path):
            nonlocal params_accordion, PARAMS0, WIDGETS, EXTRA_YAML
            PARAMS0 = load_yaml(template_path)
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

            build_params_ui(TEMPLATE)
            params_holder.children = (params_accordion,)

            with log_out:
                print("[Loaded]")
                print("Template:", TEMPLATE)
                print("Runner  :", RUN_SCRIPT)
                print("Report  :", REPORT_NB if REPORT_NB else "(none)")

        example_dd.observe(rebuild_for_example, names="value")

        # =========================================================
        # Remote panel widgets
        # =========================================================
        cluster_host = W.Text(value="login-phoenix-rh9.pace.gatech.edu", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=os.environ.get("USER", ""), placeholder="username", layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=22, layout=W.Layout(width="120px"))
        
        auth_mode = W.ToggleButtons(
        options=[("Key-only", "key"), ("Bootstrap with password (one-time)", "bootstrap")],
        value="key",
        layout=W.Layout(width="420px")
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

        remote_base_dir = W.Text(value="~/r-arobel3-0", layout=W.Layout(width="320px"))
        remote_tag = W.Text(value="icesee", layout=W.Layout(width="220px"))

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        submit_btn = W.Button(description="Submit job", icon="server", button_style="warning")
        status_btn = W.Button(description="Check status", icon="tasks", button_style="")
        tail_btn = W.Button(description="Tail log", icon="file-text", button_style="")
        terminate_btn = W.Button(description="Terminate job",icon="stop",button_style="danger")

        slurm_job_name = W.Text(value="ICESEE", layout=W.Layout(width="100%"))
        slurm_time = W.Text(value="50:00:00", layout=W.Layout(width="100%"))

        slurm_nodes = W.IntText(value=2, layout=W.Layout(width="100%"))
        slurm_ntasks = W.IntText(value=24, layout=W.Layout(width="100%"))
        slurm_tpn = W.IntText(value=24, layout=W.Layout(width="100%"))

        slurm_part = W.Text(value="cpu-large", layout=W.Layout(width="100%"))
        slurm_mem = W.Text(value="256G", layout=W.Layout(width="100%"))
        slurm_account = W.Text(value="gts-arobel3-atlas", layout=W.Layout(width="100%"))
        slurm_mail = W.Text(value="bankyanjo@gmail.com", layout=W.Layout(width="100%"))

        cluster_mpi_np = W.IntText(value=40, layout=W.Layout(width="100%"))
        cluster_model_nprocs = W.IntText(value=4, layout=W.Layout(width="100%"))

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

        def _toggle_remote_backend(_=None):
            is_ssh = (remote_backend.value == "ssh")
            ssh_box.layout.display = "block" if is_ssh else "none"
            ondemand_box.layout.display = "none" if is_ssh else "block"

        remote_backend.observe(_toggle_remote_backend, names="value")
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
        connect_btn.on_click(on_test_remote)

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

            rd = run_dir()
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
    
        def on_bootstrap_keys(_=None):
            log_out.clear_output()
            set_status("running")

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)
            pw   = cluster_password.value

            if not host or not user:
                set_status("fail")
                with log_out:
                    print("[auth][ERROR] Provide Host + User first.")
                return
            if not pw:
                set_status("fail")
                with log_out:
                    print("[auth][ERROR] Enter your password (used once; not stored).")
                return

            try:
                # 1) ensure local keypair exists
                priv, pub = ensure_local_ssh_key(key_type="ed25519")
                pubkey_text = pub.read_text(encoding="utf-8").strip()

                with log_out:
                    print("[auth] Installing public key to remote authorized_keys…")

                # 2) install pubkey using password auth
                remote_install_pubkey_with_password(
                    host=host, user=user, port=port,
                    password=pw, pubkey_text=pubkey_text
                )

                # 3) verify system ssh works (BatchMode)
                with log_out:
                    print("[auth] Verifying non-interactive SSH…")
                r = ssh_run(host, user, port, "hostname && whoami && date", timeout=15)

                if r.returncode == 0:
                    set_status("done")
                    with log_out:
                        print("[auth] ✅ Passwordless SSH is working. You can switch back to Key-only.")
                    # Optional: flip auth mode back
                    auth_mode.value = "key"
                    cluster_password.value = ""
                else:
                    set_status("fail")
                    with log_out:
                        print("[auth][ERROR] Key install ran, but BatchMode SSH still failed.")
                        print("stdout:", (r.stdout or "").strip())
                        print("stderr:", (r.stderr or "").strip())
                        print("hint :", explain_ssh_failure_hint(r.stderr or ""))

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[auth][ERROR]", type(e).__name__, e)

        # =========================================================
        # Cloud panel widgets (AWS Batch)
        # =========================================================
        aws_region = W.Text(value="us-east-1", layout=W.Layout(width="220px"))
        aws_profile = W.Text(value="", placeholder="(optional) AWS profile", layout=W.Layout(width="220px"))
        cloud_bucket = W.Text(value="", placeholder="s3://bucket/prefix", layout=W.Layout(width="320px"))

        batch_job_queue = W.Text(value="", placeholder="AWS Batch job queue", layout=W.Layout(width="320px"))
        batch_job_def = W.Text(value="", placeholder="job definition (name[:rev])", layout=W.Layout(width="320px"))
        batch_job_name = W.Text(value="icesee", layout=W.Layout(width="220px"))

        cloud_submit_btn = W.Button(description="Submit", icon="cloud-upload", button_style="warning")
        cloud_status_btn = W.Button(description="Check status", icon="search", button_style="")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text", button_style="")

        # =========================================================
        # Actions: Local / Remote / Cloud
        # =========================================================
        def run_example_local():
            example_cfg = EXAMPLES[example_dd.value]

            sync_quick_into_widgets()
            cfg = build_config_from_widgets()

            set_status("running")
            log_out.clear_output()

            try:
                result = run_local_example(
                    example_cfg=example_cfg,
                    config=cfg,
                    output_label=output_label_dd.value,
                    generate_report=gen_report.value,
                )

                with log_out:
                    print("[local] Example :", example_dd.value)
                    print("[local] Runner  :", RUN_SCRIPT)
                    print("[local] Report  :", REPORT_NB if REPORT_NB else "(none)")
                    print("[local] CWD     :", result.run_dir)
                    print("[local] Command :", " ".join(result.command))
                    print("[local] PYTHONPATH(prepended):", result.external_dir)
                    print("-" * 70)

                    for line in result.log_lines:
                        print(line)

                    print("-" * 70)
                    print("Return code:", result.returncode)

                    if result.report_notebook is not None:
                        print("[local] Report done.")

                if not result.success:
                    set_status("fail")
                    refresh_results_preview(result.run_dir, results_out)
                    return

                set_status("done")
                refresh_results_preview(result.run_dir, results_out)

                if open_latest.value:
                    with log_out:
                        print("\nRun folder:", result.run_dir)

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[local][ERROR]", type(e).__name__, e)

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
                example_cfg = EXAMPLES[example_dd.value]

                sync_quick_into_widgets()
                cfg_yaml = build_config_from_widgets()
                params_text = yaml.safe_dump(cfg_yaml, sort_keys=False)

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

                STATUS["remote_dir"] = result.remote_dir
                STATUS["jobid"] = result.jobid

                set_status("done")
                with log_out:
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

            try:
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

                set_status("done" if result["ok"] else "fail")

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
                result = remote_job_status(host, user, port, jobid)

                with log_out:
                    if result["source"] == "squeue":
                        print("--- squeue ---")
                        print((result["stdout"] or "").strip())
                    else:
                        print("(squeue empty; job likely finished or left the queue)")
                        print("--- sacct ---")
                        print((result["stdout"] or "").strip() or "(no sacct output)")
                        if (result["stderr"] or "").strip():
                            print("--- stderr ---")
                            print(result["stderr"].strip())

                set_status("done" if result["returncode"] == 0 else "fail")

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

        def run_example_cloud_submit():
            example_cfg = EXAMPLES[example_dd.value]

            sync_quick_into_widgets()
            cfg_yaml = build_config_from_widgets()

            set_status("running")
            log_out.clear_output()
            with log_out:
                print("[cloud] AWS Batch submit")
                print("example:", example_dd.value)
                print("region :", aws_region.value.strip() or "us-east-1")
                print("profile:", aws_profile.value.strip() or "(default)")
                print("s3     :", cloud_bucket.value.strip())

            try:
                result = submit_cloud_example(
                    example_name=example_dd.value,
                    example_cfg=example_cfg,
                    config=cfg_yaml,
                    region=aws_region.value.strip() or "us-east-1",
                    profile=(aws_profile.value.strip() or None),
                    s3_prefix=cloud_bucket.value.strip(),
                    job_queue=batch_job_queue.value.strip(),
                    job_definition=batch_job_def.value.strip(),
                    job_name=(batch_job_name.value.strip() or "icesee"),
                )

                STATUS["batch_job_id"] = result.batch_job_id
                STATUS["s3_run"] = result.s3_run

                set_status("done")
                with log_out:
                    for msg in result.messages:
                        print(msg)

            except Exception as e:
                set_status("fail")
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def run_example_cloud_status():
            if not STATUS.get("batch_job_id"):
                with log_out:
                    print("[cloud] No Batch job id yet. Submit first.")
                return
            cfg = AWSBatchConfig(
                region=aws_region.value.strip() or "us-east-1",
                profile=(aws_profile.value.strip() or None),
            )
            try:
                st = aws_batch_status(cfg, STATUS["batch_job_id"])
                with log_out:
                    print("[cloud] status:", st["status"])
                    if st["reason"]:
                        print("[cloud] reason:", st["reason"])
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

        connect_btn.on_click(lambda b: run_example_remote_test())
        submit_btn.on_click(lambda b: run_example_remote_submit())
        status_btn.on_click(lambda b: run_example_remote_status())
        tail_btn.on_click(lambda b: run_example_remote_tail())
        terminate_btn.on_click(lambda b: run_example_remote_cancel())

        cloud_submit_btn.on_click(lambda b: run_example_cloud_submit())
        cloud_status_btn.on_click(lambda b: run_example_cloud_status())
        cloud_logs_btn.on_click(lambda b: run_example_cloud_logs_hint())

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
        display(W.HTML(css))

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML(
            "<div class='icesee-wrap'>"
            "<div class='icesee-title'>Run ICESEE examples with one click.</div>"
            "<div class='icesee-subtitle'>Outputs and reports are saved and previewed on the right.</div>"
            "</div>"
        )

        # Local tab content
        local_tab_card = W.VBox([W.HTML("<div class='icesee-subtle'>Local mode runs directly in this notebook.</div>")])
        local_tab_card.add_class("icesee-card")

        # Remote panel
        cluster_panel = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Remote</div>"),
                W.HTML("<div class='icesee-subtle'>SSH connection</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Host:</div>"), cluster_host], layout=W.Layout(gap="12px")),
                W.HBox(
                    [
                        form_pair("User:", cluster_user),
                        form_pair("Port:", cluster_port, label_width="56px"),
                    ],
                    layout=W.Layout(gap="16px", width="100%"),
                ),
                W.HBox(
                    [
                        form_pair("Remote dir:", remote_base_dir, label_width="90px"),
                        form_pair("Tag:", remote_tag, label_width="56px"),
                    ],
                    layout=W.Layout(gap="16px", width="100%"),
                ),
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>ICESEE-Spack</div>"),
                W.Box([spack_enable], layout=W.Layout(margin="0 0 0 120px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Repo:</div>"), spack_repo_url], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Dir name:</div>"), spack_dirname], layout=W.Layout(gap="12px")),
                W.Box([spack_install_if_needed], layout=W.Layout(margin="0 0 0 120px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Install:</div>"), spack_install_mode], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>SLURM_DIR:</div>"), spack_slurm_dir], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>PMIX_DIR:</div>"),  spack_pmix_dir],  layout=W.Layout(gap="12px")),
                W.Box([spack_use_existing_sbatch], layout=W.Layout(margin="0 0 0 120px")),
                # W.HBox([connect_btn, submit_btn, status_btn, tail_btn], layout=W.Layout(gap="10px")),
                W.HBox([connect_btn, status_btn, tail_btn, terminate_btn], layout=W.Layout(gap="10px")),
                W.HTML("<div class='icesee-subtle' style='margin-top:8px'>Slurm resources</div>"),
                W.HBox(
                    [
                        form_pair("Job:", slurm_job_name),
                        form_pair("Time:", slurm_time),
                    ],
                    layout=W.Layout(gap="8px", width="100%"),
                ),
                W.HBox(
                    [
                        form_pair("Nodes:", slurm_nodes),
                        form_pair("Tasks:", slurm_ntasks),
                        form_pair("TPN:", slurm_tpn),
                    ],
                    layout=W.Layout(gap="8px", width="100%"),
                ),
                W.HBox(
                    [
                        form_pair("Part:", slurm_part),
                        form_pair("Mem:", slurm_mem),
                    ],
                    layout=W.Layout(gap="8px", width="100%"),
                ),
                W.HBox(
                    [
                        form_pair("Acct:", slurm_account),
                        form_pair("Mail:", slurm_mail),
                    ],
                    layout=W.Layout(gap="8px", width="100%"),
                ),
                W.HBox(
                    [
                        form_pair("MPI np:", cluster_mpi_np),
                        form_pair("Model nprocs:", cluster_model_nprocs, label_width="120px"),
                    ],
                    layout=W.Layout(gap="8px", width="100%"),
                ),
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Modules</div>"),
                remote_module_lines,
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Exports</div>"),
                remote_export_lines,
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>Auth</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Method:</div>"), auth_mode], layout=W.Layout(gap="12px")),
                W.Box([cluster_password], layout=W.Layout(margin="0 0 0 120px")),
                W.Box([bootstrap_btn], layout=W.Layout(margin="0 0 0 120px")),
            ],
            layout=W.Layout(gap="8px"),
        )
        cluster_panel.add_class("icesee-card")

        # Cloud panel
        cloud_panel = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Cloud</div>"),
                W.HTML("<div class='icesee-subtle'>AWS Batch backend via AWS CLI.</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Region:</div>"), aws_region, W.HTML("<div class='icesee-lbl'>Profile:</div>"), aws_profile],
                    layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>S3 prefix:</div>"), cloud_bucket], layout=W.Layout(gap="12px")),
                W.HTML("<div class='icesee-subtle' style='margin-top:10px'>AWS Batch</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Queue:</div>"), batch_job_queue], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Job def:</div>"), batch_job_def], layout=W.Layout(gap="12px")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Job name:</div>"), batch_job_name], layout=W.Layout(gap="12px")),
                W.HBox([cloud_submit_btn, cloud_status_btn, cloud_logs_btn], layout=W.Layout(gap="10px")),
            ],
            layout=W.Layout(gap="8px"),
        )
        cloud_panel.add_class("icesee-card")

        mode_tabs.children = [local_tab_card, cluster_panel, cloud_panel]
        mode_tabs.set_title(0, "Local (GHUB)")
        mode_tabs.set_title(1, "Remote")
        mode_tabs.set_title(2, "Cloud")

        local_tab_card.layout = W.Layout(width="100%")
        cluster_panel.layout   = W.Layout(width="100%")
        cloud_panel.layout     = W.Layout(width="100%")

        def _toggle_panels_from_tabs(_=None):
            mode = get_mode()

            is_remote = (mode == MODE_REMOTE)
            connect_btn.disabled = not is_remote
            submit_btn.disabled = not is_remote
            status_btn.disabled = not is_remote
            tail_btn.disabled = not is_remote
            terminate_btn.disabled = not is_remote

            is_cloud = (mode == MODE_CLOUD)
            cloud_submit_btn.disabled = not is_cloud
            cloud_status_btn.disabled = not is_cloud
            cloud_logs_btn.disabled = not is_cloud

            update_action_button()

        mode_tabs.observe(_toggle_panels_from_tabs, names="selected_index")
        _toggle_panels_from_tabs()

        left = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Run settings</div>"),
                W.HBox([W.HTML("<div class='icesee-lbl'>Mode:</div>"), mode_tabs], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Example:</div>"), example_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Preset:</div>"), preset_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Filter:</div>"), filter_alg_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Output:</div>"), output_label_dd], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Ens:</div>"), ens_sl], layout=W.Layout(gap="8px", width="100%")),
                W.HBox([W.HTML("<div class='icesee-lbl'>Seed:</div>"), seed_in], layout=W.Layout(gap="8px", width="100%")),
                W.Box([gen_report], layout=W.Layout(margin="6px 0 0 120px")),
                W.Box([open_latest], layout=W.Layout(margin="0 0 8px 120px")),
                W.HTML("<div class='icesee-subtle' style='margin:8px 0 8px'>Full configuration (from <code>params.yaml</code>)</div>"),
                params_holder,
            ],
            layout=W.Layout(gap="8px"),
        )
        left_card = W.VBox([left])
        left_card.add_class("icesee-card")
        left_card.layout = W.Layout(width="100%", flex="0 0 42%", min_width="0")

        right = W.VBox(
            [
                W.HTML("<div class='icesee-h'>Run log</div>"),
                log_out,
                W.HTML("<div class='icesee-h' style='margin-top:14px'>Results preview</div>"),
                results_out,
            ]
        )
        right_card = W.VBox([right])
        right_card.add_class("icesee-card")
        right_card.layout = W.Layout(width="100%", flex="0 0 58%", min_width="0")

        log_out.add_class("icesee-out")
        results_out.add_class("icesee-out")

        # actions = W.HBox([run_btn, clear_btn, status_chip], layout=W.Layout(gap="12px"))
        actions = W.HBox([action_btn, clear_btn, status_chip], layout=W.Layout(gap="12px"))
        actions_card = W.VBox([W.HTML("<div class='icesee-h'>Status</div>"), actions])
        actions_card.add_class("icesee-card")

        left_card.add_class("icesee-col")
        right_card.add_class("icesee-col")

        row = W.HBox([left_card, right_card], layout=W.Layout(width="100%", display="flex", gap="26px"))
        row.add_class("icesee-row")

        page = W.VBox([header, row, actions_card, back_link], layout=W.Layout(width="100%"))
        page.add_class("icesee-page")

        # cloud_submit_btn.layout.display = "none"

        set_status("idle")
        rebuild_for_example()
        # print("STEP 2: widgets created")
        return page
        # sidebar = build_sidebar()
        # main_area = W.VBox([page], layout=W.Layout(width="100%"))
        # main_area.add_class("icesee-main")

        # shell = W.HBox(
        #     [sidebar, main_area],
        #     layout=W.Layout(width="100%", align_items="stretch")
        # )
        # shell.add_class("icesee-shell")

        # return shell
    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise

