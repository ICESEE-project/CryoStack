from __future__ import annotations

import cmd
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
    slurm_optional_lines,
    remote_ensure_spack,
    remote_maybe_install_spack,
    resolve_remote_abs_path,
    remote_stage_and_submit,
    sanitize_multiline,
    RemoteSubmitResult,
)
from icesee_jupyter_book.core.cloud_runner import (
    AWSBatchConfig,
    aws_batch_status,
    submit_cloud_example,
)
from icesee_jupyter_book.ui.shared_ssh_widgets import build_ssh_key_manager


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

def expand_remote_home(path: str) -> str:
    path = path.strip()
    if path.startswith("~/"):
        return f"$HOME/{path[2:]}"
    if path == "~":
        return "$HOME"
    return path

def make_remote_run_dir(base_dir="~/r-arobel3-0", tag="icesee") -> str:
    import time
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{base_dir.rstrip('/')}/{tag}-{ts}"

def submit_remote_icesheets(
    *,
    host: str,
    user: str,
    port: int,
    remote_base_dir: str,
    remote_tag: str,
    backend: str,                  # "spack" | "container"
    model: str,                    # "issm" | "icepack"
    example_dir: str,
    exec_dir: str,
    image_uri: str,
    container_source: str,         # "docker" | "aws"
    spack_enable: bool,
    spack_repo_url: str,
    spack_dirname: str,
    spack_install_if_needed: bool,
    spack_install_mode: str,
    spack_slurm_dir: str,
    spack_pmix_dir: str,
    slurm_time: str,
    slurm_job_name: str,
    slurm_nodes: int,
    slurm_ntasks: int,
    slurm_tpn: int,
    slurm_part: str,
    slurm_mem: str,
    slurm_account: str,
    slurm_mail: str,
    remote_module_lines: str = "",
    remote_export_lines: str = "",
):
    messages: list[str] = []

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    rdir = make_remote_run_dir(
        remote_base_dir.strip() or "~/r-arobel3-0",
        remote_tag.strip() or "icesheets",
    )
    messages.append(f"[remote] Remote run dir: {rdir}")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip()
    )

    # ---------------------------------------------------------
    # Backend setup
    # ---------------------------------------------------------
    spack_path = None
    remote_example_dir = expand_remote_home(example_dir)
    remote_exec_dir = expand_remote_home(exec_dir)

    if backend == "spack":
        if not spack_enable:
            raise RuntimeError("ICESEE-Spack backend requires spack_enable=True")

        spack_parent = remote_base_dir.strip() or "~/r-arobel3-0"
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()

        messages.append("[remote] Spack backend enabled")
        messages.append(f"  parent: {spack_parent}")
        messages.append(f"  repo  : {repo}")
        messages.append(f"  name  : {spack_name}")

        spack_path, (rc, out, err) = remote_ensure_spack(
            host, user, port, spack_parent, spack_name, repo
        )
        if out.strip():
            messages.append(out.strip())
        if err.strip():
            messages.append(err.strip())
        if rc != 0:
            raise RuntimeError("Failed to ensure ICESEE-Spack on remote host.")

        spack_path = resolve_remote_abs_path(host, user, port, spack_path)
        messages.append(f"[remote] Resolved ICESEE-Spack path: {spack_path}")

        if spack_install_if_needed:
            install_flag = spack_install_mode or ""
            messages.append(f"[remote] Spack install requested: {install_flag or '(default)'}")
            rc, out, err = remote_maybe_install_spack(
                host, user, port, spack_path, install_flag, spack_slurm_dir, spack_pmix_dir
            )
            if out.strip():
                messages.append(out.strip())
            if err.strip():
                messages.append(err.strip())
            if rc != 0:
                raise RuntimeError("Remote ICESEE-Spack install failed.")

    elif backend == "container":
        messages.append("[remote] ICESEE-Container backend selected")
        messages.append("[remote] Container setup will be handled inside the submitted Slurm job.")

    else:
        raise RuntimeError(f"Unsupported backend: {backend}")

    # ---------------------------------------------------------
    # Build model-specific run block
    # ---------------------------------------------------------
    if backend == "spack":
        if model == "issm":
            run_block = f"""
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "addpath([getenv('ISSM_DIR') '/bin'], [getenv('ISSM_DIR') '/lib']); issmversion; exit"
"""
        elif model == "icepack":
            run_block = f"""
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
"""
        else:
            raise RuntimeError(f"Unsupported model: {model}")

        activation_block = f"""
cd "{spack_path}"
source "{spack_path}/scripts/activate.sh"
"""

        body = activation_block + "\n" + run_block

    else:
        sif_path = f"{expand_remote_home(remote_base_dir)}/{remote_tag}/ICESEE-Containers/spack-managed/combined-container/combined-env.sif"

        if model == "issm":
            run_block = f"""
    mkdir -p "{remote_example_dir}" "{remote_exec_dir}"
    srun --mpi=pmix -n {slurm_ntasks} apptainer exec \\
    -B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution \\
    "{sif_path}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"
    """
        elif model == "icepack":
            run_block = f"""
    mkdir -p "{remote_example_dir}" "{remote_exec_dir}"
    apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
    """
        else:
            raise RuntimeError(f"Unsupported model: {model}")

        container_setup = f"""
    # --- ICESEE-Container / Apptainer setup ---
    echo "[icesheets] Checking apptainer..."

    if ! command -v apptainer >/dev/null 2>&1; then
    echo "[icesheets] apptainer not found in PATH. Trying module load apptainer..."
    source /etc/profile >/dev/null 2>&1 || true
    module load apptainer >/dev/null 2>&1 || true
    fi

    if ! command -v apptainer >/dev/null 2>&1; then
    echo "[icesheets][ERROR] apptainer not found, and module load apptainer failed."
    exit 2
    fi

    container_root="{expand_remote_home(remote_base_dir)}/{remote_tag}/ICESEE-Containers"
    container_dir="$container_root/spack-managed/combined-container"
    sif_path="$container_dir/combined-env.sif"
    def_path="$container_dir/combined-env-inbuilt-matlab.def"

    mkdir -p "{expand_remote_home(remote_base_dir)}/{remote_tag}"

    if [ ! -d "$container_root" ]; then
    echo "[icesheets] Cloning ICESEE-Containers..."
    git clone https://github.com/ICESEE-project/ICESEE-Containers.git "$container_root"
    fi

    cd "$container_dir"

    if [ ! -f "$sif_path" ]; then
    echo "[icesheets] Building Apptainer image..."
    if [ ! -f "$def_path" ]; then
        echo "[icesheets][ERROR] Definition file not found: $def_path"
        exit 2
    fi
    apptainer build combined-env.sif combined-env-inbuilt-matlab.def
    else
    echo "[icesheets] Using existing Apptainer image: $sif_path"
    fi
    """
        body = container_setup + "\n" + run_block

    # ---------------------------------------------------------
    # Render sbatch
    # ---------------------------------------------------------
    outfile = "icesheets-%j.out"

    slurm_text = f"""#!/bin/bash
#SBATCH -J {slurm_job_name.strip() or "ICESHEETS"}
#SBATCH -t {slurm_time.strip()}
#SBATCH -N {int(slurm_nodes)}
#SBATCH --ntasks={int(slurm_ntasks)}
#SBATCH --ntasks-per-node={int(slurm_tpn)}
#SBATCH -p {slurm_part.strip()}
#SBATCH --mem={slurm_mem.strip()}
{account_line}
{mail_lines}
#SBATCH -o {outfile}

set -euo pipefail

echo "[icesheets] Host: $(hostname)"
echo "[icesheets] Date: $(date)"
echo "[icesheets] PWD : $(pwd)"

{sanitize_multiline(remote_module_lines)}
{sanitize_multiline(remote_export_lines)}

{body}
"""

    messages.append("[remote] Writing slurm_run.sh, then sbatch…")

    jobid = remote_stage_and_submit(
        host=host,
        user=user,
        port=port,
        remote_dir=rdir,
        params_text="",   # no params.yaml needed for model-only currently
        slurm_text=slurm_text,
    )

    messages.append("[remote] ✅ Submitted model-only slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {rdir}")

    return {
        "success": True,
        "jobid": jobid,
        "remote_dir": rdir,
        "log_file": f"{rdir}/icesheets-{jobid}.out" if jobid else None,
        "spack_path": spack_path,
        "messages": messages,
    }

