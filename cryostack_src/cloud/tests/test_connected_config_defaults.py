"""Basic/Auto-config cannot require an Advanced bucket for a verified account."""
import pytest
from cryostack_src.cloud.config import (bind_connected_cloud_account,
    resolve_cloud_config, validate_cloud_config)

@pytest.mark.parametrize("model", ["issm", "icepack"])
def test_verified_account_resolves_blank_basic_fields_before_validation(model):
    raw = resolve_cloud_config(model=model, region="us-west-1", bucket="", profile="operator")
    summary = dict(status="connected", account_id="123456789012", region="us-east-2")
    resolved = bind_connected_cloud_account(raw, summary=summary)
    assert not validate_cloud_config(resolved, model=model)
    assert resolved.bucket == "cryostack-runs-123456789012"
    assert resolved.region == "us-east-2" and resolved.profile is None
    assert resolved.job_definition == raw.job_definition
    assert resolved.fargate == raw.fargate
    assert raw.bucket == "" and raw.region == "us-west-1"  # caller's draft unchanged
    assert bind_connected_cloud_account(resolved, summary=summary) == resolved

def test_stale_other_account_bucket_never_survives_a_verified_account_switch():
    raw = resolve_cloud_config(model="icepack", bucket="other-account-bucket")
    result = bind_connected_cloud_account(raw, summary=dict(status="connected",
        account_id="123456789012", region="us-east-2"))
    assert result.bucket == "cryostack-runs-123456789012"

@pytest.mark.parametrize("status", ["pending", "error", "disconnected", None])
def test_unverified_or_operator_mode_does_not_invent_a_connected_account(status):
    raw = resolve_cloud_config(model="icepack", bucket="")
    assert bind_connected_cloud_account(raw, summary={"status": status}) is raw
    assert validate_cloud_config(raw, model="icepack")

def test_connected_summary_with_bad_account_fails_closed():
    with pytest.raises(ValueError):
        bind_connected_cloud_account(resolve_cloud_config(model="icepack"),
            summary=dict(status="connected", account_id="invalid", region="us-east-2"))


def test_invalid_hidden_bucket_does_not_override_the_verified_accounts_bucket():
    raw = resolve_cloud_config(model="icepack", bucket="not a valid bucket")
    assert raw.bucket_error
    result = bind_connected_cloud_account(raw, summary=dict(status="connected",
        account_id="123456789012", region="us-east-2"))
    assert not validate_cloud_config(result, model="icepack")
