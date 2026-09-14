"""Canonical S3 location normalization (the "Invalid bucket name 's3://...'" fix).

The UI "S3 prefix" field may hold a bare bucket, ``s3://bucket``,
``s3://bucket/``, or ``s3://bucket/a/b``. All of them normalize to
``S3Location(bucket, prefix)``; AWS ``Bucket=`` args get the name only, the
CLI gets the full URI, and an actual key prefix is never silently dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.s3_uri import (
    S3Location,
    S3LocationError,
    bucket_name,
    parse_s3_location,
    s3_uri,
)

_B = "cryostack-runs-713938953301"


# ── parse: every accepted form ──────────────────────────────────────────
@pytest.mark.parametrize(("value", "bucket", "prefix"), [
    (_B, _B, ""),                                    # bare bucket
    (f"s3://{_B}", _B, ""),                          # s3://bucket
    (f"s3://{_B}/", _B, ""),                         # s3://bucket/
    (f"s3://{_B}/team", _B, "team"),                 # s3://bucket/prefix
    (f"s3://{_B}/team/experiments/x", _B, "team/experiments/x"),  # nested prefix
    (f"  s3://{_B}/team/  ", _B, "team"),            # whitespace + trailing slash
    (f"S3://{_B}", _B, ""),                          # scheme case-insensitive
    (f"{_B.upper()}", _B, ""),                       # bucket lower-cased
])
def test_parse_accepts(value, bucket, prefix):
    loc = parse_s3_location(value)
    assert loc == S3Location(bucket=bucket, prefix=prefix)


# ── parse: every rejected form ──────────────────────────────────────────
@pytest.mark.parametrize("value", [
    "",                                             # empty
    "   ",                                          # whitespace only
    "s3://",                                        # empty bucket
    "s3:///prefix",                                 # empty bucket + prefix
    "https://example.com/bucket",                   # wrong scheme
    "ftp://bucket",                                 # wrong scheme
    "Bad_Bucket_Name",                              # underscore (invalid char)
    "b",                                            # too short (< 3)
    "x" * 64,                                       # too long (> 63)
    "-startsdash",                                  # must start alphanumeric
    "endsdash-",                                    # must end alphanumeric
])
def test_parse_rejects(value):
    with pytest.raises(S3LocationError):
        parse_s3_location(value)


# ── the two consumer helpers ───────────────────────────────────────────
def test_bucket_name_is_always_just_the_name():
    for v in (_B, f"s3://{_B}", f"s3://{_B}/", f"s3://{_B}/a/b"):
        assert bucket_name(v) == _B
        assert "s3://" not in bucket_name(v) and "/" not in bucket_name(v)


def test_s3_uri_builds_a_full_uri_with_optional_subkeys():
    assert s3_uri(_B) == f"s3://{_B}"
    assert s3_uri(f"s3://{_B}/") == f"s3://{_B}"
    assert s3_uri(f"s3://{_B}/team", "runs", "user-x", "cloud-1") == \
        f"s3://{_B}/team/runs/user-x/cloud-1"
    assert s3_uri(_B, "runs/user-x/cloud-1") == f"s3://{_B}/runs/user-x/cloud-1"


def test_child_nests_the_prefix():
    loc = parse_s3_location(f"s3://{_B}/team")
    assert loc.child("runs", "alice", "run-1").uri() == \
        f"s3://{_B}/team/runs/alice/run-1"
    assert parse_s3_location(_B).child("runs").uri() == f"s3://{_B}/runs"


# ── an AWS Bucket= arg never receives s3:// (integration) ───────────────
def test_ensure_bucket_receives_a_name_not_a_uri():
    from cryostack_src.cloud.drivers.aws import storage as st

    seen = []

    def fake_run_aws(config, args):
        seen.append(list(args))
        if args[:2] == ["sts", "get-caller-identity"] or "get-caller-identity" in args:
            return (0, '{"Account":"713938953301"}', "")
        if args[:2] == ["s3api", "head-bucket"]:
            return (0, "{}", "")                     # bucket exists -> reuse
        return (0, "{}", "")

    import cryostack_src.cloud.drivers.aws.auth as auth_mod
    orig = auth_mod.run_aws
    st.run_aws = fake_run_aws
    auth_mod.run_aws = fake_run_aws
    try:
        from cryostack_src.cloud.drivers.aws.models import AWSConfig
        name, created = st.ensure_bucket(
            AWSConfig(region="us-east-2"), bucket=f"s3://{_B}/some/prefix")
        assert name == _B and created is False
        head = next(c for c in seen if c[:2] == ["s3api", "head-bucket"])
        assert head[head.index("--bucket") + 1] == _B      # name only, no s3://
        assert not any("s3://" in tok for c in seen for tok in c
                       if c[:2] == ["s3api", "head-bucket"])
    finally:
        st.run_aws = orig
        auth_mod.run_aws = orig


def test_cli_sync_receives_a_full_s3_uri():
    """stage_run_inputs produces s3:// URIs for the CLI even when handed a URI."""
    import tempfile

    from cryostack_src.cloud.drivers.aws.models import AWSConfig
    from cryostack_src.cloud.drivers.aws.staging import stage_run_inputs

    d = Path(tempfile.mkdtemp()) / "ex"
    d.mkdir()
    (d / "runme.m").write_text("md=model;\n")
    calls = []
    out = stage_run_inputs(
        AWSConfig(region="us-east-2"), source=str(d), model="issm",
        run_target="runme.m", bucket=f"s3://{_B}/", run_prefix="alice-x/",
        s3=lambda a: (calls.append(a) or (0, "", "")))
    assert out.s3_run == f"s3://{_B}/runs/alice-x/{out.run_id}"
    syncs = [c for c in calls if c[:2] == ["s3", "sync"]]
    assert syncs and syncs[0][3].startswith(f"s3://{_B}/runs/alice-x/")


# ── prepare-cloud and submit-cloud agree on the same normalized bucket ──
def test_prepare_and_submit_agree_on_the_bucket():
    from cryostack_src.cloud.config import resolve_cloud_config
    ui_value = f"s3://{_B}/"

    # submit path
    submit_bucket = resolve_cloud_config(bucket=ui_value, model="issm").bucket

    # prepare path (ensure_bucket normalizes the same way)
    prepare_bucket = bucket_name(ui_value)

    assert submit_bucket == prepare_bucket == _B
