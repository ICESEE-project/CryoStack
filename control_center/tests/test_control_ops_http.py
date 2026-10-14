"""Analytics, Diagnostics and Settings over HTTP: roles, CSRF, audit,
validation, secret hygiene and live/historical labelling."""

from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from control_center.services import settings as S
from control_center.services.diagnostics import DiagnosticsService

PAGES = ("/control/analytics", "/control/diagnostics", "/control/settings")
APIS = ("/api/control/analytics", "/api/control/diagnostics", "/api/control/settings")
FAKE_SECRETS = {
    "CRYOSTACK_GITHUB_CLIENT_SECRET": "gh-secret-value-1f2e3d",
    "CRYOSTACK_ORCID_CLIENT_SECRET": "orcid-secret-value-9a8b7c",
    "AWS_SECRET_ACCESS_KEY": "aws-secret-value-5d6e7f",
    "CRYOSTACK_RELAY_CONTROL_TOKEN": "relay-token-value-0a1b2c",
    "CRYOSTACK_LT_TOKEN": "license-token-value-3c4d5e",
}


class _Closed:
    def open(self, request, timeout=None):
        raise OSError("relay not running in tests")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.delenv("CRYOSTACK_CONTROL_OPS_DATABASE", raising=False)
    # settings exported into os.environ during a test are removed afterwards
    for definition in S.SETTINGS:
        monkeypatch.setenv(definition.env, "placeholder")
        monkeypatch.delenv(definition.env)
    S._EXPORTED.clear()
    for name, value in FAKE_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    yield {"tmp": tmp_path, "auth": AuthManager()}
    S._EXPORTED.clear()


def _user(env, email, *roles):
    storage = env["auth"].storage
    user = storage.create_user(email=email, display_name=email.split("@")[0],
                               institution=None, password_hash="x")
    for role in roles:
        storage.grant_role(user_id=user.id, role=role)
    session = storage.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _run(env, script):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from control_center import install_control_center
    from control_center.pages import ops
    from control_center.services import AccessService

    app = web.Application()
    env["auth"].install(app)
    app["access_service"] = AccessService(env["auth"].storage)
    install_control_center(app, auth=env["auth"], database_path=env["tmp"] / "auth.db")
    app[ops.DIAGNOSTICS_KEY] = DiagnosticsService(
        app["control_storage"], ops_database=app["control_ops_store"].path,
        catalog_path=env["tmp"] / "catalog.db", working_cache_dir=env["tmp"] / "cache",
        workspace_root=env["tmp"] / "ws",
        ursa_availability=lambda: {"available": False, "reason": "Not installed."},
        tls_probe=lambda host: {"not_after": time.time() + 40 * 86400, "issuer": "Test CA"},
        relay_opener=_Closed())

    async def livist(request):
        return web.Response(text="<h1>LIVIST</h1>", content_type="text/html")

    app.router.add_get("/livist/", livist)

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client, app)

    return asyncio.run(go())


def _origin(client):
    return {"Origin": f"http://{client.server.host}:{client.server.port}"}


async def _post(client, cookies, data, headers=None):
    return await client.post("/control/settings", data=data, cookies=cookies,
                             headers=headers if headers is not None else _origin(client),
                             allow_redirects=False)


