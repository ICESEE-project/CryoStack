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


# icesee_jupyter_book/ui/icesheets_gateway.py
def build_icesheets_ui():
    try:
        # =========================================================
        # State
        # =========================================================
        def status_html(state: str) -> str:
            cls = {
                "idle": "icesee-idle",
                "running": "icesee-running",
                "done": "icesee-done",
                "fail": "icesee-fail",
            }[state]
            label = {
                "idle": "Idle",
                "running": "Running…",
                "done": "Done",
                "fail": "Failed",
            }[state]
            return f"<span class='icesee-status {cls}'>{label}</span>"

        # =========================================================
        # Controls
        # =========================================================
        mode_dd = W.Dropdown(
            options=[("Remote", "remote"), ("Cloud", "cloud")],
            value="remote",
            layout=W.Layout(width="100%"),
        )

        backend_dd = W.Dropdown(
            options=[("ICESEE-Spack", "spack"), ("ICESEE-Container", "container")],
            value="spack",
            layout=W.Layout(width="100%"),
        )

        model_dd = W.Dropdown(
            options=[("ISSM", "issm"), ("Icepack", "icepack")],
            value="issm",
            layout=W.Layout(width="100%"),
        )

        example_dir = W.Text(
            value="~/examples",
            layout=W.Layout(width="100%"),
        )

        exec_dir = W.Text(
            value="~/runs",
            layout=W.Layout(width="100%"),
        )

        container_source = W.Dropdown(
            options=[("Docker Hub", "docker"), ("AWS Registry", "aws")],
            value="docker",
            layout=W.Layout(width="100%"),
        )

        image_uri = W.Text(
            value="icesee/combined-container:latest",
            layout=W.Layout(width="100%"),
        )

        # =========================================================
        # Outputs
        # =========================================================
        summary_html = W.HTML()
        command_preview = W.Textarea(
            layout=W.Layout(width="100%", height="130px")
        )

        log_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.10)",
            padding="10px",
            height="340px",
            overflow="auto",
            width="100%"
        ))

        results_out = W.Output(layout=W.Layout(
            border="1px solid rgba(0,0,0,.10)",
            padding="10px",
            height="620px",
            overflow="auto",
            width="100%"
        ))

        # =========================================================
        # Dynamic logic
        # =========================================================
        def form_row(label: str, widget):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width="120px", min_width="120px")
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

        def update_visibility(_=None):
            is_container = backend_dd.value == "container"
            container_source.layout.display = "" if is_container else "none"
            image_uri.layout.display = "" if is_container else "none"
            container_source_row.layout.display = "" if is_container else "none"
            image_uri_row.layout.display = "" if is_container else "none"
            update_summary()

        def update_summary(_=None):
            backend = backend_dd.value
            model = model_dd.value
            mode = mode_dd.value

            if model == "issm":
                example_dir.placeholder = "~/examples/issm"
                exec_dir.placeholder = "~/runs/issm"
            else:
                example_dir.placeholder = "~/examples/icepack"
                exec_dir.placeholder = "~/runs/icepack"

            if backend == "spack":
                if model == "issm":
                    model_root = "ICESEE-Spack/.icesee-spack/externals/ISSM"
                    exec_note = "Use the native ISSM workflow inside the ICESEE-Spack environment."
                    cmd = f"cd {example_dir.value} && ./run_issm.sh"
                else:
                    model_root = "ICESEE-Spack/icepack"
                    exec_note = "Use the native Icepack workflow inside the ICESEE-Spack environment."
                    cmd = f"cd {example_dir.value} && python run_icepack.py"

                summary_html.value = f"""
                <div class="icesee-summary">
                <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                <div><span class="icesee-summary-k">Backend:</span> ICESEE-Spack</div>
                <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                <div><span class="icesee-summary-k">Model root:</span> {model_root}</div>
                <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """
            else:
                if container_source.value == "docker":
                    source_name = "Docker Hub"
                else:
                    source_name = "AWS Registry"

                exec_note = (
                    "Create host-side example and execution folders, then bind them into "
                    "the combined ICESEE container before launching the selected model."
                )
                cmd = (
                    f"docker run --rm "
                    f"-v {example_dir.value}:/workspace/examples "
                    f"-v {exec_dir.value}:/workspace/run "
                    f"{image_uri.value}"
                )

                summary_html.value = f"""
                <div class="icesee-summary">
                <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                <div><span class="icesee-summary-k">Backend:</span> ICESEE-Container</div>
                <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                <div><span class="icesee-summary-k">Image source:</span> {source_name}</div>
                <div><span class="icesee-summary-k">Image:</span> {image_uri.value}</div>
                <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """

            command_preview.value = cmd

        backend_dd.observe(update_visibility, names="value")
        model_dd.observe(update_summary, names="value")
        mode_dd.observe(update_summary, names="value")
        container_source.observe(update_summary, names="value")
        image_uri.observe(update_summary, names="value")
        example_dir.observe(update_summary, names="value")
        exec_dir.observe(update_summary, names="value")

        # =========================================================
        # Actions
        # =========================================================
        run_btn = W.Button(description="Run", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", icon="trash")
        status_chip = W.HTML(status_html("idle"))

        def selected_text(dd: W.Dropdown) -> str:
            for label, value in dd.options:
                if value == dd.value:
                    return label
            return str(dd.value)

        def on_run(_=None):
            status_chip.value = status_html("running")
            log_out.clear_output()

            with log_out:
                print("[icesheets] Launching job")
                print(f"[icesheets] mode    : {selected_text(mode_dd)}")
                print(f"[icesheets] backend : {selected_text(backend_dd)}")
                print(f"[icesheets] model   : {selected_text(model_dd)}")
                print(f"[icesheets] example : {example_dir.value}")
                print(f"[icesheets] exec dir: {exec_dir.value}")
                print("-" * 70)
                print(command_preview.value)
                print("-" * 70)
                print("[placeholder] Hook remote/cloud runner here.")

            status_chip.value = status_html("done")

        def on_clear(_=None):
            log_out.clear_output()
            results_out.clear_output()
            status_chip.value = status_html("idle")

        run_btn.on_click(on_run)
        clear_btn.on_click(on_clear)

        # =========================================================
        # CSS
        # =========================================================
        css = """
        <style>
        .icesee-page {
        font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
        width: 100%;
        }
        .icesee-title {
        font-size: 20px;
        font-weight: 700;
        margin: 4px 0 6px;
        color: #1f2937;
        }
        .icesee-subtitle {
        color: rgba(0,0,0,.68);
        margin-bottom: 18px;
        line-height: 1.55;
        max-width: 900px;
        }
        .icesee-h {
        font-size: 18px;
        font-weight: 750;
        margin: 2px 0 14px;
        color: #1f2937;
        }
        .icesee-card {
        border: 1px solid rgba(0,0,0,.08);
        border-radius: 16px;
        padding: 18px;
        background: #fff;
        box-shadow: 0 8px 24px rgba(0,0,0,.04);
        }
        .icesee-lbl {
        font-weight: 600;
        color: rgba(0,0,0,.78);
        padding-top: 8px;
        }
        .icesee-subtle {
        color: rgba(0,0,0,.56);
        font-size: 12px;
        margin-bottom: 6px;
        }
        .icesee-status {
        display:inline-block;
        padding: 8px 14px;
        border-radius:999px;
        font-weight:700;
        border:1px solid rgba(0,0,0,.10);
        }
        .icesee-idle { background: rgba(0,0,0,.04); }
        .icesee-running { background: rgba(16,122,255,.12); }
        .icesee-done { background: rgba(30,170,80,.14); }
        .icesee-fail { background: rgba(220,60,60,.14); }

        .icesee-summary {
        border: 1px solid rgba(0,0,0,.08);
        background: linear-gradient(to bottom, rgba(0,0,0,.015), rgba(0,0,0,.03));
        border-radius: 14px;
        padding: 14px 16px;
        line-height: 1.75;
        color: rgba(0,0,0,.78);
        }
        .icesee-summary-k {
        font-weight: 700;
        color: rgba(0,0,0,.9);
        }
        .icesee-grid {
        display: flex;
        gap: 24px;
        width: 100%;
        align-items: stretch;
        }
        .icesee-left {
        flex: 0 0 46%;
        min-width: 0;
        }
        .icesee-right {
        flex: 0 0 54%;
        min-width: 0;
        }
        .icesee-actions {
        display: flex;
        gap: 12px;
        align-items: center;
        }
        </style>
        """

        # =========================================================
        # Layout
        # =========================================================
        header = W.HTML("""
        <div class="icesee-page">
        <div class="icesee-title">Ice-Sheet Modeling GUI</div>
        <div class="icesee-subtitle">
            Launch supported ice-sheet models without the ICESEE data assimilation layer.
            Choose a backend, select a supported model, and prepare model-only workflows
            through ICESEE-Spack or ICESEE-Container in Remote or Cloud execution modes.
        </div>
        </div>
        """)

        mode_row = form_row("Mode:", mode_dd)
        backend_row = form_row("Backend:", backend_dd)
        model_row = form_row("Model:", model_dd)
        example_row = form_row("Example:", example_dir)
        exec_row = form_row("Exec dir:", exec_dir)
        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        left = W.VBox([
            W.HTML("<div class='icesee-h'>Run settings</div>"),
            mode_row,
            backend_row,
            model_row,
            example_row,
            exec_row,
            container_source_row,
            image_uri_row,
            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Execution summary</div>"),
            summary_html,
            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Command preview</div>"),
            command_preview,
        ], layout=W.Layout(gap="10px"))

        left_card = W.VBox([left])
        left_card.add_class("icesee-card")
        left_card.add_class("icesee-left")

        right = W.VBox([
            W.HTML("<div class='icesee-h'>Run log</div>"),
            log_out,
            W.HTML("<div class='icesee-h' style='margin-top:16px;'>Results preview</div>"),
            results_out,
        ])

        right_card = W.VBox([right])
        right_card.add_class("icesee-card")
        right_card.add_class("icesee-right")

        row = W.HBox([left_card, right_card], layout=W.Layout(width="100%", gap="24px"))
        row.add_class("icesee-grid")

        actions = W.HBox([run_btn, clear_btn, status_chip], layout=W.Layout(gap="12px", align_items="center"))
        actions.add_class("icesee-actions")
        actions_card = W.VBox([W.HTML("<div class='icesee-h'>Status</div>"), actions])
        actions_card.add_class("icesee-card")

        page = W.VBox([W.HTML(css), header, row, actions_card, back_link], layout=W.Layout(width="100%"))

        update_visibility()
        update_summary()
        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise