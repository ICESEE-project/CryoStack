from __future__ import annotations

import os
import io
import yaml
import subprocess
from pathlib import Path

from tornado.ioloop import PeriodicCallback

from IPython.display import HTML
import base64

import ipywidgets as W
from IPython.display import display

from icesee_jupyter_book.core.icesheet_examples import (
    examples_as_dropdown_options,
    find_example_by_path,
    example_summary_text,
)
from icesee_jupyter_book.core.remote_runner import (
    ssh_run,
    slurm_optional_lines,
    remote_ensure_spack,
    remote_maybe_install_spack,
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

from icesee_jupyter_book.ui.workspace_bridge import (
    WorkspaceBridge as WorkspacePersistenceBridge,
    load_workspace_bridge,
)

from cryostack_src.workspace import WorkspaceBridge, WorkspaceManager, build_workspace_logs

from icesee_jupyter_book.core.experiment_status import (
    experiment_update_from_job_status,
)


from cryostack_src.frontend.shared import (
    CRYOSTACK_FRONTEND_CSS,
)

from cryostack_src.frontend.cryolauncher.cloud_environment import (
    build_cloud_environment_card,
)
from cryostack_src.frontend.cryolauncher.cloud_runtime import (
    build_cloud_runtime_callbacks,
)
from cryostack_src.frontend.cryolauncher.remote_runtime import (
    build_remote_runtime_callbacks,
)
from cryostack_src.remote import RemoteBridge, expand_remote_home, normalize_remote_path
from cryostack_src.models import get_model_adapter

from cryostack_src.frontend.cryolauncher.panels import (
    build_logs_panel,
    build_results_panel,
    build_run_settings_panel,
    build_status_panel,
    build_runtime_panel,
    build_run_plan_panel,

)

from cryostack_src.frontend.cryolauncher.workspace import (
    build_run_details,
    build_workspace_explorer,
    build_workspace_toolbar,
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

def build_issm_md_config_script(md_config: dict) -> str:
    lines = [
        "disp('[ICESEE-GUI] Applying editable md configuration...');",
        "if ~exist('md','var')",
        "    disp('[ICESEE-GUI][WARN] md does not exist yet. Skipping md configuration.');",
        "    return;",
        "end",
    ]

    for key, item in (md_config or {}).items():
        key = str(key).strip()
        if not key:
            continue

        target = key if key.startswith("md.") else f"md.{key}"

        if isinstance(item, dict):
            raw_value = str(item.get("value", "")).strip()
            vtype = item.get("type", "string")
        else:
            raw_value = str(item).strip()
            vtype = "string"

        if vtype == "number":
            matlab_val = raw_value
        elif vtype == "bool":
            matlab_val = "true" if raw_value.lower() in {"true", "1", "yes", "on"} else "false"
        elif vtype == "expr":
            matlab_val = raw_value
        else:
            matlab_val = "'" + raw_value.replace("'", "''") + "'"

        lines.append("try")
        lines.append(f"    {target} = {matlab_val};")
        lines.append(f"    disp('[ICESEE-GUI] set {target} = {raw_value}');")
        lines.append("catch ME")
        lines.append(f"    disp(['[ICESEE-GUI][WARN] could not set {target}: ' ME.message]);")
        lines.append("end")

    return "\n".join(lines) + "\n"

def build_issm_postprocess_script() -> str:
    return r"""
disp('[ICESEE-GUI] Running ISSM postprocess...');

if ~exist('ICESEE_RUN_DIR', 'var') || isempty(ICESEE_RUN_DIR)
    ICESEE_RUN_DIR = pwd;
end

figdir   = fullfile(ICESEE_RUN_DIR, 'outputs', 'figures');
modeldir = fullfile(ICESEE_RUN_DIR, 'outputs', 'model');

if ~exist(figdir, 'dir'); mkdir(figdir); end
if ~exist(modeldir, 'dir'); mkdir(modeldir); end

if ~exist('md', 'var')
    disp('[ICESEE-GUI][WARN] Variable md does not exist. Nothing to postprocess.');
    return;
end

try
    save(fullfile(modeldir, 'md_final.mat'), 'md', '-v7.3');
    disp(['[ICESEE-GUI] Saved model: ' fullfile(modeldir, 'md_final.mat')]);
catch ME
    disp(['[ICESEE-GUI][WARN] Could not save md_final.mat: ' ME.message]);
end

try
    results = md.results;
catch ME
    disp(['[ICESEE-GUI][WARN] Could not access md.results: ' ME.message]);
    return;
end

if isempty(results)
    disp('[ICESEE-GUI][WARN] md.results is empty. Nothing to plot.');
    return;
end

try
    if isfield(results, 'StressbalanceSolution')
        sol = results.StressbalanceSolution;

        if isfield(sol, 'Vel')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Vel);
            title('Stressbalance velocity');
            saveas(f, fullfile(figdir, 'stressbalance_velocity.png'));
            close(f);
            disp('[ICESEE-GUI] Saved stressbalance_velocity.png');
        end

        if isfield(sol, 'Pressure')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Pressure);
            title('Stressbalance pressure');
            saveas(f, fullfile(figdir, 'stressbalance_pressure.png'));
            close(f);
            disp('[ICESEE-GUI] Saved stressbalance_pressure.png');
        end

        return;
    end

    if isfield(results, 'TransientSolution')
        sol = results.TransientSolution;
        last = sol(numel(sol));

        if isfield(last, 'Vel')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Vel);
            title('Final transient velocity');
            saveas(f, fullfile(figdir, 'transient_final_velocity.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_velocity.png');
        end

        if isfield(last, 'Thickness')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Thickness);
            title('Final transient thickness');
            saveas(f, fullfile(figdir, 'transient_final_thickness.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_thickness.png');
        end

        if isfield(last, 'Surface')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', last.Surface);
            title('Final transient surface');
            saveas(f, fullfile(figdir, 'transient_final_surface.png'));
            close(f);
            disp('[ICESEE-GUI] Saved transient_final_surface.png');
        end

        return;
    end

    if isfield(results, 'ThermalSolution')
        sol = results.ThermalSolution;

        if isfield(sol, 'Temperature')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Temperature);
            title('Thermal temperature');
            saveas(f, fullfile(figdir, 'thermal_temperature.png'));
            close(f);
            disp('[ICESEE-GUI] Saved thermal_temperature.png');
        end

        return;
    end

    if isfield(results, 'MasstransportSolution')
        sol = results.MasstransportSolution;

        if isfield(sol, 'Thickness')
            f = figure('Visible', 'off');
            plotmodel(md, 'data', sol.Thickness);
            title('Mass transport thickness');
            saveas(f, fullfile(figdir, 'masstransport_thickness.png'));
            close(f);
            disp('[ICESEE-GUI] Saved masstransport_thickness.png');
        end

        return;
    end

    disp('[ICESEE-GUI][WARN] Solver type not recognized.');
    disp(fieldnames(md.results));

catch ME
    disp(['[ICESEE-GUI][ERROR] Postprocess failed: ' ME.message]);
end
"""
    
def submit_remote_icesheets_via_connector(
    *,
    session_id: str,
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
    md_config: dict | None = None,
    cluster_name: str = "pace",
):
    import base64
    import shlex

    messages = []

    if not session_id:
        raise RuntimeError("Missing connector session ID.")

    if not host or not user:
        raise ValueError("Provide Host + User first.")

    # Resolve remote base through connector.
    remote_base_input = (remote_base_dir or "").strip() or "~/r-arobel3-0"

    resolve_cmd = f'python3 -c "import os; print(os.path.abspath(os.path.expanduser({remote_base_input!r})))"'
    rbase = connector_ssh(session_id, host, user, port, resolve_cmd, timeout=300, cluster_name=cluster_name)
    if not rbase.get("ok"):
        raise RuntimeError(f"Failed to resolve remote base dir:\n{rbase.get('stderr', '')}")

    remote_base_abs = (rbase.get("stdout") or "").strip().splitlines()[-1]
    tag = (remote_tag or "").strip() or "icesheets"

    remote_run_dir = f"{remote_base_abs.rstrip('/')}/{tag}/runs/{model}_{backend}"
    remote_submit_script = f"{remote_run_dir}/run_icesheets.sbatch"

    messages.append("[connector] Using local connector / VPN bridge")
    messages.append(f"[connector] Remote base dir : {remote_base_abs}")
    messages.append(f"[connector] Remote run dir  : {remote_run_dir}")

    account_line, mail_lines = slurm_optional_lines(
        slurm_account.strip(),
        slurm_mail.strip(),
    )

    run_file_name = Path(run_file).name if run_file else ""
    run_file_py = Path(run_file_name).with_suffix(".py").name if run_file_name else ""

    local_example_path = Path(example_dir).expanduser()
    if not local_example_path.exists():
        raise RuntimeError(f"Local example path does not exist: {local_example_path}")

    local_parent = str(local_example_path.resolve().parent)
    local_name = local_example_path.resolve().name

    # Clean and create remote run dir.
    clean_cmd = f'''
rm -rf "{remote_run_dir}"
mkdir -p "{remote_run_dir}"
'''
    cres = connector_ssh(session_id, host, user, port, clean_cmd, timeout=300, cluster_name=cluster_name)
    if not cres.get("ok"):
        raise RuntimeError(f"Failed to prepare remote run dir:\n{cres.get('stderr', '')}")

    # Upload example using connector-side rsync.
    local_upload_path = f"{local_parent}/{local_name}"
    up = connector_stage_archive(
        session_id,
        host,
        user,
        port,
        local_example_path,
        remote_run_dir,
        timeout=600,
    )

    if not up.get("ok"):
        raise RuntimeError(
            "Failed to copy local example to remote host through connector\n"
            f"FULL RESPONSE:\n{up}\n\n"
            f"STDOUT:\n{up.get('stdout','')}\n\n"
            f"STDERR:\n{up.get('stderr','')}"
        )

    remote_example_dir = f"{remote_run_dir}/{local_name}"
    remote_exec_dir = f"{remote_run_dir}/execution"

    messages.append(f"[connector] staged example dir: {remote_example_dir}")
    messages.append(f"[connector] staged exec dir   : {remote_exec_dir}")

    # Backend setup.
    spack_path = None

    if backend == "spack":
        if not spack_enable:
            raise RuntimeError("ICESEE-Spack backend requires spack_enable=True")

        spack_parent = remote_base_abs
        spack_name = spack_dirname.strip() or "ICESEE-Spack"
        repo = spack_repo_url.strip()
        spack_path = f"{spack_parent.rstrip('/')}/{spack_name}"

        ensure_cmd = f'''
set -e
mkdir -p "{spack_parent}"
if [ ! -d "{spack_path}" ]; then
    git clone "{repo}" "{spack_path}"
fi
test -f "{spack_path}/scripts/activate.sh"
echo "{spack_path}"
'''
        eres = connector_ssh(session_id, host, user, port, ensure_cmd, timeout=600, cluster_name=cluster_name)
        if not eres.get("ok"):
            raise RuntimeError(
                "Failed to ensure ICESEE-Spack on remote host through connector\n"
                f"STDOUT:\n{eres.get('stdout','')}\n\nSTDERR:\n{eres.get('stderr','')}"
            )

        messages.append("[connector] Spack backend enabled")
        messages.append(f"[connector] ICESEE-Spack path: {spack_path}")

        if spack_install_if_needed:
            install_flag = spack_install_mode or ""
            install_cmd = f'''
set -e
cd "{spack_path}"
bash ./install.sh {install_flag}
'''
            ires = connector_ssh(session_id, host, user, port, install_cmd, timeout=7200, cluster_name=cluster_name)
            if not ires.get("ok"):
                raise RuntimeError(
                    "Remote ICESEE-Spack install failed through connector\n"
                    f"STDOUT:\n{ires.get('stdout','')}\n\nSTDERR:\n{ires.get('stderr','')}"
                )

    elif backend == "container":
        messages.append("[connector] ICESEE-Container backend selected")
    else:
        raise RuntimeError(f"Unsupported backend: {backend}")

    # Write ISSM postprocess if needed.
    if model == "issm":
        postprocess_path = f"{remote_run_dir}/postprocess_icesee.m"
        postprocess_text = build_issm_postprocess_script()
        encoded_post = base64.b64encode(postprocess_text.encode("utf-8")).decode("ascii")

        write_post_cmd = (
            "python3 -c "
            + shlex.quote(
                "import base64, pathlib; "
                f"p = pathlib.Path({postprocess_path!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text(base64.b64decode({encoded_post!r}).decode('utf-8'), encoding='utf-8'); "
                "print(str(p))"
            )
        )

        pres = connector_ssh(session_id, host, user, port, write_post_cmd, timeout=60, cluster_name=cluster_name)
        if not pres.get("ok"):
            raise RuntimeError(
                "Failed to write ISSM postprocess script through connector\n"
                f"STDOUT:\n{pres.get('stdout','')}\n\nSTDERR:\n{pres.get('stderr','')}"
            )

        messages.append(f"[connector] wrote postprocess script: {postprocess_path}")

    # Build run block.
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
matlab -nodesktop -nosplash -r "{issm_matlab_setup} ICESEE_RUN_DIR='{remote_run_dir}'; run('{target_m}'); run('../postprocess_icesee.m'); exit"
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

        body = f'''
cd "{spack_path}"
source "{spack_path}/scripts/activate.sh"

{run_block}
'''

    else:
        container_root = f"{remote_base_abs.rstrip('/')}/{tag}/ICESEE-Containers"
        container_dir = f"{container_root}/spack-managed/combined-container"
        sif_path = f"{container_dir}/combined-env.sif"
        def_path = f"{container_dir}/combined-env-inbuilt-matlab.def"

        container_setup = f'''
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
    git clone https://github.com/ICESEE-project/ICESEE-Containers.git "$container_root"
fi

cd "$container_dir"

if [ ! -f "$sif_path" ]; then
    apptainer build combined-env.sif combined-env-inbuilt-matlab.def
fi
'''
        if model == "issm":
            target_m = run_file_name if run_file_name.endswith(".m") else "runme.m"
            run_block = f'''
mkdir -p "{remote_exec_dir}"
srun --mpi=pmix -n {slurm_ntasks} apptainer exec \
-B "{remote_example_dir}":/opt/ISSM/examples,"{remote_exec_dir}":/opt/ISSM/execution \
"{sif_path}" with-issm matlab -nodesktop -nosplash -r "cd('/opt/ISSM/examples'); run('{target_m}'); exit"
'''
        else:
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
apptainer exec "{sif_path}" with-icepack python -c "import icepack; print('Icepack import successful')"
'''
        body = container_setup + "\n" + run_block

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
mkdir -p outputs/model outputs/figures

echo "[icesheets] Host: $(hostname)"
echo "[icesheets] Date: $(date)"
echo "[icesheets] PWD : $(pwd)"
echo "[icesheets] Run dir: {remote_run_dir}"

{sanitize_multiline(remote_module_lines)}
{sanitize_multiline(remote_export_lines)}

{body}
"""

    encoded = base64.b64encode(slurm_text.encode("utf-8")).decode("ascii")

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

    wres = connector_ssh(session_id, host, user, port, write_cmd, timeout=60, cluster_name=cluster_name)
    if not wres.get("ok"):
        raise RuntimeError(
            "Failed to write remote sbatch script through connector\n"
            f"STDOUT:\n{wres.get('stdout','')}\n\nSTDERR:\n{wres.get('stderr','')}"
        )

    messages.append(f"[connector] wrote script: {remote_submit_script}")

    sres = connector_slurm_submit(
        session_id,
        host,
        user,
        port,
        remote_submit_script,
        timeout=60,
    )

    if not sres.get("ok") or not sres.get("submitted"):
        raise RuntimeError(
            "Failed to submit remote sbatch script through connector\n"
            f"STDOUT:\n{sres.get('stdout','')}\n\nSTDERR:\n{sres.get('stderr','')}"
        )

    jobid = sres["jobid"]

    messages.append("[connector] ✅ Submitted model-only slurm_run.sh")
    messages.append(f"  jobid : {jobid}")
    messages.append(f"  rdir  : {remote_run_dir}")

    return {
        "success": True,
        "jobid": jobid,
        "remote_dir": remote_run_dir,
        "log_file": f"{remote_run_dir}/icesheets-{jobid}.out",
        "spack_path": spack_path,
        "messages": messages,
    }

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
    md_config: dict | None = None,
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
    mkres = ssh_run(host, user, port, clean_cmd, timeout=300)

    # ---------------------------------------------------------
    # Stage local example to remote run dir
    # ---------------------------------------------------------
    local_example_path = Path(local_example_dir)
    if not local_example_path.exists():
        raise RuntimeError(f"Local example path does not exist: {local_example_path}")

    mkres = ssh_run(host, user, port, f'mkdir -p "{remote_run_dir}"', timeout=300)
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

    if model == "issm":
        import base64
        import shlex

        postprocess_path = f"{remote_run_dir}/postprocess_icesee.m"
        postprocess_text = build_issm_postprocess_script()
        encoded_post = base64.b64encode(postprocess_text.encode("utf-8")).decode("ascii")

        write_post_cmd = (
            "python3 -c "
            + shlex.quote(
                "import base64, pathlib; "
                f"p = pathlib.Path({postprocess_path!r}); "
                "p.parent.mkdir(parents=True, exist_ok=True); "
                f"p.write_text(base64.b64decode({encoded_post!r}).decode('utf-8'), encoding='utf-8'); "
                "print(str(p))"
            )
        )

        pres = ssh_run(host, user, port, write_post_cmd, timeout=60)
        if pres.returncode != 0:
            raise RuntimeError(
                "Failed to write ISSM postprocess script\n"
                f"STDOUT:\n{pres.stdout}\n\nSTDERR:\n{pres.stderr}"
            )

        messages.append(f"[remote] wrote postprocess script: {postprocess_path}")

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
matlab -nodesktop -nosplash -r "{issm_matlab_setup} ICESEE_RUN_DIR='{remote_run_dir}'; run('{target_m}'); run('../postprocess_icesee.m'); exit"
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
mkdir -p outputs/model outputs/figures # create expected output dirs

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

    vres = ssh_run(host, user, port, verify_cmd, timeout=60)
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

def build_default_md_fields(section: str) -> dict:
    """
    Fallback field map. This avoids missing sections, but still lets users
    add any field manually if a section is not pre-populated.
    """
    known = {
        "geometry": ["surface", "thickness", "base", "bed"],
        "mesh": ["x", "y", "elements", "numberofvertices", "numberofelements"],
        "mask": ["ice_levelset", "ocean_levelset"],
        "materials": ["rho_ice", "rho_water", "rheology_B", "rheology_n"],
        "friction": ["coefficient", "p", "q"],
        "stressbalance": ["restol", "reltol", "abstol", "maxiter", "requested_outputs"],
        "timestepping": ["start_time", "final_time", "time_step"],
        "transient": [
            "isstressbalance", "ismasstransport", "isthermal",
            "isgroundingline", "ismovingfront", "issmb",
        ],
        "cluster": ["np", "name", "login", "port"],
        "verbose": ["solution", "module", "processor", "convergence", "control", "qmu"],
        "smb": ["mass_balance"],
        "basalforcings": ["groundedice_melting_rate", "floatingice_melting_rate"],
        "initialization": ["vx", "vy", "vel", "pressure", "temperature"],
        "masstransport": ["spcthickness", "requested_outputs"],
        "thermal": ["spctemperature", "requested_outputs"],
        "groundingline": ["migration"],
        "flowequation": ["element_equation", "vertex_equation"],
        "settings": ["results_on_nodes", "io_gather", "lowmem"],
    }

    fields = known.get(section, [])
    return {
        f: {
            "label": f"{f}",
            "type": "expr",
            "default": f"md.{section}.{f}",
        }
        for f in fields
    }

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

        access_mode_dd = W.Dropdown(
            options=[
                ("Auto", "auto"),
                ("Direct SSH from server", "direct"),
                ("Local Connector / VPN bridge", "connector"),
            ],
            value="connector",
            layout=W.Layout(width="100%"),
        )

        save_file_btn = W.Button(
            description="Save file",
            icon="save",
            button_style="info",
        )

        deploy_example_btn = W.Button(
            description="Implement new example",
            icon="copy",
            button_style="warning",
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
        # -----------------------------
        cluster_host = W.Text(value="login-phoenix-rh9.pace.gatech.edu", layout=W.Layout(width="320px"))
        cluster_user = W.Text(value=os.environ.get("USER", ""), placeholder="username", layout=W.Layout(width="320px"))
        cluster_port = W.IntText(value=22, layout=W.Layout(width="120px"))
        # cluster_name_for_keys = W.Text(value="pace" , layout=W.Layout(width="320px"))
        cluster_name_for_keys = W.Text(value="pace", placeholder="e.g. pace, ub-ccr, frontera", layout=W.Layout(width="320px"))

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

        preview_results_btn = W.Button(
            description="Preview results",
            icon="eye",
            button_style="info",
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

        cloud_terminate_btn = W.Button(
            description="Terminate",
            icon="stop",
            button_style="danger",
        )

        ISSM_MD_SECTIONS = [
            "mesh", "mask", "geometry", "constants", "smb", "basalforcings",
            "materials", "damage", "friction", "flowequation", "timestepping",
            "initialization", "rifts", "solidearth", "dsl", "debug", "verbose",
            "settings", "toolkits", "cluster", "balancethickness",
            "stressbalance", "groundingline", "hydrology", "debris",
            "masstransport", "memmasstransport", "thermal", "steadystate",
            "transient", "levelset", "calving", "frontalforcings", "esa",
            "love", "sampling", "autodiff", "inversion", "qmu", "amr",
            "outputdefinition", "results", "radaroverlay", "miscellaneous",
            "stochasticforcing",
        ]

        ISSM_MD_FIELDS = {section: {} for section in ISSM_MD_SECTIONS}

        md_config_enabled = W.Checkbox(
            value=True,
            description="Apply md configuration before solve",
        )

        md_section_dd = W.Dropdown(
            options=ISSM_MD_SECTIONS,
            value="stressbalance",
            layout=W.Layout(width="100%"),
        )

        md_field_dd = W.Dropdown(
            options=[],
            layout=W.Layout(width="100%"),
        )

        md_value_text = W.Textarea(
            value="",
            placeholder="current/default value",
            layout=W.Layout(width="100%", height="70px"),
        )

        md_value_type_hidden = W.Text(
            value="string",
            layout=W.Layout(display="none"),
        )

        md_help = W.HTML("")

        add_md_override_btn = W.Button(
            description="Add md override",
            icon="plus",
            button_style="info",
        )

        clear_md_overrides_btn = W.Button(
            description="Clear overrides",
            icon="trash",
        )

        md_overrides = {}
        md_overrides_view = W.Textarea(
            value="No md overrides added yet.",
            disabled=True,
            layout=W.Layout(width="100%", height="120px"),
        )

        def current_cloud_bridge():
            return CloudBridge(
                provider="aws",
                region=(
                    aws_region.value.strip()
                    or "us-east-2"
                ),
                profile=(
                    aws_profile.value.strip()
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
                    collect_md_config()
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
                if SESSION.get("id") is None:
                    sess = create_session()
                    SESSION["id"] = sess["session_id"]
                    SESSION["ws_url"] = sess["ws_url"]

                    connector_setup_link.value = f"""
                    <a href="https://cryostack.eas.gatech.edu/connect/?session={SESSION['id']}"
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
                    Open ICESEE Connector Setup
                    </a>
                    """

                st = relay_check_status(SESSION["id"])

                relay_status.value = f"""
                <div style="
                    border:1px solid rgba(13,110,253,.18);
                    background:rgba(13,110,253,.06);
                    border-radius:12px;
                    padding:12px;
                    line-height:1.5;
                    margin:8px 0;
                ">
                <b>Connector session:</b> {SESSION["id"]}<br>
                <b>Status:</b> {"online" if st.get("online") else "waiting for connector"}<br>
                <b>WebSocket path:</b> {SESSION["ws_url"]}
                </div>
                """
                # is_online = st.get("online")

                # relay_status.value = f"""
                # <div style="
                #     border:1px solid {'rgba(25,135,84,.25)' if is_online else 'rgba(13,110,253,.18)'};
                #     background:{'rgba(25,135,84,.08)' if is_online else 'rgba(13,110,253,.06)'};
                #     border-radius:12px;
                #     padding:12px;
                #     line-height:1.55;
                #     margin:8px 0;
                # ">
                # <b>Connector session:</b> {SESSION["id"]}<br>
                # <b>Status:</b> {'online ✅' if is_online else 'waiting for connector'}<br>
                # <b>WebSocket path:</b> {SESSION["ws_url"]}
                # </div>
                # """

                with log_out:
                    print("[connector] Session ID:", SESSION["id"])
                    print("[connector] Status:", st)

            except Exception as e:
                relay_status.value = ""
                with log_out:
                    print("[connector][ERROR]", type(e).__name__, e)

        def refresh_md_field_dropdown(_=None):
            section = md_section_dd.value
            fields = ISSM_MD_FIELDS.get(section, {}) or build_default_md_fields(section)

            if not fields:
                md_field_dd.options = [("(custom field)", "__custom__")]
                md_field_dd.value = "__custom__"
                md_value_text.value = ""
                md_value_type_hidden.value = "string"
                md_help.value = "<div class='icesee-subtle'>No predefined fields yet. Use Advanced mode or add this section later.</div>"
                return

            opts = [(info["label"], name) for name, info in fields.items()]
            md_field_dd.options = opts
            md_field_dd.value = opts[0][1]
            refresh_md_value_from_field()


        def refresh_md_value_from_field(_=None):
            section = md_section_dd.value
            field = md_field_dd.value
            info = ISSM_MD_FIELDS.get(section, {}).get(field, {})

            md_value_text.value = str(info.get("default", ""))
            md_value_type_hidden.value = info.get("type", "string")

            label = info.get("label", field)
            md_help.value = f"<div class='icesee-subtle'><b>{section}.{field}</b>: {label}</div>"

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
            run_file = selected_run_file()
            run_file_name = Path(run_file).name if run_file else ""
            return get_model_adapter(model_dd.value).build_run_command(
                backend=backend,
                target=run_file_name,
                example_dir=example_dir.value,
                exec_dir=exec_dir.value,
                image_uri=image_uri.value,
                ntasks=slurm_ntasks.value,
            )
        
        workspace_manager = WorkspaceManager(
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

        def list_editable_files(example_path: str) -> list[tuple[str, str]]:
            return workspace_manager.list_editable_files(example_path)
        
        def refresh_file_picker(_=None):
            workspace_manager.refresh_files()

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
            workspace_manager.load_file()

        def save_selected_file(_=None):
            workspace_manager.save_file()

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
            destination = workspace_manager.clone_example(new_example_name.value.strip())
            if destination is not None:
                refresh_example_picker()

        def current_example_root() -> Path | None:
            return workspace_manager.example_root()

        def save_uploaded_datasets(_=None):
            workspace_manager.save_uploaded_datasets(dataset_upload.value)

        def maybe_seed_run_target_from_file(_=None):
            current = (run_target.value or "").strip()
            selected_file = file_picker.value or ""
            if current or not selected_file:
                return

            run_target.value = Path(selected_file).name

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

            container_source.layout.display = "" if is_container else "none"
            image_uri.layout.display = "" if is_container else "none"

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
            image_uri_row.layout.display = "" if is_container else "none"

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
            file_picker_row.layout.display = "" 
            file_editor_row.layout.display = "" if is_advanced else "none"
            run_target_row.layout.display = "" 
            advanced_buttons_row.layout.display = "" if is_advanced else "none"
            new_example_row.layout.display = "" if is_advanced else "none"
            dataset_upload_row.layout.display = "" if is_advanced else "none"
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
        md_section_dd.observe(refresh_md_field_dropdown, names="value")
        md_field_dd.observe(refresh_md_value_from_field, names="value")
        refresh_md_field_dropdown()
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
                        example_dir=example_dir.value,
                        exec_dir=exec_dir.value,
                        image_uri=image_uri.value,
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
                        md_config=collect_md_config(),
                        cluster_name=cluster_name_for_keys.value or "pace",
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
                        md_config=collect_md_config(),
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
        )
        on_test_remote = remote_runtime.check
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
        )
        on_cloud_status = cloud_runtime.status
        on_cloud_logs = cloud_runtime.logs
        on_cloud_terminate = cloud_runtime.terminate

        def refresh_md_overrides_view():
            if not md_overrides:
                md_overrides_view.value = "No md overrides added yet."
                return

            lines = []
            for k, item in md_overrides.items():
                lines.append(f"{k} = {item['value']}   ({item['type']})")
            md_overrides_view.value = "\n".join(lines)

        def add_md_override(_=None):
            section = (md_section_dd.value or "").strip()
            field = (md_field_dd.value or "").strip()
            value = (md_value_text.value or "").strip()
            vtype = md_value_type_hidden.value or "string"

            if not section or not field or field == "__custom__":
                md_overrides_view.value = "[ERROR] Select a valid md field."
                return

            key = f"{section}.{field}"
            md_overrides[key] = {
                "value": value,
                "type": vtype,
            }
            refresh_md_overrides_view()

        def current_workspace_state() -> dict:
            return {
                "model": model_dd.value,
                "backend": backend_dd.value,
                "execution_mode": mode_dd.value,
                "user_mode": ui_mode_dd.value,

                "example": (
                    example_picker.value or ""
                ),

                "example_directory": (
                    example_dir.value.strip()
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
                    "job_name": slurm_job_name.value,
                    "time": slurm_time.value,
                    "nodes": slurm_nodes.value,
                    "tasks": slurm_ntasks.value,
                    "tasks_per_node": slurm_tpn.value,
                    "partition": slurm_part.value,
                    "memory": slurm_mem.value,
                },

                "job": {
                    "job_id": STATUS.get("jobid"),
                    "remote_directory": (
                        STATUS.get("remote_dir")
                    ),
                    "log_file": (
                        STATUS.get("log_file")
                    ),
                },
            }

        def clear_md_overrides(_=None):
            md_overrides.clear()
            refresh_md_overrides_view()

        def collect_md_config() -> dict:
            if model_dd.value != "issm" or not md_config_enabled.value:
                return {}
            return dict(md_overrides)

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
        save_file_btn.on_click(save_selected_file)
        deploy_example_btn.on_click(deploy_current_example)
        upload_dataset_btn.on_click(save_uploaded_datasets)
        results_download_btn.on_click(workspace_manager.download_results)
        figures_download_btn.on_click(workspace_manager.download_figures)
        preview_results_btn.on_click(workspace_manager.preview_results)
        add_md_override_btn.on_click(add_md_override)
        clear_md_overrides_btn.on_click(clear_md_overrides)
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
        file_picker_row = form_row("Files:", file_picker)
        file_editor_row = form_row("Editor:", file_editor)
        run_target_row = form_row("Run target:", run_target)
        md_config_inner = W.VBox([
            md_config_enabled,
            form_row("md section:", md_section_dd),
            form_row("field:", md_field_dd),
            md_help,
            form_row("value:", md_value_text),
            md_value_type_hidden,
            W.HBox(
                [add_md_override_btn, clear_md_overrides_btn],
                layout=W.Layout(gap="10px", flex_wrap="wrap"),
            ),
            md_overrides_view,
        ], layout=W.Layout(gap="8px"))

        md_config_panel = W.Accordion(children=[md_config_inner])
        md_config_panel.set_title(0, "⚙️ Editable ISSM md configuration")
        # md_config_panel.selected_index = 0  # open by default
        new_example_row = form_row("New name:", new_example_name)
        dataset_upload_row = form_row("Datasets:", dataset_upload)
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

        advanced_buttons_row = W.HBox(
            [save_file_btn, deploy_example_btn, upload_dataset_btn],
            layout=W.Layout(gap="10px", flex_wrap="wrap"),
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
            spack_enable_row,
            spack_repo_row,
            spack_dir_row,
            spack_install_row,
            spack_install_mode_row,
            # spack_slurm_row,
            # spack_pmix_row,
        ], layout=W.Layout(gap="8px"))

        def _toggle_exec_backend_ui(_=None):
            is_container = backend_dd.value == "container"

            container_source_row.layout.display = "flex" if is_container else "none"
            image_uri_row.layout.display = "flex" if is_container else "none"

            spack_display = "none" if is_container else "flex"
            spack_box_display = "none" if is_container else "block"

            spack_enable_row.layout.display = spack_box_display
            spack_repo_row.layout.display = spack_display
            spack_dir_row.layout.display = spack_display
            spack_install_row.layout.display = spack_box_display
            spack_install_mode_row.layout.display = spack_display
            spack_slurm_row.layout.display = spack_display
            spack_pmix_row.layout.display = spack_display
        
        backend_dd.observe(_toggle_exec_backend_ui, names="value")
        _toggle_exec_backend_ui()

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

        output_workspace = build_run_details(
            log_output=log_out,
            results_output=results_out,
            download_controls=download_buttons_row,
            log_controls=log_runtime_controls,
        )

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
                file_picker_row,
                file_editor_row,
                run_target_row,
                md_config_panel,
                new_example_row,
                advanced_buttons_row,
                dataset_upload_row,
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

        update_visibility()
        update_summary()

        return page

    except Exception as e:
        import traceback
        print("ERROR:", e)
        traceback.print_exc()
        raise