def test_role_matrix(env):
    _u, plain = _user(env, "user@example.org")
    _d, developer = _user(env, "dev@example.org", "developer")
    roles = {role: _user(env, f"{role}@example.org", role)[1]
             for role in ("maintainer", "admin", "owner")}
    change = {"op": "save", "key": "cloud.poll_seconds", "value": "30", "reason": "test"}

    async def script(client, app):
        out = {}
        for path in PAGES + APIS:
            out[("anon", path)] = (await client.get(path, allow_redirects=False)).status
            out[("plain", path)] = (await client.get(path, cookies=plain)).status
            out[("developer", path)] = (await client.get(path, cookies=developer)).status
            for role, cookies in roles.items():
                out[(role, path)] = (await client.get(path, cookies=cookies)).status
        out["anon_post"] = (await _post(client, {}, change)).status
        out["plain_post"] = (await _post(client, plain, change)).status
        out["developer_post"] = (await _post(client, developer, change)).status
        developer_page = await (await client.get("/control/settings", cookies=developer)).text()
        out["developer_forms"] = 'name="op" value="save"' in developer_page
        out["developer_api"] = (await (await client.get("/api/control/settings",
                                                        cookies=developer)).json())["can_write"]
        for index, (role, cookies) in enumerate(roles.items()):
            response = await _post(client, cookies, {**change, "value": str(30 + index)})
            out[f"{role}_post"] = (response.status, response.headers.get("Location", ""))
        out["audit"] = app["control_settings_service"].audit()
        return out

    out = _run(env, script)
    for path in PAGES + APIS:
        assert out[("anon", path)] == 302, path
        assert out[("plain", path)] == 403, path
        for role in ("developer", "maintainer", "admin", "owner"):
            assert out[(role, path)] == 200, (role, path)
    assert out["anon_post"] == 302
    assert out["plain_post"] == 403 and out["developer_post"] == 403
    assert out["developer_forms"] is False and out["developer_api"] is False
    for role in ("maintainer", "admin", "owner"):
        status, location = out[f"{role}_post"]
        assert status == 303 and location.startswith("/control/settings?done=saved")
    assert [a["actor_label"] for a in out["audit"]] == [
        "owner@example.org", "admin@example.org", "maintainer@example.org"]


def test_cross_origin_changes_are_refused(env):
    _m, maint = _user(env, "maint@example.org", "maintainer")
    change = {"op": "save", "key": "cloud.poll_seconds", "value": "30", "reason": "test"}

    async def script(client, app):
        return {
            "none": (await _post(client, maint, change, headers={})).status,
            "foreign": (await _post(client, maint, change,
                                    headers={"Origin": "https://evil.example"})).status,
            "foreign_referer": (await _post(client, maint, change,
                                            headers={"Referer": "https://evil.example/x"})).status,
            "stored": app["control_ops_store"].stored_settings(),
        }

    out = _run(env, script)
    assert out["none"] == out["foreign"] == out["foreign_referer"] == 403
    assert out["stored"] == {}


def test_validation_audit_and_rollback_over_http(env):
    _m, maint = _user(env, "maint@example.org", "maintainer")

    async def script(client, app):
        out = {}
        bad = await _post(client, maint, {"op": "save", "key": "frozen_legacies.ursa_concurrency",
                                          "value": "99", "reason": "too many"})
        out["range"] = (bad.status, await bad.text())
        unknown = await _post(client, maint, {"op": "save", "key": "frozen_legacies.ursa_python",
                                              "value": "/bin/sh", "reason": "x"})
        out["unknown"] = unknown.status
        no_reason = await _post(client, maint, {"op": "save", "key": "cloud.poll_seconds",
                                                "value": "30"})
        out["no_reason"] = no_reason.status
        bogus_op = await _post(client, maint, {"op": "exec", "key": "cloud.poll_seconds"})
        out["bogus_op"] = bogus_op.status
        out["stored_after_rejects"] = app["control_ops_store"].stored_settings()
        await _post(client, maint, {"op": "save", "key": "frozen_legacies.ursa_timeout_s",
                                    "value": "600", "reason": "shorter jobs"})
        await _post(client, maint, {"op": "save", "key": "frozen_legacies.ursa_timeout_s",
                                    "value": "900", "reason": "a bit longer"})
        audit = app["control_settings_service"].audit()
        out["env_after_save"] = os.environ.get("CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT")
        rollback = await _post(client, maint, {"op": "rollback", "audit_id": str(audit[0]["id"])})
        out["rollback"] = rollback.status
        out["env_after_rollback"] = os.environ.get("CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT")
        page = await (await client.get("/control/settings", cookies=maint)).text()
        out["page"] = page
        out["api"] = await (await client.get("/api/control/settings", cookies=maint)).json()
        return out

    out = _run(env, script)
    status, text = out["range"]
    assert status == 400 and "at most 8" in text
    assert out["unknown"] == 400 and out["no_reason"] == 400 and out["bogus_op"] == 400
    assert out["stored_after_rejects"] == {}
    assert out["env_after_save"] == "900"                # applies immediately
    assert out["rollback"] == 303 and out["env_after_rollback"] == "600"
    audit = out["api"]["audit"]
    assert [a["action"] for a in audit] == ["rollback", "set", "set"]
    assert (audit[0]["old_value"], audit[0]["new_value"]) == (900, 600)
    assert all("actor_id" not in a for a in audit)
    assert "a bit longer" in out["page"] and "Roll back" in out["page"]
    timeout = next(s for s in out["api"]["settings"]
                   if s["key"] == "frozen_legacies.ursa_timeout_s")
    assert (timeout["source"], timeout["configured_value"]) == ("stored", 600)
    assert out["api"]["precedence"] == ["environment", "stored", "default"]


