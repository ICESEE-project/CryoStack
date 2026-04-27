from __future__ import annotations

import os
import io
import yaml
import zipfile
import shutil
import asyncio
import subprocess
from pathlib import Path
from IPython.display import FileLink

import ipywidgets as W
from IPython.display import display, Image

from icesee_jupyter_book.core.icesheet_examples import (
    examples_as_dropdown_options,
    find_example_by_path,
    example_summary_text,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    remote_test_connection,
    remote_job_status,
    remote_cancel_job,
    slurm_optional_lines,
    remote_ensure_spack,
    remote_maybe_install_spack,
    resolve_remote_abs_path,
    remote_stage_and_submit,
    sanitize_multiline,
)
from icesee_jupyter_book.core.cloud_runner import (
    AWSBatchConfig,
    aws_batch_status,
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

# def expand_remote_home(path: str) -> str:
#     if path is None:
#         return ""
#     path = str(path).strip()
#     if not path:
#         return ""
#     if path.startswith("/"):
#         return path
#     if path.startswith("~/"):
#         return f"$HOME/{path[2:]}"
#     if path == "~":
#         return "$HOME"
#     return path

def expand_remote_home(path: str) -> str:
    if path is None:
        return ""
    path = str(path).strip()
    if not path:
        return ""
    return path

def make_remote_run_dir(base_dir="~/r-arobel3-0", tag="icesee") -> str:
    import time
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = str(base_dir).rstrip("/")
    return f"{base}/{tag}-{ts}"

def normalize_remote_path(path: str) -> str:
    path = expand_remote_home(path)
    if not path:
        return ""
    while "//" in path:
        path = path.replace("//", "/")
    return path

def submit_remote_icesheets(
    *,
    host: str,
    user: str,
    port: int,
    remote_base_dir: str,
    remote_tag: str,
    backend: str,
    model: str,
    example_dir: str,
    exec_dir: str,
    image_uri: str,
    container_source: str,
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
    test_mode: bool = False,
    run_file: str = "",
):
    import base64
    import time

    messages: list[str] = []

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    # ---------------------------------------------------------
    # Remote base/run paths
    # ---------------------------------------------------------
    remote_base_input = (remote_base_dir or "").strip() or "~/r-arobel3-0"
    remote_base_shell = expand_remote_home(remote_base_input)
    remote_base_abs = resolve_remote_abs_path(host, user, port, remote_base_shell)

    tag = (remote_tag or "").strip() or "icesheets"
    # ts = time.strftime("%Y%m%d-%H%M%S")
    # remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}-{ts}"
    
    remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}/runs/{model}_{backend}"
    remote_submit_script = f"{remote_run_dir}/run_icesheets.sbatch"

    messages.append(f"[remote] Remote base dir : {remote_base_abs}")
    messages.append(f"[remote] Remote run dir  : {remote_run_dir}")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    spack_path = None
    run_file_name = Path(run_file).name if run_file else ""
    run_file_py = Path(run_file_name).with_suffix(".py").name if run_file_name else ""

    local_example_dir = str(Path(example_dir).expanduser())
    local_exec_dir = str(Path(exec_dir).expanduser())

    messages.append(f"[remote] example_dir input : {local_example_dir}")
    messages.append(f"[remote] exec_dir input    : {local_exec_dir}")
    messages.append(f"[remote] run_file input    : {run_file or '(none)'}")
    messages.append(f"[remote] test_mode         : {test_mode}")

    # ---------------------------------------------------------
    # Backend setup
    # ---------------------------------------------------------
    if backend == "spack":
        if not spack_enable:
            raise RuntimeError("ICESEE-Spack backend requires spack_enable=True")

        spack_parent = remote_base_abs
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()

        messages.append("[remote] Spack backend enabled")
        messages.append(f"  parent: {spack_parent}")
        messages.append(f"  repo  : {repo}")
        messages.append(f"  name  : {spack_name}")

        spack_path_raw, (rc, out, err) = remote_ensure_spack(
            host, user, port, spack_parent, spack_name, repo
        )
        if out.strip():
            messages.append(out.strip())
        if err.strip():
            messages.append(err.strip())
        if rc != 0:
            raise RuntimeError("Failed to ensure ICESEE-Spack on remote host.")

        spack_path = resolve_remote_abs_path(host, user, port, spack_path_raw)
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
    
    clean_cmd = f'''
    rm -rf "{remote_run_dir}"
    mkdir -p "{remote_run_dir}"
    '''
    mkres = ssh_run(host, user, port, clean_cmd, timeout=30)

    # ---------------------------------------------------------
    # Stage local example to remote run dir
    # ---------------------------------------------------------
    local_example_path = Path(local_example_dir)
    if not local_example_path.exists():
        raise RuntimeError(f"Local example path does not exist: {local_example_path}")

    mkres = ssh_run(host, user, port, f'mkdir -p "{remote_run_dir}"', timeout=30)
    if mkres.returncode != 0:
        raise RuntimeError(f"Failed to create remote run dir:\n{mkres.stderr}")

    local_parent = str(local_example_path.resolve().parent)
    local_name = local_example_path.resolve().name

    rsync_cmd = [
        "rsync",
        "-az",
        "-e",
        f"ssh -p {port}",
        f"{local_parent}/{local_name}",
        f"{user}@{host}:{remote_run_dir}/",
    ]
    rs = subprocess.run(rsync_cmd, capture_output=True, text=True)
    if rs.returncode != 0:
        raise RuntimeError(
            "Failed to copy local example to remote host\n"
            f"STDOUT:\n{rs.stdout}\n\nSTDERR:\n{rs.stderr}"
        )

    remote_example_dir = f"{remote_run_dir}/{local_name}"
    remote_exec_dir = f"{remote_run_dir}/execution"

    messages.append(f"[remote] staged example dir: {remote_example_dir}")
    messages.append(f"[remote] staged exec dir   : {remote_exec_dir}")

    # ---------------------------------------------------------
    # Build model-specific run block
    # ---------------------------------------------------------
    if backend == "spack":
        issm_matlab_setup = (
            "addpath([getenv('ISSM_DIR') '/bin'], [getenv('ISSM_DIR') '/lib']); "
            "issmversion; "
        )
        if test_mode:
            if model == "issm":
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup}; exit"
'''
            elif model == "icepack":
                run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")
        else:
            if model == "issm":
                target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
                run_block = f'''
