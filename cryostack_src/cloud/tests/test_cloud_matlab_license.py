"""ISSM cloud MATLAB-license readiness seam.

CryoStack stores ONLY a non-secret AWS Secrets Manager ARN. The license
value (MLM_LICENSE_FILE = <port>@<host>, or a MathWorks token) stays in the
user's own account and never reaches CryoStack, git, the image, an S3 run
artifact, a manifest, a command preview, or a log. AWS Batch injects it into
the container at launch via containerProperties.secrets.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.execution import CloudExecution
from cryostack_src.cloud.connect.models import AWSConnection
from cryostack_src.cloud.drivers.aws.batch_config import (
    container_properties_payload,
    job_definition_fingerprint,
)
from cryostack_src.cloud.matlab_license import (
    MATLAB_LICENSE_ENV,
    NOT_CONFIGURED,
    CloudMatlabLicense,
    assert_not_a_license_value,
    is_secret_arn,
    resolve_cloud_matlab_license,
)

_ARN = "arn:aws:secretsmanager:us-east-2:123456789012:secret:cryostack/issm-matlab-AbCdEf"


def _conn(**over):
    c = AWSConnection(connection_id="c1", external_id="e1", region="us-east-2")
    for k, v in over.items():
        c = c.__class__(**{**c.to_dict(), k: v})
    return c


# ── the seam: ARN only, never a value ──────────────────────────────────
def test_unconfigured_connection_is_not_ready():
    assert resolve_cloud_matlab_license(_conn()) == NOT_CONFIGURED
    assert NOT_CONFIGURED.configured is False
    assert NOT_CONFIGURED.batch_secrets_block() == []


def test_a_valid_secret_arn_makes_issm_runtime_configured():
    lic = resolve_cloud_matlab_license(_conn(matlab_license_secret_arn=_ARN))
    assert lic.configured and lic.mechanism == "secrets-manager"
    assert lic.secret_arn == _ARN
    assert lic.batch_secrets_block() == [
        {"name": MATLAB_LICENSE_ENV, "valueFrom": _ARN}]


def test_a_malformed_arn_is_treated_as_unconfigured_never_a_crash():
    for bad in ("not-an-arn", "arn:aws:s3:::bucket", "27000@license.example.com", ""):
        assert resolve_cloud_matlab_license(
            _conn(matlab_license_secret_arn=bad)) == NOT_CONFIGURED


def test_is_secret_arn():
    assert is_secret_arn(_ARN)
    assert not is_secret_arn("arn:aws:iam::123456789012:role/x")
    assert not is_secret_arn("27000@matlab.example.com")


def test_leak_guard_rejects_a_license_value():
    assert_not_a_license_value(_ARN)          # an ARN is fine
    assert_not_a_license_value("")            # empty is fine
    for value in ("27000@license.example.com", "MLM_LICENSE_FILE=1711@host",
                  "1711@matlablic.example.edu"):
        with pytest.raises(ValueError):
            assert_not_a_license_value(value)


# ── CloudExecution.matlab_license ──────────────────────────────────────
def test_cloud_execution_surfaces_license_state_non_secret():
    ex_none = CloudExecution(mode="developer", region="us-east-2")
    assert ex_none.matlab_license == NOT_CONFIGURED

    ex_byo = CloudExecution(mode="byo", region="us-east-2",
                            connection=_conn(matlab_license_secret_arn=_ARN))
    assert ex_byo.matlab_license.configured
    blob = json.dumps(ex_byo.matlab_license.as_public_dict())
    assert _ARN in blob                       # the ARN is fine to surface
    assert "@" not in blob.replace(_ARN, "")  # ... but no license VALUE shape


# ── the connection record persists an ARN, never a secret ─────────────
def test_connection_round_trips_the_arn_and_it_is_non_secret():
    from cryostack_src.cloud.connect.redaction import assert_no_aws_secrets

    c = _conn().with_matlab_license_secret(_ARN)
    d = c.to_dict()
    assert d["matlab_license_secret_arn"] == _ARN
    assert AWSConnection.from_dict(d).matlab_license_secret_arn == _ARN
    assert_no_aws_secrets(d, context="connection")           # ARN is not a secret
    assert_no_aws_secrets(c.to_public_dict(own=True), context="connection")


# ── job definition: secrets are ARN references, never values ──────────
def test_container_properties_payload_wires_the_secret_arn_reference():
    lic = CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                             secret_arn=_ARN)
    cp = container_properties_payload(
        model="issm", image="repo@sha256:" + "a" * 64,
        job_role_arn="arn:aws:iam::123456789012:role/job",
        execution_role_arn="arn:aws:iam::123456789012:role/exec",
        region="us-east-2", secrets=lic.batch_secrets_block())
    assert cp["secrets"] == [{"name": "MLM_LICENSE_FILE", "valueFrom": _ARN}]
    # the fingerprint tracks it -> a license add/remove re-registers the job def
    fp = job_definition_fingerprint(container_properties=cp,
                                    timeout_seconds=3600, attempts=1)
    assert ("MLM_LICENSE_FILE", _ARN) in fp["secrets"]


def test_container_properties_payload_rejects_a_raw_value_in_valueFrom():
    with pytest.raises(ValueError):
        container_properties_payload(
            model="issm", image="repo@sha256:" + "a" * 64,
            job_role_arn="arn:aws:iam::123456789012:role/job",
            execution_role_arn="arn:aws:iam::123456789012:role/exec",
            region="us-east-2",
            secrets=[{"name": "MLM_LICENSE_FILE", "valueFrom": "27000@host"}])


def test_no_secrets_block_when_unconfigured():
    cp = container_properties_payload(
        model="issm", image="repo@sha256:" + "a" * 64,
        job_role_arn="arn:aws:iam::123456789012:role/job",
        execution_role_arn="arn:aws:iam::123456789012:role/exec",
        region="us-east-2", secrets=NOT_CONFIGURED.batch_secrets_block())
    assert "secrets" not in cp


# ── end-to-end security contract: only the ARN travels, never the value ──
def test_the_license_value_never_travels_only_the_secret_arn_does():
    from cryostack_src.cloud.drivers.aws.submit import build_container_overrides
    from cryostack_src.cloud.runtime import build_cloud_runner, build_run_descriptor
    from cryostack_src.cloud.runtime import descriptor_is_clean

    lic = CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                             secret_arn=_ARN)

    # 1. the Batch job definition gets ONLY the ARN reference
    assert lic.batch_secrets_block() == [
        {"name": "MLM_LICENSE_FILE", "valueFrom": _ARN}]

    # 2. runtime containerOverrides.environment cannot carry MLM_LICENSE_FILE
    #    (it is a fixed 3-value set; "mlm_license" is also in _FORBIDDEN_ENV_HINTS)
    ov = build_container_overrides(
        s3_run="s3://b/runs/r", model="issm", run_target="runme.m")
    assert {e["name"] for e in ov["environment"]} == {
        "CRYOSTACK_S3_RUN", "CRYOSTACK_MODEL", "CRYOSTACK_RUN_TARGET"}

    # 3. the generic cloud runtime script embeds no license value
    assert "MLM_LICENSE_FILE=" not in build_cloud_runner()

    # 4. the run descriptor (provenance) fails its no-secrets check if a
    #    license value is smuggled in; a clean one passes
    assert descriptor_is_clean(build_run_descriptor(
        model="issm", run_target="runme.m")) is True
    assert descriptor_is_clean(
        {"x": "MLM_LICENSE_FILE=27000@test-license.invalid"}) is False


def test_iam_grant_is_scoped_to_exactly_the_configured_secret_arn():
    """The ARN wired into containerProperties.secrets must be the SAME ARN the
    ECS execution-role policy is scoped to -- no wildcard, one secret only."""
    from cryostack_src.cloud.drivers.aws.iam_policies import (
        matlab_license_secret_policy,
    )

    secret_block = CloudMatlabLicense(
        configured=True, mechanism="secrets-manager",
        secret_arn=_ARN).batch_secrets_block()
    policy = matlab_license_secret_policy(secret_arn=_ARN)

    (stmt,) = policy["Statement"]
    assert stmt["Action"] == "secretsmanager:GetSecretValue"
    assert stmt["Resource"] == secret_block[0]["valueFrom"] == _ARN
    assert "*" not in json.dumps(policy)


# ── private-service tunnel: site fact, never per-user/per-run ───────────
def test_site_requires_cloud_license_tunnel_reflects_the_pace_profile():
    from cryostack_src.cloud.matlab_license import site_requires_cloud_license_tunnel

    assert site_requires_cloud_license_tunnel() is True  # PACE: not reachable from Fargate


def test_resolve_cloud_matlab_license_carries_requires_tunnel(monkeypatch):
    conn = _conn(matlab_license_secret_arn=_ARN)
    lic = resolve_cloud_matlab_license(conn)
    assert lic.configured is True
    assert lic.requires_tunnel is True                       # PACE site fact
    assert lic.license_path() == "institutional_connector"


def test_unconfigured_license_is_always_the_direct_path():
    assert NOT_CONFIGURED.license_path() == "direct"
    assert NOT_CONFIGURED.requires_tunnel is False


def test_requires_tunnel_false_when_site_profile_does_not_need_it(monkeypatch):
    """If a future/other site's license IS reachable from Fargate directly,
    the existing (unchanged) direct path is retained -- the tunnel is used
    only when the site profile says the service needs it."""
    from cryostack_src.resources import profiles as resources_profiles

    monkeypatch.setitem(
        resources_profiles.COMPUTE_PROFILES, "pace",
        resources_profiles.ComputeProfile(
            name="pace", matlab_license_value="1711@public-license.example.edu",
            matlab_license_cloud_requires_tunnel=False,
        ),
    )
    conn = _conn(matlab_license_secret_arn=_ARN)
    lic = resolve_cloud_matlab_license(conn)
    assert lic.requires_tunnel is False
    assert lic.license_path() == "direct"
    # the Secrets Manager representation is completely unaffected either way
    assert lic.batch_secrets_block() == [{"name": "MLM_LICENSE_FILE", "valueFrom": _ARN}]


def test_as_public_dict_reports_requires_tunnel():
    lic = CloudMatlabLicense(configured=True, mechanism="secrets-manager",
                              secret_arn=_ARN, requires_tunnel=True)
    assert lic.as_public_dict()["requires_tunnel"] is True


def test_local_mlm_license_file_points_at_loopback():
    from cryostack_src.cloud.matlab_license import local_mlm_license_file

    assert local_mlm_license_file(1711) == "1711@127.0.0.1"


def test_site_cloud_license_port_parses_the_pace_site_value():
    from cryostack_src.cloud.matlab_license import site_cloud_license_port

    assert site_cloud_license_port() == 1711


# ── plan_license_tunnel: the one decision point joining Cloud + Connector ──
def test_plan_returns_none_when_no_tunnel_is_required():
    from cryostack_src.cloud.matlab_license import plan_license_tunnel

    assert plan_license_tunnel(
        requires_tunnel=False, session_id="sid-1", relay_url="https://relay.example") is None


def test_plan_fails_closed_without_a_connector_session():
    from cryostack_src.cloud.matlab_license import (
        LicenseTunnelUnavailable, plan_license_tunnel,
    )

    with pytest.raises(LicenseTunnelUnavailable):
        plan_license_tunnel(requires_tunnel=True, session_id=None, relay_url="https://relay.example")
    with pytest.raises(LicenseTunnelUnavailable):
        plan_license_tunnel(requires_tunnel=True, session_id="", relay_url="https://relay.example")


def test_plan_never_falls_back_to_direct_when_tunnel_required_and_unavailable():
    """Explicit regression for "do not silently fall back to an insecure
    path": a caller that (incorrectly) tried to swallow the exception and
    proceed would still have no env vars to submit with -- there is no
    partial/degraded dict returned on this path, only a raise."""
    from cryostack_src.cloud.matlab_license import (
        LicenseTunnelUnavailable, plan_license_tunnel,
    )

    try:
        result = plan_license_tunnel(
            requires_tunnel=True, session_id=None, relay_url="https://relay.example")
        pytest.fail(f"expected LicenseTunnelUnavailable, got a result: {result!r}")
    except LicenseTunnelUnavailable:
        pass


def test_plan_mints_a_grant_and_returns_the_expected_env_vars():
    from cryostack_src.cloud.matlab_license import plan_license_tunnel

    seen = {}

    def fake_mint(session_id, purpose, *, ttl_seconds=None):
        seen.update(session_id=session_id, purpose=purpose, ttl_seconds=ttl_seconds)
        return {"grant_id": "g-1", "token": "tok-1", "purpose": purpose, "expires_at": 1.0}

    plan = plan_license_tunnel(
        requires_tunnel=True, session_id="sid-1", relay_url="https://relay.example",
        mint_grant=fake_mint, ttl_seconds=3600,
    )
    assert plan == {
        "CRYOSTACK_LICENSE_TUNNEL_REQUIRED": "1",
        "CRYOSTACK_LT_RELAY": "https://relay.example",
        "CRYOSTACK_LT_SESSION": "sid-1",
        "CRYOSTACK_LT_TOKEN": "tok-1",
        "CRYOSTACK_LT_PURPOSE": "matlab-license",
        "CRYOSTACK_LT_ENDPOINT": "primary",
        "CRYOSTACK_LT_PORT": "1711",
        "_grant_id": "g-1",
    }
    assert seen == {"session_id": "sid-1", "purpose": "matlab-license", "ttl_seconds": 3600}


def test_plan_never_receives_or_leaks_the_raw_license_value():
    """plan_license_tunnel takes only a bool (never a CloudMatlabLicense,
    a secret, or an ARN) and the resulting env-var dict never contains
    anything shaped like a real institutional host/value -- only the relay
    URL, session id, an opaque token, symbolic purpose/endpoint, and a
    port number."""
    from cryostack_src.cloud.matlab_license import plan_license_tunnel

    plan = plan_license_tunnel(
        requires_tunnel=True, session_id="sid-1", relay_url="https://relay.example",
        mint_grant=lambda *a, **k: {"grant_id": "g-1", "token": "tok-1", "purpose": "matlab-license"},
    )
    assert "matlablic.ecs.gatech.edu" not in json.dumps(plan)