def build_icesheets_ui():
    try:
        # =========================================================
        # State
        # =========================================================
        STATUS = {
            "mode": "idle",
            "remote_dir": None,
            "jobid": None,
            "batch_job_id": None,
            "cloud_run": None,
        }

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

        example_dir = W.Text(value="~/examples", layout=W.Layout(width="100%"))
        exec_dir = W.Text(value="~/runs", layout=W.Layout(width="100%"))

        container_source = W.Dropdown(
            options=[("Docker Hub", "docker"), ("AWS Registry", "aws")],
            value="docker",
            layout=W.Layout(width="100%"),
        )

        image_uri = W.Text(
            value="icesee/combined-container:latest",
            layout=W.Layout(width="100%"),
        )

        # -----------------------------
        # Remote controls
        # -----------------------------
        cluster_host = W.Text(value="login-phoenix-rh9.pace.gatech.edu", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=os.environ.get("USER", ""), placeholder="username", layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=22, layout=W.Layout(width="120px"))

        remote_base_dir = W.Text(value="~/r-arobel3-0", layout=W.Layout(width="320px"))
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

        slurm_job_name = W.Text(value="ICESHEETS", layout=W.Layout(width="100%"))
        slurm_time = W.Text(value="04:00:00", layout=W.Layout(width="100%"))
        slurm_nodes = W.IntText(value=1, layout=W.Layout(width="100%"))
        slurm_ntasks = W.IntText(value=8, layout=W.Layout(width="100%"))
        slurm_tpn = W.IntText(value=8, layout=W.Layout(width="100%"))
        slurm_part = W.Text(value="cpu-large", layout=W.Layout(width="100%"))
        slurm_mem = W.Text(value="64G", layout=W.Layout(width="100%"))
        slurm_account = W.Text(value="gts-arobel3-atlas", layout=W.Layout(width="100%"))
        slurm_mail = W.Text(value="bankyanjo@gmail.com", layout=W.Layout(width="100%"))

        connect_btn = W.Button(description="Test SSH", icon="terminal", button_style="info")
        status_btn = W.Button(description="Check status", icon="tasks")
        tail_btn = W.Button(description="Tail log", icon="file-text")
        terminate_btn = W.Button(description="Terminate job", icon="stop", button_style="danger")

        def build_spack_activation_block() -> str:
            remote_root = f"{expand_remote_home(remote_base_dir.value)}/{remote_tag.value}"
            spack_repo = f"{remote_root}/ICESEE-Spack"

            return f"""
        # --- ICESEE-Spack setup ---
        mkdir -p "{remote_root}"

        if [ ! -d "{spack_repo}" ]; then
        echo "[icesheets] ICESEE-Spack not found. Cloning..."
        git clone https://github.com/ICESEE-project/ICESEE-Spack.git "{spack_repo}"
        fi

        cd "{spack_repo}"

        if [ ! -f "./scripts/activate.sh" ]; then
        echo "[icesheets][ERROR] scripts/activate.sh not found in ICESEE-Spack."
        exit 2
        fi

        source ./scripts/activate.sh
        """

        def build_container_setup_block() -> str:
            remote_root = f"{expand_remote_home(remote_base_dir.value)}/{remote_tag.value}"
            container_root = f"{remote_root}/ICESEE-Containers"
            container_dir = f"{container_root}/spack-managed/combined-container"
            sif_path = f"{container_dir}/combined-env.sif"
            def_path = f"{container_dir}/combined-env-inbuilt-matlab.def"

            return f"""
        # --- ICESEE-Container / Apptainer setup ---
        echo "[icesheets] Checking apptainer..."

        if ! command -v apptainer >/dev/null 2>&1; then
        echo "[icesheets] apptainer not found in PATH. Trying module load apptainer..."
        module load apptainer >/dev/null 2>&1 || true
        fi

        if ! command -v apptainer >/dev/null 2>&1; then
        echo "[icesheets][ERROR] apptainer not found, and module load apptainer failed."
        exit 2
        fi

        mkdir -p "{remote_root}"

        if [ ! -d "{container_root}" ]; then
        echo "[icesheets] Cloning ICESEE-Containers..."
        git clone https://github.com/ICESEE-project/ICESEE-Containers.git "{container_root}"
        fi

        cd "{container_dir}"

        if [ ! -f "{sif_path}" ]; then
        echo "[icesheets] Apptainer image not found."

        if [ ! -f "{def_path}" ]; then
            echo "[icesheets][ERROR] Definition file not found:"
            echo "  {def_path}"
            exit 2
        fi

        echo "[icesheets] Building image from definition file..."
        apptainer build combined-env.sif combined-env-inbuilt-matlab.def
        else
        echo "[icesheets] Using existing Apptainer image:"
        echo "  {sif_path}"
        fi
        """

        def build_remote_model_run_block() -> str:
            backend = backend_dd.value
            model = model_dd.value

            example_path = expand_remote_home(example_dir.value)
            exec_path = expand_remote_home(exec_dir.value)

            if backend == "spack":
                if model == "issm":
                    return (
                        'matlab -nodesktop -nosplash -r '
                        '"addpath([getenv(\'ISSM_DIR\') \'/bin\'], [getenv(\'ISSM_DIR\') \'/lib\']); '
                        'issmversion; exit"'
                    )
                return 'python -c "import icepack; print(\'Icepack import successful\')"'

            remote_root = f"{expand_remote_home(remote_base_dir.value)}/{remote_tag.value}"
            container_dir = f"{remote_root}/ICESEE-Containers/spack-managed/combined-container"
            sif_path = f"{container_dir}/combined-env.sif"

            if model == "issm":
                return f"""
        # --- ISSM via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec \\
        -B "{example_path}":/opt/ISSM/examples,"{exec_path}":/opt/ISSM/execution \\
        "{sif_path}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"
        """
            return f"""
        # --- Icepack via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
        """

        def build_icesheets_sbatch_script() -> str:
            header = f"""#!/bin/bash
        #SBATCH -J {slurm_job_name.value}
        #SBATCH -t {slurm_time.value}
        #SBATCH -N {slurm_nodes.value}
        #SBATCH --ntasks={slurm_ntasks.value}
        #SBATCH --ntasks-per-node={slurm_tpn.value}
        #SBATCH -p {slurm_part.value}
        #SBATCH --mem={slurm_mem.value}
        #SBATCH -A {slurm_account.value}
        #SBATCH --mail-user={slurm_mail.value}
        #SBATCH --mail-type=END,FAIL

        set -euo pipefail

        echo "[icesheets] Host: $(hostname)"
        echo "[icesheets] Date: $(date)"
        echo "[icesheets] PWD : $(pwd)"
        """

            if backend_dd.value == "spack":
                body = build_spack_activation_block() + "\n" + build_remote_model_run_block()
            else:
                body = build_container_setup_block() + "\n" + build_remote_model_run_block()

            return header + "\n" + body + "\n"

        # -----------------------------
        # Cloud controls
        # -----------------------------
        aws_region = W.Text(value="us-east-1", layout=W.Layout(width="220px"))
        aws_profile = W.Text(value="", placeholder="(optional) AWS profile", layout=W.Layout(width="220px"))
        cloud_bucket = W.Text(value="", placeholder="s3://bucket/prefix", layout=W.Layout(width="320px"))

        batch_job_queue = W.Text(value="", placeholder="AWS Batch job queue", layout=W.Layout(width="320px"))
        batch_job_def = W.Text(value="", placeholder="job definition (name[:rev])", layout=W.Layout(width="320px"))
        batch_job_name = W.Text(value="icesheets", layout=W.Layout(width="220px"))

        cloud_status_btn = W.Button(description="Check status", icon="search")
        cloud_logs_btn = W.Button(description="Logs hint", icon="file-text")

        # =========================================================
        # Outputs
        # =========================================================
        summary_html = W.HTML()
        command_preview = W.Textarea(layout=W.Layout(width="100%", height="130px"))

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
        # Helpers
        # =========================================================
        def form_row(label: str, widget):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width="120px", min_width="120px")
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

        def form_pair(label: str, widget, label_width: str = "80px"):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

        def selected_text(dd: W.Dropdown) -> str:
            for label, value in dd.options:
                if value == dd.value:
                    return label
            return str(dd.value)

        def build_model_command():
            backend = backend_dd.value
            model = model_dd.value

            if backend == "spack":
                if model == "issm":
                    return (
                            'matlab -nodesktop -nosplash -r '
                            '"addpath([getenv('"'\"ISSM_DIR\"'"') ''/bin''], '
                            '[getenv('"'\"ISSM_DIR\"'"') ''/lib'']); '
                            'issmversion; exit"'
                        )
                return f"cd {example_dir.value} && python -c \"import icepack\""

            if model == "issm":
                return (
                    f"mkdir -p {example_dir.value} {exec_dir.value} && "
                    f"srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec "
                    f"-B {example_dir.value}:/opt/ISSM/examples,{exec_dir.value}:/opt/ISSM/execution "
                    f"{image_uri.value} with-issm matlab -r \"issmversion\""
                )

            return f"apptainer exec {image_uri.value} with-icepack python -c \"import icepack\""

        # =========================================================
        # Dynamic logic
        # =========================================================
        def update_visibility(_=None):
            is_container = backend_dd.value == "container"
            is_remote = mode_dd.value == "remote"
            is_cloud = mode_dd.value == "cloud"

            container_source_row.layout.display = "" if is_container else "none"
            image_uri_row.layout.display = "" if is_container else "none"

            remote_box.layout.display = "" if is_remote else "none"
            cloud_box.layout.display = "" if is_cloud else "none"

            remote_actions.layout.display = "" if is_remote else "none"
            cloud_actions.layout.display = "" if is_cloud else "none"

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
                else:
                    model_root = "ICESEE-Spack/icepack"
                    exec_note = "Use the native Icepack workflow inside the ICESEE-Spack environment."

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
                source_name = "Docker Hub" if container_source.value == "docker" else "AWS Registry"
                exec_note = (
                    "Create host-side example and execution folders, then bind them into "
                    "the combined ICESEE container before launching the selected model."
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

            command_preview.value = build_model_command()

        backend_dd.observe(update_visibility, names="value")
        model_dd.observe(update_summary, names="value")
        mode_dd.observe(update_visibility, names="value")
        container_source.observe(update_summary, names="value")
        image_uri.observe(update_summary, names="value")
        example_dir.observe(update_summary, names="value")
        exec_dir.observe(update_summary, names="value")
        slurm_ntasks.observe(update_summary, names="value")

        # =========================================================
        # Actions
        # =========================================================
        run_btn = W.Button(description="Submit job", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", icon="trash")
        status_chip = W.HTML(status_html("idle"))

        def on_run(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            mode = mode_dd.value

            if mode == "cloud":
                with log_out:
                    print("[cloud] Placeholder for AWS Batch submission.")
                    print(f"[cloud] backend : {selected_text(backend_dd)}")
                    print(f"[cloud] model   : {selected_text(model_dd)}")
                    print(f"[cloud] region  : {aws_region.value.strip() or 'us-east-1'}")
                    print(f"[cloud] profile : {aws_profile.value.strip() or '(default)'}")
                    print(f"[cloud] bucket  : {cloud_bucket.value.strip() or '(not set)'}")
                    print(f"[cloud] queue   : {batch_job_queue.value.strip() or '(not set)'}")
                    print(f"[cloud] job def : {batch_job_def.value.strip() or '(not set)'}")
                    print(f"[cloud] job name: {batch_job_name.value.strip() or 'icesheets'}")
                    print("[cloud] Next step is to adapt submit_cloud_example for model-only workflows.")
                status_chip.value = status_html("done")
                return

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            if not host or not user:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR] Host and User are required.")
                return

            try:
                result = submit_remote_icesheets(
                    host=host,
                    user=user,
                    port=port,
                    remote_base_dir=remote_base_dir.value,
                    remote_tag=remote_tag.value,
                    backend=backend_dd.value,
                    model=model_dd.value,
                    example_dir=example_dir.value,
                    exec_dir=exec_dir.value,
                    image_uri=image_uri.value,
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
                )

                STATUS["remote_dir"] = result["remote_dir"]
                STATUS["jobid"] = result["jobid"]
                STATUS["log_file"] = result.get("log_file")

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

        def on_test_remote(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")
            try:
                result = remote_test_connection(
                    cluster_host.value.strip(),
                    cluster_user.value.strip(),
                    int(cluster_port.value),
                )
                with log_out:
                    print("[remote] Test SSH")
                    print("returncode:", result["returncode"])
                    if (result["stdout"] or "").strip():
                        print("--- stdout ---")
                        print(result["stdout"].strip())
                    if (result["stderr"] or "").strip():
                        print("--- stderr ---")
                        print(result["stderr"].strip())
                status_chip.value = status_html("done" if result["ok"] else "fail")
            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_status(_=None):
            log_out.clear_output()
            jobid = STATUS.get("jobid")
            if not jobid:
                with log_out:
                    print("[remote] No JobID yet. Submit first.")
                return

            try:
                result = remote_job_status(
                    cluster_host.value.strip(),
                    cluster_user.value.strip(),
                    int(cluster_port.value),
                    jobid,
                )
                with log_out:
                    print("[remote] Status")
                    print((result["stdout"] or "").strip() or "(no output)")
                status_chip.value = status_html("done" if result["returncode"] == 0 else "fail")
            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_tail(_=None):
            log_out.clear_output()

            rdir = STATUS.get("remote_dir")
            jobid = STATUS.get("jobid")

            if not rdir or not jobid:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote] No remote_dir / JobID yet. Submit first.")
                return

            log_file = STATUS.get("log_file") or f"{rdir}/icesheets-{jobid}.out"

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            tail_cmd = f"""
        set -e
        log_file="{log_file}"
        run_dir="{rdir}"

        if [ -f "$log_file" ]; then
        echo "[remote] file: $log_file"
        echo "--- tail ---"
        tail -n 120 "$log_file"
        else
        echo "[remote] log file not found yet: $log_file"
        echo
        echo "[remote] contents of run dir:"
        ls -lah "$run_dir" || true
        fi
        """

            try:
                result = ssh_run(host, user, port, tail_cmd, timeout=30)

                with log_out:
                    if (result.stdout or "").strip():
                        print(result.stdout.rstrip())
                    if (result.stderr or "").strip():
                        print("--- stderr ---")
                        print(result.stderr.strip())

                status_chip.value = status_html("done" if result.returncode == 0 else "fail")

            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_terminate(_=None):
            log_out.clear_output()
            jobid = STATUS.get("jobid")
            if not jobid:
                with log_out:
                    print("[remote] No JobID found.")
                return

            try:
                result = remote_cancel_job(
                    cluster_host.value.strip(),
                    cluster_user.value.strip(),
                    int(cluster_port.value),
                    jobid,
                )
                with log_out:
                    print("returncode:", result["returncode"])
                    if (result["stdout"] or "").strip():
                        print(result["stdout"].strip())
                    if (result["stderr"] or "").strip():
                        print(result["stderr"].strip())
            except Exception as e:
                with log_out:
                    print("[remote][ERROR]", type(e).__name__, e)

        def on_cloud_status(_=None):
            log_out.clear_output()
            jobid = STATUS.get("batch_job_id")
            if not jobid:
                with log_out:
                    print("[cloud] No Batch job id yet. Submit first.")
                return

            try:
                cfg = AWSBatchConfig(
                    region=aws_region.value.strip() or "us-east-1",
                    profile=(aws_profile.value.strip() or None),
                )
                st = aws_batch_status(cfg, jobid)
                with log_out:
                    print("[cloud] status:", st["status"])
                    if st["reason"]:
                        print("[cloud] reason:", st["reason"])
                status_chip.value = status_html("done")
            except Exception as e:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[cloud][ERROR]", type(e).__name__, e)

        def on_cloud_logs(_=None):
            log_out.clear_output()
            with log_out:
                print("[cloud] Logs depend on the AWS Batch job definition (awslogs driver).")
                print("Open AWS Console -> Batch -> Job -> Logs")
                if STATUS.get("batch_job_id"):
                    print("JobID:", STATUS["batch_job_id"])
                if STATUS.get("cloud_run"):
                    print("Cloud run:", STATUS["cloud_run"])

        run_btn.on_click(on_run)
        clear_btn.on_click(on_clear)
        connect_btn.on_click(on_test_remote)
        status_btn.on_click(on_status)
        tail_btn.on_click(on_tail)
        terminate_btn.on_click(on_terminate)
        cloud_status_btn.on_click(on_cloud_status)
        cloud_logs_btn.on_click(on_cloud_logs)

        # =========================================================
        # CSS
        # =========================================================
        css = """
        <style>
        .icesee-page { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; width: 100%; }
        .icesee-title { font-size: 20px; font-weight: 700; margin: 4px 0 6px; color: #1f2937; }
        .icesee-subtitle { color: rgba(0,0,0,.68); margin-bottom: 18px; line-height: 1.55; max-width: 900px; }
        .icesee-h { font-size: 18px; font-weight: 750; margin: 2px 0 14px; color: #1f2937; }
        .icesee-card { border: 1px solid rgba(0,0,0,.08); border-radius: 16px; padding: 18px; background: #fff; box-shadow: 0 8px 24px rgba(0,0,0,.04); }
        .icesee-lbl { font-weight: 600; color: rgba(0,0,0,.78); padding-top: 8px; }
        .icesee-subtle { color: rgba(0,0,0,.56); font-size: 12px; margin-bottom: 6px; }
        .icesee-status { display:inline-block; padding: 8px 14px; border-radius:999px; font-weight:700; border:1px solid rgba(0,0,0,.10); }
        .icesee-idle { background: rgba(0,0,0,.04); }
        .icesee-running { background: rgba(16,122,255,.12); }
        .icesee-done { background: rgba(30,170,80,.14); }
        .icesee-fail { background: rgba(220,60,60,.14); }
        .icesee-summary { border: 1px solid rgba(0,0,0,.08); background: linear-gradient(to bottom, rgba(0,0,0,.015), rgba(0,0,0,.03)); border-radius: 14px; padding: 14px 16px; line-height: 1.75; color: rgba(0,0,0,.78); }
        .icesee-summary-k { font-weight: 700; color: rgba(0,0,0,.9); }
        .icesee-grid { display: flex; gap: 24px; width: 100%; align-items: stretch; }
        .icesee-left { flex: 0 0 46%; min-width: 0; }
        .icesee-right { flex: 0 0 54%; min-width: 0; }
        .icesee-actions { display: flex; gap: 12px; align-items: center; }
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

        def form_pair(label: str, widget, label_width: str = "80px"):
            lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
            lbl.layout = W.Layout(width=label_width, min_width=label_width)
            return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

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

        cluster_name_for_keys = W.Text(value="pace" , layout=W.Layout(width="320px"))
        ssh_key_manager = build_ssh_key_manager(
            cluster_name_widget=cluster_name_for_keys,
            host_widget=cluster_host,
            user_widget=cluster_user,
        )

        remote_box = W.VBox([
            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Remote connection</div>"),
            cluster_host_row,
            W.HBox([cluster_user_row, cluster_port_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([remote_base_dir_row, remote_tag_row], layout=W.Layout(gap="12px", width="100%")),

            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Authentication</div>"),
            W.HBox([W.HTML("<div class='icesee-lbl'>Method:</div>"), auth_mode], layout=W.Layout(gap="10px")),
            cluster_password,
            bootstrap_btn,

            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>SSH key manager</div>"),
            ssh_key_manager,

            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Slurm resources</div>"),
            W.HBox([slurm_job_name_row, slurm_time_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_nodes_row, slurm_ntasks_row, slurm_tpn_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_part_row, slurm_mem_row], layout=W.Layout(gap="12px", width="100%")),
            W.HBox([slurm_account_row, slurm_mail_row], layout=W.Layout(gap="12px", width="100%")),
        ], layout=W.Layout(gap="10px"))

        cloud_box = W.VBox([
            W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Cloud configuration</div>"),
            W.HBox([
                form_pair("Region:", aws_region, "90px"),
                form_pair("Profile:", aws_profile, "90px"),
            ], layout=W.Layout(gap="12px", width="100%")),
            form_pair("S3 prefix:", cloud_bucket, "90px"),
            W.HBox([
                form_pair("Queue:", batch_job_queue, "90px"),
                form_pair("Job def:", batch_job_def, "90px"),
            ], layout=W.Layout(gap="12px", width="100%")),
            form_pair("Job name:", batch_job_name, "90px"),
        ], layout=W.Layout(gap="10px"))

        left = W.VBox([
            W.HTML("<div class='icesee-h'>Run settings</div>"),
            mode_row,
            backend_row,
            model_row,
            example_row,
            exec_row,
            container_source_row,
            image_uri_row,
            remote_box,
            cloud_box,
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

        remote_actions = W.HBox(
            [connect_btn, status_btn, tail_btn, terminate_btn],
            layout=W.Layout(gap="10px", flex_wrap="wrap")
        )

        cloud_actions = W.HBox(
            [cloud_status_btn, cloud_logs_btn],
            layout=W.Layout(gap="10px", flex_wrap="wrap")
        )

        actions = W.HBox(
            [run_btn, clear_btn, status_chip],
            layout=W.Layout(gap="12px", align_items="center")
        )
        actions.add_class("icesee-actions")

        actions_card = W.VBox([
            W.HTML("<div class='icesee-h'>Status</div>"),
            actions,
            W.HTML("<div class='icesee-subtle' style='margin-top:10px;'>Remote job controls</div>"),
            remote_actions,
            W.HTML("<div class='icesee-subtle' style='margin-top:10px;'>Cloud job controls</div>"),
            cloud_actions,
        ])
        actions_card.add_class("icesee-card")

        def _toggle_auth_widgets(_=None):
            show = (auth_mode.value == "bootstrap")
            cluster_password.layout.display = "block" if show else "none"
            bootstrap_btn.layout.display = "block" if show else "none"

        auth_mode.observe(_toggle_auth_widgets, names="value")
        _toggle_auth_widgets()

        page = W.VBox([W.HTML(css), header, row, actions_card, back_link], layout=W.Layout(width="100%"))

        update_visibility()
        update_summary()
        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise