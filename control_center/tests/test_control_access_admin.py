"""Control Center access administration.

Authorization matrix for viewing and changing access, last-owner and
self-escalation protection, same-origin checks, the append-only audit trail,
session revocation, sign-in diagnostics, workspace status, pagination, and
that no credential material reaches any HTML or JSON response.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from control_center import install_control_center
from control_center.services import AccessService
from control_center.services.workspaces import WorkspaceInspector, safe_id_for
from icesee_auth import AuthManager
from icesee_auth import access_log
from icesee_auth.security import hash_password

CONTROL_ROLES = ("developer", "maintainer", "admin", "owner")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PASSWORD = "correct horse battery"


class Env:
    def __init__(self, tmp_path: Path):
        self.db = tmp_path / "auth.db"
        self.ws = tmp_path / "ws"
        self.auth = AuthManager(database_path=self.db, secure_cookies=False)
        self.storage = self.auth.storage
        self.app = web.Application()
        self.auth.install(self.app)
        self.access = AccessService(self.storage)
        self.app["access_service"] = self.access
        self.app["control_workspace_root"] = str(self.ws)
        install_control_center(self.app, auth=self.auth, database_path=self.db)
        self.sessions: list[str] = []

    def user(self, name: str, *roles: str, password_hash: str = "scrypt$1$1$1$00$00"):
        user = self.storage.create_user(email=f"{name}@example.org", display_name=name.title(),
                                        institution="Test U", password_hash=password_hash)
        for role in roles:
            self.storage.grant_role(user_id=user.id, role=role)
        return user

    def login(self, user) -> dict:
        session = self.storage.create_session(ttl_seconds=3600, user_id=user.id)
        self.sessions.append(session.id)
        return {"icesee_session": session.id}

    def role(self, user) -> str | None:
        return self.access.effective_role(user_id=user.id)

    def audit_rows(self) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM access_audit_log ORDER BY created_at")]

    def events(self, event_type: str | None = None) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute("SELECT * FROM access_events ORDER BY id")]
        return [r for r in rows if event_type is None or r["event_type"] == event_type]

    def run(self, script):
        async def go():
            async with TestClient(TestServer(self.app)) as client:
                return await script(client)
        return asyncio.run(go())


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("GITHUB", "ORCID"):
        for part in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"):
            monkeypatch.delenv(f"CRYOSTACK_{name}_{part}", raising=False)
    return Env(tmp_path)


def test_owner_can_delegate_and_revoke_developer_docs_access(env):
    owner = env.user("owner", "owner")
    maintainer = env.user("maintainer", "maintainer")
    ordinary = env.user("ordinary")
    assert not env.access.can_read_developer_docs(user_id=maintainer.id)
    env.access.set_developer_docs_access(actor_user_id=owner.id,
        target_user_id=maintainer.id, enabled=True, reason="continuity coverage")
    assert env.access.can_read_developer_docs(user_id=maintainer.id)
    with pytest.raises(PermissionError):
        env.access.set_developer_docs_access(actor_user_id=maintainer.id,
            target_user_id=maintainer.id, enabled=False, reason="not allowed")
    with pytest.raises(ValueError):
        env.access.set_developer_docs_access(actor_user_id=owner.id,
            target_user_id=ordinary.id, enabled=True, reason="wrong role")
    env.access.set_developer_docs_access(actor_user_id=owner.id,
        target_user_id=maintainer.id, enabled=False, reason="rotation complete")
    assert not env.access.can_read_developer_docs(user_id=maintainer.id)
    assert [r["action"] for r in env.audit_rows()].count("developer_docs_access_changed") == 2


def test_stale_developer_docs_capability_fails_closed(env):
    user = env.user("stale", "developer", "developer_docs")
    assert not env.access.can_read_developer_docs(user_id=user.id)


def test_owner_manages_developer_docs_access_through_user_page(env):
    owner = env.user("owner", "owner")
    maintainer = env.user("maintainer", "maintainer")
    admin = env.user("admin", "admin")
    owner_cookies = env.login(owner)
    maintainer_cookies = env.login(maintainer)

    async def script(client):
        owner_page = await _get(client, f"/control/users/{maintainer.id}", owner_cookies)
        owner_html = await owner_page.text()
        maint_page = await _get(client, f"/control/users/{admin.id}", maintainer_cookies)
        maint_html = await maint_page.text()
        denied = await _post(
            client, f"/control/users/{admin.id}/developer-docs", maintainer_cookies,
            {"enabled": "1", "reason": "not owner"})
        granted = await _post(
            client, f"/control/users/{maintainer.id}/developer-docs", owner_cookies,
            {"enabled": "1", "reason": "leave coverage"})
        updated_page = await _get(
            client, f"/control/users/{maintainer.id}", owner_cookies)
        updated_html = await updated_page.text()
        revoked = await _post(
            client, f"/control/users/{maintainer.id}/developer-docs", owner_cookies,
            {"reason": "coverage ended"})
        return (owner_page.status, owner_html, maint_page.status, maint_html,
                denied.status, granted.status, updated_html, revoked.status)

    (owner_status, owner_html, maint_status, maint_html,
     denied, granted, updated_html, revoked) = env.run(script)
    assert owner_status == maint_status == 200
    assert f'/control/users/{maintainer.id}/developer-docs' in owner_html
    assert "Allow access to owner documentation" in owner_html
    assert "/developer-docs" not in maint_html
    assert denied == 403
    assert granted == 303 and "checked" in updated_html
    assert revoked == 303 and not env.access.can_read_developer_docs(user_id=maintainer.id)


def test_developer_docs_access_requires_reason_and_same_origin(env):
    owner = env.user("owner", "owner")
    target = env.user("target", "admin")
    cookies = env.login(owner)

    async def script(client):
        missing = await _post(
            client, f"/control/users/{target.id}/developer-docs", cookies,
            {"enabled": "1", "reason": " "})
        cross = await _post(
            client, f"/control/users/{target.id}/developer-docs", cookies,
            {"enabled": "1", "reason": "cross origin"},
            origin="https://evil.example")
        return missing.status, cross.status

    assert env.run(script) == (400, 403)
    assert not env.access.can_read_developer_docs(user_id=target.id)
    assert env.audit_rows() == []


def test_demotion_revokes_delegated_developer_docs_access_atomically(env):
    owner = env.user("owner", "owner")
    maintainer = env.user("maintainer", "maintainer")
    env.access.set_developer_docs_access(
        actor_user_id=owner.id, target_user_id=maintainer.id,
        enabled=True, reason="continuity coverage",
    )

    env.access.set_control_role(
        actor_user_id=owner.id, target_user_id=maintainer.id,
        new_role="developer", reason="duties changed",
    )

    assert env.role(maintainer) == "developer"
    assert not env.access.can_read_developer_docs(user_id=maintainer.id)
    changes = [row for row in env.audit_rows()
               if row["action"] == "developer_docs_access_changed"]
    assert [(row["previous_value"], row["new_value"], row["reason"])
            for row in changes] == [
                ("false", "true", "continuity coverage"),
                ("true", "false", "duties changed"),
            ]


async def _post(client, path, cookies, data, origin=None):
    headers = {"Origin": origin} if origin else {}
    client.session.cookie_jar.clear()
    return await client.post(path, data=data, cookies=cookies, headers=headers,
                             allow_redirects=False)


async def _get(client, path, cookies=None):
    client.session.cookie_jar.clear()
    return await client.get(path, cookies=cookies or {}, allow_redirects=False)


# ----------------------------------------------------------------------
# storage regressions
# ----------------------------------------------------------------------

def test_add_user_role_accepts_maintainer_and_rejects_typo(env):
    user = env.user("m")
    env.storage.add_user_role(user_id=user.id, role="maintainer")
    assert env.storage.get_user_roles(user_id=user.id) == ["maintainer"]
    with pytest.raises(ValueError):
        env.storage.add_user_role(user_id=user.id, role="nmaintainer")


def test_baseline_database_migrates_additively(tmp_path):
    db = tmp_path / "baseline.db"
    with sqlite3.connect(db) as c:
        c.executescript((FIXTURES / "baseline_auth_schema.sql").read_text())
        c.execute("INSERT INTO users (id, email, display_name, password_hash, created_at) "
                  "VALUES ('u1', 'old@example.org', 'Old', 'h', 1.0)")
        c.execute("INSERT INTO sessions VALUES ('sess-old', 'u1', ?, ?, ?)",
                  (time.time(), time.time(), time.time() + 3600))
        c.execute("INSERT INTO user_roles VALUES ('r1', 'u1', 'owner', 1.0, NULL)")
        c.execute("INSERT INTO control_audit_log VALUES ('a1', 'u1', 'u1', 'x', '{}', 1.0)")
        before = {name: [tuple(col) for col in c.execute(f"PRAGMA table_info({name})")]
                  for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    auth = AuthManager(database_path=db)
    with sqlite3.connect(db) as c:
        tables = {name for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        after = {name: [tuple(col) for col in c.execute(f"PRAGMA table_info({name})")]
                 for name in before}
    assert {"access_events", "access_audit_log"} <= tables
    assert after == before  # existing tables untouched
    # the existing session and role still work
    assert auth.storage.get_session("sess-old").user_id == "u1"
    assert auth.storage.get_user_roles(user_id="u1") == ["owner"]
    # reopening is idempotent
    AuthManager(database_path=db)
    auth.storage.record_access_event(event_type="logout", outcome="success", user_id="u1")
    assert len(auth.storage.record_access_audit(
        actor_user_id=None, actor_label="t", target_user_id="u1", target_label=None,
        action="x", previous_value=None, new_value=None, reason="test")) == 32


def test_audit_log_is_append_only(env):
    env.storage.record_access_audit(actor_user_id=None, actor_label="t", target_user_id=None,
                                    target_label=None, action="x", previous_value=None,
                                    new_value=None, reason="initial")
    with sqlite3.connect(env.db) as c:
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("UPDATE access_audit_log SET reason = 'changed'")
        with pytest.raises(sqlite3.DatabaseError):
            c.execute("DELETE FROM access_audit_log")
    assert env.audit_rows()[0]["reason"] == "initial"


def test_event_retention_prunes_old_rows(env, monkeypatch):
    monkeypatch.setenv(access_log.RETENTION_DAYS_ENV, "10")
    old = time.time() - 11 * 86400
    env.storage.record_access_event(event_type="logout", outcome="success", now=old)
    env.storage.record_access_event(event_type="logout", outcome="success")
    assert len(env.events("logout")) == 1


# ----------------------------------------------------------------------
# authorization matrix
# ----------------------------------------------------------------------

@pytest.mark.parametrize("role,status", [(None, 403), ("developer", 200), ("maintainer", 200),
                                         ("admin", 200), ("owner", 200)])
def test_view_matrix(env, role, status):
    viewer = env.user("viewer", *([role] if role else []))
    target = env.user("target")
    cookies = env.login(viewer)
    paths = ["/control/users", f"/control/users/{target.id}", "/control/access",
             "/control/workspaces", "/api/control/users", f"/api/control/users/{target.id}",
             "/api/control/access/events", "/api/control/workspaces"]

    async def script(client):
        return [(p, (await _get(client, p, cookies)).status) for p in paths]

    for path, got in env.run(script):
        assert got == status, path
    if role is None:
        denied = env.events("control_denied")
        assert denied and denied[-1]["user_id"] == viewer.id


def test_anonymous_redirected_to_login(env):
    async def script(client):
        r = await _get(client, "/control/access")
        return r.status, r.headers.get("Location", "")
    status, location = env.run(script)
    assert status == 302 and location.startswith("/auth/login")


# (actor role, target role, new role, allowed)
MATRIX = [
    (None, None, "developer", False),
    ("developer", None, "developer", False),
    ("maintainer", None, "developer", True),
    ("maintainer", None, "maintainer", False),
    ("maintainer", "developer", "", True),
    ("maintainer", "maintainer", "developer", False),
    ("admin", None, "maintainer", True),
    ("admin", "maintainer", "developer", True),
    ("admin", None, "admin", False),
    ("admin", None, "owner", False),
    ("admin", "admin", "developer", False),
    ("admin", "owner", "", False),
    ("owner", None, "admin", True),
    ("owner", None, "owner", True),
    ("owner", "admin", "maintainer", True),
]


@pytest.mark.parametrize("actor_role,target_role,new_role,allowed", MATRIX)
def test_role_change_matrix(env, actor_role, target_role, new_role, allowed):
    env.user("root", "owner")  # keeps an owner present in every case
    actor = env.user("actor", *([actor_role] if actor_role else []))
    target = env.user("target", *([target_role] if target_role else []))
    cookies = env.login(actor)

    async def script(client):
        return await _post(client, f"/control/users/{target.id}/role", cookies,
                           {"control_role": new_role, "reason": "matrix test"})

    response = env.run(script)
    if allowed:
        assert response.status == 303
        assert env.role(target) == (new_role or None)
        audit = env.audit_rows()[-1]
        assert (audit["actor_user_id"], audit["target_user_id"]) == (actor.id, target.id)
        assert audit["previous_value"] == (target_role or "user")
        assert audit["new_value"] == (new_role or "user")
        assert audit["reason"] == "matrix test"
        assert audit["actor_label"] == "actor@example.org"
        assert env.events("role_changed")[-1]["actor_user_id"] == actor.id
    else:
        assert response.status == 403
        assert env.role(target) == target_role
        assert env.audit_rows() == []


@pytest.mark.parametrize("role,new_role", [("maintainer", "owner"), ("admin", "owner"),
                                           ("owner", "developer"), ("developer", "owner")])
def test_no_self_change(env, role, new_role):
    env.user("other-owner", "owner")
    actor = env.user("self", role)
    cookies = env.login(actor)

    async def script(client):
        return await _post(client, f"/control/users/{actor.id}/role", cookies,
                           {"control_role": new_role, "reason": "promote myself"})

    assert env.run(script).status == 403
    assert env.role(actor) == role
    denied = env.events("role_change_denied")
    if role != "developer":
        assert denied[-1]["category"] == "self_change"


def test_last_owner_cannot_be_removed(env, monkeypatch):
    owner = env.user("owner", "owner")
    maint = env.user("maint", "maintainer")
    # A permission check that passed before a concurrent demotion committed:
    # the in-transaction count still protects the last owner.
    monkeypatch.setattr(AccessService, "can_change_role", lambda self, **kw: True)
    with pytest.raises(ValueError, match="at least one owner"):
        env.access.set_control_role(actor_user_id=maint.id, target_user_id=owner.id,
                                    new_role="admin", reason="race test")
    assert env.role(owner) == "owner"
    assert env.audit_rows() == []


def test_owner_can_demote_another_owner_while_one_remains(env):
    a = env.user("a", "owner")
    b = env.user("b", "owner")
    env.access.set_control_role(actor_user_id=a.id, target_user_id=b.id, new_role="admin",
                                reason="handover")
    assert env.role(b) == "admin" and env.access.owner_count() == 1


def test_cli_refuses_last_owner_and_audits(env, monkeypatch, capsys):
    from control_center import manage_roles
    owner = env.user("solo", "owner")
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(env.db))
    monkeypatch.setattr(sys, "argv", ["manage_roles", "remove", owner.email, "owner",
                                      "--reason", "cleanup"])
    with pytest.raises(SystemExit, match="at least one owner"):
        manage_roles.main()
    monkeypatch.setattr(sys, "argv", ["manage_roles", "add", owner.email, "maintainer",
                                      "--reason", "bootstrap"])
    manage_roles.main()
    row = env.audit_rows()[-1]
    assert row["action"] == "role_granted" and row["actor_label"].startswith("local-cli:")
    assert row["reason"] == "bootstrap" and row["actor_user_id"] is None


def test_reason_required(env):
    owner = env.user("owner", "owner")
    target = env.user("target")
    cookies = env.login(owner)

    async def script(client):
        return await _post(client, f"/control/users/{target.id}/role", cookies,
                           {"control_role": "developer", "reason": "  "})

    response = env.run(script)
    assert response.status == 400
    assert env.role(target) is None and env.audit_rows() == []


def test_cross_origin_post_refused_and_get_not_allowed(env):
    owner = env.user("owner", "owner")
    target = env.user("target")
    cookies = env.login(owner)

    async def script(client):
        cross = await _post(client, f"/control/users/{target.id}/role", cookies,
                            {"control_role": "admin", "reason": "csrf attempt"},
                            origin="https://evil.example")
        cross_revoke = await _post(client, f"/control/users/{target.id}/sessions/revoke",
                                   cookies, {"reason": "csrf attempt"},
                                   origin="https://evil.example")
        get = await _get(client, f"/control/users/{target.id}/role", cookies)
        same = await _post(client, f"/control/users/{target.id}/role", cookies,
                           {"control_role": "developer", "reason": "same site"},
                           origin=str(client.make_url("")).rstrip("/"))
        return cross.status, cross_revoke.status, get.status, same.status

    cross, cross_revoke, get, same = env.run(script)
    assert (cross, cross_revoke, get) == (403, 403, 405)
    assert same == 303 and env.role(target) == "developer"


def test_unknown_target_is_404(env):
    owner = env.user("owner", "owner")
    cookies = env.login(owner)

    async def script(client):
        return await _post(client, "/control/users/does-not-exist/role", cookies,
                           {"control_role": "developer", "reason": "nobody"})

    assert env.run(script).status == 404


# ----------------------------------------------------------------------
# sessions
# ----------------------------------------------------------------------

def test_revoke_sessions_signs_user_out_and_is_audited(env):
    admin = env.user("admin", "admin")
    target = env.user("target", "developer")
    admin_cookies = env.login(admin)
    target_cookies = env.login(target)
    env.login(target)

    async def script(client):
        before = (await _get(client, "/control/users", target_cookies)).status
        revoke = await _post(client, f"/control/users/{target.id}/sessions/revoke",
                             admin_cookies, {"reason": "lost laptop"})
        after = await _get(client, "/control/users", target_cookies)
        return before, revoke.status, after.status, after.headers.get("Location", "")

    before, revoke, after, location = env.run(script)
    assert (before, revoke, after) == (200, 303, 302)
    assert location.startswith("/auth/login")
    audit = env.audit_rows()[-1]
    assert audit["action"] == "sessions_revoked" and audit["previous_value"] == "2"
    assert audit["reason"] == "lost laptop" and audit["actor_user_id"] == admin.id
    summary = env.app["control_storage"].login_summary(user_id=target.id, now=time.time())
    assert summary["sessions_total"] == 0 and summary["last_revoked_at"]


@pytest.mark.parametrize("actor_role,target_role,allowed", [
    ("developer", None, False), ("maintainer", None, True), ("maintainer", "admin", False),
    ("admin", "owner", False), ("owner", "owner", True)])
def test_revoke_matrix(env, actor_role, target_role, allowed):
    env.user("root", "owner")
    actor = env.user("actor", actor_role)
    target = env.user("target", *([target_role] if target_role else []))
    cookies = env.login(actor)
    env.login(target)

    async def script(client):
        return await _post(client, f"/control/users/{target.id}/sessions/revoke", cookies,
                           {"reason": "matrix test"})

    status = env.run(script).status
    remaining = env.app["control_storage"].login_summary(
        user_id=target.id, now=time.time())["sessions_total"]
    if allowed:
        assert status == 303 and remaining == 0
    else:
        assert status == 403 and remaining == 1


def test_password_login_events_rotation_and_throttle(env):
    user = env.user("pw", password_hash=hash_password(PASSWORD))

    async def script(client):
        client.session.cookie_jar.clear()
        page = await client.get("/auth/login")
        pre = page.cookies["icesee_session"].value
        bad = await client.post("/auth/login", data={"email": user.email, "password": "nope-nope"},
                                allow_redirects=False)
        unknown = await client.post("/auth/login",
                                    data={"email": "ghost@example.org", "password": "whatever1"},
                                    allow_redirects=False)
        ok = await client.post("/auth/login", data={"email": user.email, "password": PASSWORD},
                               allow_redirects=False)
        post = ok.cookies["icesee_session"].value
        statuses = []
        for _ in range(10):
            r = await client.post("/auth/login", data={"email": user.email, "password": "bad-bad-bad"},
                                  allow_redirects=False)
            statuses.append(r.status)
        r = await client.post("/auth/login", data={"email": user.email, "password": PASSWORD},
                              allow_redirects=False)
        statuses.append(r.status)
        return pre, bad.status, unknown.status, ok.status, post, statuses

    pre, bad, unknown, ok, post, statuses = env.run(script)
    assert (bad, unknown, ok) == (400, 400, 302)
    assert pre != post  # pre-login session id is never promoted
    assert env.storage.get_session(pre) is None
    assert env.storage.get_session(post).user_id == user.id
    failures = env.events("login_failure")
    assert [f["category"] for f in failures][:2] == ["wrong_password", "unknown_account"]
    assert failures[0]["user_id"] == user.id and failures[1]["user_id"] is None
    assert env.events("login_success")[0]["user_id"] == user.id
    # a successful sign-in reset the throttle; ten new failures trip it
    assert statuses[:10] == [400] * 10 and statuses[10] == 429
    assert env.events("login_rate_limited")[-1]["user_id"] == user.id


def test_oauth_callback_failure_is_categorised(env):
    async def script(client):
        return (await _get(client, "/auth/github/callback?code=c&state=s")).status

    assert env.run(script) == 503
    event = env.events("login_failure")[-1]
    assert event["category"] == "provider_not_configured" and event["provider"] == "github"


# ----------------------------------------------------------------------
# workspaces
# ----------------------------------------------------------------------

def test_workspace_status_and_ownership(env, tmp_path):
    owner = env.user("owner", "owner")
    has_ws = env.user("haswork")
    env.user("nowork")
    root = env.ws / "users" / safe_id_for(has_ws.id)
    (root / "examples" / "private-model").mkdir(parents=True)
    (root / "examples" / "private-model" / "secret_notes.txt").write_text("x" * 5000)
    (root / ".cryostack" / "runs").mkdir(parents=True)
    (env.ws / "users" / "orphan-dir-123").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"0" * 100000)
    (root / "link-out").symlink_to(outside)

    status = WorkspaceInspector(env.ws).status(has_ws.id)
    assert status["exists"] and status["size_bytes"] == 5000  # symlink not followed
    assert set(status["areas"]) == {"Examples", "Run history"}
    assert status["other_entries"] == 1 and status["last_activity"]

    ownership = WorkspaceInspector(env.ws).ownership(env.app["control_storage"].account_index())
    assert [m["user_id"] for m in ownership["mapped"]] == [has_ws.id]
    assert {o["name"] for o in ownership["orphaned"]} == {"orphan-dir-123"}
    assert len(ownership["without_workspace"]) == 2

    cookies = env.login(owner)

    async def script(client):
        detail = await (await _get(client, f"/control/users/{has_ws.id}", cookies)).text()
        overview = await (await _get(client, "/control/workspaces", cookies)).text()
        api = await (await _get(client, "/api/control/workspaces", cookies)).text()
        return detail + overview + api

    text = env.run(script)
    assert "orphan-dir-123" in text and "Examples" in text
    for private in ("secret_notes", "private-model", "link-out", "big.bin"):
        assert private not in text


def test_symlinked_owner_root_is_not_followed(env, tmp_path):
    user = env.user("linked")
    (env.ws / "users").mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "data.bin").write_bytes(b"1" * 1000)
    (env.ws / "users" / safe_id_for(user.id)).symlink_to(target)
    status = WorkspaceInspector(env.ws).status(user.id)
    assert status["symlink"] and not status["exists"] and status["size_bytes"] == 0


# ----------------------------------------------------------------------
# directory, pagination, no leakage
# ----------------------------------------------------------------------

def test_search_filter_and_pagination(env):
    owner = env.user("owner", "owner")
    for i in range(60):
        env.user(f"bulk{i:02d}")
    env.user("special_name%", "maintainer")
    cookies = env.login(owner)

    async def script(client):
        p1 = await (await _get(client, "/api/control/users?per_page=25", cookies)).json()
        p3 = await (await _get(client, "/api/control/users?per_page=25&page=3", cookies)).json()
        search = await (await _get(client, "/api/control/users?q=bulk05", cookies)).json()
        wildcard = await (await _get(client, "/api/control/users?q=%25", cookies)).json()
        role = await (await _get(client, "/api/control/users?role=maintainer", cookies)).json()
        html = await (await _get(client, "/control/users?q=bulk&page=2", cookies)).text()
        return p1, p3, search, wildcard, role, html

    p1, p3, search, wildcard, role, html = env.run(script)
    assert p1["total"] == 62 and p1["pages"] == 3 and len(p1["users"]) == 25
    assert len(p3["users"]) == 12
    assert [u["email"] for u in search["users"]] == ["bulk05@example.org"]
    assert [u["email"] for u in wildcard["users"]] == ["special_name%@example.org"]
    assert [u["control_role"] for u in role["users"]] == ["maintainer"]
    assert "Page 2 of 2" in html


def test_no_secret_leakage(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_GITHUB_CLIENT_SECRET", "GH-CLIENT-SECRET-MARKER")
    marker_hash = "scrypt$16384$8$1$deadbeefsalt$HASHMARKER0123456789"
    owner = env.user("owner", "owner", password_hash=marker_hash)
    victim = env.user("victim", "developer", password_hash=marker_hash)
    env.storage.create_user_identity(user_id=victim.id, provider="github",
                                     provider_subject="4242", provider_username="victim-gh",
                                     provider_email=None, provider_profile_url=None)
    anonymous = env.storage.create_session(ttl_seconds=600)
    env.sessions.append(anonymous.id)
    env.storage.create_oauth_flow(state="OAUTH-STATE-MARKER", session_id=anonymous.id,
                                  provider="github", code_verifier="PKCE-VERIFIER-MARKER",
                                  return_to="/")
    cookies = env.login(owner)
    env.login(victim)
    env.login(victim)
    env.storage.record_access_event(event_type="login_failure", outcome="failure",
                                    category="wrong_password", user_id=victim.id)
    paths = ["/control/users", f"/control/users/{victim.id}", f"/control/users/{owner.id}",
             "/api/control/users", f"/api/control/users/{victim.id}", "/control/access",
             "/api/control/access/events", "/control/authentication",
             "/api/control/authentication", "/control/workspaces", "/api/control/workspaces"]

    async def script(client):
        bodies = []
        for p in paths:
            r = await _get(client, p, cookies)
            assert r.status == 200, p
            bodies.append(await r.text())
        return "\n".join(bodies)

    text = env.run(script)
    secrets = ["HASHMARKER", "deadbeefsalt", marker_hash, "OAUTH-STATE-MARKER",
               "PKCE-VERIFIER-MARKER", "GH-CLIENT-SECRET-MARKER", "password_hash"]
    for session_id in env.sessions:
        secrets += [session_id, session_id[:12]]
    for secret in secrets:
        assert secret not in text, secret
    assert "victim@example.org" in text  # the pages did render real content


# ----------------------------------------------------------------------
# PATCH /api/v1/experiments/{id}
# ----------------------------------------------------------------------

def test_experiment_patch_updates_status_for_owner_only(env):
    owner = env.user("runner")
    other = env.user("intruder")
    experiment = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="run", backend="local",
        configuration_snapshot_json="{}")
    path = f"/api/v1/experiments/{experiment.id}"
    owner_cookies = env.login(owner)
    other_cookies = env.login(other)

    async def script(client):
        client.session.cookie_jar.clear()
        anon = await client.patch(path, json={"status": "running"})
        client.session.cookie_jar.clear()
        foreign = await client.patch(path, json={"status": "failed"}, cookies=other_cookies)
        client.session.cookie_jar.clear()
        bad = await client.patch(path, json={"status": "bogus"}, cookies=owner_cookies)
        client.session.cookie_jar.clear()
        ok = await client.patch(path, json={"status": "running"}, cookies=owner_cookies)
        body = await ok.json()
        client.session.cookie_jar.clear()
        listed = await client.get("/api/v1/experiments", cookies=owner_cookies)
        client.session.cookie_jar.clear()
        foreign_get = await client.get(path, cookies=other_cookies)
        client.session.cookie_jar.clear()
        own_get = await client.get(path, cookies=owner_cookies)
        return (anon.status, foreign.status, bad.status, ok.status, body,
                listed.status, foreign_get.status, own_get.status)

    anon, foreign, bad, ok, body, listed, foreign_get, own_get = env.run(script)
    assert (anon, foreign, bad, ok) == (401, 404, 400, 200)
    assert (listed, foreign_get, own_get) == (200, 404, 200)
    assert body["status"] == "running"
    stored = env.storage.get_experiment(experiment_id=experiment.id, user_id=owner.id)
    assert stored.status == "running"
    events = env.storage.list_experiment_events(experiment_id=experiment.id, user_id=owner.id)
    assert [e.event_type for e in events] == ["running"]
