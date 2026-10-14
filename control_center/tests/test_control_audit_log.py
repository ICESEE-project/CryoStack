"""Control Center audit log: browsing, filters, pagination and export.

Role gating for the page, the JSON API and the export; filters by time
range, action, actor and target; pagination bounds; CSV/JSON export contents
with formula-injection escaping and a size cap; the export itself is
audited; no credential material reaches any response; and the page fits a
phone-width screen with the shared top-bar navigation.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from control_center import install_control_center
from control_center.services import AccessService
from control_center.services import audit as audit_service
from control_center.services.audit import AuditLogService, parse_filters, safe_cell
from control_center.templates import control_layout
from control_center.templates_audit import audit_log_content
from icesee_auth import AuthManager, access_log

CONTROL_ROLES = ("developer", "maintainer", "admin", "owner")
EXPORT_ROLES = ("maintainer", "admin", "owner")
PASSWORD_HASH = "scrypt$16384$8$1$deadbeefsalt$c0ffeehashvalue"


def _ts(day: str, hour: int = 12) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(
        hour=hour, tzinfo=timezone.utc).timestamp()


class Env:
    def __init__(self, tmp_path: Path):
        self.db = tmp_path / "auth.db"
        self.auth = AuthManager(database_path=self.db, secure_cookies=False)
        self.storage = self.auth.storage
        self.app = web.Application()
        self.auth.install(self.app)
        self.app["access_service"] = AccessService(self.storage)
        self.app["control_workspace_root"] = str(tmp_path / "ws")
        install_control_center(self.app, auth=self.auth, database_path=self.db)
        self.sessions: list[str] = []

    def user(self, name: str, *roles: str):
        user = self.storage.create_user(email=f"{name}@example.org", display_name=name.title(),
                                        institution="Test U", password_hash=PASSWORD_HASH)
        for role in roles:
            self.storage.grant_role(user_id=user.id, role=role)
        return user

    def login(self, user) -> dict:
        session = self.storage.create_session(ttl_seconds=3600, user_id=user.id)
        self.sessions.append(session.id)
        return {"icesee_session": session.id}

    def audit(self, *, actor=None, actor_label=None, target=None, target_label=None,
              action="role_changed", previous="user", new="developer",
              reason="Needs access for testing", now=None, metadata=None) -> str:
        return self.storage.record_access_audit(
            actor_user_id=actor.id if actor else None,
            actor_label=actor_label or (actor.email if actor else "unknown"),
            target_user_id=target.id if target else None,
            target_label=target_label or (target.email if target else None),
            action=action, previous_value=previous, new_value=new,
            reason=reason, now=now, metadata=metadata,
        )

    def audit_rows(self) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM access_audit_log ORDER BY created_at")]

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


async def _get(client, path, cookies=None):
    client.session.cookie_jar.clear()
    return await client.get(path, cookies=cookies or {}, allow_redirects=False)


async def _post(client, path, cookies, data, origin=None):
    headers = {"Origin": origin} if origin else {}
    client.session.cookie_jar.clear()
    return await client.post(path, data=data, cookies=cookies, headers=headers,
                             allow_redirects=False)


# ----------------------------------------------------------------------
# role gating
# ----------------------------------------------------------------------

def test_anonymous_is_sent_to_login(env):
    async def script(client):
        page = await _get(client, "/control/audit")
        api = await _get(client, "/api/control/audit")
        export = await _post(client, "/control/audit/export", {}, {"format": "csv"})
        return page, api, export

    for response in env.run(script):
        assert response.status == 302
        assert response.headers["Location"].startswith("/auth/login")
    assert all(r["action"] != "audit_exported" for r in env.audit_rows())


def test_view_and_export_role_matrix(env):
    plain = env.user("plain")
    users = {role: env.user(role, role) for role in CONTROL_ROLES}

    async def script(client):
        out = {}
        for name, user in [("user", plain), *users.items()]:
            cookies = env.login(user)
            page = await _get(client, "/control/audit", cookies)
            api = await _get(client, "/api/control/audit", cookies)
            export = await _post(client, "/control/audit/export", cookies, {"format": "csv"})
            out[name] = (page.status, api.status, export.status, await page.text(),
                         page.headers.get("Cache-Control"))
        return out

    result = env.run(script)
    assert result["user"][:3] == (403, 403, 403)
    for role in CONTROL_ROLES:
        page, api, export, html, cache = result[role]
        assert (page, api) == (200, 200), role
        assert cache == "no-store"
        if role in EXPORT_ROLES:
            assert export == 200, role
            assert 'action="/control/audit/export"' in html
        else:
            assert export == 403, role
            assert 'action="/control/audit/export"' not in html
            assert "requires the maintainer, admin or owner role" in html
    exports = [r for r in env.audit_rows() if r["action"] == "audit_exported"]
    assert sorted(r["actor_user_id"] for r in exports) == sorted(
        users[role].id for role in EXPORT_ROLES)


def test_export_requires_same_origin_and_post(env):
    owner = env.user("owner", "owner")

    async def script(client):
        cookies = env.login(owner)
        cross = await _post(client, "/control/audit/export", cookies, {"format": "csv"},
                            origin="https://evil.example")
        get = await _get(client, "/control/audit/export", cookies)
        bad = await _post(client, "/control/audit/export", cookies, {"format": "xlsx"})
        return cross.status, get.status, bad.status

    assert env.run(script) == (403, 405, 400)
    assert all(r["action"] != "audit_exported" for r in env.audit_rows())


# ----------------------------------------------------------------------
# filters and pagination
# ----------------------------------------------------------------------

@pytest.fixture
def seeded(env):
    owner = env.user("owner", "owner")
    alice = env.user("alice")
    bob = env.user("bob")
    env.audit(actor=owner, target=alice, now=_ts("2026-03-01"), reason="Alice joins the team")
    env.audit(actor=owner, target=bob, action="sessions_revoked", previous="2", new="0",
              now=_ts("2026-03-05"), reason="Lost laptop")
    env.audit(actor=None, actor_label="local-cli:ops", target=bob, action="role_granted",
              previous="user", new="maintainer", now=_ts("2026-03-10"), reason="Bootstrap")
    return owner, alice, bob


def _service(env) -> AuditLogService:
    return AuditLogService(env.app["control_storage"])


def _reasons(env, **filters) -> list[str]:
    result = _service(env).page(parse_filters(filters))
    return [row["reason"] for row in result["rows"]]


def test_filters_by_action_actor_target_and_time(env, seeded):
    owner, alice, bob = seeded
    assert _reasons(env) == ["Bootstrap", "Lost laptop", "Alice joins the team"]
    assert _reasons(env, action="sessions_revoked") == ["Lost laptop"]
    assert _reasons(env, actor=owner.id) == ["Lost laptop", "Alice joins the team"]
    assert _reasons(env, actor="OWNER@example.org") == ["Lost laptop", "Alice joins the team"]
    assert _reasons(env, actor="local-cli:ops") == ["Bootstrap"]
    assert _reasons(env, target=bob.email) == ["Bootstrap", "Lost laptop"]
    assert _reasons(env, target=alice.id, action="role_changed") == ["Alice joins the team"]
    assert _reasons(env, **{"from": "2026-03-05"}) == ["Bootstrap", "Lost laptop"]
    assert _reasons(env, to="2026-03-05") == ["Lost laptop", "Alice joins the team"]
    assert _reasons(env, **{"from": "2026-03-02", "to": "2026-03-09"}) == ["Lost laptop"]
    # reversed range is swapped, not empty
    assert _reasons(env, **{"from": "2026-03-09", "to": "2026-03-02"}) == ["Lost laptop"]
    # unknown email and patterns match nothing rather than everything
    assert _reasons(env, actor="nobody@example.org") == []
    assert _reasons(env, target="%") == []


def test_invalid_filters_are_dropped():
    filters = parse_filters({"from": "yesterday", "to": "2026-13-40",
                             "action": "x'; DROP TABLE users;--", "actor": "a" * 999})
    assert filters["from"] == filters["to"] == filters["action"] == ""
    assert len(filters["actor"]) == 200


def test_filters_via_http_render_rows(env, seeded):
    owner, _alice, bob = seeded

    async def script(client):
        cookies = env.login(owner)
        page = await _get(client, f"/control/audit?target={bob.id}&action=sessions_revoked",
                          cookies)
        api = await _get(client, "/api/control/audit?actor=local-cli:ops", cookies)
        return await page.text(), await api.json()

    html, payload = env.run(script)
    assert "Lost laptop" in html and "Alice joins the team" not in html
    assert "Sessions revoked" in html and "2 → 0" in html
    assert f'href="/control/users/{bob.id}"' in html
    assert [row["reason"] for row in payload["rows"]] == ["Bootstrap"]
    assert payload["rows"][0]["actor_label"] == "local-cli:ops"
    assert payload["filters"]["actor"] == "local-cli:ops"


def test_pagination_bounds(env):
    owner = env.user("owner", "owner")
    target = env.user("target")
    base = _ts("2026-01-01")
    for index in range(120):
        env.audit(actor=owner, target=target, reason=f"entry {index:03d}", now=base + index)
    service = _service(env)
    first = service.page({}, page=1)
    assert (first["total"], first["pages"], len(first["rows"])) == (120, 3, 50)
    assert first["rows"][0]["reason"] == "entry 119"
    last = service.page({}, page=3)
    assert len(last["rows"]) == 20 and last["rows"][-1]["reason"] == "entry 000"
    assert service.page({}, page=99)["page"] == 3
    assert service.page({}, page=-4)["page"] == 1
    assert service.page({}, page="junk")["page"] == 1
    assert service.page({}, per_page=10_000)["per_page"] == 200
    assert service.page({}, per_page=0)["per_page"] == 1

    async def script(client):
        cookies = env.login(owner)
        page = await _get(client, "/control/audit?page=2", cookies)
        api = await _get(client, "/api/control/audit?page=500&per_page=500", cookies)
        return await page.text(), await api.json()

    html, payload = env.run(script)
    assert "Page 2 of 3" in html
    assert 'href="/control/audit?page=1"' in html and 'href="/control/audit?page=3"' in html
    assert payload["page"] == 1 and payload["per_page"] == 200 and len(payload["rows"]) == 120


def test_empty_database_renders(env):
    owner = env.user("owner", "owner")

    async def script(client):
        response = await _get(client, "/control/audit", env.login(owner))
        return response.status, await response.text()

    status, html = env.run(script)
    assert status == 200 and "No audit entries match these filters." in html


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------

def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_export_contents_escaping_and_audit(env, seeded):
    owner, alice, _bob = seeded
    dangerous = ["=HYPERLINK(\"http://x\")", "+SUM(1)", "-2+3", "@cmd", "\tTabbed", "\rReturn"]
    for index, reason in enumerate(dangerous[:4]):
        env.audit(actor=owner, target=alice, reason=reason, now=_ts("2026-04-01") + index)
    # the append helper strips surrounding whitespace, so write the
    # tab/CR-led rows directly to exercise the export escaping
    with sqlite3.connect(env.db) as c:
        for index, reason in enumerate(dangerous[4:], start=4):
            c.execute("INSERT INTO access_audit_log (id, created_at, actor_user_id, actor_label, "
                      "target_user_id, target_label, action, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (f"raw{index}", _ts("2026-04-01") + index, owner.id, owner.email,
                       alice.id, alice.email, "role_changed", reason))

    async def script(client):
        cookies = env.login(owner)
        response = await _post(client, "/control/audit/export", cookies,
                               {"format": "csv", "target": alice.id, "from": "2026-02-01"})
        return response.status, dict(response.headers), await response.text()

    status, headers, body = env.run(script)
    assert status == 200
    assert headers["Content-Type"].startswith("text/csv")
    assert re.match(r'attachment; filename="cryostack-audit-\d{8}T\d{6}Z\.csv"',
                    headers["Content-Disposition"])
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-CryoStack-Export-Rows"] == "7"
    assert headers["X-CryoStack-Export-Truncated"] == "false"
    rows = _csv(body)
    assert list(rows[0].keys()) == list(audit_service.EXPORT_COLUMNS)
    assert len(rows) == 7 and all(r["target_user_id"] == alice.id for r in rows)
    reasons = {r["reason"] for r in rows}
    for value in dangerous:
        assert "'" + value in reasons
    assert "Alice joins the team" in reasons
    assert rows[-1]["created_at_utc"] == "2026-03-01T12:00:00Z"
    assert rows[-1]["actor_label"] == owner.email
    # no cell starts with a formula trigger
    for row in rows:
        for value in row.values():
            assert not value.startswith(("=", "+", "-", "@", "\t", "\r"))

    exported = [r for r in env.audit_rows() if r["action"] == "audit_exported"]
    assert len(exported) == 1
    entry = exported[0]
    assert entry["actor_user_id"] == owner.id and entry["actor_label"] == owner.email
    assert entry["target_user_id"] is None
    assert entry["new_value"] == "7 rows (csv)"
    assert "Exported 7 audit row(s) as CSV" in entry["reason"]
    assert f"target={alice.id}" in entry["reason"] and "from=2026-02-01" in entry["reason"]
    metadata = json.loads(entry["metadata_json"])
    assert metadata == {"format": "csv", "rows": 7, "truncated": False,
                        "filters": f"from=2026-02-01, target={alice.id}"}


def test_export_row_is_visible_and_append_only(env, seeded):
    owner, _alice, _bob = seeded

    async def script(client):
        cookies = env.login(owner)
        await _post(client, "/control/audit/export", cookies, {"format": "json"})
        page = await _get(client, "/control/audit?action=audit_exported", cookies)
        return await page.text()

    html = env.run(script)
    assert "Audit log exported" in html and "format=json; rows=3" in html
    with sqlite3.connect(env.db) as c, pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM access_audit_log WHERE action = 'audit_exported'")


def test_json_export_and_size_cap(env, monkeypatch):
    owner = env.user("owner", "owner")
    target = env.user("target")
    for index in range(8):
        env.audit(actor=owner, target=target, reason=f"entry {index}",
                  now=_ts("2026-05-01") + index)
    monkeypatch.setattr(audit_service, "EXPORT_MAX_ROWS", 5)

    async def script(client):
        cookies = env.login(owner)
        js = await _post(client, "/control/audit/export", cookies, {"format": "json"})
        cs = await _post(client, "/control/audit/export", cookies, {"format": "csv"})
        return (js.status, dict(js.headers), await js.json(),
                cs.headers["X-CryoStack-Export-Rows"], await cs.text())

    status, headers, payload, csv_rows, csv_body = env.run(script)
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert headers["X-CryoStack-Export-Truncated"] == "true"
    assert payload["matched"] == 8 and payload["rows_exported"] == 5
    assert payload["truncated"] is True and payload["max_rows"] == 5
    assert [r["reason"] for r in payload["rows"]] == [f"entry {i}" for i in (7, 6, 5, 4, 3)]
    assert csv_rows == "5" and len(_csv(csv_body)) == 5
    exported = [json.loads(r["metadata_json"]) for r in env.audit_rows()
                if r["action"] == "audit_exported"]
    assert exported == [
        {"filters": "none", "format": "json", "rows": 5, "truncated": True},
        {"filters": "none", "format": "csv", "rows": 5, "truncated": True},
    ]


def test_safe_cell():
    assert safe_cell("=1+1") == "'=1+1"
    assert safe_cell("-") == "'-"
    assert safe_cell("\tx") == "'\tx" and safe_cell("\rx") == "'\rx"
    assert safe_cell("plain") == "plain"
    assert safe_cell(None) == ""
    assert safe_cell(3) == "3"


# ----------------------------------------------------------------------
# no secret material
# ----------------------------------------------------------------------

def test_no_secret_material_in_any_output(env, seeded):
    owner, alice, _bob = seeded
    env.audit(actor=owner, target=alice, reason="With extra metadata",
              metadata={"session_id": "sess-leak-marker", "token": "tok-leak-marker",
                        "format": "csv"})
    env.storage.record_access_event(event_type=access_log.LOGIN_FAILURE, outcome="failure",
                                    category="unknown_account")

    async def script(client):
        cookies = env.login(owner)
        bodies = []
        for path in ("/control/audit", "/api/control/audit",
                     f"/control/audit?target={alice.id}"):
            bodies.append(await (await _get(client, path, cookies)).text())
        for fmt in ("csv", "json"):
            response = await _post(client, "/control/audit/export", cookies, {"format": fmt})
            bodies.append(await response.text())
        return bodies

    bodies = env.run(script)
    secrets = [PASSWORD_HASH, "deadbeefsalt", "c0ffeehashvalue", "password_hash",
               "sess-leak-marker", "tok-leak-marker", "metadata_json"]
    secrets += env.sessions + [sid[:12] for sid in env.sessions]
    for body in bodies:
        for secret in secrets:
            assert secret not in body, secret
    assert "With extra metadata" in bodies[0]


# ----------------------------------------------------------------------
# phone layout
# ----------------------------------------------------------------------

def _phone_rules(html: str) -> str:
    match = re.search(r"@media \(max-width: 760px\) \{(.*?)\n    \}\n  </style>", html, re.S)
    assert match, "phone-width rules not found"
    return match.group(1)


def _audit_html() -> str:
    row = {"id": "a1", "created_at": _ts("2026-03-01"), "actor_user_id": "u1",
           "actor_label": "owner@example.org", "target_user_id": "u2",
           "target_label": "target@example.org", "action": "role_changed",
           "previous_value": "user", "new_value": "developer", "reason": "x" * 400,
           "metadata": {}, "actor_exists": True, "target_exists": False}
    content = audit_log_content(
        result={"rows": [row], "total": 1, "page": 1, "pages": 1, "per_page": 50},
        filters=parse_filters({}), actions=list(audit_service.KNOWN_ACTIONS),
        can_export=True)
    return control_layout(title="Audit Log", active="audit", content=content)


def test_audit_page_in_navigation_and_phone_top_bar():
    html = _audit_html()
    assert re.search(r'class="control-nav-item active"\s+href="/control/audit"', html)
    for key in ("users", "access", "settings"):
        other = control_layout(title="x", active=key, content="")
        assert 'href="/control/audit"' in other
    rules = _phone_rules(html)
    nav = re.search(r"\.control-nav \{(.*?)\}", rules, re.S).group(1)
    assert "display: flex" in nav and "overflow-x: auto" in nav


def test_audit_table_scrolls_inside_its_panel_on_phones():
    html = _audit_html()
    # the wide table is wrapped so it scrolls inside the panel, not the page
    assert re.search(r'<div class="access-table-wrap"><table>\s*<thead><tr><th>When', html)
    wrap = re.search(r"\.access-table-wrap \{(.*?)\}", html, re.S).group(1)
    assert "overflow-x: auto" in wrap
    panel = re.findall(r"\.panel \{(.*?)\}", html, re.S)
    assert any("overflow: hidden" in rule for rule in panel)
    main = re.search(r"\.control-main \{(.*?)\}", html, re.S).group(1)
    assert "min-width: 0" in main
    # long reasons wrap instead of widening the page
    assert "overflow-wrap: anywhere" in re.search(r"\.audit-reason \{(.*?)\}", html, re.S).group(1)
    # filters and the export form stack one control per row on phones
    phone_css = "".join(re.findall(r"@media \(max-width: 760px\) \{(.*?)\n  \}\n</style>",
                                   html, re.S))
    assert ".access-filters > *" in phone_css and "flex: 1 1 100%" in phone_css
    assert ".audit-export > *" in phone_css
    assert 'type="date"' in html and "min-width: 0" in phone_css
