"""R1 — cross-model contract matrix.

For every supported model, the same facts must line up across the
ModelCapabilities registry, the result contract, the planning layer, and what
an agent can discover. If a third model is added, this test tells you exactly
which surface you forgot to wire.
"""
from __future__ import annotations

import pytest

from cryostack_src.agents import Permission, Trace, default_registry
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.planning import RunPlan, _RESULT_CONTRACT
from cryostack_src.models import SUPPORTED_MODELS, get_model_capabilities
from cryostack_src.models.results_common import (
    resolve_result_reader,
    resolve_visualizer,
)
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="r1-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_capabilities_and_planning_agree_on_the_result_contract(model):
    cap = get_model_capabilities(model)
    assert cap.result_contract == _RESULT_CONTRACT[model]
    p = RunPlan(application="icesheets", model=model, example="x",
                execution_mode="remote", compute_resource="pace", backend="spack")
    assert p.expected_result_contract == cap.result_contract


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_cloud_capability_is_enforced_at_plan_construction(model):
    cap = get_model_capabilities(model)
    kw = dict(application="icesheets", model=model, example="x",
              execution_mode="cloud", compute_resource="pace", backend="container")
    if cap.cloud_supported:
        RunPlan(**kw)                       # constructs fine
    else:
        with pytest.raises(ValueError, match="cloud"):
            RunPlan(**kw)                   # an impossible plan is not constructible


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_result_reader_and_visualizer_resolve_per_capabilities(model, tmp_path):
    cap = get_model_capabilities(model)
    pkg = resolve_result_reader(model)(tmp_path)
    assert pkg.is_readable() is False               # empty dir
    assert callable(getattr(pkg, "available_solutions"))
    viz = resolve_visualizer(model)
    assert (viz is not None) == cap.visualization


@pytest.mark.parametrize("model", SUPPORTED_MODELS)
def test_agent_can_discover_every_supported_model(model):
    reg = default_registry()
    ctx = _ctx(Permission.OBSERVE)
    listed = {m["name"] for m in reg.invoke("list_models", ctx).value}
    caps = {c["name"] for c in reg.invoke("list_model_capabilities", ctx).value}
    assert model in listed and model in caps


def test_matrix_is_exhaustive():
    # the registry, the adapters map, and the planning tuple are the same set
    from cryostack_src.models import MODEL_CAPABILITIES
    from cryostack_src.agents.readonly_tools import _MODELS
    assert set(SUPPORTED_MODELS) == set(MODEL_CAPABILITIES) == set(_MODELS)
    assert set(_RESULT_CONTRACT) == set(SUPPORTED_MODELS)
