"""Performance pass: the Check SSH button reuses its connectivity probe's
`whoami` line for identity instead of a second remote round trip -- while the
Run gate still re-verifies fresh."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.remote.access_state import (
    can_reuse_connectivity_identity,
    identity_result_from_output,
    enforce_remote_access,
)
from cryostack_src.resources.profiles import ComputeProfile


def test_reuse_only_when_verification_command_is_whoami():
    assert can_reuse_connectivity_identity("whoami")
    assert can_reuse_connectivity_identity("")
    assert can_reuse_connectivity_identity("  WHOAMI ")
    assert not can_reuse_connectivity_identity("id -un")
    assert not can_reuse_connectivity_identity("cat /etc/id")


def test_identity_from_output_match_mismatch_and_blank():
    ok = identity_result_from_output(whoami_line="alice", expected_username="Alice")
    assert ok.ok and ok.remote_identity == "alice"

    bad = identity_result_from_output(whoami_line="root", expected_username="alice")
    assert bad.mismatch and not bad.ok

    blank = identity_result_from_output(whoami_line="", expected_username="alice")
    assert not blank.ok and not blank.mismatch  # unverified, not a mismatch

    no_user = identity_result_from_output(whoami_line="alice", expected_username="")
    assert not no_user.ok


class _SpyBridge:
    """Fails the test if the Run gate skips fresh verification."""

    def __init__(self):
        self.calls = 0

    def check_backend(self, *, command, timeout=30):
        self.calls += 1
        return {"ok": True, "returncode": 0, "stdout": "alice\n", "stderr": ""}


def test_run_gate_still_calls_the_bridge_fresh():
    bridge = _SpyBridge()
    profile = ComputeProfile(name="pace", verification_command="whoami", account_required=False)
    result = enforce_remote_access(
        bridge,
        profile=profile,
        access_mode="direct",
        resolved_mode="direct",
        hpc_username="alice",
        remote_directory="/scratch/alice",
    )
    assert bridge.calls == 1          # the gate re-verified, no reuse shortcut
    assert result.ok