def test_no_secret_leaks_in_any_page_or_api(env):
    _o, owner = _user(env, "owner@example.org", "owner")

    async def script(client, app):
        await _post(client, owner, {"op": "save", "key": "cloud.poll_seconds", "value": "45",
                                    "reason": "test"})
        bodies = []
        for path in PAGES + APIS + ("/control/diagnostics?refresh=1",):
            response = await client.get(path, cookies=owner)
            assert response.status == 200, path
            bodies.append(await response.text())
        return bodies

    bodies = _run(env, script)
    for body in bodies:
        for name, value in FAKE_SECRETS.items():
            assert value not in body, name
        assert owner["icesee_session"] not in body
        assert "password_hash" not in body


def test_live_and_historical_measurements_are_labelled(env):
    _d, developer = _user(env, "dev@example.org", "developer")

    async def script(client, app):
        diag_api = await (await client.get("/api/control/diagnostics", cookies=developer)).json()
        diag_page = await (await client.get("/control/diagnostics", cookies=developer)).text()
        analytics_api = await (await client.get("/api/control/analytics",
                                                cookies=developer)).json()
        analytics_page = await (await client.get("/control/analytics", cookies=developer)).text()
        return diag_api, diag_page, analytics_api, analytics_page

    diag_api, diag_page, analytics_api, analytics_page = _run(env, script)
    assert diag_api["measured_at"] > 0
    kinds = {c["kind"] for s in diag_api["sections"] for c in s["checks"]}
    assert {"live", "configuration"} <= kinds
    for section in diag_api["sections"]:
        for check in section["checks"]:
            if check["kind"] == "live":
                assert check["measured_at"] == pytest.approx(diag_api["measured_at"], abs=5)
            else:
                assert check["measured_at"] is None
    assert 'class="ops-kind live"' in diag_page and "UTC" in diag_page
    assert 'class="ops-kind configuration"' in diag_page
    ids = [s["id"] for s in diag_api["sections"]]
    assert ids[0] == "gateway" and {"applications", "connections", "workers", "databases",
                                    "storage", "tls"} <= set(ids)
    assert analytics_api["usage"]["kind"] == "historical"
    assert analytics_api["jobs"]["kind"] == "historical"
    assert analytics_api["indexing"]["kind"] == "historical"
    assert analytics_api["storage"]["kind"] == "live"
    assert 'class="ops-kind historical"' in analytics_page
    assert 'class="ops-kind live"' in analytics_page


def test_application_opens_are_counted_in_aggregate(env):
    _u, plain = _user(env, "user@example.org")

    async def script(client, app):
        await client.get("/livist/", cookies=plain)
        await client.get("/livist/")
        await client.get("/livist/", headers={"User-Agent": "CryoStack-HealthCheck/1.0"})
        await client.get("/livist/", headers={"User-Agent": "CryoStack-Diagnostics/1.0"})
        await client.get("/livist/missing")
        await client.post("/livist/")
        app["control_analytics_service"].counter.flush()
        return app["control_ops_store"].usage(since_day="2000-01-01")

    rows = _run(env, script)
    assert len(rows) == 1
    assert rows[0]["application"] == "livist" and rows[0]["opens"] == 2
    assert set(rows[0]) == {"day", "application", "opens"}
    assert json.dumps(rows).count("user@example.org") == 0
