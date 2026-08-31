from __future__ import annotations

from pathlib import Path

#: filenames that make a directory a runnable ISSM example
EXAMPLE_ENTRYPOINTS = ("runme.m",)


def example_runnable(path) -> bool:
    """A directory is a runnable ISSM example iff it has an entrypoint file."""
    root = Path(path)
    return root.is_dir() and any((root / e).is_file() for e in EXAMPLE_ENTRYPOINTS)


def example_template() -> dict[str, str]:
    """Minimal starter files for a new user ISSM example."""
    return {
        "runme.m": (
            "% New ISSM example -- scaffold created by CryoLauncher.\n"
            "% Build your mesh / parameters, then run the solver, e.g.:\n"
            "%\n"
            "%   md = model();\n"
            "%   md = triangle(md, 'DomainOutline.exp', 50000);\n"
            "%   md = setmask(md, 'all', '');\n"
            "%   md = parameterize(md, 'Square.par');\n"
            "%   md = setflowequation(md, 'SSA', 'all');\n"
            "%   md.cluster = generic('name', oshostname, 'np', 2);\n"
            "%   md = solve(md, 'Stressbalance');\n"
        ),
    }


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
