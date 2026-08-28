from __future__ import annotations

from pathlib import Path


def build_run_command(*, backend, target, example_dir, exec_dir, image_uri, ntasks) -> str:
    if backend == "spack":
        if target.endswith(".py"):
            return f'cd "{example_dir}" && python "{target}"'
        if target.endswith(".ipynb"):
            python_name = Path(target).with_suffix(".py").name
            return f'cd "{example_dir}" && jupyter nbconvert --to script "{target}" && python "{python_name}"'
        return f'cd "{example_dir}" && python -c "import icepack"'
    if target.endswith(".py"):
        return f'apptainer exec "{image_uri}" with-icepack python "{target}"'
    if target.endswith(".ipynb"):
        python_name = Path(target).with_suffix(".py").name
        return f'apptainer exec "{image_uri}" with-icepack bash -lc \'jupyter nbconvert --to script "{target}" && python "{python_name}"\''
    return f'apptainer exec "{image_uri}" with-icepack python -c "import icepack"'


def build_activation_check() -> str:
    return 'python -c "import icepack; print(\'Icepack import successful\')"'


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
