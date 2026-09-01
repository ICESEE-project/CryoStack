"""B3: user x resource x HPC-identity SSH credential namespace (server side)."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.remote.ssh_identity import (
    credential_namespace,
    cryostack_key_paths,
    legacy_cluster_key_paths,
)


def test_different_users_on_the_same_resource_get_different_namespaces():
    a = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice")
    b = credential_namespace(cryostack_user_id="user-b", resource_id="pace", hpc_username="alice")
    assert a != b


def test_different_resources_for_the_same_user_get_different_namespaces():
    pace = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice")
    other = credential_namespace(cryostack_user_id="user-a", resource_id="ub-ccr", hpc_username="alice")
    assert pace != other


def test_different_hpc_identities_get_different_namespaces_even_same_cryostack_user():
    n1 = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice")
    n2 = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice2")
    assert n1 != n2


def test_namespace_is_deterministic():
    n1 = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice")
    n2 = credential_namespace(cryostack_user_id="user-a", resource_id="pace", hpc_username="alice")
    assert n1 == n2


def test_namespace_never_embeds_a_raw_unsanitised_string():
    ns = credential_namespace(cryostack_user_id="user a/../weird!", resource_id="pace",
                              hpc_username="al ice;rm -rf")
    assert all(c.isalnum() or c == "-" for c in ns)
    assert "/" not in ns and " " not in ns and ";" not in ns


def test_no_identity_dimensions_is_unscoped_not_empty():
    assert credential_namespace() == "unscoped"


def test_key_paths_live_under_a_dedicated_cryostack_subdir(tmp_path):
    priv, pub = cryostack_key_paths("some-namespace", ssh_dir=tmp_path)
    assert priv.parent == tmp_path
    assert pub == priv.with_suffix(priv.suffix + ".pub") or str(pub) == str(priv) + ".pub"
    assert "some-namespace" in priv.name


def test_legacy_path_is_the_old_cluster_only_scheme(tmp_path):
    priv, _pub = legacy_cluster_key_paths("PACE", ssh_dir=tmp_path)
    assert priv.name == "id_ed25519_icesee_pace"
