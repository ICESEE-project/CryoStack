#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from aiohttp import ClientSession, WSMsgType, web

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def book_root() -> Path:
    return repo_root() / "icesee_jupyter_book" / "_build" / "html"


def run_center_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "run_center_voila.ipynb"


def icesheets_nb() -> Path:
    return repo_root() / "icesee_jupyter_book" / "icesee_jupyter_notebooks" / "icesheets_voila.ipynb"


def wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


async def root_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/index.html")


class ManagedProcess:
    def __init__(self, command: list[str], cwd: Path):
        self.command = command
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(self.cwd),
            stdout=sys.stdout,
            stderr=sys.stderr,
            preexec_fn=os.setsid,
        )

    def stop(self) -> None:
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass


class ICESEEState:
    def __init__(self) -> None:
        py = sys.executable
        root = repo_root()

        self.run_center_port = 8866
        self.icesheets_port = 8870

        self.run_center = ManagedProcess(
            [
                py,
                "-m",
                "voila",
                str(run_center_nb()),
                "--no-browser",
                "--Voila.ip=127.0.0.1",
                "--port=8866",
                "--Voila.base_url=/icesee-gui/",
                "--Voila.allow_origin=http://127.0.0.1:8080",
            ],
            root,
        )

        self.icesheets = ManagedProcess(
            [
                py,
                "-m",
                "voila",
                str(icesheets_nb()),
                "--no-browser",
                "--Voila.ip=127.0.0.1",
                "--port=8870",
                "--Voila.base_url=/icesheets/",
                "--Voila.allow_origin=http://127.0.0.1:8080",
            ],
            root,
        )

        self.client: ClientSession | None = None

    async def startup(self, app: web.Application) -> None:
        if not book_root().joinpath("index.html").exists():
            raise RuntimeError(f"Missing built book at {book_root() / 'index.html'}")
        if not run_center_nb().exists():
            raise RuntimeError(f"Missing notebook {run_center_nb()}")
        if not icesheets_nb().exists():
            raise RuntimeError(f"Missing notebook {icesheets_nb()}")

        self.run_center.start()
        self.icesheets.start()

        if not wait_for_port("127.0.0.1", self.run_center_port, timeout=45):
            raise RuntimeError("Run center Voilà failed to start on port 8866")
        if not wait_for_port("127.0.0.1", self.icesheets_port, timeout=45):
            raise RuntimeError("Icesheets Voilà failed to start on port 8870")

        self.client = ClientSession()

    async def cleanup(self, app: web.Application) -> None:
        if self.client:
            await self.client.close()
        self.run_center.stop()
        self.icesheets.stop()


def build_upstream_headers(request: web.Request, upstream_port: int) -> dict[str, str]:
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() not in {"host", "origin"}
    }
    headers["Host"] = f"127.0.0.1:{upstream_port}"
    headers["Origin"] = f"http://127.0.0.1:{upstream_port}"
    headers["X-Forwarded-Proto"] = "http"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-For"] = request.remote or "127.0.0.1"
    return headers


async def proxy_http(request: web.Request, upstream_port: int) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)
    body = await request.read()

    async with state.client.request(
        request.method,
        upstream_url,
        headers=headers,
        data=body if body else None,
        allow_redirects=False,
    ) as resp:
        out = web.StreamResponse(status=resp.status, reason=resp.reason)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_BY_HOP:
                out.headers[k] = v

        await out.prepare(request)
        async for chunk in resp.content.iter_chunked(65536):
            await out.write(chunk)
        await out.write_eof()
        return out


async def proxy_ws(request: web.Request, upstream_port: int) -> web.WebSocketResponse:
    state: ICESEEState = request.app["state"]
    assert state.client is not None

    upstream_url = f"http://127.0.0.1:{upstream_port}{request.rel_url}"
    headers = build_upstream_headers(request, upstream_port)

    browser_ws = web.WebSocketResponse()
    await browser_ws.prepare(request)

    async with state.client.ws_connect(upstream_url, headers=headers) as upstream_ws:

        async def browser_to_upstream() -> None:
            async for msg in browser_ws:
                if msg.type == WSMsgType.TEXT:
                    await upstream_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await upstream_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await upstream_ws.close()

        async def upstream_to_browser() -> None:
            async for msg in upstream_ws:
                if msg.type == WSMsgType.TEXT:
                    await browser_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await browser_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await browser_ws.close()

        await asyncio.gather(browser_to_upstream(), upstream_to_browser())

    return browser_ws


async def proxy_dispatch(request: web.Request, upstream_port: int) -> web.StreamResponse:
    upgrade = request.headers.get("Upgrade", "").lower()
    connection = request.headers.get("Connection", "").lower()
    if upgrade == "websocket" or "upgrade" in connection:
        return await proxy_ws(request, upstream_port)
    return await proxy_http(request, upstream_port)


async def proxy_run_center(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await proxy_dispatch(request, state.run_center_port)


async def proxy_icesheets(request: web.Request) -> web.StreamResponse:
    state: ICESEEState = request.app["state"]
    return await proxy_dispatch(request, state.icesheets_port)


def make_app() -> web.Application:
    app = web.Application()
    state = ICESEEState()
    app["state"] = state

    app.on_startup.append(state.startup)
    app.on_cleanup.append(state.cleanup)

    app.router.add_route("*", "/icesee-gui", proxy_run_center)
    app.router.add_route("*", "/icesee-gui/{tail:.*}", proxy_run_center)

    app.router.add_route("*", "/icesheets", proxy_icesheets)
    app.router.add_route("*", "/icesheets/{tail:.*}", proxy_icesheets)

    app.router.add_get("/", root_redirect)
    app.router.add_static("/", path=str(book_root()), show_index=True)

    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=8080)