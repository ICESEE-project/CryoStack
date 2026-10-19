"""Gateway credentials never reach Voila or its notebook kernels.

The gateway's environment carries the OAuth client secrets, the connector-relay
deployment token and operator session variables. Voila servers are launched
with an allowlisted environment, so the kernels they start (and everything a
kernel spawns) see only application settings plus the per-request identity and
relay grant the gateway forwards as headers.

The unit tests check the launch environment and the forwarded headers. The
end-to-end tests run the real gateway assembly with both application Voila
servers (ICESEE and CryoLauncher) serving a probe notebook on free ports, with
sentinel credentials in the gateway environment, and inspect what the running
kernels actually see: after authenticated rendering, over the kernel websocket,
and after a kernel restart. Sentinel values are never printed; the probe only
reports variable names and booleans.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import importlib.util
import json
import os
import re
import socket
import sys
import time
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_APP_PATH = _REPO / "bin" / "icesee_app.py"

#: gateway-only credentials, set to sentinel values for these tests
_GATEWAY_SECRETS = {
    "CRYOSTACK_GITHUB_CLIENT_SECRET": "sentinel-github-secret-5c1e",
    "CRYOSTACK_ORCID_CLIENT_SECRET": "sentinel-orcid-secret-7a2d",
    "CRYOSTACK_RELAY_CONTROL_TOKEN": "sentinel-relay-deploy-token-9b3f",
    "AWS_ACCESS_KEY_ID": "SENTINELAKIA0000KEY",
    "AWS_SECRET_ACCESS_KEY": "sentinel-aws-secret-key-1f4e",
    "AWS_SESSION_TOKEN": "sentinel-aws-session-token-2e8c",
    "ICESEE_API_TOKEN": "sentinel-prefixed-token-6d0a",
}
#: operator / non-credential gateway variables kernels do not need
_GATEWAY_ONLY = {
    "CRYOSTACK_GITHUB_CLIENT_ID": "sentinel-github-client-id",
    "KRB5CCNAME": "FILE:/tmp/sentinel-krb5cc",
    "SSH_AUTH_SOCK": "/tmp/sentinel-agent.sock",
    "VSCODE_IPC_HOOK_CLI": "/tmp/sentinel-vscode.sock",
    "CRYOSTACK_WORKSPACE_USER": "sentinel-override-user",
}
#: application settings kernels legitimately need
_KERNEL_SETTINGS = {
    "AWS_PROFILE": "sentinel-cloud-profile",
    "AWS_DEFAULT_REGION": "us-east-2",
    "CRYOSTACK_AGENT_PANEL": "1",
    "CRYOSTACK_AWS_PRINCIPAL_ARN": "arn:aws:iam::000000000000:user/sentinel",
    "ICEPACK_ROOT": "/tmp/sentinel-icepack",
}


def _load(monkeypatch, tmp_path, name):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", "lazy")
    monkeypatch.setenv("CRYOSTACK_LIVIST_DATABASE", str(tmp_path / "livist.db"))
    monkeypatch.setenv("CRYOSTACK_CONTROL_OPS_DATABASE", str(tmp_path / "ops.db"))
    monkeypatch.setenv("CRYOSTACK_FROZEN_LEGACIES_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "workspace"))
    spec = importlib.util.spec_from_file_location(name, _APP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _set_gateway_env(monkeypatch):
    for values in (_GATEWAY_SECRETS, _GATEWAY_ONLY, _KERNEL_SETTINGS):
        for name, value in values.items():
            monkeypatch.setenv(name, value)


def _leaks(text: str) -> list[str]:
    """Names of sentinel credentials whose *value* occurs in ``text``."""
    return [name for name, value in {**_GATEWAY_SECRETS, **_GATEWAY_ONLY}.items() if value in text]


class _Recorder:
    instances: list = []

    def __init__(self, command, cwd, env=None):
        self.command, self.cwd, self.env = command, cwd, env
        _Recorder.instances.append(self)

    def start(self):
        pass

    def stop(self):
        pass


# ── unit: launch environment and forwarded headers ───────────────────────

def test_voila_environment_is_an_allowlist(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, "_icesee_app_isolation_env")
    source = {**_GATEWAY_SECRETS, **_GATEWAY_ONLY, **_KERNEL_SETTINGS,
              "PATH": "/usr/bin", "HOME": "/home/svc", "LC_ALL": "C.UTF-8",
              "CRYOSTACK_AUTH_DATABASE": "/srv/auth.db",
              "APPTAINER_DOCKER_PASSWORD": "sentinel-registry-password",
              "AWS_SHARED_CREDENTIALS_FILE": "/home/svc/.aws/credentials",
              "CRYOSTACK_CLOUD_OPERATOR_USER_IDS": "operator-id",
              "JUPYTER_CONFIG_PATH": "/etc/jupyter"}
    env = mod.voila_environment("tok", source)

    for name in (*_GATEWAY_SECRETS, *_GATEWAY_ONLY, "APPTAINER_DOCKER_PASSWORD"):
        assert name not in env, name
    for name in (*_KERNEL_SETTINGS, "PATH", "HOME", "LC_ALL", "CRYOSTACK_AUTH_DATABASE",
                 "AWS_SHARED_CREDENTIALS_FILE", "CRYOSTACK_CLOUD_OPERATOR_USER_IDS"):
        assert env[name] == source[name], name
    assert env["CRYOSTACK_VOILA_TOKEN"] == "tok"
    config_path = env["JUPYTER_CONFIG_PATH"].split(os.pathsep)
    assert Path(config_path[0], "voila.py").is_file() and config_path[1] == "/etc/jupyter"


def test_both_voila_servers_get_the_allowlisted_env_and_identity_headers(monkeypatch, tmp_path):
    _set_gateway_env(monkeypatch)
    mod = _load(monkeypatch, tmp_path, "_icesee_app_isolation_launch")
    monkeypatch.setattr(mod, "ManagedProcess", _Recorder)
    _Recorder.instances = []
    mod.ICESEEState()
    assert len(_Recorder.instances) == 2
    for proc in _Recorder.instances:
        assert not _leaks(json.dumps(proc.env)) and not _leaks(" ".join(proc.command))
        assert proc.env["AWS_PROFILE"] == _KERNEL_SETTINGS["AWS_PROFILE"]
        for header in ("X-CryoStack-User-Id", "X-CryoStack-User-Name", "X-CryoStack-Relay-Grant"):
            assert f"--VoilaConfiguration.http_header_envs={header}" in proc.command


def test_upstream_headers_carry_only_the_users_own_relay_grant(monkeypatch, tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    from icesee_jupyter_book.core.connector_relay_auth import owner_grant

    monkeypatch.setenv("CRYOSTACK_RELAY_CONTROL_TOKEN", _GATEWAY_SECRETS["CRYOSTACK_RELAY_CONTROL_TOKEN"])
    mod = _load(monkeypatch, tmp_path, "_icesee_app_isolation_headers")

    class State:
        voila_token = "gateway-token"

    class User:
        id, email, display_name = "alice-id", "alice@example.org", "Alice"

    app = web.Application()
    app["state"] = State()
    forged = {"X-CryoStack-Relay-Grant": owner_grant("bob-id")}
    request = make_mocked_request("GET", "/icesheets/", headers=forged, app=app)
    request["cryostack_user"] = User()
    headers = mod.build_upstream_headers(request, 8870)
    assert headers["X-CryoStack-Relay-Grant"] == owner_grant("alice-id")
    assert not _leaks(json.dumps(headers))

    anon = make_mocked_request("GET", "/icesheets/", headers=forged, app=app)
    assert not any(k.lower() == "x-cryostack-relay-grant" for k in mod.build_upstream_headers(anon, 8870))

    monkeypatch.delenv("CRYOSTACK_RELAY_CONTROL_TOKEN")
    request = make_mocked_request("GET", "/icesheets/", app=app)
    request["cryostack_user"] = User()
    assert "X-CryoStack-Relay-Grant" not in mod.build_upstream_headers(request, 8870)


# ── end to end: real kernels behind the real gateway ─────────────────────

_PROBE = re.compile(r"KERNEL-PROBE=(\{.*?\})KERNEL-PROBE-END")

_PROBE_SOURCE = '''
import hashlib, json, os
_values = json.loads(os.environ.get("CRYOSTACK_TEST_SENTINEL_HASHES_PATH") and open(os.environ["CRYOSTACK_TEST_SENTINEL_HASHES_PATH"]).read() or "[]")
def _proc(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""
def _found(blob):
    return sorted({h for h in _values for part in blob.split(b"\\0") for v in [part.split(b"=", 1)[-1]] if hashlib.sha256(v).hexdigest() == h})
_grant = os.environ.get("HTTP_X_CRYOSTACK_RELAY_GRANT", "")
print("KERNEL-PROBE=" + json.dumps({
    "identity": os.environ.get("HTTP_X_CRYOSTACK_USER_ID", ""),
    "names": sorted(os.environ),
    "env_hits": _found("\\0".join(f"{k}={v}" for k, v in os.environ.items()).encode()),
    "self_hits": _found(_proc("/proc/self/environ")),
    "voila_hits": _found(_proc(f"/proc/{os.getppid()}/environ")),
    "grant_sha": hashlib.sha256(_grant.encode()).hexdigest() if _grant else "",
}) + "KERNEL-PROBE-END")
'''


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def probe_notebook(tmp_path_factory):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("voila")
    folder = tmp_path_factory.mktemp("kernel_isolation")
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(_PROBE_SOURCE)]
    path = folder / "probe.ipynb"
    nbformat.write(nb, str(path))
    return path


_APPS = {
    # route prefix: (production notebook, production port flag)
    "icesee-gui": ("run_center_voila.ipynb", "--port=8866"),
    "icesheets": ("icesheets_voila.ipynb", "--port=8870"),
}


@pytest.fixture()
def gateway(monkeypatch, tmp_path, probe_notebook):
    """The production gateway assembly; both application Voila servers serve the
    probe notebook on free ports with their production flags and environment."""
    _set_gateway_env(monkeypatch)
    # The probe recognises sentinel values by their SHA-256 digests only, read
    # from a file whose path is added to the (already filtered) Voila env.
    hashes = tmp_path / "sentinel_hashes.json"
    hashes.write_text(json.dumps([_sha(v) for v in {**_GATEWAY_SECRETS, **_GATEWAY_ONLY}.values()]))
    mod = _load(monkeypatch, tmp_path, "_icesee_app_isolation_e2e")
    real = mod.ManagedProcess
    ports = {name: _free_port() for name in _APPS}
    launched = {}

    class Rewritten(real):
        def __init__(self, command, cwd, env=None):
            command = list(command)
            for name, (notebook, port_flag) in _APPS.items():
                if any(str(arg).endswith(notebook) for arg in command):
                    command = [
                        str(probe_notebook) if str(arg).endswith(notebook)
                        else f"--port={ports[name]}" if arg == port_flag
                        else arg
                        for arg in command
                    ] + ["--Voila.port_retries=0"]
                    env = dict(env or {})
                    env["CRYOSTACK_TEST_SENTINEL_HASHES_PATH"] = str(hashes)
                    launched[name] = self
            super().__init__(command, cwd, env)

    monkeypatch.setattr(mod, "ManagedProcess", Rewritten)
    app = mod.make_app()
    state = app["state"]
    state.run_center.port, state.icesheets.port = ports["icesee-gui"], ports["icesheets"]
    state.run_center._port_timeout = state.icesheets._port_timeout = 120.0
    yield mod, app, launched
    for proc in launched.values():
        proc.stop()


def _kernel_pids(voila_pid: int) -> dict[str, int]:
    """``{kernel_id: pid}`` for the ipykernel children of one Voila server."""
    found = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        match = re.search(rb"kernel-([0-9a-f-]{36})\.json", b" ".join(cmdline))
        if ppid == voila_pid and match:
            found[match.group(1).decode()] = int(entry.name)
    return found


def _proc_environ(pid: int) -> dict[str, str]:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    return dict(part.decode("utf-8", "replace").split("=", 1) for part in raw.split(b"\0") if b"=" in part)


def _assert_clean_kernel_env(env: dict[str, str], identity: str):
    assert not _leaks("\0".join(f"{k}={v}" for k, v in env.items()))
    for name in (*_GATEWAY_SECRETS, *_GATEWAY_ONLY, "CRYOSTACK_VOILA_TOKEN"):
        assert name not in env, name
    assert env.get("HTTP_X_CRYOSTACK_USER_ID") == identity
    for name in _KERNEL_SETTINGS:
        assert env.get(name) == _KERNEL_SETTINGS[name], name


def _msg(msg_type: str, content: dict) -> dict:
    return {
        "header": {"msg_id": uuid.uuid4().hex, "msg_type": msg_type, "username": "test",
                   "session": uuid.uuid4().hex, "version": "5.3", "date": ""},
        "parent_header": {}, "metadata": {}, "content": content, "channel": "shell",
        "buffers": [],
    }


async def _replies(ws, msg_type: str, timeout: float) -> list[dict]:
    """Every message of ``msg_type`` received within ``timeout`` seconds."""
    seen, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            frame = await ws.receive(timeout=max(0.05, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if frame.type.name != "TEXT":
            if frame.type.name in ("CLOSE", "CLOSED", "ERROR"):
                break
            continue
        data = json.loads(frame.data)
        if data.get("msg_type") == msg_type or data.get("header", {}).get("msg_type") == msg_type:
            seen.append(data)
            if msg_type != "execute_reply":
                break
    return seen


def test_kernels_never_see_gateway_credentials(gateway, tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    from icesee_auth import AuthManager
    from icesee_jupyter_book.core.connector_relay_auth import owner_grant

    mod, app, launched = gateway
    relay_token = _GATEWAY_SECRETS["CRYOSTACK_RELAY_CONTROL_TOKEN"]
    marker = tmp_path / "execute_request_ran"

    async def render(client, prefix, cookie, expected_user):
        deadline = time.time() + 180
        while True:
            response = await client.get(f"/{prefix}/", allow_redirects=False,
                                        cookies={"icesee_session": cookie})
            body = html.unescape(await response.text())
            found = _PROBE.search(body)
            if found or time.time() > deadline:
                break
            await asyncio.sleep(1)
        assert response.status == 200 and found, (prefix, response.status)
        probe = json.loads(found.group(1))
        assert probe["identity"] == expected_user
        assert probe["env_hits"] == [] and probe["self_hits"] == [] and probe["voila_hits"] == []
        for name in (*_GATEWAY_SECRETS, *_GATEWAY_ONLY, "CRYOSTACK_VOILA_TOKEN"):
            assert name not in probe["names"], (prefix, name)
        for name in (*_KERNEL_SETTINGS, "PATH", "HOME", "CRYOSTACK_AUTH_DATABASE",
                     "HTTP_X_CRYOSTACK_USER_ID"):
            assert name in probe["names"], (prefix, name)
        # the kernel holds its own user's relay grant, never the deployment token
        assert probe["grant_sha"] == _sha(owner_grant(expected_user, relay_token))
        return probe

    async def go():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            auth = AuthManager()
            users = {}
            for name in ("alice", "bob"):
                user = auth.storage.create_user(email=f"{name}@isolation.invalid", display_name=name,
                                                institution=None, password_hash="x")
                users[name] = (user.id, auth.storage.create_session(ttl_seconds=600, user_id=user.id).id)
            alice_id, alice_cookie = users["alice"]

            for prefix in _APPS:
                voila_pid = launched[prefix].proc and launched[prefix].proc.pid
                before = set(_kernel_pids(voila_pid)) if voila_pid else set()

                # authenticated access + kernel creation
                await render(client, prefix, alice_cookie, alice_id)
                voila_pid = launched[prefix].proc.pid
                assert not _leaks(Path(f"/proc/{voila_pid}/environ").read_bytes().decode("utf-8", "replace"))
                kernels = {k: p for k, p in _kernel_pids(voila_pid).items() if k not in before}
                assert len(kernels) == 1, (prefix, kernels)
                (kernel_id, pid), = kernels.items()
                _assert_clean_kernel_env(_proc_environ(pid), alice_id)

                channels = f"/{prefix}/api/kernels/{kernel_id}/channels"
                # anonymous websocket through the gateway is refused
                anon = await client.get(channels, allow_redirects=False)
                assert anon.status in (302, 303, 401, 403)

                # authenticated websocket through the gateway
                async with client.ws_connect(channels, headers={"Cookie": f"icesee_session={alice_cookie}"}) as ws:
                    await ws.send_json(_msg("kernel_info_request", {}))
                    assert await _replies(ws, "kernel_info_reply", 30)
                    # arbitrary code execution is not a websocket capability
                    code = f"open({str(marker)!r}, 'w').write('ran')"
                    await ws.send_json(_msg("execute_request", {
                        "code": code, "silent": False, "store_history": False,
                        "user_expressions": {}, "allow_stdin": False, "stop_on_error": True}))
                    assert await _replies(ws, "execute_reply", 3) == []
                    assert not marker.exists()

                    # kernel restart keeps the same clean, per-user environment
                    await ws.send_json(_msg("shutdown_request", {"restart": True}))
                    await _replies(ws, "shutdown_reply", 30)

                deadline = time.time() + 90
                while time.time() < deadline:
                    new_pid = _kernel_pids(voila_pid).get(kernel_id)
                    if new_pid and new_pid != pid:
                        break
                    await asyncio.sleep(0.5)
                assert new_pid and new_pid != pid, (prefix, "kernel did not restart")
                _assert_clean_kernel_env(_proc_environ(new_pid), alice_id)
                async with client.ws_connect(channels, headers={"Cookie": f"icesee_session={alice_cookie}"}) as ws:
                    await ws.send_json(_msg("kernel_info_request", {}))
                    assert await _replies(ws, "kernel_info_reply", 60)

                # another user gets their own identity and grant, still no credentials
                await render(client, prefix, users["bob"][1], users["bob"][0])
        finally:
            await client.close()

    asyncio.run(go())
