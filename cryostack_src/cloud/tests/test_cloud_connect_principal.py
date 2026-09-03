"""C7.2 -- the deployment-configured CryoStack AWS principal ARN."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import pytest

from cryostack_src.cloud.connect.principal import (
    PRINCIPAL_ENV,
    PrincipalNotConfiguredError,
    cryostack_principal_arn,
    is_valid_principal_arn,
)


def test_missing_env_raises_a_clear_actionable_error():
    with pytest.raises(PrincipalNotConfiguredError) as err:
        cryostack_principal_arn(env={})
    assert PRINCIPAL_ENV in str(err.value)


def test_malformed_arn_is_rejected():
    with pytest.raises(PrincipalNotConfiguredError):
        cryostack_principal_arn(env={PRINCIPAL_ENV: "not-an-arn"})


@pytest.mark.parametrize(
    "arn",
    [
        "arn:aws:iam::713938953301:role/cryostack-service",
        "arn:aws:iam::713938953301:root",
        "arn:aws:sts::713938953301:assumed-role/cryostack/session",
    ],
)
def test_valid_principal_arns_pass(arn):
    assert is_valid_principal_arn(arn)
    assert cryostack_principal_arn(env={PRINCIPAL_ENV: arn}) == arn


def test_no_personal_or_root_arn_is_hardcoded_in_product_code():
    src = (Path(__file__).resolve().parents[1] / "connect").glob("*.py")
    for path in src:
        text = path.read_text(encoding="utf-8")
        # no bare 12-digit account embedded in an ARN literal in the module body
        assert "arn:aws:iam::7" not in text, path.name
        assert "arn:aws:iam::1" not in text, path.name
