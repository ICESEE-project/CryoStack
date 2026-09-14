"""P1: the ModelCapabilities registry stays consistent with the adapters and
subsystems it summarises."""
from __future__ import annotations

import pytest

from cryostack_src.cloud.runtime import SUPPORTED_CLOUD_MODELS
from cryostack_src.models import (
    SUPPORTED_MODELS,
    get_model_adapter,
    get_model_capabilities,
)
from cryostack_src.models.capabilities import MODEL_CAPABILITIES


def test_every_supported_model_has_an_adapter_and_capabilities():
    for name in SUPPORTED_MODELS:
        assert get_model_adapter(name) is not None
        cap = get_model_capabilities(name)
        assert cap.name == name
        assert cap.result_contract.startswith("cryostack.")


def test_unknown_model_raises():
    with pytest.raises(ValueError):
        get_model_capabilities("firedrake-but-not-really")


def test_cloud_support_matches_cloud_runtime():
    for name, cap in MODEL_CAPABILITIES.items():
        assert cap.cloud_supported == (name in SUPPORTED_CLOUD_MODELS)
        assert ("cloud" in cap.execution_modes) == cap.cloud_supported


def test_matlab_requirement_matches_language():
    assert get_model_capabilities("issm").requires_matlab is True
    assert get_model_capabilities("icepack").requires_matlab is False


def test_basic_mode_flag_matches_the_adapter():
    from cryostack_src.models.icepack import HAS_BASIC_CONFIG
    assert get_model_capabilities("icepack").basic_mode_config == HAS_BASIC_CONFIG
    from cryostack_src.models.issm import CURATED_MD_PARAMETERS
    assert get_model_capabilities("issm").basic_mode_config == bool(CURATED_MD_PARAMETERS)


def test_agent_layer_consumes_the_registry():
    # the agent tuple is the registry's, not a private copy
    from cryostack_src.agents.readonly_tools import _MODELS as agent_models
    from cryostack_src.agents.planning import _RESULT_CONTRACT
    assert tuple(agent_models) == SUPPORTED_MODELS
    for name, cap in MODEL_CAPABILITIES.items():
        assert _RESULT_CONTRACT[name] == cap.result_contract
