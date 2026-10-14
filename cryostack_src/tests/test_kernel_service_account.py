"""Running Voila kernels under their own service account.

* Kernels read the signed-in user's saved workspace state through a
  loopback-only gateway route with a per-user grant, so they no longer need
  the auth database (password hashes, sessions).
* ``CRYOSTACK_VOILA_MODE=external``: the gateway proxies to Voila servers
  another account supervises (``icesee_app.py voila <app>``) and shares the
  Voila token through a file instead of starting them as its own children.
* ``deployment/check_kernel_isolation.py`` reports what the kernel account
  can reach.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from icesee_auth import kernel_access  # noqa: E402

_APP_PATH = _REPO / "bin" / "icesee_app.py"
_KEY = b"k" * 32


def _load(monkeypatch, tmp_path, name):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", "lazy")
    monkeypatch.setenv("CRYOSTACK_LIVIST_DATABASE", str(tmp_path / "livist.db"))
    monkeypatch.setenv("CRYOSTACK_CONTROL_OPS_DATABASE", str(tmp_path / "ops.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_CATALOG", str(tmp_path / "catalog.db"))
    spec = importlib.util.spec_from_file_location(name, _APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Recorder:
    instances: list = []

    def __init__(self, command, cwd, env=None):
        self.command, self.cwd, self.env = command, cwd, env
        _Recorder.instances.append(self)

    def start(self):
        pass

    def stop(self):
        pass


def _token_file(tmp_path, mode=0o640, token="t" * 40):
    path = tmp_path / "voila_token"
    path.write_text(token + "\n")
    path.chmod(mode)
    return path


# ── grants ────────────────────────────────────────────────────────────────

def test_grants_are_per_user_and_per_key():
    alice = kernel_access.workspace_grant("alice-id", _KEY)
    assert alice and alice != kernel_access.workspace_grant("bob-id", _KEY)
    assert alice != kernel_access.workspace_grant("alice-id", b"x" * 32)
    assert kernel_access.grant_matches("alice-id", alice, _KEY)
    assert not kernel_access.grant_matches("bob-id", alice, _KEY)
    assert not kernel_access.grant_matches("alice-id", None, _KEY)
    assert kernel_access.workspace_grant("", _KEY) is None
    assert kernel_access.workspace_grant("alice-id", b"") is None
    # a relay grant for the same user is not a workspace grant
    from icesee_jupyter_book.core.connector_relay_auth import owner_grant
    assert not kernel_access.grant_matches("alice-id", owner_grant("alice-id", _KEY.decode()), _KEY)


def test_upstream_headers_carry_only_the_users_own_workspace_grant(monkeypatch, tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request

    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_headers")

    class State:
        voila_token = "gateway-token"
        kernel_grant_key = _KEY

    class User:
        id, email, display_name = "alice-id", "alice@example.org", "Alice"

    app = web.Application()
    app["state"] = State()
    forged = {kernel_access.WORKSPACE_GRANT_HEADER: kernel_access.workspace_grant("bob-id", _KEY)}
    request = make_mocked_request("GET", "/icesheets/", headers=forged, app=app)
    request["cryostack_user"] = User()
    headers = mod.build_upstream_headers(request, 8870)
    assert headers[kernel_access.WORKSPACE_GRANT_HEADER] == kernel_access.workspace_grant("alice-id", _KEY)
    assert _KEY.decode() not in json.dumps(headers)
    anon = make_mocked_request("GET", "/icesheets/", headers=forged, app=app)
    assert not any(k.lower() == kernel_access.WORKSPACE_GRANT_HEADER.lower()
                   for k in mod.build_upstream_headers(anon, 8870))


def test_both_voila_servers_pass_the_grant_to_kernels(monkeypatch, tmp_path):
    monkeypatch.delenv("CRYOSTACK_VOILA_MODE", raising=False)
    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_launch")
    monkeypatch.setattr(mod, "ManagedProcess", _Recorder)
    _Recorder.instances = []
    state = mod.ICESEEState()
    assert state.voila_mode == "managed" and len(state.kernel_grant_key) == 32
    assert len(_Recorder.instances) == 2
    for proc in _Recorder.instances:
        assert (f"--VoilaConfiguration.http_header_envs={kernel_access.WORKSPACE_GRANT_HEADER}"
                in proc.command)
        assert state.kernel_grant_key.hex() not in json.dumps(proc.env)
    assert [p.command for p in _Recorder.instances] == [mod.voila_command("icesee"),
                                                         mod.voila_command("icesheets")]


# ── the gateway route ─────────────────────────────────────────────────────

@pytest.fixture
def gateway(monkeypatch, tmp_path):
    from icesee_auth.storage import AuthStorage

    monkeypatch.delenv("CRYOSTACK_VOILA_MODE", raising=False)
    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_route")
    monkeypatch.setattr(mod, "ManagedProcess", _Recorder)
    app = mod.make_app()
    storage = AuthStorage(tmp_path / "auth.db")
    alice = storage.create_user(email="alice@x.test", display_name="Alice", institution=None,
                                password_hash="scrypt$x").id
    bob = storage.create_user(email="bob@x.test", display_name="Bob", institution=None,
                              password_hash="scrypt$x").id
    storage.save_workspace(user_id=alice, application="cryolauncher",
                           state_json='{"resource": "alice-hpc"}')
    storage.save_workspace(user_id=bob, application="cryolauncher",
                           state_json='{"resource": "bob-hpc"}')
    return mod, app, alice, bob


def _serve(app, coroutine):
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        async with TestClient(TestServer(app)) as client:
            return await coroutine(client)
    return asyncio.run(run())


def test_route_returns_only_the_granted_users_state(gateway):
    mod, app, alice, bob = gateway
    key = app["state"].kernel_grant_key
    path = kernel_access.KERNEL_WORKSPACE_STATE_PATH

    async def calls(client):
        out = {}

        async def get(name, user, grant, application="cryolauncher", extra=None):
            headers = {"X-CryoStack-User-Id": user}
            if grant:
                headers[kernel_access.WORKSPACE_GRANT_HEADER] = grant
            headers.update(extra or {})
            response = await client.get(path, params={"application": application}, headers=headers)
            out[name] = (response.status, await response.text(), response.headers.get("Cache-Control"))
        await get("own", alice, kernel_access.workspace_grant(alice, key))
        await get("other-users-id", bob, kernel_access.workspace_grant(alice, key))
        await get("no-grant", alice, None)
        await get("wrong-key", alice, kernel_access.workspace_grant(alice, b"z" * 32))
        await get("via-nginx", alice, kernel_access.workspace_grant(alice, key),
                  extra={"X-Forwarded-For": "203.0.113.9"})
        await get("real-ip", alice, kernel_access.workspace_grant(alice, key),
                  extra={"X-Real-IP": "203.0.113.9"})
        await get("unknown-app", alice, kernel_access.workspace_grant(alice, key), application="admin")
        await get("empty", alice, kernel_access.workspace_grant(alice, key), application="icesee")
        return out

    out = _serve(app, calls)
    assert out["own"][0] == 200 and json.loads(out["own"][1]) == {"state": {"resource": "alice-hpc"}}
    assert out["own"][2] == "no-store"
    assert out["other-users-id"][0] == 403 and "bob-hpc" not in out["other-users-id"][1]
    assert out["no-grant"][0] == 403 and out["wrong-key"][0] == 403
    assert out["via-nginx"][0] == 404 and out["real-ip"][0] == 404
    assert out["unknown-app"][0] == 400
    assert out["empty"][0] == 200 and json.loads(out["empty"][1]) == {"state": {}}


def test_kernel_loader_uses_the_gateway_not_the_database(gateway, monkeypatch):
    from aiohttp.test_utils import TestServer
    from icesee_jupyter_book.ui import workspace_persistence

    mod, app, alice, bob = gateway
    key = app["state"].kernel_grant_key

    def no_database():
        raise AssertionError("the kernel opened the auth database")

    async def run():
        server = TestServer(app)
        await server.start_server()
        try:
            monkeypatch.setenv(kernel_access.GATEWAY_URL_ENV, str(server.make_url("")).rstrip("/"))
            monkeypatch.setattr(workspace_persistence, "auth_database_path", no_database)
            loop = asyncio.get_running_loop()
            results = {}
            for label, grant, user in (("own", kernel_access.workspace_grant(alice, key), alice),
                                       ("forged", kernel_access.workspace_grant(alice, key), bob)):
                monkeypatch.setenv(kernel_access.WORKSPACE_GRANT_ENV, grant)
                results[label] = await loop.run_in_executor(
                    None, workspace_persistence.load_user_workspace_state, user, "icesheets")
            return results
        finally:
            await server.close()

    results = asyncio.run(run())
    assert results["own"] == {"resource": "alice-hpc"}
    assert results["forged"] == {}                       # fails closed


def test_kernel_loader_degrades_to_blank_when_the_gateway_is_down(monkeypatch):
    from icesee_jupyter_book.ui import workspace_persistence

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv(kernel_access.GATEWAY_URL_ENV, f"http://127.0.0.1:{port}")
    monkeypatch.setenv(kernel_access.WORKSPACE_GRANT_ENV, "anything")
    monkeypatch.setattr(workspace_persistence, "auth_database_path",
                        lambda: (_ for _ in ()).throw(AssertionError("database opened")))
    assert workspace_persistence.load_user_workspace_state("alice-id", "icesheets") == {}


# ── external Voila ────────────────────────────────────────────────────────

def test_external_mode_starts_nothing_and_reads_the_shared_token(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_external")
    monkeypatch.setattr(mod, "ManagedProcess", _Recorder)
    _Recorder.instances = []
    monkeypatch.setenv("CRYOSTACK_VOILA_MODE", "external")
    monkeypatch.setenv("CRYOSTACK_VOILA_TOKEN_FILE", str(_token_file(tmp_path)))
    state = mod.ICESEEState()
    assert _Recorder.instances == []
    assert state.voila_token == "t" * 40
    assert isinstance(state.run_center._process, mod.ExternalVoilaProcess)
    state.icesheets.stop()                                 # nothing to stop


@pytest.mark.parametrize("setup, message", [
    (lambda tmp: {"CRYOSTACK_VOILA_MODE": "external"}, "CRYOSTACK_VOILA_TOKEN_FILE is required"),
    (lambda tmp: {"CRYOSTACK_VOILA_MODE": "external",
                  "CRYOSTACK_VOILA_TOKEN_FILE": str(_token_file(tmp, mode=0o644))}, "other accounts"),
    (lambda tmp: {"CRYOSTACK_VOILA_MODE": "external",
                  "CRYOSTACK_VOILA_TOKEN_FILE": str(_token_file(tmp, token="short"))}, "at least 32"),
    (lambda tmp: {"CRYOSTACK_VOILA_MODE": "sideways"}, "must be 'managed' or 'external'"),
])
def test_external_mode_refuses_unsafe_configuration(monkeypatch, tmp_path, setup, message):
    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_refuse")
    monkeypatch.delenv("CRYOSTACK_VOILA_TOKEN_FILE", raising=False)
    for name, value in setup(tmp_path).items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=message):
        mod.ICESEEState()


def test_voila_command_runs_the_same_server_under_any_account(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, "_icesee_app_ksa_run")
    monkeypatch.setenv("CRYOSTACK_VOILA_TOKEN_FILE", str(_token_file(tmp_path)))
    monkeypatch.setenv("CRYOSTACK_SESSION_SECRET_FOR_TEST", "must-not-pass")
    captured = {}

    def execve(path, argv, env):
        captured.update(path=path, argv=argv, env=env)
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execve", execve)
    monkeypatch.setattr(mod.os, "chdir", lambda path: captured.setdefault("cwd", path))
    with pytest.raises(SystemExit):
        mod.run_voila("icesheets")
    assert captured["argv"] == mod.voila_command("icesheets")
    assert captured["env"]["CRYOSTACK_VOILA_TOKEN"] == "t" * 40
    assert not any("t" * 40 in a for a in captured["argv"])
    assert "CRYOSTACK_SESSION_SECRET_FOR_TEST" not in captured["env"]
    assert "CRYOSTACK_VOILA_TOKEN_FILE" not in captured["env"]
    assert captured["cwd"] == mod.repo_root()
    with pytest.raises(SystemExit, match="usage"):
        mod.run_voila("control")


def test_voila_config_drops_the_token_file_location(monkeypatch, tmp_path):
    class Config:
        class Voila:
            token = None
    monkeypatch.setenv("CRYOSTACK_VOILA_TOKEN", "x" * 40)
    monkeypatch.setenv("CRYOSTACK_VOILA_TOKEN_FILE", "/somewhere/voila_token")
    code = (_REPO / "bin" / "voila_config" / "voila.py").read_text()
    exec(compile(code, "voila.py", "exec"), {"c": Config})
    assert Config.Voila.token == "x" * 40
    assert "CRYOSTACK_VOILA_TOKEN" not in os.environ and "CRYOSTACK_VOILA_TOKEN_FILE" not in os.environ


# ── isolation self-check ──────────────────────────────────────────────────

def _layout(tmp_path):
    from deployment import check_kernel_isolation as tool

    install, home = tmp_path / "repo", tmp_path / "home"
    for d in (install / "var", install / "bin", install / "icesee_auth", install / "users",
              install / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "users",
              home / ".aws", home / ".ssh", home / ".cryostack", home / "cryostack-backups"):
        d.mkdir(parents=True)
    for name in ("cryostack_auth.db", "control_center_ops.db", "livist.db", "frozen_legacies_catalog.db"):
        (install / "var" / name).write_bytes(b"db")
    (install / "bin" / "icesee_app.py").write_text("# gateway")
    (home / ".aws" / "credentials").write_text("[default]")
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "environ").write_bytes(b"SECRET=1\0")
    (proc / "4242" / "cmdline").write_bytes(b"python\0/x/bin/icesee_app.py\0")
    (proc / "4243").mkdir()
    (proc / "4243" / "cmdline").write_bytes(b"python\0/x/bin/icesee_app.py\0voila\0icesheets\0")
    return tool, install, home, proc


def test_isolation_check_reports_every_exposure_of_a_shared_account(tmp_path):
    tool, install, home, proc = _layout(tmp_path)
    assert tool.gateway_pids(proc) == [4242]
    result = tool.check(install, home, proc=proc)
    assert result["ok"] is False and result["same_account_as_gateway"] is True
    assert "gateway environment (pid 4242)" in result["exposed"]
    assert "database var/cryostack_auth.db" in result["exposed"]
    assert "write access to the gateway code" in result["exposed"]
    assert "operator AWS config" in result["not_present"]
    assert result["missing_access"] == []
    assert "credentials" not in json.dumps(result).replace("operator AWS credentials", "")


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses permission bits")
def test_isolation_check_passes_when_everything_sensitive_is_closed(tmp_path):
    tool, install, home, proc = _layout(tmp_path)
    for path in [proc / "4242" / "environ", *(install / "var").iterdir(), home / ".aws" / "credentials"]:
        path.chmod(0o000)
    for path in (home / ".ssh", home / ".cryostack", home / "cryostack-backups", install / "users"):
        path.chmod(0o000)
    (install / "bin" / "icesee_app.py").chmod(0o444)
    (install / "icesee_auth").chmod(0o555)
    try:
        result = tool.check(install, home, proc=proc)
        assert result["exposed"] == []
        assert "read the gateway code" in result["allowed"]
        assert result["same_account_as_gateway"] is True       # a test can only use its own account
        assert result["ok"] is False
    finally:
        for path in (home / ".ssh", home / ".cryostack", home / "cryostack-backups", install / "users",
                     install / "icesee_auth"):
            path.chmod(0o700)
