"""The agent CORE (permissions / context / trace / approval / execution /
planning / store / fingerprint / llm) must not hard-depend on the
`icesee_jupyter_book` UI package — only the two tool modules that resolve
examples / Slurm rules may, and only lazily (PASS 4; PASS-3 audit §3a).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

_AGENTS = Path(__file__).resolve().parent.parent

_CORE = [
    "permissions", "context", "trace", "trace_store", "tools", "registry",
    "policy", "planning", "approval", "execution", "experiment", "fingerprint",
    "store", "llm", "llm_adapters", "assistant", "inspect", "eval",
]
#: allowed to import the UI package, and only inside a function body
_LAZY_UI_OK = {"readonly_tools", "planning_tools"}


def _module_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in tree.body:                      # module level only
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_core_modules_have_no_module_level_ui_import():
    offenders = []
    for name in _CORE:
        p = _AGENTS / f"{name}.py"
        if not p.is_file():
            continue
        if "icesee_jupyter_book" in _module_level_imports(p):
            offenders.append(name)
    assert not offenders, f"core agent modules import the UI at module level: {offenders}"


def test_the_two_tool_modules_only_import_ui_lazily():
    for name in _LAZY_UI_OK:
        p = _AGENTS / f"{name}.py"
        # not at module level ...
        assert "icesee_jupyter_book" not in _module_level_imports(p), name
        # ... but somewhere in the file (a function body)
        assert "icesee_jupyter_book" in p.read_text(), name


def test_core_imports_with_the_ui_package_unavailable():
    """A fresh interpreter that cannot see `icesee_jupyter_book` must still
    import the agent core and build a context / plan / approval."""
    code = (
        "import sys, types\n"
        "sys.modules['icesee_jupyter_book'] = None\n"   # force ImportError on use
        "from cryostack_src.agents import (Permission, RunPlan, SlurmRequest,\n"
        "    PlanStore, Trace, RunInputFingerprint, ManagedPlan)\n"
        "from cryostack_src.agents.context import ToolContext\n"
        "from cryostack_src.agents.execution import DryRunExecutionCoordinator\n"
        "from cryostack_src.workspace import WorkspaceUser\n"
        "u = WorkspaceUser(user_id='nodep', source='cryostack-auth')\n"
        "ctx = ToolContext(user=u, application='icesheets',\n"
        "    max_permission=Permission.EXECUTE, trace=Trace())\n"
        "p = RunPlan(application='icesheets', model='issm', example='x',\n"
        "    execution_mode='remote', compute_resource='pace', backend='spack',\n"
        "    run_target='runme.m',\n"
        "    slurm=SlurmRequest(job_name='ISSM', wall_time='01:00:00', account='a'))\n"
        "s = PlanStore(); mp = s.create(owner=u, plan=p)\n"
        "mp.mark_validated(mp.plan); mp.submit_for_approval(); mp.approve(u)\n"
        "print('OK', mp.plan.digest()[:8])\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OK ")
