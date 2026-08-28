from __future__ import annotations


def build_run_command(*, backend, target, example_dir, exec_dir, image_uri, ntasks) -> str:
    target = target or "runme.m"
    if backend == "spack":
        if target.endswith(".m"):
            return f'cd "{example_dir}" && matlab -nodesktop -nosplash -r "run(\'{target}\'); exit"'
        return f'cd "{example_dir}" && matlab -nodesktop -nosplash -r "issmversion; exit"'
    prefix = (
        f'mkdir -p "{example_dir}" "{exec_dir}" && '
        f'srun --mpi=pmix -n {ntasks} apptainer exec '
        f'-B "{example_dir}":/opt/ISSM/examples,"{exec_dir}":/opt/ISSM/execution '
        f'"{image_uri}" with-issm matlab -nodesktop -nosplash -r '
    )
    action = f'"run(\'{target}\'); exit"' if target.endswith(".m") else '"issmversion; exit"'
    return prefix + action


def build_activation_check() -> str:
    return "addpath([getenv('ISSM_DIR') '/bin'], [getenv('ISSM_DIR') '/lib']); issmversion; "


def order_run_targets(names):
    preferred = [name for name in names if name.lower().endswith((".m", ".py", ".ipynb"))]
    others = [name for name in names if not name.lower().endswith((".m", ".py", ".ipynb"))]
    return preferred + others


def choose_run_target(names):
    ordered = order_run_targets(names)
    if "runme.m" in ordered:
        return "runme.m"
    for suffix in (".m", ".py", ".ipynb"):
        for name in ordered:
            if name.endswith(suffix):
                return name
    return ordered[0] if ordered else ""
