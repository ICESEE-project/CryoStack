"""The single authoritative workflow-capability resolver.

MATLAB/ISSM behavior must never be keyed on the top-level model name alone
-- an ICESEE run whose forecast model is ISSM needs a MATLAB license exactly
like a direct ISSM run does, and an ICESEE run using only Icepack does not.
"""
from __future__ import annotations

from cryostack_src.cloud.drivers.aws.batch_config import (
    GPU_IMAGE_QUALIFIED,
    MULTINODE_RUNTIME_SUPPORTED,
)
from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities


def test_direct_icepack():
    cap = resolve_workflow_capabilities(model="icepack")
    assert cap.uses_icepack is True
    assert cap.uses_issm is False
    assert cap.requires_matlab_license is False


def test_direct_issm():
    cap = resolve_workflow_capabilities(model="issm")
    assert cap.uses_issm is True
    assert cap.uses_icepack is False
    assert cap.requires_matlab_license is True


def test_icesee_using_icepack_only():
    cap = resolve_workflow_capabilities(model="icesee", forecast_model="icepack")
    assert cap.uses_icepack is True
    assert cap.uses_issm is False
    assert cap.requires_matlab_license is False


def test_icesee_using_issm():
    cap = resolve_workflow_capabilities(model="icesee", forecast_model="issm")
    assert cap.uses_issm is True
    assert cap.uses_icepack is False
    assert cap.requires_matlab_license is True


def test_icesee_using_both():
    cap = resolve_workflow_capabilities(
        model="icesee", forecast_model="issm+icepack coupled")
    assert cap.uses_issm is True
    assert cap.uses_icepack is True
    assert cap.requires_matlab_license is True


def test_icesee_using_neither_needs_no_license():
    # the synthetic Lorenz-96 example: no external forward model at all
    cap = resolve_workflow_capabilities(model="icesee", forecast_model="lorenz96")
    assert cap.uses_issm is False
    assert cap.uses_icepack is False
    assert cap.requires_matlab_license is False


def test_forecast_model_match_is_case_insensitive():
    cap = resolve_workflow_capabilities(model="icesee", forecast_model="ISSM")
    assert cap.uses_issm is True


def test_unknown_model_is_neutral():
    cap = resolve_workflow_capabilities(model="something-unknown")
    assert cap.uses_issm is False and cap.uses_icepack is False
    assert cap.requires_matlab_license is False


def test_ec2_gpu_multinode_mirror_the_single_global_qualification_flags():
    # never re-derived per model -- same source cloud/drivers/aws/batch_config
    # uses for the actual submission gate.
    for model in ("issm", "icepack"):
        cap = resolve_workflow_capabilities(model=model)
        assert cap.supports_ec2 is True
        assert cap.supports_gpu == GPU_IMAGE_QUALIFIED
        assert cap.supports_multinode == MULTINODE_RUNTIME_SUPPORTED
