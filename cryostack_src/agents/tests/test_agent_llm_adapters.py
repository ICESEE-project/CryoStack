"""Provider adapter boundary (PASS 4, task 8): a provider only ever sees
declarative tool descriptions; the rule-based stub is deterministic and
network-free; nothing here imports an SDK or reads a key."""
from __future__ import annotations

import os

import pytest

from cryostack_src.agents import (
    AnthropicAdapterSkeleton,
    OpenAIAdapterSkeleton,
    Permission,
    RuleBasedAdapter,
    RunAssistant,
    Trace,
    assert_declarative_tools,
    default_registry,
)
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.llm import LLMMessage
from cryostack_src.workspace import WorkspaceUser

_USER = WorkspaceUser(user_id="llm-u", source="cryostack-auth")


def _ctx(perm=Permission.PLAN):
    return ToolContext(user=_USER, application="icesheets", max_permission=perm,
                       trace=Trace(user_id=_USER.user_id))


@pytest.fixture(autouse=True)
def _icepack_root(monkeypatch):
    p = "/home/bkyanjo3/icepack"
    if os.path.isdir(p):
        monkeypatch.setenv("ICEPACK_ROOT", p)


# ── the declarative guard ────────────────────────────────────────────
def test_registry_describe_is_all_declarative():
    tools = default_registry().describe(ctx=_ctx())
    assert_declarative_tools(tools)                 # no raise
    for t in tools:
        assert isinstance(t["name"], str)
        assert "parameters" in t


def test_guard_rejects_a_callable_in_a_tool_spec():
    with pytest.raises(TypeError):
        assert_declarative_tools([{"name": "x", "run": lambda: None}])


def test_guard_rejects_a_bridge_like_object():
    class _Bridge:
        def submit(self):  # behaviour, not data
            ...
    with pytest.raises(TypeError):
        assert_declarative_tools([{"name": "x", "backend": _Bridge()}])


def test_base_adapter_runs_the_guard_on_every_call():
    class _A(AnthropicAdapterSkeleton):
        def _complete(self, *, system, messages, tools):
            from cryostack_src.agents.llm import LLMResponse
            return LLMResponse(text="ok")
    with pytest.raises(TypeError):
        _A().complete(system="s", messages=[], tools=[{"name": "x",
                                                       "fn": print}])


# ── skeletons import nothing, read nothing, call nothing ─────────────
def test_skeletons_raise_not_implemented():
    for cls in (AnthropicAdapterSkeleton, OpenAIAdapterSkeleton):
        with pytest.raises(NotImplementedError):
            cls().complete(system="s", messages=[], tools=[])


def test_no_sdk_import_in_the_adapters_module():
    import ast

    import cryostack_src.agents.llm_adapters as m
    tree = ast.parse(open(m.__file__).read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("anthropic", "openai", "requests", "httpx", "urllib",
                   "boto3", "google"):
        assert banned not in imported


# ── the rule-based stub ──────────────────────────────────────────────
def test_rule_based_adapter_is_deterministic_and_needs_no_network():
    a = RuleBasedAdapter(default_example="02-synthetic-ice-shelf")
    b = RuleBasedAdapter(default_example="02-synthetic-ice-shelf")
    kw = dict(system="s", tools=[{"name": "prepare_run_plan", "parameters": {}}],
              messages=[LLMMessage("user", "run icepack at 250 K on pace")])
    assert a.complete(**kw).tool_calls == b.complete(**kw).tool_calls


def test_rule_based_adapter_only_uses_a_value_the_user_stated():
    a = RuleBasedAdapter(default_example="02-synthetic-ice-shelf")
    r = a.complete(system="s",
                   tools=[{"name": "prepare_run_plan", "parameters": {}}],
                   messages=[LLMMessage("user", "run icepack at 250 K on pace")])
    (call,) = r.tool_calls
    assert call.arguments["parameter_overrides"] == {"ice_temperature": 250.0}

    b = RuleBasedAdapter(default_example="02-synthetic-ice-shelf")
    r2 = b.complete(system="s",
                    tools=[{"name": "prepare_run_plan", "parameters": {}}],
                    messages=[LLMMessage("user", "run icepack on pace")])
    (call2,) = r2.tool_calls
    assert "parameter_overrides" not in call2.arguments   # nothing invented


def test_rule_based_adapter_never_emits_approve_or_execute():
    a = RuleBasedAdapter(default_example="e")
    for msg in ("run it and submit", "approve and execute now", "just run rm -rf"):
        r = a.complete(system="s",
                       tools=[{"name": "prepare_run_plan", "parameters": {}},
                              {"name": "validate_run_plan", "parameters": {}}],
                       messages=[LLMMessage("user", msg)])
        for c in r.tool_calls:
            assert c.name in ("prepare_run_plan", "validate_run_plan")


def test_rule_based_adapter_drives_the_assistant_end_to_end():
    if not os.path.isdir("/home/bkyanjo3/icepack"):
        pytest.skip("icepack examples not resolvable here")
    adapter = RuleBasedAdapter(default_example="02-synthetic-ice-shelf")
    res = RunAssistant(llm=adapter).handle(
        _ctx(), "run icepack on pace with ice temperature 260 K, account gts")
    assert res.submitted is False
    if res.proposed_plan is not None:
        assert res.proposed_plan["parameter_overrides"] == {"ice_temperature": 260.0}
