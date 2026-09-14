"""C7.1 -- the non-secret AWS connection record + per-user store."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect import (
    AWSConnection,
    AWSConnectionStore,
    account_id_from_role_arn,
    generate_external_id,
)
from cryostack_src.cloud.connect.external_id import external_id_belongs_to
from cryostack_src.cloud.connect.models import (
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_PENDING,
)
from cryostack_src.workspace.identity import WorkspaceUser

ROLE_B = "arn:aws:iam::774888247882:role/CryoStackExecutionRole"


def _user(uid: str) -> WorkspaceUser:
    return WorkspaceUser(user_id=uid, source="cryostack-auth")


def test_account_id_is_parsed_from_the_role_arn():
    assert account_id_from_role_arn(ROLE_B) == "774888247882"
    assert account_id_from_role_arn("not-an-arn") == ""


def test_external_id_is_unique_random_and_user_bound():
    u = _user("alice@example.org")
    a, b = generate_external_id(u), generate_external_id(u)
    assert a != b
    assert len(a) > 30
    assert external_id_belongs_to(a, u)
    assert not external_id_belongs_to(a, _user("mallory@example.org"))


def test_connection_transitions_never_mutate_in_place():
    conn = AWSConnection(connection_id="c1", external_id="x", region="us-east-2")
    assert conn.status == STATUS_PENDING

    with_role = conn.with_role(ROLE_B)
    assert conn.role_arn == "" and with_role.role_arn == ROLE_B

    ok = with_role.mark_connected(account_id="774888247882")
    assert ok.status == STATUS_CONNECTED and ok.is_connected and ok.verified_at

    bad = with_role.mark_error("nope")
    assert bad.status == STATUS_ERROR and not bad.is_connected


def test_store_round_trips_and_creates_pending_records(tmp_path):
    store = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    assert store.load() is None

    conn = store.create(region="us-east-2")
    assert conn.status == STATUS_PENDING
    assert conn.external_id and conn.connection_id
    assert store.load().connection_id == conn.connection_id

    verified = conn.with_role(ROLE_B).mark_connected(account_id="774888247882")
    store.save(verified)
    assert store.load().is_connected

    store.delete()
    assert store.load() is None


def test_store_path_is_scoped_to_the_user_safe_id(tmp_path):
    a = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    b = AWSConnectionStore(user=_user("bob"), workspace_root=tmp_path)
    assert a.path != b.path
    assert "users" in a.path.parts
    a.create(region="us-east-2")
    assert a.path.exists() and not b.path.exists()


def test_persisted_file_contains_no_secret_keys(tmp_path):
    store = AWSConnectionStore(user=_user("alice"), workspace_root=tmp_path)
    store.save(
        AWSConnection(
            connection_id="c1",
            external_id="cryostack:alice:xyz",
            region="us-east-2",
            role_arn=ROLE_B,
        ).mark_connected(account_id="774888247882")
    )
    text = store.path.read_text(encoding="utf-8").lower()
    for forbidden in ("secretaccesskey", "sessiontoken", "aws_access_key_id"):
        assert forbidden not in text
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data) <= set(AWSConnection.__dataclass_fields__)


def test_public_dict_hides_everything_for_a_foreign_connection():
    conn = AWSConnection(
        connection_id="c1", external_id="e1", region="us-east-2", role_arn=ROLE_B
    ).mark_connected(account_id="774888247882")
    own = conn.to_public_dict(own=True)
    foreign = conn.to_public_dict(own=False)
    assert own["role_arn"] == ROLE_B and own["external_id"] == "e1"
    assert "role_arn" not in foreign and "external_id" not in foreign
    assert "account_id" not in foreign
