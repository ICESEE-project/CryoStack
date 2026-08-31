"""Execution-level proof: a run-local ICESEE bound onto /opt/ICESEE wins.

The image ships an *editable* ICESEE install (a .pth pointing at /opt/ICESEE)
plus PYTHONPATH=/opt. This test simulates that layout and then a bind mount of
a run-local checkout over /opt/ICESEE, and shows a fresh Python resolves
``import ICESEE`` through the override -- not through any previously installed
copy.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _fake_image(root: Path, marker: str) -> tuple[Path, Path]:
    """Build opt/ + a venv-style site-packages that editable-installed ICESEE."""
    opt = root / "opt"
    (opt / "ICESEE").mkdir(parents=True)
    (opt / "ICESEE" / "__init__.py").write_text(
        f'MARKER = "{marker}"\n__version__ = "0.1.9"\n'
    )
    site = root / "venv-icesee" / "site-packages"
    site.mkdir(parents=True)
    # modern `pip install -e /opt/ICESEE` drops a .pth that puts /opt on sys.path
    (site / "__editable__.ICESEE-0.1.9.pth").write_text(str(opt) + "\n")
    return opt, site


def _import_icesee(opt: Path, site: Path) -> tuple[str, str]:
    code = textwrap.dedent(
        """
        import ICESEE
        print(ICESEE.MARKER)
        print(ICESEE.__file__)
        """
    )
    env = {
        "PYTHONPATH": f"{opt}:{site}",   # image sets PYTHONPATH=/opt
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    marker, path = out.stdout.strip().splitlines()
    return marker, path


def _bind_over(opt: Path, override_src: Path) -> None:
    """Emulate `apptainer exec -B <override_src>:/opt/ICESEE` (replace the dir)."""
    import shutil

    shutil.rmtree(opt / "ICESEE")
    shutil.copytree(override_src, opt / "ICESEE")


def test_baked_icesee_resolves_before_any_override(tmp_path):
    opt, site = _fake_image(tmp_path, marker="baked")
    marker, path = _import_icesee(opt, site)
    assert marker == "baked"
    assert path == str(opt / "ICESEE" / "__init__.py")


def test_run_local_override_bound_onto_opt_icesee_wins(tmp_path):
    opt, site = _fake_image(tmp_path, marker="baked")

    # a run-local checkout of a different commit
    override = tmp_path / "run" / ".stack" / "icesee"
    override.mkdir(parents=True)
    (override / "__init__.py").write_text(
        'MARKER = "override-f7bcd21260be"\n__version__ = "0.1.9+git"\n'
    )

    _bind_over(opt, override)

    marker, path = _import_icesee(opt, site)
    assert marker == "override-f7bcd21260be"          # the override executed
    assert path == str(opt / "ICESEE" / "__init__.py")  # via the bound path


def test_override_wins_even_with_a_stale_site_packages_copy(tmp_path):
    """PYTHONPATH=/opt is ahead of site-packages, so the bound override still wins."""
    opt, site = _fake_image(tmp_path, marker="baked")

    # a non-editable copy that must NOT shadow the override
    (site / "ICESEE").mkdir()
    (site / "ICESEE" / "__init__.py").write_text('MARKER = "stale-site-packages-copy"\n')

    override = tmp_path / "run" / ".stack" / "icesee"
    override.mkdir(parents=True)
    (override / "__init__.py").write_text('MARKER = "override-aced865c"\n')
    _bind_over(opt, override)

    marker, path = _import_icesee(opt, site)
    assert marker == "override-aced865c"
    assert path == str(opt / "ICESEE" / "__init__.py")
