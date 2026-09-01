"""B1: resource facts from ComputeProfile; no developer/personal defaults.

A newly authenticated CryoStack user must never see another user's or the
developer's HPC username, remote directory, Slurm allocation, or notification
email -- and a missing remote directory must fail closed, never silently
substitute one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.resources.profiles import (
    ComputeProfile,
    SchedulerDefaults,
    get_compute_profile,
    initial_remote_fields,
)
from cryostack_src.remote.runtime import RemoteConfigError, require_remote_base_dir

_ICESHEETS_GW = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"
_ICESEE_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
_SUBMISSION = _REPO / "cryostack_src/models/submission.py"
_REMOTE_RUNNER = _REPO / "icesee_jupyter_book/core/remote_runner.py"

# Values that must never appear as a runtime default in a first-party path.
_DEV_VALUES = ("r-arobel3-0", "gts-arobel3-atlas", "bankyanjo@gmail")


# ── ComputeProfile: resource facts, PACE, unknown, MATLAB preserved ──────
def test_pace_profile_carries_resource_facts_not_personal_ones():
    p = get_compute_profile("pace")
    assert p.login_host == "login-phoenix-rh9.pace.gatech.edu"
    assert p.ssh_port == 22
    assert p.scheduler_defaults.partition == "cpu-large"
    assert p.scheduler_defaults.wall_time == "04:00:00"
    assert p.account_required is True
    assert "connector" in p.supported_access_modes
    # nothing personal
    blob = repr(p)
    for bad in _DEV_VALUES + ("bkyanjo3", "USER"):
        assert bad not in blob


def test_matlab_license_behaviour_is_unchanged():
    p = get_compute_profile("pace")
    assert p.has_matlab_license
    assert p.matlab_license_config() == {
        "env_var": "MLM_LICENSE_FILE", "value": "1711@matlablic.ecs.gatech.edu",
    }
    assert get_compute_profile("ub-ccr").matlab_license_config() is None
    assert get_compute_profile("Phoenix").matlab_license_config() == p.matlab_license_config()


def test_unknown_resource_is_neutral_not_pace():
    u = get_compute_profile("frontera")
    assert u.login_host == ""
    assert u.ssh_port == 22
    assert u.scheduler_defaults == SchedulerDefaults()
    assert u.account_required is False
    assert u.requires_vpn is False and u.requires_mfa is False
    assert u.portal_url == "" and u.portal_name == ""


def test_profile_rejects_bad_config():
    with pytest.raises(ValueError):
        ComputeProfile(name="x", key_registration_method="bogus")
    with pytest.raises(ValueError):
        ComputeProfile(name="x", ssh_port=0)


# ── initial_remote_fields: personal blank, resource populated ────────────
def test_initial_fields_blank_personal_populated_resource_for_pace():
    f = initial_remote_fields("pace")
    assert f["hpc_username"] == ""
    assert f["remote_directory"] == ""
    assert f["slurm_account"] == ""
    assert f["notification_email"] == ""
    assert f["login_host"] == "login-phoenix-rh9.pace.gatech.edu"
    assert f["ssh_port"] == 22
    assert f["partition"] == "cpu-large"
    assert f["wall_time"] == "04:00:00"
    assert f["account_required"] is True


def test_initial_fields_neutral_for_unknown_resource():
    f = initial_remote_fields("some-unknown-cluster")
    assert f["login_host"] == ""
    assert f["partition"] == ""
    assert f["wall_time"] == ""
    assert f["account_required"] is False
    assert all(f[k] == "" for k in ("hpc_username", "remote_directory", "slurm_account", "notification_email"))


def test_initial_fields_never_reads_server_user(monkeypatch):
    monkeypatch.setenv("USER", "svcaccount-not-the-user")
    monkeypatch.setenv("LOGNAME", "svcaccount-not-the-user")
    f = initial_remote_fields("pace")
    assert "svcaccount-not-the-user" not in repr(f)
    assert f["hpc_username"] == ""


# ── fail closed: missing remote directory ──────────────────────────────
def test_require_remote_base_dir_fails_closed():
    for bad in ("", "   ", None):
        with pytest.raises(RemoteConfigError):
            require_remote_base_dir(bad)
    assert require_remote_base_dir("  ~/scratch/run  ") == "~/scratch/run"


def test_make_remote_run_dir_has_no_default_base():
    import icesee_jupyter_book.core.remote_runner as rr
    # base_dir is required now -- no "~/r-arobel3-0" default
    assert rr.make_remote_run_dir.__defaults__ == ("icesee",)  # only `tag`
    with pytest.raises(TypeError):
        rr.make_remote_run_dir()  # type: ignore[call-arg]


def test_resolve_remote_base_fails_closed(monkeypatch):
    from cryostack_src.remote.bridge import RemoteBridge
    b = RemoteBridge(mode="connector", host="h", user="u", port=22, session_id="s")
    with pytest.raises(RemoteConfigError):
        b.resolve_remote_base("")


# ── source guard: no developer default may be reintroduced ─────────────
@pytest.mark.parametrize("path", [_ICESHEETS_GW, _ICESEE_GW, _SUBMISSION, _REMOTE_RUNNER])
def test_no_developer_default_in_first_party_runtime_source(path):
    src = path.read_text()
    for bad in _DEV_VALUES:
        assert bad not in src, f"{path.name} still references {bad!r}"


@pytest.mark.parametrize("path", [_ICESHEETS_GW, _ICESEE_GW])
def test_gateways_source_resource_facts_and_blank_personal_fields(path):
    src = path.read_text()
    assert "initial_remote_fields(" in src
    # HPC username / remote dir / account / email come from _rf (blank), not literals
    assert 'value=os.environ.get("USER"' not in src
    assert re.search(r"cluster_user\s*=\s*W\.Text\(\s*value=_rf\[", src)
    assert re.search(r"remote_base_dir\s*=\s*W\.Text\(\s*value=_rf\[", src)
    assert re.search(r"slurm_account\s*=\s*W\.Text\(", src)
    assert '_rf["slurm_account"]' in src and '_rf["notification_email"]' in src
    # host / port / partition / wall time come from the profile
    assert '_rf["login_host"]' in src and '_rf["ssh_port"]' in src
    assert '_rf["partition"]' in src and '_rf["wall_time"]' in src


# ── build the real gateways: no personal identity anywhere in the tree ──
def _string_values(widget, acc):
    for attr in ("value", "placeholder"):
        v = getattr(widget, attr, None)
        if isinstance(v, str):
            acc.append(v)
    for child in getattr(widget, "children", None) or []:
        _string_values(child, acc)


@pytest.fixture
def _no_network(monkeypatch):
    import icesee_jupyter_book.core.connector_relay_client as rc

    def _boom(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(rc.requests, "post", _boom, raising=False)
    monkeypatch.setattr(rc.requests, "get", _boom, raising=False)


@pytest.mark.parametrize("builder_name", ["build_icesheets_ui", "build_icesee_ui"])
def test_fresh_gateway_has_no_personal_identity(builder_name, monkeypatch, _no_network):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "b1-synthetic-user")
    monkeypatch.setenv("USER", "b1-injected-service-user")
    monkeypatch.setenv("LOGNAME", "b1-injected-service-user")

    if builder_name == "build_icesheets_ui":
        from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui as build
    else:
        from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui as build

    ui = build()
    values = []
    _string_values(ui, values)
    joined = "\n".join(values)

    # The injected server $USER must never surface as a widget value/placeholder
    # (it is the Voila service identity, not the user's HPC identity), and no
    # audited developer allocation / directory / email may appear as a default.
    for bad in _DEV_VALUES + ("b1-injected-service-user",):
        assert bad not in joined, f"{builder_name}: leaked {bad!r}"

    # resource facts DID populate from the PACE profile
    assert "login-phoenix-rh9.pace.gatech.edu" in joined
    assert "cpu-large" in joined
    assert "04:00:00" in joined
