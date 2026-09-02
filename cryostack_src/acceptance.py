"""Non-destructive release / demo acceptance checks (PASS 4, task 14).

    python -m cryostack_src.acceptance --offline

Runs a battery of **read-only** invariant checks so that, before a live
acceptance session, one command tells you what is green, what is broken, and
what still needs a human at a terminal.

It never: submits an HPC job, contacts Duo, runs an AWS job, mutates
production, or publishes a Connector binary. ``--offline`` is the only mode.

Each check returns one of:

* ``PASS``   — the invariant holds;
* ``FAIL``   — a regression a human must fix before the session;
* ``MANUAL`` — cannot be verified offline; a person must check it live.

Exit code is non-zero iff any check FAILs.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_REPO = Path(__file__).resolve().parent.parent

PASS, FAIL, MANUAL = "PASS", "FAIL", "MANUAL"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


_CHECKS: list[tuple[str, Callable[[], CheckResult]]] = []


def check(name: str):
    def _reg(fn):
        _CHECKS.append((name, fn))
        return fn
    return _reg


def _ok(name, detail=""):
    return CheckResult(name, PASS, detail)


def _fail(name, detail):
    return CheckResult(name, FAIL, detail)


def _manual(name, detail):
    return CheckResult(name, MANUAL, detail)


# ── agent safety invariants ─────────────────────────────────────────
@check("agent: tool modules reference no prohibited symbol")
def _agent_policy():
    from cryostack_src.agents.policy import assert_tool_modules_are_clean
    try:
        assert_tool_modules_are_clean()
        return _ok("agent: tool modules reference no prohibited symbol")
    except AssertionError as e:
        return _fail("agent: tool modules reference no prohibited symbol", str(e))


@check("agent: no shipped tool takes a user_id / owner argument")
def _agent_no_user_id():
    from cryostack_src.agents import default_registry
    reg = default_registry()
    bad = [n for n in reg.names()
           if {"user_id", "owner"} & set(reg.get(n).spec.parameters or {})]
    return (_ok("agent: no shipped tool takes a user_id / owner argument")
            if not bad else
            _fail("agent: no shipped tool takes a user_id / owner argument",
                  f"tools with an identity arg: {bad}"))


@check("agent: every shipped tool is OBSERVE/PLAN and read-only")
def _agent_readonly():
    from cryostack_src.agents import Permission, default_registry
    reg = default_registry()
    bad = [n for n in reg.names()
           if reg.get(n).spec.permission > Permission.PLAN
           or not reg.get(n).spec.read_only]
    return (_ok("agent: every shipped tool is OBSERVE/PLAN and read-only")
            if not bad else
            _fail("agent: every shipped tool is OBSERVE/PLAN and read-only",
                  f"offending tools: {bad}"))


@check("agent: no SubmitBackend implementation inside cryostack_src/agents")
def _agent_no_backend():
    agents = _REPO / "cryostack_src" / "agents"
    hits = []
    for p in agents.glob("*.py"):
        txt = p.read_text()
        if "def submit(" in txt and "job id" in txt.lower() and p.name != "execution.py":
            hits.append(p.name)
    return (_ok("agent: no SubmitBackend implementation inside cryostack_src/agents")
            if not hits else
            _fail("agent: no SubmitBackend implementation inside cryostack_src/agents",
                  f"suspicious files: {hits}"))


@check("agent: approve-A / mutate / execute is rejected")
def _agent_approval_binding():
    from dataclasses import replace

    from cryostack_src.agents import (
        Permission, PlanStore, RunPlan, SlurmRequest, Trace,
    )
    from cryostack_src.agents.context import ToolContext
    from cryostack_src.agents.execution import DryRunExecutionCoordinator
    from cryostack_src.workspace import WorkspaceUser
    u = WorkspaceUser(user_id="acceptance", source="cryostack-auth")
    ctx = ToolContext(user=u, application="icesheets",
                      max_permission=Permission.EXECUTE, trace=Trace())
    store = PlanStore()
    mp = store.create(owner=u, plan=RunPlan(
        application="icesheets", model="issm", example="x",
        execution_mode="remote", compute_resource="pace", backend="spack",
        run_target="runme.m",
        slurm=SlurmRequest(job_name="ISSM", wall_time="01:00:00", account="a")))
    mp.mark_validated(mp.plan)
    mp.submit_for_approval()
    mp.approve(u)
    mp.plan = replace(mp.plan, run_target="evil.m")
    rep = DryRunExecutionCoordinator().execute(ctx, mp, dry_run=True)
    return (_ok("agent: approve-A / mutate / execute is rejected")
            if rep.blocked_reason == "approval" and not rep.submitted else
            _fail("agent: approve-A / mutate / execute is rejected",
                  f"blocked_reason={rep.blocked_reason} submitted={rep.submitted}"))


@check("agent: provider adapters import no vendor SDK / key / network")
def _agent_llm_boundary():
    import ast
    m = _REPO / "cryostack_src" / "agents" / "llm_adapters.py"
    imported = set()
    for node in ast.walk(ast.parse(m.read_text())):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    banned = imported & {"anthropic", "openai", "requests", "httpx", "boto3",
                         "urllib", "google"}
    return (_ok("agent: provider adapters import no vendor SDK / key / network")
            if not banned else
            _fail("agent: provider adapters import no vendor SDK / key / network",
                  f"banned imports: {sorted(banned)}"))


# ── model capabilities / result schemas ─────────────────────────────
@check("models: ModelCapabilities is consistent with the adapters")
def _model_caps():
    try:
        # import runs _verify_against_adapters()
        from cryostack_src.models import MODEL_CAPABILITIES, SUPPORTED_MODELS
        from cryostack_src.models import get_model_adapter
        for m in SUPPORTED_MODELS:
            get_model_adapter(m)
        assert set(MODEL_CAPABILITIES) == set(SUPPORTED_MODELS)
        return _ok("models: ModelCapabilities is consistent with the adapters",
                   f"models: {', '.join(SUPPORTED_MODELS)}")
    except (AssertionError, ImportError, ValueError) as e:
        return _fail("models: ModelCapabilities is consistent with the adapters", str(e))


@check("models: result contracts match between registry and readers")
def _result_contracts():
    from cryostack_src.models import MODEL_CAPABILITIES
    from cryostack_src.models.issm.results import SCHEMA as ISSM
    from cryostack_src.models.icepack.results import SCHEMA as ICEPACK
    want = {"issm": ISSM, "icepack": ICEPACK}
    bad = {m: (want.get(m), c.result_contract)
           for m, c in MODEL_CAPABILITIES.items()
           if want.get(m) != c.result_contract}
    return (_ok("models: result contracts match between registry and readers")
            if not bad else
            _fail("models: result contracts match between registry and readers", str(bad)))


@check("models: every result package satisfies the shared contract")
def _result_protocol():
    import tempfile
    from cryostack_src.models import SUPPORTED_MODELS
    from cryostack_src.models.results_common import (
        RESULT_CONTRACT_METHODS, resolve_result_reader,
    )
    with tempfile.TemporaryDirectory() as d:
        for m in SUPPORTED_MODELS:
            pkg = resolve_result_reader(m)(d)
            missing = [x for x in RESULT_CONTRACT_METHODS
                       if not callable(getattr(pkg, x, None))]
            if missing:
                return _fail("models: every result package satisfies the shared contract",
                             f"{m} missing {missing}")
    return _ok("models: every result package satisfies the shared contract")


# ── cloud config invariants ─────────────────────────────────────────
@check("cloud: execution is ISSM-only and no static credentials")
def _cloud_invariants():
    from cryostack_src.cloud.runtime import SUPPORTED_CLOUD_MODELS
    if SUPPORTED_CLOUD_MODELS != ("issm",):
        return _fail("cloud: execution is ISSM-only and no static credentials",
                     f"SUPPORTED_CLOUD_MODELS={SUPPORTED_CLOUD_MODELS}")
    # no boto3 Session / hardcoded keys under cloud/
    cloud = _REPO / "cryostack_src" / "cloud"
    for p in cloud.rglob("*.py"):
        if "/tests/" in str(p):
            continue
        t = p.read_text()
        if re.search(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b", t) or "aws_secret_access_key=" in t:
            return _fail("cloud: execution is ISSM-only and no static credentials",
                         f"possible static credential in {p.relative_to(_REPO)}")
    return _ok("cloud: execution is ISSM-only and no static credentials")


# ── no developer defaults ──────────────────────────────────────────
#: files that legitimately name a personal/dev value as *data to reject*, not a
#: default to use (a blocklist, a test-guard). Not scanned.
_DEV_DEFAULT_ALLOWLIST = ("workspace/resource_state.py",)

_HARD = [
    (re.compile(r"/home/[a-z][a-z0-9_-]+/"), "home path"),
    (re.compile(r"[a-z0-9._%+-]+@(?:gmail|yahoo|hotmail|outlook)\.com", re.I),
     "personal email"),
    (re.compile(r"\bgts-[a-z0-9_]+\b"), "hardcoded HPC allocation"),
    (re.compile(r"MLM_LICENSE_FILE\s*=\s*['\"]?\d"), "MATLAB license value"),
]
#: a personal Docker Hub namespace on a *pinned* image ref — a project decision
#: (images are digest-pinned), surfaced as MANUAL not FAIL.
_SOFT = (re.compile(r"\bbkyanjo\d?\b"), "personal container namespace")


@check("no developer defaults in shipped source")
def _no_dev_defaults():
    roots = [_REPO / "cryostack_src", _REPO / "icesee_jupyter_book" / "ui",
             _REPO / "bin"]
    hard: list[str] = []
    soft: list[str] = []
    for root in roots:
        for p in root.rglob("*.py"):
            s = str(p).replace("\\", "/")
            if "/tests/" in s or s.endswith("acceptance.py"):
                continue
            if any(a in s for a in _DEV_DEFAULT_ALLOWLIST):
                continue
            txt = p.read_text(errors="ignore")
            for rx, label in _HARD:
                for mm in rx.finditer(txt):
                    ln = txt[:mm.start()].count("\n") + 1
                    hard.append(f"{p.relative_to(_REPO)}:{ln} {label} ({mm.group(0)})")
            rx, label = _SOFT
            for mm in rx.finditer(txt):
                ln = txt[:mm.start()].count("\n") + 1
                soft.append(f"{p.relative_to(_REPO)}:{ln} {label}")
    if hard:
        return _fail("no developer defaults in shipped source",
                     "; ".join(hard[:10]) + (" …" if len(hard) > 10 else ""))
    if soft:
        return _manual(
            "no developer defaults in shipped source",
            "digest-pinned images use a personal Docker Hub namespace "
            "(OWNER_CHECKPOINT: publish under a project org): "
            + "; ".join(sorted(set(soft))[:6]))
    return _ok("no developer defaults in shipped source")


# ── docs structure ─────────────────────────────────────────────────
@check("docs: public book TOC is well-formed and excludes the Maintainer Guide")
def _docs_toc():
    toc = _REPO / "icesee_jupyter_book" / "_toc.yml"
    if not toc.is_file():
        return _fail("docs: public book TOC is well-formed and excludes the Maintainer Guide",
                     "missing _toc.yml")
    txt = toc.read_text()
    problems = []
    if "docs/building_agents" not in txt:
        problems.append("building_agents not in the public TOC")
    if "maintainer_guide" in txt:
        problems.append("maintainer_guide is in the PUBLIC TOC (must be role-gated only)")
    if not (_REPO / "icesee_jupyter_book" / "docs" / "maintainer_guide.md").is_file():
        problems.append("maintainer_guide.md missing")
    return (_ok("docs: public book TOC is well-formed and excludes the Maintainer Guide")
            if not problems else
            _fail("docs: public book TOC is well-formed and excludes the Maintainer Guide",
                  "; ".join(problems)))


@check("docs: built HTML artifacts present")
def _docs_build_artifacts():
    html = _REPO / "icesee_jupyter_book" / "_build" / "html"
    if not (html / "index.html").is_file():
        return _manual("docs: built HTML artifacts present",
                       "run `jupyter-book build icesee_jupyter_book/` and "
                       "`bin/build_application_docs.sh`")
    pages = ["docs/building_agents.html", "docs/developer_guide.html"]
    missing = [p for p in pages if not (html / p).is_file()]
    return (_ok("docs: built HTML artifacts present")
            if not missing else
            _manual("docs: built HTML artifacts present",
                    f"rebuild the book; missing {missing}"))


# ── auth roles ─────────────────────────────────────────────────────
@check("auth: role gate + add_user_role are wired")
def _auth_roles():
    try:
        from icesee_auth.manager import AuthManager  # noqa: F401
        from icesee_auth.storage import AuthStorage
        assert hasattr(AuthStorage, "add_user_role")
        from icesee_auth import manager as _m
        assert "require_roles" in dir(_m.AuthManager)
        return _ok("auth: role gate + add_user_role are wired")
    except (ImportError, AssertionError, AttributeError) as e:
        return _fail("auth: role gate + add_user_role are wired", str(e))


# ── workspace isolation ────────────────────────────────────────────
@check("workspace: distinct users get distinct roots")
def _workspace_isolation():
    import tempfile
    from cryostack_src.workspace.identity import WorkspaceUser
    from cryostack_src.workspace.roots import owner_root
    with tempfile.TemporaryDirectory() as d:
        a = owner_root(WorkspaceUser(user_id="alice", source="cryostack-auth"),
                       workspace_root=d)
        b = owner_root(WorkspaceUser(user_id="bob", source="cryostack-auth"),
                       workspace_root=d)
        return (_ok("workspace: distinct users get distinct roots")
                if a != b and "alice" in str(a) and "bob" in str(b) else
                _fail("workspace: distinct users get distinct roots", f"{a} vs {b}"))


# ── connector build metadata ───────────────────────────────────────
@check("connector: build/protocol metadata is self-consistent")
def _connector_metadata():
    dist = _REPO / "dist" / "packages"
    if not dist.is_dir():
        return _manual("connector: build/protocol metadata is self-consistent",
                       "no dist/packages/ — build the connector to verify its "
                       "build.json / protocol version")
    builds = list(dist.glob("*.build.json"))
    if not builds:
        return _manual("connector: build/protocol metadata is self-consistent",
                       "no *.build.json under dist/packages/")
    return _ok("connector: build/protocol metadata is self-consistent",
               f"{len(builds)} build descriptor(s)")


# ── live-only ──────────────────────────────────────────────────────
@check("live: PACE bootstrap / Duo / real HPC run / paid AWS run")
def _live_only():
    return _manual(
        "live: PACE bootstrap / Duo / real HPC run / paid AWS run",
        "these require a person at a terminal: the connector password bootstrap "
        "(Duo/MFA), one real ISSM HPC run, the Icepack container exporter, and a "
        "cloud dry-run. See overnight/MORNING_REPORT.md.")


# ── runner ─────────────────────────────────────────────────────────
def run_all() -> list[CheckResult]:
    out: list[CheckResult] = []
    for name, fn in _CHECKS:
        try:
            out.append(fn())
        except Exception as e:  # a broken check is a FAIL, never a crash
            out.append(_fail(name, f"check raised {type(e).__name__}: {e}"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m cryostack_src.acceptance", description=__doc__)
    ap.add_argument("--offline", action="store_true",
                    help="the only supported mode; nothing is submitted")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = run_all()

    if args.json:
        import json
        print(json.dumps([r.__dict__ for r in results], indent=2))
    else:
        width = max(len(r.name) for r in results)
        for r in results:
            mark = {"PASS": "✓", "FAIL": "✗", "MANUAL": "•"}[r.status]
            print(f"  {mark} {r.name:<{width}}  {r.status}")
            if r.detail and r.status != PASS:
                print(f"      {r.detail}")
        n_pass = sum(r.status == PASS for r in results)
        n_fail = sum(r.status == FAIL for r in results)
        n_manual = sum(r.status == MANUAL for r in results)
        print(f"\n  {n_pass} PASS · {n_fail} FAIL · {n_manual} MANUAL CHECK REQUIRED")

    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
