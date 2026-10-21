"""Run provenance names the ICESEE commit from the external/ICESEE submodule."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core import provenance


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                           "protocol.file.allow=always", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_icesee_commit_comes_from_the_submodule(tmp_path, monkeypatch):
    icesee = tmp_path / "ICESEE"
    icesee.mkdir()
    _git(icesee, "init", "-q")
    (icesee / "pyproject.toml").write_text("[project]\nname='ICESEE'\n")
    _git(icesee, "add", ".")
    _git(icesee, "commit", "-q", "-m", "icesee")
    pin = _git(icesee, "rev-parse", "HEAD")

    repo = tmp_path / "CryoLauncher"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "submodule", "add", "-q", str(icesee), "external/ICESEE")
    _git(repo, "commit", "-q", "-m", "launcher")

    monkeypatch.setattr(provenance, "REPO", repo)
    monkeypatch.setattr(provenance, "_CODE_CACHE", {})
    code = provenance.code_versions()
    assert code["icesee"]["upstream_commit"] == pin == code["icesee"]["pinned_commit"]
    assert code["icesee"]["local_changes"] is False
    assert code["cryolauncher"]["local_changes"] is False

    (repo / "external" / "ICESEE" / "pyproject.toml").write_text("changed\n")
    monkeypatch.setattr(provenance, "_CODE_CACHE", {})
    code = provenance.code_versions()
    assert code["icesee"]["local_changes"] is True
    assert code["cryolauncher"]["local_changes"] is False  # reported on the ICESEE side
