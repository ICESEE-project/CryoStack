"""Password sign-in throttling layers and event-loop safety.

* per email: 10 failures / 15 min (covered in test_control_access_admin.py);
* per client address: 50 failures / 15 min, so one source cannot spray
  passwords across many addresses;
* scrypt runs off the event loop, so a burst of sign-ins does not stall
  the gateway for everyone else.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from icesee_auth import AuthManager
from icesee_auth import manager as auth_manager
from icesee_auth.security import hash_password


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    for name in ("GITHUB", "ORCID"):
        for part in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"):
            monkeypatch.delenv(f"CRYOSTACK_{name}_{part}", raising=False)
    auth = AuthManager(database_path=tmp_path / "auth.db", secure_cookies=False)
    app = web.Application()
    auth.install(app)

    async def ping(request):
        return web.Response(text="pong")

    app.router.add_get("/ping", ping)
    return auth, app


def _run(app, script):
    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client)
    return asyncio.run(go())


def test_client_address_trusts_x_real_ip_only_from_loopback():
    def request(remote, real_ip):
        req = make_mocked_request("POST", "/auth/login", headers={"X-Real-IP": real_ip},
                                  transport=_Transport(remote))
        return auth_manager.client_address(req)

    assert request("127.0.0.1", "203.0.113.7") == "203.0.113.7"     # nginx on loopback
    assert request("::1", "203.0.113.7") == "203.0.113.7"
    assert request("198.51.100.9", "203.0.113.7") == "198.51.100.9"  # spoofed from outside


class _Transport:
    def __init__(self, remote):
        self._remote = remote

    def get_extra_info(self, name, default=None):
        return (self._remote, 12345) if name == "peername" else default

    def is_closing(self):
        return False


def test_one_address_cannot_spray_passwords_across_many_accounts(auth_app):
    auth, app = auth_app
    limit = auth_manager.LOGIN_ADDRESS_FAILURE_LIMIT
    victim = auth.storage.create_user(email="victim@example.org", display_name="V", institution=None,
                                      password_hash=hash_password("correct horse battery"))

    async def script(client):
        statuses = []
        for i in range(limit):
            r = await client.post("/auth/login", headers={"X-Real-IP": "203.0.113.7"},
                                  data={"email": f"spray{i}@example.org", "password": "guess-1234"},
                                  allow_redirects=False)
            statuses.append(r.status)
        sprayer = await client.post("/auth/login", headers={"X-Real-IP": "203.0.113.7"},
                                    data={"email": victim.email, "password": "correct horse battery"},
                                    allow_redirects=False)
        other = await client.post("/auth/login", headers={"X-Real-IP": "198.51.100.20"},
                                  data={"email": victim.email, "password": "correct horse battery"},
                                  allow_redirects=False)
        return statuses, sprayer.status, other.status

    statuses, sprayer, other = _run(app, script)
    assert statuses == [400] * limit           # each address only failed once
    assert sprayer == 429                      # the source is throttled ...
    assert other == 302                        # ... the victim elsewhere is not


def test_password_hashing_does_not_block_the_event_loop(auth_app, monkeypatch):
    auth, app = auth_app
    auth.storage.create_user(email="slow@example.org", display_name="S", institution=None,
                             password_hash=hash_password("correct horse battery"))

    def slow_verify(password, encoded):
        time.sleep(0.6)                        # a blocking scrypt stand-in
        return False

    monkeypatch.setattr(auth_manager, "verify_password", slow_verify)

    async def script(client):
        login = asyncio.ensure_future(client.post(
            "/auth/login", data={"email": "slow@example.org", "password": "wrong-pass"},
            allow_redirects=False))
        await asyncio.sleep(0.1)               # the sign-in is now hashing
        started = time.perf_counter()
        ping = await client.get("/ping")
        ping_seconds = time.perf_counter() - started
        response = await login
        return ping.status, ping_seconds, response.status

    ping_status, ping_seconds, login_status = _run(app, script)
    assert ping_status == 200 and login_status == 400
    assert ping_seconds < 0.3                  # served while the hash was running