cd "{remote_example_dir}"
matlab -nodesktop -nosplash -r "{issm_matlab_setup} run('{target_m}'); exit"
'''
            elif model == "icepack":
                if run_file_name.endswith(".py"):
                    run_block = f'''
cd "{remote_example_dir}"
python "{run_file_name}"
'''
                elif run_file_name.endswith(".ipynb"):
                    run_block = f'''
cd "{remote_example_dir}"
jupyter nbconvert --to script "{run_file_name}"
python "{run_file_py}"
'''
                else:
                    run_block = f'''
cd "{remote_example_dir}"
python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")

        activation_block = f'''
cd "{spack_path}"
source "{spack_path}/scripts/activate.sh"
'''
        body = activation_block + "\n" + run_block

    else:
        container_root = f"{remote_base_abs.rstrip('/')}/{tag}/ICESEE-Containers"
        container_dir = f"{container_root}/spack-managed/combined-container"
        sif_path = f"{container_dir}/combined-env.sif"
        def_path = f"{container_dir}/combined-env-inbuilt-matlab.def"

        container_setup = f'''
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

container_root="{container_root}"
container_dir="{container_dir}"
sif_path="{sif_path}"
def_path="{def_path}"

mkdir -p "{remote_base_abs.rstrip('/')}/{tag}"

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
'''

        if test_mode:
            if model == "issm":
                run_block = f'''
mkdir -p "{remote_exec_dir}"
srun --mpi=pmix -n {slurm_ntasks} apptainer exec \
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"
'''
            elif model == "icepack":
                run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec \
-B "{remote_example_dir}":/workspace/example,"{remote_exec_dir}":/workspace/run \
"{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")
        else:
            if model == "issm":
                target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
                run_block = f'''
mkdir -p "{remote_exec_dir}"
srun --mpi=pmix -n {slurm_ntasks} apptainer exec \
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); run('{target_m}'); exit"
'''
            elif model == "icepack":
                if run_file_name.endswith(".py"):
                    run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec \
