"""The Voila identity boundary.

The kernel's CryoStack identity (HTTP_X_CRYOSTACK_USER_ID) comes from a header
that only the gateway may set. Voila listens on 127.0.0.1, so any local process
can reach it; these tests check that such a process cannot render a notebook
(and therefore cannot choose the identity) without the gateway's per-process
token, and that authenticated users still get their own identity through the
gateway.

The unit tests need nothing. The end-to-end tests start one real Voila server
on a free port with a two-line notebook that prints the identity its kernel
received; production ports and notebooks are never used.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_APP_PATH = _REPO / "bin" / "icesee_app.py"
_IDENTITY = re.compile(r"KERNEL-IDENTITY=([A-Za-z0-9_<>-]+)")
_TOKEN_IN_KERNEL = re.compile(r"TOKEN-IN-KERNEL=(True|False)")


def _load(monkeypatch, tmp_path, name):
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", "lazy")
    # the full gateway also opens the LIVIST store, Control Center ops store
    # and Frozen Legacies catalog: keep them out of the repository's var/
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


# ── unit: what the gateway sends and how it launches Voila ──────────────

def test_voila_token_travels_only_in_the_child_environment(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, "_icesee_app_boundary_env")
    monkeypatch.setattr(mod, "ManagedProcess", _Recorder)
    _Recorder.instances = []
    state = mod.ICESEEState()
    token = state.voila_token
    assert len(token) >= 32
    assert len(_Recorder.instances) == 2
    for proc in _Recorder.instances:
        assert not any(token in arg for arg in proc.command)          # never in argv / ps
        assert proc.env["CRYOSTACK_VOILA_TOKEN"] == token
        config_dir = proc.env["JUPYTER_CONFIG_PATH"].split(os.pathsep)[0]
        assert (Path(config_dir) / "voila.py").is_file()
    assert "CRYOSTACK_VOILA_TOKEN" not in os.environ                   # gateway env untouched
    assert mod.ICESEEState().voila_token != token                      # per process


def test_upstream_headers_replace_client_identity_token_and_voila_cookie(monkeypatch, tmp_path):
    from aiohttp.test_utils import make_mocked_request
    from aiohttp import web

    mod = _load(monkeypatch, tmp_path, "_icesee_app_boundary_headers")

    class State:
        voila_token = "gateway-token-123"

    class User:
        id, email, display_name = "alice-id", "alice@example.org", "Alice"

    app = web.Application()
    app["state"] = State()
    request = make_mocked_request(
        "GET", "/icesheets/",
        headers={
            "X-CryoStack-User-Id": "victim-id",
            "X-CryoStack-User-Email": "victim@example.org",
            "Authorization": "token forged",
            "Cookie": "icesee_session=s1; username-127-0-0-1-8870=stolen; _xsrf=x1",
        },
        app=app,
    )
    request["cryostack_user"] = User()
    headers = mod.build_upstream_headers(request, 8870)
    assert headers["X-CryoStack-User-Id"] == "alice-id"
    assert headers["X-CryoStack-User-Email"] == "alice@example.org"
    assert headers["Authorization"] == "token gateway-token-123"
    assert "username-" not in headers["Cookie"]
    assert "_xsrf=x1" in headers["Cookie"]

    # anonymous: no identity at all, client values never pass through
    anon = make_mocked_request("GET", "/icesheets/", headers={"X-CryoStack-User-Id": "victim-id"}, app=app)
    headers = mod.build_upstream_headers(anon, 8870)
    assert not any(k.lower() == "x-cryostack-user-id" for k in headers)


# ── end to end: real Voila behind the real gateway ───────────────────────

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace"), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), error.headers


@pytest.fixture(scope="module")
def whoami_notebook(tmp_path_factory):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("voila")
    folder = tmp_path_factory.mktemp("voila_boundary")
    nb = nbformat.v4.new_notebook()
    nb.cells = [nbformat.v4.new_code_cell(
        "import os\n"
        "print('KERNEL-IDENTITY=' + os.environ.get('HTTP_X_CRYOSTACK_USER_ID', '<none>'))\n"
        "print('TOKEN-IN-KERNEL=' + str('CRYOSTACK_VOILA_TOKEN' in os.environ))"
    )]
    path = folder / "whoami.ipynb"
    nbformat.write(nb, str(path))
    return path


@pytest.fixture()
def gateway_with_real_voila(monkeypatch, tmp_path, whoami_notebook):
    """The production gateway assembly; its CryoLauncher Voila serves the test
    notebook on a free port (same flags, same token mechanism)."""
    mod = _load(monkeypatch, tmp_path, "_icesee_app_boundary_e2e")
    port = _free_port()
    real = mod.ManagedProcess
    launched = []

    class Rewritten(real):
        def __init__(self, command, cwd, env=None):
            command = list(command)
            if any(str(arg).endswith("icesheets_voila.ipynb") for arg in command):
                command = [
                    str(whoami_notebook) if str(arg).endswith("icesheets_voila.ipynb")
                    else f"--port={port}" if arg == "--port=8870"
                    else arg
                    for arg in command
                ] + ["--Voila.port_retries=0"]
                launched.append(self)
            super().__init__(command, cwd, env)

        def start(self):
            if self in launched:
                super().start()

    monkeypatch.setattr(mod, "ManagedProcess", Rewritten)
    app = mod.make_app()
    state = app["state"]
    state.icesheets.port = port
    state.icesheets._port_timeout = 120.0
    yield mod, app, port
    for proc in launched:
        proc.stop()


def _render(body):
    found = _IDENTITY.search(body)
    return found.group(1) if found else None


def test_direct_local_access_cannot_choose_the_kernel_identity(gateway_with_real_voila):
    mod, app, port = gateway_with_real_voila
    from aiohttp.test_utils import TestClient, TestServer
    from icesee_auth import AuthManager

    async def go():
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            auth = AuthManager()
            users = {}
            for name in ("alice", "bob"):
                user = auth.storage.create_user(email=f"{name}@boundary.invalid", display_name=name,
                                                institution=None, password_hash="x")
                users[name] = (user.id, auth.storage.create_session(ttl_seconds=600, user_id=user.id).id)

            # Normal authenticated access through the gateway (starts Voila on demand).
            deadline = time.time() + 150
            while True:
                response = await client.get("/icesheets/", allow_redirects=False,
                                            cookies={"icesee_session": users["alice"][1]},
                                            headers={"X-CryoStack-User-Id": users["bob"][0]})
                body = await response.text()
                if _render(body) or time.time() > deadline:
                    break
                await asyncio.sleep(1)
            assert response.status == 200
            assert _render(body) == users["alice"][0]          # forged header ignored
            assert _TOKEN_IN_KERNEL.search(body).group(1) == "False"
            assert not any(v.startswith("username-") for v in response.headers.getall("Set-Cookie", []))

            # Workspace isolation: each user's kernel sees only that user.
            response = await client.get("/icesheets/", cookies={"icesee_session": users["bob"][1]})
            assert _render(await response.text()) == users["bob"][0]

            # Anonymous through the gateway: login, never a kernel.
            response = await client.get("/icesheets/", allow_redirects=False,
                                        headers={"X-CryoStack-User-Id": users["alice"][0]})
            assert response.status in (302, 303, 401)

            base = f"http://127.0.0.1:{port}/icesheets/"
            token = app["state"].voila_token
            loop = asyncio.get_running_loop()

            def direct(url, headers):
                return _get(url, headers)

            # Direct local access with a forged identity: refused, no kernel output.
            for url, headers in (
                (base, {"X-CryoStack-User-Id": users["alice"][0]}),
                (base, {"X-CryoStack-User-Id": users["alice"][0], "Authorization": "token wrong"}),
                (base + "?token=wrong", {"X-CryoStack-User-Id": users["alice"][0]}),
                (base + "api/kernels", {}),
                (base, {"X-CryoStack-User-Id": users["alice"][0],
                        "Cookie": f"username-127-0-0-1-{port}=forged"}),
            ):
                status, body, _ = await loop.run_in_executor(None, direct, url, headers)
                assert status in (302, 401, 403), (url, status)
                assert _render(body) is None

            # The token itself is what grants access (sanity check of the test).
            status, body, _ = await loop.run_in_executor(
                None, direct, base, {"Authorization": f"token {token}", "X-CryoStack-User-Id": "probe"})
            assert status == 200 and _render(body) == "probe"

            # The token never appears in any local process's command line.
            ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
            assert token not in ps
        finally:
            await client.close()

    asyncio.run(go())
