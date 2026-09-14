"""B2: per-resource user settings -- shape, hydration lifecycle, migration."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.workspace.resource_state import (
    PERSONAL_FIELDS,
    ResourceStateController,
    assert_no_secrets,
    blank_personal,
    migrate_legacy_state,
    normalize_resource_id,
    read_resource_settings,
    strip_secrets,
    write_resource_settings,
)


# ── a fake "gateway": personal widgets + a recording save channel ────────
class FakeGateway:
    def __init__(self, resource="pace"):
        self.personal = blank_personal()
        self.resource = resource
        self.saved: list[dict] = []
        self.stored: dict | None = None
        self.ctrl: ResourceStateController | None = None

    def controller(self, service_username=""):
        self.ctrl = ResourceStateController(
            load_state=lambda: self.stored,
            save_state=self.saved.append,
            read_personal=lambda: dict(self.personal),
            apply_personal=self.personal.update,
            resource_name=lambda: self.resource,
            set_resource_name=lambda n: setattr(self, "resource", n),
            service_username=service_username,
        )
        return self.ctrl

    def switch(self, new_name):
        """What the cluster-name widget observer does: value changes first,
        then the controller is told."""
        old = self.resource
        self.resource = new_name
        self.ctrl.switch_resource(old, new_name)


ALICE_PACE = {
    "hpc_username": "alice",
    "remote_directory": "/synthetic/alice",
    "account": "project-a",
    "email": "alice@example.test",
    "access_mode": "connector",
    "auth_mode": "key",
}


# ── cross-user isolation ───────────────────────────────────────────────
def test_user_b_sees_none_of_user_a_settings():
    a = FakeGateway()
    a.stored = None                      # A hasn't saved yet -> everyone blank
    ctrl_a = a.controller()
    ctrl_a.hydrate()
    a.personal.update(ALICE_PACE)
    ctrl_a.persist()
    saved_state = a.saved[-1]

    # B is a different gateway/kernel with its own (empty) store
    b = FakeGateway()
    b.stored = None
    ctrl_b = b.controller()
    warnings = ctrl_b.hydrate()

    assert b.personal == blank_personal()
    for v in ALICE_PACE.values():
        assert v not in b.personal.values()
    assert b.saved == []                 # loading blank never writes
    # A's own state round-trips
    a2 = FakeGateway()
    a2.stored = saved_state
    a2.controller().hydrate()
    assert a2.personal["hpc_username"] == "alice"
    assert a2.personal["account"] == "project-a"


# ── cross-resource isolation ──────────────────────────────────────────
def test_pace_settings_do_not_bleed_into_resource_b():
    g = FakeGateway(resource="pace")
    g.stored = None
    ctrl = g.controller()
    ctrl.hydrate()
    g.personal.update(ALICE_PACE)
    ctrl.persist()

    # switch to a different (custom) resource
    g.switch("univ-cluster")
    assert g.resource == "univ-cluster"
    assert g.personal == blank_personal()          # incoming resource -> blank

    # configure resource-B differently
    g.personal.update({"hpc_username": "a_on_b", "account": "grant-b"})
    ctrl.persist()

    # back to PACE -> Alice's PACE values, not resource-B's
    g.switch("pace")
    assert g.personal["hpc_username"] == "alice"
    assert g.personal["account"] == "project-a"

    state = ctrl.capture()
    pace_id = normalize_resource_id("pace")
    b_id = normalize_resource_id("univ-cluster")
    assert pace_id != b_id
    assert state["resources"][pace_id]["hpc_username"] == "alice"
    assert state["resources"][b_id]["hpc_username"] == "a_on_b"


def test_switch_never_copies_outgoing_values_into_incoming():
    g = FakeGateway(resource="pace")
    g.stored = None
    ctrl = g.controller()
    ctrl.hydrate()
    g.personal.update({"hpc_username": "alice", "account": "project-a"})
    g.switch("frontera")
    assert g.personal["hpc_username"] == ""
    assert g.personal["account"] == ""


# ── hydration race: no blank PUT before restore completes ─────────────
def test_hydration_does_not_persist_blank_over_stored_state():
    g = FakeGateway()
    g.stored = {
        "schema_version": 2, "selected_resource": "pace",
        "resources": {"pace": dict(ALICE_PACE)},
    }
    ctrl = g.controller()

    # a save observer that fires eagerly during build must be a no-op
    ctrl.persist()                       # phase still "building"
    assert g.saved == []

    ctrl.hydrate()
    assert g.saved == []                 # hydrate itself never writes
    assert g.personal["hpc_username"] == "alice"   # stored state survived intact
    assert g.personal["account"] == "project-a"


def test_applying_restored_fields_is_not_six_partial_saves():
    g = FakeGateway()
    g.stored = {
        "schema_version": 2, "selected_resource": "pace",
        "resources": {"pace": dict(ALICE_PACE)},
    }
    ctrl = g.controller()
    ctrl.hydrate()
    assert len(g.saved) == 0            # zero PUTs during a full restore
    # and a later explicit persist writes exactly one coherent state
    ctrl.persist()
    assert len(g.saved) == 1
    assert g.saved[0]["resources"]["pace"] == {k: ALICE_PACE[k] for k in PERSONAL_FIELDS}


# ── failed / missing GET -> blank, warn, no fallback ─────────────────
def test_failed_load_warns_and_leaves_personal_blank():
    g = FakeGateway()

    def _boom():
        raise RuntimeError("workspace API down")

    ctrl = ResourceStateController(
        load_state=_boom,
        save_state=g.saved.append,
        read_personal=lambda: dict(g.personal),
        apply_personal=g.personal.update,
        resource_name=lambda: "pace",
        service_username="svc-account",
    )
    warnings = ctrl.hydrate()
    assert warnings and "blank" in warnings[0].lower()
    assert g.personal == blank_personal()
    assert g.saved == []


def test_missing_row_is_indistinguishable_from_blank_and_never_falls_back():
    g = FakeGateway()
    g.stored = None
    ctrl = g.controller(service_username="svc-account")
    assert ctrl.hydrate() == []          # None-from-load is "no row", not an error
    assert g.personal == blank_personal()


# ── secret hygiene ────────────────────────────────────────────────────
def test_secrets_are_stripped_from_persisted_state():
    g = FakeGateway()
    g.stored = None
    ctrl = g.controller()
    ctrl.hydrate()
    g.personal.update(ALICE_PACE)
    # even if a caller tried to smuggle secrets into read_personal:
    ctrl._read_personal = lambda: {
        **ALICE_PACE,
        "bootstrap_password": "hunter2",
        "session_secret": "abc",
        "control_secret": "def",
        "private_key": "-----BEGIN-----",
        "matlab_license_value": "1711@x",
        "pairing_code": "AAAAA-BBBBB",
    }
    ctrl.persist()
    state = g.saved[-1]
    assert_no_secrets(state)
    blob = repr(state)
    for leak in ("hunter2", "BEGIN", "1711@x", "AAAAA-BBBBB"):
        assert leak not in blob


def test_strip_secrets_is_recursive():
    dirty = {"resources": {"pace": {"hpc_username": "a", "aws_secret_key": "x"}},
             "nested": [{"token": "t"}, {"ok": 1}]}
    clean = strip_secrets(dirty)
    assert clean["resources"]["pace"] == {"hpc_username": "a"}
    assert clean["nested"] == [{}, {"ok": 1}]
    assert_no_secrets(clean)


# ── legacy migration ─────────────────────────────────────────────────
def test_v1_state_migrates_without_crashing_and_drops_developer_defaults():
    legacy = {
        "model": "issm", "backend": "spack", "execution_mode": "remote",
        "access_mode": "connector",
        "cluster": {"name": "pace", "host": "login-phoenix-rh9.pace.gatech.edu", "port": 22},
        "slurm": {"job_name": "ICESHEETS", "time": "04:00:00", "nodes": 1,
                  "tasks": 8, "tasks_per_node": 8, "partition": "cpu-large",
                  "memory": "64G",
                  # hand-crafted hostile values that must NOT be canonised:
                  "account": "gts-arobel3-atlas"},
        "job": {"job_id": "123"},
    }
    v2 = migrate_legacy_state(legacy, service_username="bkyanjo3")
    assert v2["schema_version"] == 2
    pace = normalize_resource_id("pace")
    entry = v2.get("resources", {}).get(pace, {})
    assert entry.get("access_mode") == "connector"
    # no developer allocation, no dev host, no personal fields invented
    blob = repr(v2)
    for bad in ("gts-arobel3-atlas", "r-arobel3-0", "login-phoenix"):
        assert bad not in blob
    assert "account" not in entry or entry["account"] == ""
    assert "hpc_username" not in entry


def test_v1_custom_resource_keeps_user_host_but_not_dev_host():
    legacy = {"access_mode": "direct",
              "cluster": {"name": "my-lab", "host": "hpc.lab.univ.edu", "port": 2222}}
    v2 = migrate_legacy_state(legacy)
    rid = normalize_resource_id("my-lab")
    assert v2["resources"][rid]["custom_login_host"] == "hpc.lab.univ.edu"
    assert v2["resources"][rid]["custom_ssh_port"] == 2222

    legacy_dev = {"cluster": {"name": "my-lab", "host": "login-phoenix-rh9.pace.gatech.edu"}}
    v2b = migrate_legacy_state(legacy_dev)
    assert "custom_login_host" not in v2b["resources"].get(normalize_resource_id("my-lab"), {})


def test_v2_state_passthrough_still_sanitised():
    v2 = {"schema_version": 2, "selected_resource": "pace",
          "resources": {"pace": {"hpc_username": "alice", "account": "gts-arobel3-atlas",
                                 "bootstrap_password": "x"}}}
    out = migrate_legacy_state(v2, service_username="bkyanjo3")
    assert out["resources"]["pace"]["hpc_username"] == "alice"
    assert out["resources"]["pace"]["account"] == ""          # dev default scrubbed
    assert_no_secrets(out)


def test_empty_and_garbage_state_is_safe():
    for bad in (None, {}, [], "nope", 42):
        v2 = migrate_legacy_state(bad)  # type: ignore[arg-type]
        assert v2["schema_version"] == 2
        assert v2["resources"] == {}


# ── resource id normalisation ────────────────────────────────────────
def test_resource_id_is_stable_and_safe():
    assert normalize_resource_id("PACE") == "pace"
    assert normalize_resource_id("phoenix") == "pace"        # alias collapses
    assert normalize_resource_id("  ") == ""
    rid = normalize_resource_id("hpc.lab.univ.edu/alice")
    assert rid.startswith("custom-")
    assert "/" not in rid and " " not in rid
    assert normalize_resource_id("hpc.lab.univ.edu/alice") == rid   # deterministic


def test_read_resource_settings_returns_blanks_for_unknown_entry():
    assert read_resource_settings({}, "pace") == blank_personal()
    assert read_resource_settings({"resources": {"pace": {"hpc_username": "a"}}}, "pace")["hpc_username"] == "a"
    assert read_resource_settings({"resources": {"pace": {"hpc_username": "a"}}}, "pace")["account"] == ""
