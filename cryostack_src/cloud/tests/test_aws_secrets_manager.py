"""Guided ISSM MATLAB-license Secrets Manager setup
(cryostack_src/cloud/drivers/aws/secrets.py).

No real AWS Secrets Manager secret is ever created here -- run_aws is
replaced with a fake that records the call and returns a canned response.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

import cryostack_src.cloud.drivers.aws.secrets as secrets_mod
from cryostack_src.cloud.drivers.aws.models import AWSConfig
from cryostack_src.cloud.drivers.aws.secrets import (
    SECRET_NAME_PREFIX,
    SecretAlreadyExists,
    SecretCreateError,
    SecretDescribeError,
    SecretNameInvalid,
    create_matlab_license_secret,
    describe_matlab_license_secret,
    validate_secret_name,
)

_ARN = ("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
       "cryostack/issm-matlab-license-AbCdEf")
_CFG = AWSConfig(region="us-east-2", credentials={
    "AWS_ACCESS_KEY_ID": "ASIA_X", "AWS_SECRET_ACCESS_KEY": "s",
    "AWS_SESSION_TOKEN": "t"})
_VALUE = "27000@do-not-leak-me.invalid"


def _fake_run_aws(*, code=0, stdout="", stderr=""):
    calls: list[dict] = []

    def fake(config, arguments, *, input=None):
        calls.append({"config": config, "arguments": list(arguments), "input": input})
        return code, stdout, stderr

    return fake, calls


# ── SECRET_NAME_PREFIX / validate_secret_name (before any AWS call) ─────
def test_secret_name_prefix_is_cryostack():
    assert SECRET_NAME_PREFIX == "cryostack/"


def test_empty_name_rejected():
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("")
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("   ")


def test_name_outside_cryostack_prefix_rejected():
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("my-secret")
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("issm-matlab-license")   # missing the prefix


def test_name_with_disallowed_characters_rejected():
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("cryostack/issm license!")
    with pytest.raises(SecretNameInvalid):
        validate_secret_name("cryostack/" + "x" * 600)   # too long


def test_valid_name_accepted_and_stripped():
    assert (validate_secret_name("  cryostack/issm-matlab-license  ")
           == "cryostack/issm-matlab-license")


# ── create_matlab_license_secret: call shape ─────────────────────────────
def test_create_secret_calls_run_aws_with_expected_region_and_name(monkeypatch):
    fake, calls = _fake_run_aws(
        stdout=json.dumps({"ARN": _ARN, "Name": "cryostack/issm-matlab-license"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    result = create_matlab_license_secret(
        _CFG, name="cryostack/issm-matlab-license", value=_VALUE)

    assert result == {"arn": _ARN, "name": "cryostack/issm-matlab-license"}
    assert len(calls) == 1
    call = calls[0]
    assert call["config"] is _CFG
    assert call["config"].region == "us-east-2"
    args = call["arguments"]
    assert args[:2] == ["secretsmanager", "create-secret"]
    assert args[args.index("--name") + 1] == "cryostack/issm-matlab-license"
    assert args[args.index("--secret-string") + 1] == "file:///dev/stdin"


def test_license_value_is_passed_only_via_stdin_never_argv(monkeypatch):
    fake, calls = _fake_run_aws(
        stdout=json.dumps({"ARN": _ARN, "Name": "cryostack/x"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    create_matlab_license_secret(_CFG, name="cryostack/x", value=_VALUE)

    call = calls[0]
    assert call["input"] == _VALUE                     # the ONLY place it travels
    assert _VALUE not in " ".join(call["arguments"])    # never on argv


def test_returned_metadata_never_includes_the_value(monkeypatch):
    fake, _calls = _fake_run_aws(
        stdout=json.dumps({"ARN": _ARN, "Name": "cryostack/x"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    result = create_matlab_license_secret(_CFG, name="cryostack/x", value=_VALUE)

    assert _VALUE not in json.dumps(result)
    assert set(result) == {"arn", "name"}


# ── errors ────────────────────────────────────────────────────────────
def test_missing_value_rejected_before_any_aws_call(monkeypatch):
    fake, calls = _fake_run_aws()
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(ValueError):
        create_matlab_license_secret(_CFG, name="cryostack/x", value="   ")
    assert calls == []


def test_invalid_name_rejected_before_any_aws_call(monkeypatch):
    fake, calls = _fake_run_aws()
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretNameInvalid):
        create_matlab_license_secret(_CFG, name="not-cryostack", value=_VALUE)
    assert calls == []


def test_duplicate_secret_name_raises_secret_already_exists(monkeypatch):
    fake, _calls = _fake_run_aws(
        code=254,
        stderr=("An error occurred (ResourceExistsException) when calling "
                 "the CreateSecret operation: The operation failed because "
                 "the secret cryostack/x already exists."))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretAlreadyExists):
        create_matlab_license_secret(_CFG, name="cryostack/x", value=_VALUE)


def test_access_denied_raises_secret_create_error_with_sanitized_message(monkeypatch):
    fake, _calls = _fake_run_aws(
        code=254,
        stderr=("An error occurred (AccessDeniedException) when calling "
                 "the CreateSecret operation: User: "
                 "arn:aws:sts::774888247882:assumed-role/x is not "
                 "authorized to perform: secretsmanager:CreateSecret"))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretCreateError) as exc:
        create_matlab_license_secret(_CFG, name="cryostack/x", value=_VALUE)
    assert "AccessDeniedException" in str(exc.value)
    assert _VALUE not in str(exc.value)


def test_missing_arn_in_response_raises_secret_create_error(monkeypatch):
    fake, _calls = _fake_run_aws(stdout=json.dumps({"Name": "cryostack/x"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretCreateError):
        create_matlab_license_secret(_CFG, name="cryostack/x", value=_VALUE)


# ── describe_matlab_license_secret: metadata-only recovery lookup ───────
def test_describe_secret_calls_run_aws_with_expected_shape(monkeypatch):
    fake, calls = _fake_run_aws(
        stdout=json.dumps({"ARN": _ARN, "Name": "cryostack/issm-matlab-license"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    result = describe_matlab_license_secret(
        _CFG, name="cryostack/issm-matlab-license")

    assert result == {"arn": _ARN, "name": "cryostack/issm-matlab-license"}
    assert len(calls) == 1
    call = calls[0]
    assert call["config"] is _CFG
    assert call["input"] is None                      # never writes anything
    args = call["arguments"]
    assert args[:2] == ["secretsmanager", "describe-secret"]
    assert args[args.index("--secret-id") + 1] == "cryostack/issm-matlab-license"
    # the value is never requested by this call at all -- no --version-id,
    # no --version-stage, nothing that could return SecretString/SecretBinary
    assert "get-secret-value" not in " ".join(args)


def test_describe_secret_returned_metadata_has_no_value_shaped_fields(monkeypatch):
    fake, _calls = _fake_run_aws(
        stdout=json.dumps({"ARN": _ARN, "Name": "cryostack/x"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    result = describe_matlab_license_secret(_CFG, name="cryostack/x")

    assert set(result) == {"arn", "name"}


def test_describe_secret_invalid_name_rejected_before_any_aws_call(monkeypatch):
    fake, calls = _fake_run_aws()
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretNameInvalid):
        describe_matlab_license_secret(_CFG, name="not-cryostack")
    assert calls == []


def test_describe_secret_not_found_or_denied_raises_secret_describe_error(monkeypatch):
    fake, _calls = _fake_run_aws(
        code=254,
        stderr=("An error occurred (AccessDeniedException) when calling "
                "the DescribeSecret operation: not authorized"))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretDescribeError) as exc:
        describe_matlab_license_secret(_CFG, name="cryostack/x")
    assert "AccessDeniedException" in str(exc.value)


def test_describe_secret_missing_arn_in_response_raises_secret_describe_error(monkeypatch):
    fake, _calls = _fake_run_aws(stdout=json.dumps({"Name": "cryostack/x"}))
    monkeypatch.setattr(secrets_mod, "run_aws", fake)

    with pytest.raises(SecretDescribeError):
        describe_matlab_license_secret(_CFG, name="cryostack/x")
