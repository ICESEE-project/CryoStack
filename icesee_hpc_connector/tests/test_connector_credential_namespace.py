"""B3 (connector side): the workstation SSH key is namespaced by resource +
HPC identity, not cluster name alone, and the legacy cluster-only key is never
read or adopted."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import icesee_hpc_connector.connector_core as cc


def test_namespace_differs_by_hpc_identity_not_just_cluster():
    a = cc._credential_namespace("pace", hpc_user="alice", host="login.example.edu")
    b = cc._credential_namespace("pace", hpc_user="bob", host="login.example.edu")
    assert a != b


def test_namespace_is_deterministic_and_safe():
    n1 = cc._credential_namespace("pace", hpc_user="alice", host="h")
    n2 = cc._credential_namespace("pace", hpc_user="alice", host="h")
    assert n1 == n2
    assert all(c.isalnum() or c == "-" for c in n1)


def test_ensure_local_ssh_key_uses_the_new_namespaced_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    priv, pub = cc.ensure_local_ssh_key("pace", hpc_user="alice", host="login.example.edu")
    assert Path(priv).is_file() and Path(pub).is_file()
    assert (tmp_path / ".ssh" / "cryostack") == Path(priv).parent
    # never the legacy cluster-only filename
    assert Path(priv).name != "id_ed25519_icesee_pace"


def test_two_hpc_identities_get_two_distinct_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    priv_a, _ = cc.ensure_local_ssh_key("pace", hpc_user="alice", host="h")
    priv_b, _ = cc.ensure_local_ssh_key("pace", hpc_user="bob", host="h")
    assert priv_a != priv_b
    assert Path(priv_a).is_file() and Path(priv_b).is_file()


def test_legacy_key_is_never_read_or_adopted(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    legacy_dir = tmp_path / ".ssh"
    legacy_dir.mkdir(parents=True)
    legacy_priv = legacy_dir / "id_ed25519_icesee_pace"
    legacy_priv.write_text("NOT-A-REAL-KEY-DO-NOT-USE")
    (legacy_dir / "id_ed25519_icesee_pace.pub").write_text("ssh-ed25519 AAAA... legacy")

    priv, _ = cc.ensure_local_ssh_key("pace", hpc_user="alice", host="h")
    assert Path(priv) != legacy_priv
    assert Path(priv).read_text() != "NOT-A-REAL-KEY-DO-NOT-USE"


def test_ssh_identity_args_namespaces_from_the_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    args_a = cc.ssh_identity_args({"cluster_name": "pace", "user": "alice", "host": "h"})
    args_b = cc.ssh_identity_args({"cluster_name": "pace", "user": "bob", "host": "h"})
    assert args_a[0] == "-i" and args_b[0] == "-i"
    assert args_a[1] != args_b[1]


def test_public_key_request_carries_hpc_identity_from_the_gateway():
    for path in (_REPO / "icesee_jupyter_book/ui/icesheets_gateway.py",
                 _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"):
        src = path.read_text()
        assert "connector_get_public_key(" in src
        assert "hpc_username=cluster_user.value.strip()" in src
