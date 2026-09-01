"""B3: AccessState + remote-identity verification + the Run gate.

    credential exists != access verified
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.remote.access_state import (
    AccessInputs,
    AccessState,
    classify_access_state,
    enforce_remote_access,
    run_blocked,
    verify_remote_identity,
)
from cryostack_src.resources.profiles import ComputeProfile, get_compute_profile

_ISHEETS = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_ISEE = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


class FakeBridge:
    """Duck-typed RemoteBridge: only check_backend is used."""

    def __init__(self, *, ok=True, stdout="alice\n", stderr="", rc=0, raises=None):
        self._r = {"ok": ok, "returncode": rc, "stdout": stdout, "stderr": stderr}
        self._raises = raises

    def check_backend(self, *, command, timeout=30):
        if self._raises:
            raise self._raises
        return dict(self._r)


# ── classify_access_state ──────────────────────────────────────────────
def test_incomplete_identity_blocks_first():
    assert classify_access_state(AccessInputs(hpc_username="", remote_directory="/x")) \
        == AccessState.IDENTITY_INCOMPLETE
    assert classify_access_state(AccessInputs(hpc_username="alice", remote_directory="")) \
        == AccessState.IDENTITY_INCOMPLETE


def test_connector_offline_is_a_prerequisite():
    i = AccessInputs(hpc_username="alice", remote_directory="/x",
                     access_mode="connector", connector_online=False)
    assert classify_access_state(i) == AccessState.PREREQUISITE_REQUIRED


def test_credential_exists_is_not_verified():
    i = AccessInputs(hpc_username="alice", remote_directory="/x", key_exists=True)
    assert classify_access_state(i) == AccessState.VERIFICATION_PENDING
    assert run_blocked(AccessState.VERIFICATION_PENDING)


def test_missing_key_and_portal_registration():
    base = dict(hpc_username="alice", remote_directory="/x", key_exists=False)
    assert classify_access_state(AccessInputs(**base)) == AccessState.CREDENTIAL_MISSING
    assert classify_access_state(AccessInputs(**base, key_registration_method="portal")) \
        == AccessState.PORTAL_REGISTRATION_REQUIRED


def test_verified_match_and_mismatch():
    ok = AccessInputs(hpc_username="alice", remote_directory="/x", verified_identity="alice")
    assert classify_access_state(ok) == AccessState.SSH_VERIFIED
    assert classify_access_state(
        AccessInputs(hpc_username="alice", remote_directory="/x",
                     verified_identity="alice", environment_ready=True)
    ) == AccessState.READY
    bad = AccessInputs(hpc_username="alice", remote_directory="/x", verified_identity="bob")
    assert classify_access_state(bad) == AccessState.IDENTITY_MISMATCH
    assert run_blocked(AccessState.IDENTITY_MISMATCH)


def test_verification_error_is_access_failed():
    i = AccessInputs(hpc_username="alice", remote_directory="/x",
                     verification_error="Permission denied (publickey)")
    assert classify_access_state(i) == AccessState.ACCESS_FAILED


# ── verify_remote_identity ────────────────────────────────────────────
def test_verify_matches_case_insensitively():
    v = verify_remote_identity(FakeBridge(stdout="Alice\n"),
                               verification_command="whoami", expected_username="alice")
    assert v.ok and v.remote_identity == "Alice" and not v.mismatch


def test_verify_detects_mismatch():
    v = verify_remote_identity(FakeBridge(stdout="root\n"),
                               verification_command="whoami", expected_username="alice")
    assert not v.ok and v.mismatch and v.remote_identity == "root" and v.expected == "alice"


def test_verify_reports_connection_failure():
    v = verify_remote_identity(FakeBridge(ok=False, rc=255, stderr="ssh: connect timed out"),
                               verification_command="whoami", expected_username="alice")
    assert not v.ok and not v.mismatch and "timed out" in v.error


def test_verify_handles_a_raising_bridge():
    v = verify_remote_identity(FakeBridge(raises=RuntimeError("No connector session")),
                               verification_command="whoami", expected_username="alice")
    assert not v.ok and "No connector session" in v.error


def test_verify_needs_an_expected_username():
    v = verify_remote_identity(FakeBridge(), verification_command="whoami", expected_username="  ")
    assert not v.ok and "no HPC username" in v.error


# ── enforce_remote_access -- the Run gate ─────────────────────────────
def _gate(bridge, **kw):
    kw.setdefault("profile", get_compute_profile("pace"))
    kw.setdefault("access_mode", "connector")
    kw.setdefault("resolved_mode", "connector")
    kw.setdefault("hpc_username", "alice")
    kw.setdefault("remote_directory", "~/scratch/alice")
    return enforce_remote_access(bridge, **kw)


def test_gate_passes_on_a_verified_matching_identity():
    r = _gate(FakeBridge(stdout="alice\n"))
    assert r.ok and r.state == AccessState.SSH_VERIFIED


def test_gate_blocks_on_identity_mismatch():
    r = _gate(FakeBridge(stdout="bkyanjo3\n"))
    assert not r.ok and r.state == AccessState.IDENTITY_MISMATCH
    assert any("BLOCKED" in m and "bkyanjo3" in m and "alice" in m for m in r.messages)


def test_gate_blocks_on_incomplete_config_without_touching_the_network():
    called = []

    class Spy(FakeBridge):
        def check_backend(self, **k):
            called.append(k)
            return super().check_backend(**k)

    r = enforce_remote_access(Spy(), profile=get_compute_profile("pace"),
                              access_mode="connector", resolved_mode="connector",
                              hpc_username="", remote_directory="")
    assert not r.ok and r.state == AccessState.IDENTITY_INCOMPLETE
    assert called == []


def test_gate_blocks_when_the_connector_is_offline():
    r = _gate(FakeBridge(), connector_online=False)
    assert not r.ok and r.state == AccessState.PREREQUISITE_REQUIRED


def test_gate_blocks_on_access_failure():
    r = _gate(FakeBridge(ok=False, rc=255, stderr="Permission denied (publickey)"))
    assert not r.ok and r.state == AccessState.ACCESS_FAILED


def test_direct_ssh_shared_trust_is_warned_but_not_blocked():
    r = _gate(FakeBridge(stdout="alice\n"), access_mode="direct", resolved_mode="direct")
    assert r.ok
    assert any("shared service-account" in w and "not per-user isolated" in w.lower()
               for w in r.warnings)


def test_direct_ssh_single_tenant_has_no_warning():
    prof = ComputeProfile(name="lab", direct_ssh_trust="single_tenant")
    r = _gate(FakeBridge(stdout="alice\n"), profile=prof,
              access_mode="direct", resolved_mode="direct")
    assert r.ok and r.warnings == []


# ── profile field ────────────────────────────────────────────────────
def test_profile_direct_ssh_trust_defaults_to_shared_and_is_validated():
    assert get_compute_profile("pace").direct_ssh_trust == "shared"
    assert get_compute_profile("frontera").direct_ssh_trust == "shared"
    with pytest.raises(ValueError):
        ComputeProfile(name="x", direct_ssh_trust="bogus")


# ── gateway wiring source guard ──────────────────────────────────────
@pytest.mark.parametrize("path", [_ISHEETS, _ISEE])
def test_both_gateways_enforce_the_access_gate_on_run_and_verify_on_test(path):
    src = path.read_text()
    assert "enforce_remote_access(" in src
    assert "verify_remote_identity(" in src
    assert "from cryostack_src.remote.access_state import" in src