-B "{remote_example_dir}":/workspace/example,"{remote_exec_dir}":/workspace/run \
"{sif_path}" with-icepack bash -lc 'cd /workspace/example && python "{run_file_name}"'
'''
                elif run_file_name.endswith(".ipynb"):
                    run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec \
-B "{remote_example_dir}":/workspace/example,"{remote_exec_dir}":/workspace/run \
"{sif_path}" with-icepack bash -lc 'cd /workspace/example && jupyter nbconvert --to script "{run_file_name}" && python "{run_file_py}"'
'''
                else:
                    run_block = f'''
mkdir -p "{remote_exec_dir}"
apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
            else:
                raise RuntimeError(f"Unsupported model: {model}")

        body = container_setup + "\n" + run_block

    # ---------------------------------------------------------
    # Render sbatch
    # ---------------------------------------------------------
    outfile = f"{remote_run_dir}/icesheets-%j.out"

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

cd "{remote_run_dir}"

echo "[icesheets] Host: $(hostname)"
echo "[icesheets] Date: $(date)"
echo "[icesheets] PWD : $(pwd)"
echo "[icesheets] Run dir: {remote_run_dir}"

{sanitize_multiline(remote_module_lines)}
{sanitize_multiline(remote_export_lines)}

{body}
"""

    messages.append("[remote] Writing slurm_run.sh, then sbatch...")

    import shlex
    encoded = base64.b64encode(slurm_text.encode("utf-8")).decode("ascii")

    remote_submit_script_q = shlex.quote(remote_submit_script)
    remote_run_dir_q = shlex.quote(remote_run_dir)
    encoded_q = shlex.quote(encoded)

    # Write the sbatch file using python -c instead of heredoc
    write_cmd = (
        "python3 -c "
        + shlex.quote(
            "import base64, pathlib; "
            f"p = pathlib.Path({remote_submit_script!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(base64.b64decode({encoded!r}).decode('utf-8'), encoding='utf-8'); "
            "print(str(p))"
        )
    )

    wres = ssh_run(host, user, port, write_cmd, timeout=60)
    if wres.returncode != 0:
        raise RuntimeError(
            "Failed to write remote sbatch script\n"
            f"STDOUT:\n{wres.stdout}\n\nSTDERR:\n{wres.stderr}"
        )
    if (wres.stdout or "").strip():
        messages.append(f"[remote] wrote script: {(wres.stdout or '').strip()}")

    verify_cmd = (
        f'test -f {remote_submit_script_q} && '
        f'echo FOUND && ls -lah {remote_submit_script_q} || '
        f'(echo MISSING && ls -lah {remote_run_dir_q} && exit 1)'
    )

    vres = ssh_run(host, user, port, verify_cmd, timeout=30)
    if vres.returncode != 0:
        raise RuntimeError(
            "Remote submit script was not found after write step\n"
            f"STDOUT:\n{vres.stdout}\n\nSTDERR:\n{vres.stderr}"
        )
    if (vres.stdout or "").strip():
        messages.append((vres.stdout or "").strip())

    submit_cmd = f"sbatch {remote_submit_script_q}"
    sres = ssh_run(host, user, port, submit_cmd, timeout=60)
    if sres.returncode != 0:
        raise RuntimeError(
            "Failed to submit remote sbatch script\n"
            f"STDOUT:\n{sres.stdout}\n\nSTDERR:\n{sres.stderr}"
        )

    stdout = (sres.stdout or "").strip()
    stderr = (sres.stderr or "").strip()

    if stdout:
        messages.append(stdout)
    if stderr:
        messages.append(stderr)

    jobid = None
    for line in stdout.splitlines():
        line = line.strip()
        if "Submitted batch job" in line:
            jobid = line.split()[-1]
            break

    if not jobid:
        raise RuntimeError(f"Could not parse job ID from sbatch output:\n{stdout}")

    messages.append("[remote] ✅ Submitted model-only slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {remote_run_dir}")

    return {
        "success": True,
        "jobid": jobid,
        "remote_dir": remote_run_dir,
        "log_file": f"{remote_run_dir}/icesheets-{jobid}.out" if jobid else None,
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
            "selected_example_path": None,
        }

        AUTO_TAIL = {
            "task": None,
            "running": False,
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
        ui_mode_dd = W.ToggleButtons(
            options=[("Basic", "basic"), ("Advanced", "advanced")],
            value="basic",
            layout=W.Layout(width="auto"),
        )
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
        example_picker = W.Dropdown(
            options=[],
            layout=W.Layout(width="100%"),
        )

        example_info = W.Textarea(
            value="",
            layout=W.Layout(width="100%", height="130px"),
            disabled=True,
        )
        example_dir = W.Text(value="", layout=W.Layout(width="100%"))
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
        advanced_action_dd = W.Dropdown(
            options=[
                ("Test environment", "test"),
                ("Run example", "run"),
                ("Deploy new example", "deploy"),
            ],
            value="run",
            layout=W.Layout(width="100%"),
        )

        file_picker = W.Dropdown(
            options=[],
            layout=W.Layout(width="100%"),
        )

        file_editor = W.Textarea(
            value="",
            layout=W.Layout(width="100%", height="280px"),
        )

        run_target = W.Combobox(
            placeholder="Select or type run target",
            options=[],
            ensure_option=False,
            layout=W.Layout(width="100%"),
        )

        save_file_btn = W.Button(
            description="Save file",
            icon="save",
            button_style="info",
        )

        new_example_name = W.Text(
            value="",
            placeholder="new example name",
            layout=W.Layout(width="100%"),
        )

        deploy_example_btn = W.Button(
            description="Implement new example",
            icon="copy",
            button_style="warning",
        )

        dataset_upload = W.FileUpload(
            accept="",
            multiple=True,
            layout=W.Layout(width="100%"),
        )

        upload_dataset_btn = W.Button(
            description="Upload datasets",
            icon="upload",
            button_style="info",
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

            run_file = selected_run_file()
            run_file_name = Path(run_file).name if run_file else ""
            run_file_py = Path(run_file_name).with_suffix(".py").name if run_file_name else ""

            # ---------------------------------------------------------
            # Default behavior when user has not explicitly chosen a run target
            # ---------------------------------------------------------
            if model == "issm":
                default_target = "runme.m"
            else:
                default_target = ""

            chosen_target = run_file_name or default_target

            # ---------------------------------------------------------
            # Spack backend
            # ---------------------------------------------------------
            if backend == "spack":
                if model == "issm":
                    if chosen_target.endswith(".m"):
                        return f'''
        cd "{example_path}"
        matlab -nodesktop -nosplash -r "run('{chosen_target}'); exit"
        '''
                    return f'''
        cd "{example_path}"
        matlab -nodesktop -nosplash -r "issmversion; exit"
        '''

                # icepack + spack
                if chosen_target.endswith(".py"):
                    return f'''
        cd "{example_path}"
        python "{chosen_target}"
        '''
                if chosen_target.endswith(".ipynb"):
                    return f'''
        cd "{example_path}"
        jupyter nbconvert --to script "{chosen_target}"
        python "{Path(chosen_target).with_suffix(".py").name}"
        '''
                return f'''
        cd "{example_path}"
        python -c "import icepack; print('Icepack import successful')"
        '''

            # ---------------------------------------------------------
            # Container backend
            # ---------------------------------------------------------
            remote_root = f"{expand_remote_home(remote_base_dir.value)}/{remote_tag.value}"
            container_dir = f"{remote_root}/ICESEE-Containers/spack-managed/combined-container"
            sif_path = f"{container_dir}/combined-env.sif"

            if model == "issm":
                if chosen_target.endswith(".m"):
                    return f"""
        # --- ISSM via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec \\
        -B "{example_path}":/opt/ISSM/examples,"{exec_path}":/opt/ISSM/execution \\
        "{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); run('{chosen_target}'); exit"
        """
                return f"""
        # --- ISSM via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec \\
        -B "{example_path}":/opt/ISSM/examples,"{exec_path}":/opt/ISSM/execution \\
        "{sif_path}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"
        """

            # icepack + container
            if chosen_target.endswith(".py"):
                return f"""
        # --- Icepack via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        apptainer exec \\
        -B "{example_path}":/workspace/example,"{exec_path}":/workspace/run \\
        "{sif_path}" with-icepack bash -lc 'cd /workspace/example && python "{chosen_target}"'
        """

            if chosen_target.endswith(".ipynb"):
                py_name = Path(chosen_target).with_suffix(".py").name
                return f"""
        # --- Icepack via ICESEE-Container ---
        mkdir -p "{example_path}" "{exec_path}"

        apptainer exec \\
        -B "{example_path}":/workspace/example,"{exec_path}":/workspace/run \\
        "{sif_path}" with-icepack bash -lc 'cd /workspace/example && jupyter nbconvert --to script "{chosen_target}" && python "{py_name}"'
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
        
        def refresh_example_picker(_=None):
            opts = examples_as_dropdown_options(model_dd.value)
            if not opts:
                example_picker.options = [("(no examples found)", "")]
                example_picker.value = ""
                example_info.value = "No native examples were discovered for this model."
                if ui_mode_dd.value == "basic":
                    example_dir.value = ""
                STATUS["selected_example_path"] = None
                update_summary()
                return

            example_picker.options = opts
            example_picker.value = opts[0][1]

        def apply_selected_example(_=None):
            selected = example_picker.value or ""
            STATUS["selected_example_path"] = selected or None

            ex = None
            if selected:
                ex = find_example_by_path(model_dd.value, selected)

            example_info.value = example_summary_text(ex)

            if selected:
                example_dir.value = selected

            refresh_file_picker()
            refresh_run_target_options()

            # reset auto-target when example changes
            run_target.value = ""
            auto_set_run_target()

            load_selected_file()
            update_summary()

        def build_model_command():
            backend = backend_dd.value
            model = model_dd.value
            run_file = selected_run_file()
            run_file_name = Path(run_file).name if run_file else ""

            if model == "issm":
                default_target = "runme.m"
            else:
                default_target = ""

            chosen_target = run_file_name or default_target

            if backend == "spack":
                if model == "issm":
                    if chosen_target.endswith(".m"):
                        return f'cd "{example_dir.value}" && matlab -nodesktop -nosplash -r "run(\'{chosen_target}\'); exit"'
                    return f'cd "{example_dir.value}" && matlab -nodesktop -nosplash -r "issmversion; exit"'

                if chosen_target.endswith(".py"):
                    return f'cd "{example_dir.value}" && python "{chosen_target}"'
                if chosen_target.endswith(".ipynb"):
                    py_name = Path(chosen_target).with_suffix(".py").name
                    return f'cd "{example_dir.value}" && jupyter nbconvert --to script "{chosen_target}" && python "{py_name}"'
                return f'cd "{example_dir.value}" && python -c "import icepack"'

            if model == "issm":
                if chosen_target.endswith(".m"):
                    return (
                        f'mkdir -p "{example_dir.value}" "{exec_dir.value}" && '
                        f'srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec '
                        f'-B "{example_dir.value}":/opt/ISSM/examples,"{exec_dir.value}":/opt/ISSM/execution '
                        f'"{image_uri.value}" with-issm matlab -nodesktop -nosplash -r "run(\'{chosen_target}\'); exit"'
                    )
                return (
                    f'mkdir -p "{example_dir.value}" "{exec_dir.value}" && '
                    f'srun --mpi=pmix -n {slurm_ntasks.value} apptainer exec '
                    f'-B "{example_dir.value}":/opt/ISSM/examples,"{exec_dir.value}":/opt/ISSM/execution '
                    f'"{image_uri.value}" with-issm matlab -nodesktop -nosplash -r "issmversion; exit"'
                )

            if chosen_target.endswith(".py"):
                return f'apptainer exec "{image_uri.value}" with-icepack python "{chosen_target}"'
            if chosen_target.endswith(".ipynb"):
                py_name = Path(chosen_target).with_suffix(".py").name
                return f'apptainer exec "{image_uri.value}" with-icepack bash -lc \'jupyter nbconvert --to script "{chosen_target}" && python "{py_name}"\''
            return f'apptainer exec "{image_uri.value}" with-icepack python -c "import icepack"'
        
        def list_editable_files(example_path: str) -> list[tuple[str, str]]:
            root = Path(example_path).expanduser()
            if not root.exists():
                return []

            allowed = {".m", ".py", ".ipynb", ".yaml", ".yml", ".sh", ".txt", ".md", ".json"}
            files = []

            if root.is_file():
                if root.suffix.lower() in allowed:
                    return [(root.name, str(root))]
                return []

            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix.lower() in allowed:
                    try:
                        rel = p.relative_to(root)
                        files.append((str(rel), str(p)))
                    except Exception:
                        files.append((p.name, str(p)))

            return files
        
        def refresh_file_picker(_=None):
            selected = example_dir.value.strip()
            files = list_editable_files(selected)

            if not files:
                file_picker.options = [("(no editable files found)", "")]
                file_picker.value = ""
                file_editor.value = ""
                return

            file_picker.options = files
            file_picker.value = files[0][1]

        def refresh_run_target_options(_=None):
            files = list_editable_files(example_dir.value.strip())
            opts = [Path(v).name for _, v in files if v]

            preferred = []
            others = []

            for name in opts:
                lower = name.lower()
                if lower == "runme.m":
                    preferred.append(name)
                elif lower.endswith(".m"):
                    preferred.append(name)
                elif lower.endswith(".py"):
                    preferred.append(name)
                elif lower.endswith(".ipynb"):
                    preferred.append(name)
                else:
                    others.append(name)

            final_opts = preferred + others
            run_target.options = final_opts

            current = (run_target.value or "").strip()
            if current and current in final_opts:
                return

            if "runme.m" in final_opts:
                run_target.value = "runme.m"
            elif final_opts:
                run_target.value = final_opts[0]
            else:
                run_target.value = ""
                
        def auto_set_run_target(_=None):
            current = (run_target.value or "").strip()
            if current:
                return

            opts = list(run_target.options or [])
            if not opts:
                run_target.value = ""
                return

            # best default preference
            for preferred in ("runme.m",):
                if preferred in opts:
                    run_target.value = preferred
                    return

            for name in opts:
                if name.endswith(".m"):
                    run_target.value = name
                    return

            for name in opts:
                if name.endswith(".py"):
                    run_target.value = name
                    return

            for name in opts:
                if name.endswith(".ipynb"):
                    run_target.value = name
                    return

            run_target.value = opts[0]

        def load_selected_file(_=None):
            selected_file = file_picker.value or ""
            if not selected_file:
                file_editor.value = ""
                return

            p = Path(selected_file).expanduser()
            if not p.exists() or not p.is_file():
                file_editor.value = ""
                return

            try:
                if p.suffix.lower() == ".ipynb":
                    py_path = p.with_suffix(".py")

                    try:
                        import nbformat
                        from nbconvert import PythonExporter

                        nb = nbformat.read(str(p), as_version=4)
                        exporter = PythonExporter()
                        py_source, _ = exporter.from_notebook_node(nb)
                        py_path.write_text(py_source, encoding="utf-8")
                        file_editor.value = py_source
                        return

                    except Exception as conv_err:
                        file_editor.value = (
                            f"[ERROR] Could not convert notebook to Python script:\n"
                            f"{type(conv_err).__name__}: {conv_err}"
                        )
                        return

                file_editor.value = p.read_text(encoding="utf-8")

            except UnicodeDecodeError:
                file_editor.value = "[Binary or non-text file cannot be displayed here.]"
            except Exception as e:
                file_editor.value = f"[ERROR] Could not read file: {type(e).__name__}: {e}"

        def save_selected_file(_=None):
            log_out.clear_output()
            selected_file = file_picker.value or ""

            if not selected_file:
                with log_out:
                    print("[advanced] No file selected.")
                return

            p = Path(selected_file).expanduser()

            try:
                if p.suffix.lower() == ".ipynb":
                    py_path = p.with_suffix(".py")
                    py_path.write_text(file_editor.value, encoding="utf-8")
                    with log_out:
                        print(f"[advanced] Saved converted script: {py_path}")
                    return

                p.write_text(file_editor.value, encoding="utf-8")
                with log_out:
                    print(f"[advanced] Saved: {p}")

            except Exception as e:
                with log_out:
                    print("[advanced][ERROR]", type(e).__name__, e)

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

            if target.endswith(".ipynb"):
                return f"{target} -> {Path(target).with_suffix('.py').name}"
            return target

        def deploy_current_example(_=None):
            log_out.clear_output()

            src = Path(example_dir.value).expanduser()
            new_name = new_example_name.value.strip()

            if not src.exists():
                with log_out:
                    print("[advanced][ERROR] Source example path does not exist.")
                return

            if not new_name:
                with log_out:
                    print("[advanced][ERROR] Provide a new example name first.")
                return

            try:
                if src.is_file():
                    dest = src.parent / new_name
                    if dest.suffix == "":
                        dest = dest.with_suffix(src.suffix)
                    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    dest = src.parent / new_name
                    if dest.exists():
                        with log_out:
                            print(f"[advanced][ERROR] Target already exists: {dest}")
                        return

                    import shutil
                    shutil.copytree(src, dest)

                with log_out:
                    print(f"[advanced] New example created: {dest}")

                # Refresh discovered examples after deployment
                refresh_example_picker()

            except Exception as e:
                with log_out:
                    print("[advanced][ERROR]", type(e).__name__, e)

        def current_example_root() -> Path | None:
            p = Path(example_dir.value).expanduser()
            if p.exists():
                return p if p.is_dir() else p.parent
            return None

        def save_uploaded_datasets(_=None):
            log_out.clear_output()

            root = current_example_root()
            if root is None:
                with log_out:
                    print("[upload][ERROR] Example directory is not available.")
                return

            if not dataset_upload.value:
                with log_out:
                    print("[upload] No files selected.")
                return

            target_dir = root / "_uploaded_datasets"
            target_dir.mkdir(parents=True, exist_ok=True)

            saved = 0

            try:
                value = dataset_upload.value

                # ipywidgets may expose tuple/dict depending on version
                if isinstance(value, dict):
                    items = value.items()
                else:
                    items = []
                    for item in value:
                        name = item.get("name", "uploaded_file")
                        items.append((name, item))

                for name, meta in items:
                    content = meta["content"] if isinstance(meta, dict) else meta.content
                    out_path = target_dir / name
                    with open(out_path, "wb") as f:
                        f.write(content)
                    saved += 1

                with log_out:
                    print(f"[upload] Saved {saved} file(s) to: {target_dir}")

            except Exception as e:
                with log_out:
                    print("[upload][ERROR]", type(e).__name__, e)

        def make_zip_from_dir(src_dir: Path, zip_path: Path):
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(src_dir.rglob("*")):
                    if p.is_file():
                        zf.write(p, arcname=p.relative_to(src_dir))

        def download_results_bundle(_=None):
            results_out.clear_output()

            root = current_example_root()
            if root is None:
                with results_out:
                    print("[download][ERROR] Example directory is not available.")
                return

            candidates = [
                root / "results",
                root / "_modelrun_datasets",
                root / "output",
            ]
            src = next((p for p in candidates if p.exists() and p.is_dir()), None)

            if src is None:
                with results_out:
                    print("[download] No results directory found.")
                return

            zip_path = root / "results_bundle.zip"
            try:
                make_zip_from_dir(src, zip_path)
                with results_out:
                    print(f"Created: {zip_path}")
                    display(FileLink(str(zip_path), result_html_prefix="Download: "))
            except Exception as e:
                with results_out:
                    print("[download][ERROR]", type(e).__name__, e)

        def download_figures_bundle(_=None):
            results_out.clear_output()

            root = current_example_root()
            if root is None:
                with results_out:
                    print("[download][ERROR] Example directory is not available.")
                return

            candidates = [
                root / "figures",
                root / "results" / "figures",
            ]
            src = next((p for p in candidates if p.exists() and p.is_dir()), None)

            if src is None:
                with results_out:
                    print("[download] No figures directory found.")
                return

            zip_path = root / "figures_bundle.zip"
            try:
                make_zip_from_dir(src, zip_path)
                with results_out:
                    print(f"Created: {zip_path}")
                    display(FileLink(str(zip_path), result_html_prefix="Download: "))
            except Exception as e:
                with results_out:
                    print("[download][ERROR]", type(e).__name__, e)

        def maybe_seed_run_target_from_file(_=None):
            current = (run_target.value or "").strip()
            selected_file = file_picker.value or ""
            if current or not selected_file:
                return

            run_target.value = Path(selected_file).name

        # =========================================================
        # Dynamic logic
        # =========================================================
        def update_visibility(_=None):
            is_container = backend_dd.value == "container"
            is_remote = mode_dd.value == "remote"
            is_cloud = mode_dd.value == "cloud"
            is_basic = ui_mode_dd.value == "basic"
            is_advanced = ui_mode_dd.value == "advanced"

            container_source_row.layout.display = "" if is_container else "none"
            image_uri_row.layout.display = "" if is_container else "none"

            remote_box.layout.display = "" if is_remote else "none"
            cloud_box.layout.display = "" if is_cloud else "none"

            remote_actions.layout.display = "" if is_remote else "none"
            cloud_actions.layout.display = "" if is_cloud else "none"

            example_picker_row.layout.display = ""
            example_info_row.layout.display = ""

            example_row.layout.display = "none" if is_basic else ""
            exec_row.layout.display = ""

            advanced_action_row.layout.display = "" if is_advanced else "none"
            file_picker_row.layout.display = "" 
            file_editor_row.layout.display = "" if is_advanced else "none"
            run_target_row.layout.display = "" 
            advanced_buttons_row.layout.display = "" if is_advanced else "none"
            new_example_row.layout.display = "" if is_advanced else "none"
            dataset_upload_row.layout.display = "" if is_advanced else "none"
            download_buttons_row.layout.display = ""

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
                source_name = "Docker Hub" if container_source.value == "docker" else "AWS Registry"
                exec_note = (
                    "Create host-side example and execution folders, then bind them into "
                    "the combined ICESEE container before launching the selected model."
                )

                summary_html.value = f"""
                <div class="icesee-summary">
                  <div><span class="icesee-summary-k">User mode:</span> {user_mode.title()}</div>
                  <div><span class="icesee-summary-k">Execution mode:</span> {mode.title()}</div>
                  <div><span class="icesee-summary-k">Backend:</span> ICESEE-Container</div>
                  <div><span class="icesee-summary-k">Model:</span> {model.upper()}</div>
                  {selected_line}
                  <div><span class="icesee-summary-k">Image source:</span> {source_name}</div>
                  <div><span class="icesee-summary-k">Image:</span> {image_uri.value}</div>
                  <div><span class="icesee-summary-k">Execution:</span> {exec_note}</div>
                </div>
                """

            # run_target.value = compute_run_target_text()
            command_preview.value = build_model_command()

        backend_dd.observe(update_visibility, names="value")
        model_dd.observe(refresh_example_picker, names="value")
        model_dd.observe(update_summary, names="value")
        mode_dd.observe(update_visibility, names="value")
        ui_mode_dd.observe(update_visibility, names="value")
        ui_mode_dd.observe(apply_selected_example, names="value")
        container_source.observe(update_summary, names="value")
        image_uri.observe(update_summary, names="value")
        example_dir.observe(update_summary, names="value")
        example_dir.observe(refresh_file_picker, names="value")
        exec_dir.observe(update_summary, names="value")
        slurm_ntasks.observe(update_summary, names="value")
        example_picker.observe(apply_selected_example, names="value")
        file_picker.observe(load_selected_file, names="value")
        # run_target.observe(update_summary, names="value")
        file_picker.observe(maybe_seed_run_target_from_file, names="value")
        

        # =========================================================
        # Actions
        # =========================================================
        run_btn = W.Button(description="Submit job", button_style="success", icon="play")
        clear_btn = W.Button(description="Clear", icon="trash")
        status_chip = W.HTML(status_html("idle"))

        def on_run(_=None):
            log_out.clear_output()
            status_chip.value = status_html("running")

            action = advanced_action_dd.value
            mode = mode_dd.value

            # ----------------------------------------
            # DEPLOY
            # ----------------------------------------
            if ui_mode_dd.value == "advanced" and action == "deploy":
                deploy_current_example()
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
                    test_mode=test_mode,
                    run_file=selected_run_file(),
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

            rdir = normalize_remote_path(STATUS.get("remote_dir") or "")
            jobid = STATUS.get("jobid")

            if not rdir or not jobid:
                status_chip.value = status_html("fail")
                with log_out:
                    print("[remote] No remote_dir / JobID yet. Submit first.")
                return

            log_file = STATUS.get("log_file") or f"{rdir}/icesheets-{jobid}.out"
            log_file = normalize_remote_path(log_file)

            host = cluster_host.value.strip()
            user = cluster_user.value.strip()
            port = int(cluster_port.value)

            tail_cmd = f"""
set -e
log_file="{log_file}"
run_dir="{rdir}"

echo "[remote] checking run dir: $run_dir"
if [ -d "$run_dir" ]; then
    echo "[remote] run dir exists"
else
    echo "[remote] run dir missing"
fi

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



        async def auto_tail_worker():
            loop = asyncio.get_running_loop()

            while AUTO_TAIL["running"]:
                try:
                    # run blocking on_tail in a thread (non-blocking for asyncio)
                    await loop.run_in_executor(None, on_tail, None)

                except Exception as e:
                    with log_out:
                        print("[auto-tail][ERROR]", type(e).__name__, e)

                await asyncio.sleep(5)

        def on_auto_tail_change(change):
            if change["name"] != "value":
                return

            if change["new"]:
                AUTO_TAIL["running"] = True
                auto_tail_btn.description = "Stop auto tail"
                auto_tail_btn.button_style = "warning"

                AUTO_TAIL["task"] = asyncio.create_task(auto_tail_worker())

            else:
                AUTO_TAIL["running"] = False
                auto_tail_btn.description = "Auto tail"
                auto_tail_btn.button_style = "info"

                task = AUTO_TAIL.get("task")
                if task is not None:
                    task.cancel()
                    AUTO_TAIL["task"] = None

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
        # auto_tail_btn.on_click(on_auto_tail_click)
        terminate_btn.on_click(on_terminate)
        cloud_status_btn.on_click(on_cloud_status)
        cloud_logs_btn.on_click(on_cloud_logs)
        save_file_btn.on_click(save_selected_file)
        deploy_example_btn.on_click(deploy_current_example)
        upload_dataset_btn.on_click(save_uploaded_datasets)
        results_download_btn.on_click(download_results_bundle)
        figures_download_btn.on_click(download_figures_bundle)

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
        file_picker_row = form_row("Files:", file_picker)
        file_editor_row = form_row("Editor:", file_editor)
        run_target_row = form_row("Run target:", run_target)
        new_example_row = form_row("New name:", new_example_name)
        dataset_upload_row = form_row("Datasets:", dataset_upload)
        container_source_row = form_row("Source:", container_source)
        image_uri_row = form_row("Image:", image_uri)

        # def form_pair(label: str, widget, label_width: str = "80px"):
        #     lbl = W.HTML(f"<div class='icesee-lbl'>{label}</div>")
        #     lbl.layout = W.Layout(width=label_width, min_width=label_width)
        #     return W.HBox([lbl, widget], layout=W.Layout(gap="10px", width="100%"))

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

        ssh_key_manager_box = W.Accordion(children=[ssh_key_manager])
        ssh_key_manager_box.set_title(0, "🔐 SSH Key Manager")
        ssh_key_manager_box.selected_index = None

        ssh_key_manager_box.layout = W.Layout(
            width="100%",
            border="1px solid rgba(0,0,0,.08)",
            border_radius="12px",
            margin="8px 0 4px 0"
        )

        advanced_buttons_row = W.HBox(
            [save_file_btn, deploy_example_btn, upload_dataset_btn],
            layout=W.Layout(gap="10px", flex_wrap="wrap"),
        )

        download_buttons_row = W.HBox(
            [results_download_btn, figures_download_btn],
            layout=W.Layout(
                gap="10px",
                justify_content="flex-end",
                align_items="center",
                width="100%",
                margin="10px 0 0 0",
            ),
        )
        remote_conn_inner = W.VBox([
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

        remote_box = W.VBox([
            # W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Remote connection</div>"),
            # cluster_host_row,
            # W.HBox([cluster_user_row, cluster_port_row], layout=W.Layout(gap="12px", width="100%")),
            # W.HBox([remote_base_dir_row, remote_tag_row], layout=W.Layout(gap="12px", width="100%")),
            remote_conn_box,


            # W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Authentication</div>"),
            # W.HBox([W.HTML("<div class='icesee-lbl'>Method:</div>"), auth_mode], layout=W.Layout(gap="10px")),
            # cluster_password,
            # bootstrap_btn,
            auth_box,

            # W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>SSH key manager</div>"),
            # ssh_key_manager,
            ssh_key_manager_box,

            # W.HTML("<div class='icesee-subtle' style='margin-top:12px;'>Slurm resources</div>"),
            # W.HBox([slurm_job_name_row, slurm_time_row], layout=W.Layout(gap="12px", width="100%")),
            # W.HBox([slurm_nodes_row, slurm_ntasks_row, slurm_tpn_row], layout=W.Layout(gap="12px", width="100%")),
            # W.HBox([slurm_part_row, slurm_mem_row], layout=W.Layout(gap="12px", width="100%")),
            # W.HBox([slurm_account_row, slurm_mail_row], layout=W.Layout(gap="12px", width="100%")),
            slurm_box,
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
            ui_mode_row,
            mode_row,
            backend_row,
            model_row,
            example_picker_row,
            example_info_row,
            example_row,
            exec_row,
            advanced_action_row,
            file_picker_row,
            file_editor_row,
            run_target_row,
            new_example_row,
            advanced_buttons_row,
            dataset_upload_row,
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
            download_buttons_row,
        ])

        right_card = W.VBox([right])
        right_card.add_class("icesee-card")
        right_card.add_class("icesee-right")

        row = W.HBox([left_card, right_card], layout=W.Layout(width="100%", gap="24px"))
        row.add_class("icesee-grid")

        auto_tail_btn.observe(on_auto_tail_change, names="value")

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
        refresh_example_picker()
        apply_selected_example()

        page = W.VBox([W.HTML(css), header, row, actions_card, back_link], layout=W.Layout(width="100%"))

        update_visibility()
        update_summary()

        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise