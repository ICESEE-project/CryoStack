"""Cloud Commit 3 -- pre-submit gates: no billable job for a misconfigured run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryostack_src.cloud.preflight import (
    assert_cloud_run_allowed,
    cloud_run_preflight,
)
from cryostack_src.cloud.runtime import CloudRuntimeError


def test_issm_without_a_cloud_matlab_license_is_blocked():
    reasons = cloud_run_preflight(model="issm", matlab_license_configured=False)
    assert reasons and "MATLAB license reachable from AWS" in reasons[0]
    assert "Secrets Manager" in reasons[0]
    with pytest.raises(CloudRuntimeError):
        assert_cloud_run_allowed(model="issm", matlab_license_configured=False)


def test_issm_with_a_configured_license_passes():
    assert cloud_run_preflight(model="issm", matlab_license_configured=True) == []
    assert_cloud_run_allowed(model="issm", matlab_license_configured=True)  # no raise


def test_icepack_needs_no_matlab_license():
    """Icepack Cloud Execution checkpoint: the MATLAB-license gate is
    ISSM-only. Icepack passes preflight regardless of the compute profile's
    license state -- true whether or not one happens to be configured."""
    assert cloud_run_preflight(model="icepack", matlab_license_configured=False) == []
    assert cloud_run_preflight(model="icepack", matlab_license_configured=True) == []
    assert_cloud_run_allowed(model="icepack", matlab_license_configured=False)  # no raise


def test_unknown_model_is_blocked():
    assert cloud_run_preflight(model="", matlab_license_configured=True)
    assert cloud_run_preflight(model="firedrake", matlab_license_configured=True)


def test_preflight_uses_the_single_workflow_capability_resolver():
    """The MATLAB-license gate must be one authoritative answer
    (cryostack_src.models.workflow_capabilities), not a duplicated
    ``model == "issm"`` string check re-derived here."""
    import inspect

    from cryostack_src.cloud import preflight as preflight_module

    src = inspect.getsource(preflight_module.cloud_run_preflight)
    assert "resolve_workflow_capabilities" in src
    assert '== "issm"' not in src


def test_connector_required_but_not_connected_blocks_even_with_a_configured_license():
    """Distinct from "license not configured" -- the license CAN be
    configured and this can still block, fail-closed, when the already-
    resolved CloudMatlabLicense.requires_tunnel says the Connector is
    needed and it is not currently paired."""
    reasons = cloud_run_preflight(
        model="issm", matlab_license_configured=True,
        connector_required=True, connector_connected=False,
    )
    assert reasons
    assert any("CryoStack Connector" in r for r in reasons)
    with pytest.raises(CloudRuntimeError):
        assert_cloud_run_allowed(
            model="issm", matlab_license_configured=True,
            connector_required=True, connector_connected=False,
        )


def test_connector_required_and_connected_passes():
    assert cloud_run_preflight(
        model="issm", matlab_license_configured=True,
        connector_required=True, connector_connected=True,
    ) == []
    assert_cloud_run_allowed(
        model="issm", matlab_license_configured=True,
        connector_required=True, connector_connected=True,
    )  # no raise


def test_connector_not_required_is_unaffected_by_connector_state():
    """A site/workflow that does not require the Connector never blocks on
    it, regardless of connector_connected -- never a generic "Cloud uses
    Connector" requirement."""
    assert cloud_run_preflight(
        model="issm", matlab_license_configured=True,
        connector_required=False, connector_connected=False,
    ) == []


def test_icepack_never_blocked_by_the_connector_reason():
    """Icepack has no MATLAB requirement at all -- the connector gate is
    reached only through requires_matlab_license, so it must never fire
    for a non-MATLAB workflow even if connector_required is mistakenly
    passed True."""
    assert cloud_run_preflight(
        model="icepack", matlab_license_configured=False,
        connector_required=True, connector_connected=False,
    ) == []


def test_connector_reason_never_leaks_implementation_details():
    """The scientist only needs to know CryoStack needs the Connector to
    reach their institution -- no tunnel/relay/WebSocket/session id/
    token/FlexNet/vendor-daemon/host-port/MLM_LICENSE_FILE wording."""
    reasons = cloud_run_preflight(
        model="issm", matlab_license_configured=True,
        connector_required=True, connector_connected=False,
    )
    blob = " ".join(reasons).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "session id", "token",
        "flexnet", "vendor", "host", "port", "mlm_license_file",
    ):
        assert forbidden not in blob, forbidden


def test_missing_license_reason_still_wins_over_the_connector_reason():
    """Configure the license first: when the license itself is not
    configured, the connector-specific reason must not also fire (avoids
    a confusing double-blocked message for one root cause)."""
    reasons = cloud_run_preflight(
        model="issm", matlab_license_configured=False,
        connector_required=True, connector_connected=False,
    )
    assert len(reasons) == 1
    assert "MATLAB license reachable from AWS" in reasons[0]
    assert "CryoStack Connector" not in reasons[0]


def test_the_default_aws_compute_profile_has_no_license():
    """The AWS profile must stay unconfigured for MATLAB until a real cloud
    license mechanism exists -- so ISSM cloud is blocked by default."""
    from cryostack_src.resources.profiles import get_compute_profile

    aws = get_compute_profile("aws")
    assert aws.has_matlab_license is False
    assert aws.matlab_license_config() is None
    assert cloud_run_preflight(
        model="issm",
        matlab_license_configured=aws.has_matlab_license) != []
