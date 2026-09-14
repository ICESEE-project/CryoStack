"""B3 (server side): the "SSH Key Manager" credential is namespaced by
resource + HPC username, not cluster name alone, and never silently adopts the
legacy shared key."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_jupyter_book.core.ssh_key_manager import (
    cluster_key_paths,
    cluster_setup_summary,
    legacy_cluster_key_paths,
    make_ssh_key_info,
)


def test_two_hpc_usernames_on_one_cluster_get_different_paths():
    a_priv, _ = cluster_key_paths("pace", "alice")
    b_priv, _ = cluster_key_paths("pace", "bob")
    assert a_priv != b_priv


def test_same_hpc_username_is_deterministic():
    p1, _ = cluster_key_paths("pace", "alice")
    p2, _ = cluster_key_paths("pace", "alice")
    assert p1 == p2


def test_key_info_uses_the_namespaced_path_not_the_legacy_one():
    info = make_ssh_key_info(cluster_id="pace", host="h.example.edu", user="alice")
    legacy_priv, _ = legacy_cluster_key_paths("pace")
    assert info.private_key != legacy_priv
    assert "cryostack" in str(info.private_key)


def test_summary_reports_a_legacy_key_without_adopting_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    legacy_dir = tmp_path / ".ssh"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "id_ed25519_icesee_pace").write_text("legacy-shared-key")
    (legacy_dir / "id_ed25519_icesee_pace.pub").write_text("ssh-ed25519 AAAA legacy")

    summary = cluster_setup_summary(cluster_id="pace", host="h.example.edu", user="alice")
    assert summary["legacy_shared_key_exists"] is True
    # the ACTIVE key is the new namespaced one, not the legacy file
    assert summary["private_key"] != summary["legacy_shared_key_path"]
    assert "cryostack" in summary["private_key"]
