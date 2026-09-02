"""Cloud Commit 4 -- cloud run configuration resolution + validation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.cloud.config import (
    DEFAULT_CLOUD_REGION,
    resolve_cloud_config,
    validate_cloud_config,
)


def test_deterministic_queue_and_definition_when_not_supplied():
    cfg = resolve_cloud_config(bucket="cryostack-runs-1", model="issm")
    assert cfg.job_queue == "cryostack-queue"
    assert cfg.job_definition == "cryostack-issm"
    assert cfg.region == DEFAULT_CLOUD_REGION


def test_explicit_overrides_win():
    cfg = resolve_cloud_config(
        region="eu-west-1", bucket="cryostack-b1", model="issm",
        job_queue="my-queue", job_definition="my-def:3",
    )
    assert (cfg.region, cfg.job_queue, cfg.job_definition) == ("eu-west-1", "my-queue", "my-def:3")


def test_bucket_accepts_a_plain_name_or_an_s3_uri():
    assert resolve_cloud_config(bucket="cryostack-runs-1").bucket == "cryostack-runs-1"
    assert resolve_cloud_config(bucket="s3://cryostack-runs-1").bucket == "cryostack-runs-1"
    # an s3://bucket/prefix keeps the bucket name only + a base_prefix
    c = resolve_cloud_config(bucket="s3://cryostack-runs-1/team/x")
    assert c.bucket == "cryostack-runs-1" and c.base_prefix == "team/x"
    assert validate_cloud_config(c, model="issm").count(
        "An S3 bucket is required for cloud run inputs and outputs.") == 0


def test_valid_config_has_no_problems():
    cfg = resolve_cloud_config(bucket="cryostack-runs-123456789012", model="issm")
    assert validate_cloud_config(cfg, model="issm") == []


def test_missing_bucket_is_the_first_actionable_problem():
    cfg = resolve_cloud_config(model="issm")
    problems = validate_cloud_config(cfg, model="issm")
    assert any("S3 bucket is required" in p for p in problems)
    assert all(len(p) < 120 and p.endswith(".") for p in problems)


@pytest.mark.parametrize("bad_region", ["useast2", "us_east_2", "US-EAST-2", "x"])
def test_bad_region_is_flagged(bad_region):
    cfg = resolve_cloud_config(region=bad_region, bucket="cryostack-runs-1")
    assert any("Region must look like" in p for p in validate_cloud_config(cfg))


def test_bad_bucket_name_is_flagged():
    cfg = resolve_cloud_config(bucket="Not_A_Valid_Bucket", model="issm")
    assert any("not a valid S3 bucket name" in p for p in validate_cloud_config(cfg))


def test_non_s3_scheme_is_flagged():
    cfg = resolve_cloud_config(bucket="https://example.com/bucket", model="issm")
    assert cfg.bucket == "" and cfg.bucket_error
    assert any("bucket name or an s3:// URI" in p for p in validate_cloud_config(cfg))


def test_unsupported_provider_is_flagged():
    cfg = resolve_cloud_config(provider="gcp", bucket="b")
    assert any("not supported" in p for p in validate_cloud_config(cfg))


def test_provenance_carries_only_non_secret_facts():
    cfg = resolve_cloud_config(
        region="us-east-2", bucket="cryostack-runs-1", profile="my-sso-profile",
        model="issm",
    )
    prov = cfg.provenance()
    assert prov == {
        "provider": "aws", "region": "us-east-2", "bucket": "cryostack-runs-1",
        "job_queue": "cryostack-queue", "job_definition": "cryostack-issm",
    }
    # the local CLI profile selector is never provenance
    assert "profile" not in prov
    blob = str(prov).lower()
    for secret in ("secret", "token", "password", "credential", "profile"):
        assert secret not in blob
