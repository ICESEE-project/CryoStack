"""Agent core: permission ceiling, identity binding, confirmation gate, trace
redaction, policy scan (A2 + A3)."""
from __future__ import annotations

from datetime import datetime

import pytest

from cryostack_src.agents import (
    Permission, PermissionError, Trace, build_tool_context, default_registry,
)
from cryostack_src.agents.context import ToolContext
from cryostack_src.agents.policy import (
    assert_tool_modules_are_clean, scan_tool_module,
)
from cryostack_src.agents.tools import ToolSpec, tool
from cryostack_src.agents.trace import redact
from cryostack_src.workspace import WorkspaceManager, WorkspaceUser
from cryostack_src.workspace.identity import WorkspaceIdentityError
from cryostack_src.workspace.models import RunInfo

_AUTH = WorkspaceUser(user_id="agent-u1", source="cryostack-auth")
_OTHER = WorkspaceUser(user_id="agent-u2", source="cryostack-auth")


class _W:
    def __init__(self, v=""):
        self.value, self.options = v, ()


def _mgr(owner, root):
    return WorkspaceManager(
        owner=owner, workspace_root=root, status={}, session={"id": "s"},
        example_dir=_W(str(root)), model="icepack", backend=_W("spack"),
        file_picker=_W(), file_editor=_W(), log_output=None, results_output=None,
        cluster_host=_W(""), cluster_user=_W(""), cluster_port=_W(1),
        access_mode=_W(""), normalize_remote_path=lambda p: p,
        connector_fetch_archive=None, should_use_connector=lambda: False,
        connector_ssh=None, ssh_run=None, cluster_name=_W(""),
    )


def _ctx(user=_AUTH, *, perm=Permission.PLAN, mgr=None):
    return ToolContext(user=user, application="icesheets", max_permission=perm,
                       workspace_manager=mgr, trace=Trace(user_id=user.user_id))


# ── identity ─────────────────────────────────────────────────────────
def test_context_refuses_anonymous_identity():
    with pytest.raises(WorkspaceIdentityError):
        ToolContext(user=WorkspaceUser(user_id="anonymous", source="unauthenticated"),
                    application="icesheets", max_permission=Permission.OBSERVE)


def test_context_refuses_unknown_application():
    with pytest.raises(ValueError):
        ToolContext(user=_AUTH, application="hacker-app", max_permission=Permission.OBSERVE)


def test_build_tool_context_is_fail_closed(monkeypatch):
    monkeypatch.delenv("CRYOSTACK_WORKSPACE_USER", raising=False)
    monkeypatch.delenv("HTTP_X_CRYOSTACK_USER_ID", raising=False)
    with pytest.raises(WorkspaceIdentityError):
        build_tool_context(application="icesheets", env={})


def test_ceiling_can_only_go_down():
    c = _ctx(perm=Permission.EXECUTE)
    assert c.with_ceiling(Permission.OBSERVE).max_permission == Permission.OBSERVE
    assert c.with_ceiling(Permission.DESTRUCTIVE).max_permission == Permission.EXECUTE


# ── permission ceiling ──────────────────────────────────────────────
def test_registry_refuses_under_privileged_call():
    from cryostack_src.agents.registry import ToolRegistry
    from cryostack_src.agents.tools import Tool, ToolSpec, drain_pending
    drain_pending()
    reg = ToolRegistry()

    @tool(name="_t_execute_probe", description="x", permission=Permission.EXECUTE,
          read_only=False, requires_confirmation=True, scientific_effect="submits a job")
    def _probe(ctx):
        return "ran"

    reg.register_module_tools()
    r = reg.invoke("_t_execute_probe", _ctx(perm=Permission.PLAN), confirm=True)
    assert r.ok is False and "permission denied" in r.error


def test_confirmation_gate():
    from cryostack_src.agents.registry import ToolRegistry
    from cryostack_src.agents.tools import drain_pending
    drain_pending()
    reg = ToolRegistry()

    @tool(name="_t_prepare_probe", description="x", permission=Permission.PREPARE,
          read_only=False, requires_confirmation=True,
          scientific_effect="stages a working copy")
    def _probe(ctx):
        return "staged"

    reg.register_module_tools()
    c = _ctx(perm=Permission.PREPARE)
    assert reg.invoke("_t_prepare_probe", c).ok is False          # no confirm
    assert reg.invoke("_t_prepare_probe", c, confirm=True).ok is True


