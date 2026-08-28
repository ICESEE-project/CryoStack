from __future__ import annotations

from pathlib import Path

from icesee_jupyter_book.core.remote_runner import (
    connector_slurm_submit,
    connector_ssh,
    connector_stage_archive,
    remote_ensure_spack,
    remote_maybe_install_spack,
    resolve_remote_abs_path,
    sanitize_multiline,
    slurm_optional_lines,
    ssh_run,
)
from cryostack_src.models.issm.postprocess import (
    build_postprocess as build_issm_postprocess_script,
)
from cryostack_src.remote.runtime import expand_remote_home


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
