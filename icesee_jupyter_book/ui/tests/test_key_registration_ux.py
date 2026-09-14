"""Pre-release Connector/HPC-access polish: a first-use SSH-key registration
failure (B3 namespaced key not yet authorized on the resource) must become an
actionable state, and a successful password bootstrap must re-check access."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GATEWAYS = [
    _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py",
    _REPO / "icesee_jupyter_book/ui/icesee_gateway.py",
]


@pytest.mark.parametrize("path", _GATEWAYS)
def test_check_ssh_classifies_failures_and_only_pubkey_maps_to_registration(path):
    src = path.read_text()
    assert "classify_ssh_failure(" in src
    assert "SSH_KEY_NOT_AUTHORIZED" in src
    assert "set_key_unregistered(" in src
    # a non-pubkey failure must stay a generic Failed, never "key not registered"
    assert 'set_status("failed")' in src


@pytest.mark.parametrize("path", _GATEWAYS)
def test_successful_bootstrap_reruns_the_ssh_check_and_clears_the_password(path):
    src = path.read_text()
    assert 'cluster_password.value = ""' in src
    # re-verify after a successful bootstrap without a second manual click
    assert ("on_test_remote(None)" in src) or ("run_example_remote_test()" in src)


@pytest.mark.parametrize("path", _GATEWAYS)
def test_bootstrap_button_has_immediate_state_and_a_finally_reenable(path):
    src = path.read_text()
    lo = src.index("def on_bootstrap_keys")
    hi = src.index("def ", lo + 10)
    body = src[lo:hi]
    assert "bootstrap_btn.disabled = True" in body
    assert 'set_bootstrap_state("registering")' in src or '_bootstrap_panel("registering")' in body
    assert "finally:" in body
    assert "bootstrap_btn.disabled = False" in body
    # the connector reason is consulted, not just result["ok"]
    assert "classify_bootstrap_result(" in body


@pytest.mark.parametrize("path", _GATEWAYS)
def test_bootstrap_password_is_cleared_on_every_path(path):
    src = path.read_text()
    lo = src.index("def on_bootstrap_keys")
    hi = src.index("def ", lo + 10)
    body = src[lo:hi]
    # cleared right after the call returns AND in finally
    assert body.count('cluster_password.value = ""') >= 2


@pytest.mark.parametrize("path", _GATEWAYS)
def test_bootstrap_is_not_auto_triggered_just_because_ssh_failed(path):
    src = path.read_text()
    # the only bootstrap entry points are the explicit button / auth toggle
    assert "bootstrap_btn.on_click(on_bootstrap_keys)" in src
    # set_key_unregistered must not itself call the bootstrap function
    lo = src.index("set_key_unregistered(")
    window = src[lo - 400: lo + 400]
    assert "bootstrap_passwordless_ssh(" not in window


def test_auth_toggle_is_not_pinned_to_a_clipping_fixed_width():
    for path in _GATEWAYS:
        src = path.read_text()
        assert 'layout=W.Layout(width="420px")' not in src