def test_discovery_is_permission_filtered():
    reg = default_registry()
    observe = {s.name for s in reg.specs(ctx=_ctx(perm=Permission.OBSERVE))}
    assert "list_models" in observe
    # no EXECUTE/DESTRUCTIVE tool visible to an OBSERVE context
    assert all(s.permission <= Permission.OBSERVE
               for s in reg.specs(ctx=_ctx(perm=Permission.OBSERVE)))


# ── ToolSpec invariants ─────────────────────────────────────────────
def test_read_only_tool_cannot_need_more_than_plan():
    with pytest.raises(ValueError):
        ToolSpec(name="x", description="", permission=Permission.EXECUTE,
                 read_only=True, requires_confirmation=False, scientific_effect="none")


def test_mutating_tool_must_declare_a_scientific_effect():
    with pytest.raises(ValueError):
        ToolSpec(name="x", description="", permission=Permission.PREPARE,
                 read_only=False, requires_confirmation=True, scientific_effect="none")


# ── trace redaction ─────────────────────────────────────────────────
def test_trace_redacts_secrets():
    t = Trace()
    t.append("tool_call", {"args": {"password": "hunter2", "host": "h"},
                           "note": "-----BEGIN OPENSSH PRIVATE KEY-----abc"})
    blob = t.to_json()
    assert "hunter2" not in blob and "PRIVATE KEY" not in blob
    assert '"host": "h"' in blob


@pytest.mark.parametrize("payload", [
    {"aws_secret_access_key": "x"}, {"pairing_code": "ABCDE-FGHJK"},
    {"matlab_license": "1711@matlablic.ecs.gatech.edu"},
    {"nested": [{"token": "t"}]},
])
def test_redact_covers_more_secret_shapes(payload):
    out = redact(payload)
    assert "x" not in str(out) or "***" in str(out)
    assert "1711@matlablic" not in str(out)
    assert "ABCDE-FGHJK" not in str(out) or "***" in str(out)


# ── policy: no prohibited symbols in tool modules ───────────────────
def test_tool_modules_do_not_import_arbitrary_command_or_secret_surface():
    assert_tool_modules_are_clean()


def test_policy_scan_catches_a_planted_violation(tmp_path):
    bad = tmp_path / "bad_tool.py"
    bad.write_text("from x import connector_ssh\ndef t(ctx): return send_command(1)\n")
    found = scan_tool_module(bad)
    assert "connector_ssh" in found and "send_command" in found


# ── read-only tools: user isolation ────────────────────────────────
def test_list_runs_is_scoped_to_the_context_user(tmp_path):
    reg = default_registry()
    root = tmp_path / "ws"
    a = _mgr(_AUTH, root)
    b = _mgr(_OTHER, root)
    a.register_run(RunInfo(id="r-a", name="r-a", model="icepack", backend="spack",
                           execution_mode="remote", status="completed",
                           created=datetime.now(), jobid="j"))
    b.register_run(RunInfo(id="r-b", name="r-b", model="icepack", backend="spack",
                           execution_mode="remote", status="completed",
                           created=datetime.now(), jobid="j"))

    ra = reg.invoke("list_runs", _ctx(_AUTH, mgr=a))
    rb = reg.invoke("list_runs", _ctx(_OTHER, mgr=b))
    assert {x["id"] for x in ra.value} == {"r-a"}
    assert {x["id"] for x in rb.value} == {"r-b"}
    # A's context cannot inspect B's run id
    assert reg.invoke("inspect_run", _ctx(_AUTH, mgr=a), run_id="r-b").ok is False


def test_resource_tool_never_returns_the_matlab_license_value():
    reg = default_registry()
    r = reg.invoke("inspect_resource_requirements", _ctx(), resource="pace")
    assert r.ok
    assert "1711@matlablic" not in str(r.value)
    assert r.value["matlab_license_configured"] is True
