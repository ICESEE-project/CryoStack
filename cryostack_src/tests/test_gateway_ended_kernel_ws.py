"""A browser tab left open across a gateway restart keeps reconnecting to its
old kernel. The gateway asks Voila once, then answers later attempts itself,
so Voila is not hit (and does not log a traceback) on every retry.

Both servers are local aiohttp stand-ins on free ports; no Voila is started.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

GONE = "9db7b030-a401-4182-8956-f8c73a218ad9"
LIVE = "1c4f6a2e-0b7d-4a51-9e3c-2d8f5b6a7c90"


def _load(monkeypatch, tmp_path):
    for key, name in (("CRYOSTACK_AUTH_DATABASE", "auth.db"), ("CRYOSTACK_LIVIST_DATABASE", "livist.db"),
                      ("CRYOSTACK_CONTROL_OPS_DATABASE", "ops.db"),
                      ("CRYOSTACK_FROZEN_LEGACIES_CATALOG", "catalog.db")):
        monkeypatch.setenv(key, str(tmp_path / name))
    monkeypatch.setenv("CRYOSTACK_APP_START_MODE", "lazy")
    spec = importlib.util.spec_from_file_location("gateway_ws_test", _REPO / "bin" / "icesee_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "build_upstream_headers", lambda request, port: {})
    return mod


def test_ended_kernel_is_answered_by_the_gateway_after_one_upstream_404(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    hits = []

    async def channels(request):
        hits.append(request.match_info["kernel"])
        if request.match_info["kernel"] != LIVE:
            raise web.HTTPNotFound(text="Kernel does not exist")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            await ws.send_str("echo:" + msg.data)
        return ws

    async def scenario():
        upstream = web.Application()
        upstream.router.add_get("/icesheets/api/kernels/{kernel}/channels", channels)
        async with TestServer(upstream) as up, aiohttp.ClientSession() as client:
            gateway = web.Application()
            gateway["state"] = SimpleNamespace(client=client, ended_kernels={})
            gateway.router.add_get("/{tail:.*}", lambda r: mod.proxy_ws(r, up.port))
            async with TestServer(gateway) as gw:
                url = f"http://127.0.0.1:{gw.port}/icesheets/api/kernels/%s/channels?session_id=s"
                for _ in range(5):
                    try:
                        await client.ws_connect(url % GONE)
                        raise AssertionError("a gone kernel must not open a websocket")
                    except aiohttp.WSServerHandshakeError as exc:
                        assert exc.status == 404
                async with client.ws_connect(url % LIVE) as ws:
                    await ws.send_str("hi")
                    assert (await ws.receive()).data == "echo:hi"
                return gateway["state"].ended_kernels

    ended = asyncio.run(scenario())
    assert hits.count(GONE) == 1 and hits.count(LIVE) == 1
    assert list(ended) and all(k[1] == GONE for k in ended)
