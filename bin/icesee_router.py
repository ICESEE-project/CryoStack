#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from aiohttp import web, ClientSession, WSMsgType

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


def pick_target(request, book_port: int, voila_port: int, icesheet_port: int):
    path = request.path

    if path == "/icesee-gui" or path.startswith("/icesee-gui/"):
        return "127.0.0.1", voila_port, path

    if path == "/icesheets" or path.startswith("/icesheets/"):
        return "127.0.0.1", icesheet_port, path

    return "127.0.0.1", book_port, path


async def handle_http(request: web.Request) -> web.StreamResponse:
    host, port, upstream_path = pick_target(
        request,
        request.app["book_port"],
        request.app["voila_port"],
        request.app["icesheet_port"],
    )

    upstream_url = f"http://{host}:{port}{upstream_path}"
    if request.query_string:
        upstream_url += f"?{request.query_string}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    }
    headers["Host"] = f"{host}:{port}"

    body = await request.read()

    async with request.app["client"].request(
        request.method,
        upstream_url,
        headers=headers,
        data=body if body else None,
        allow_redirects=False,
    ) as resp:
        proxy_resp = web.StreamResponse(status=resp.status, reason=resp.reason)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_BY_HOP:
                proxy_resp.headers[k] = v
        await proxy_resp.prepare(request)

        async for chunk in resp.content.iter_chunked(65536):
            await proxy_resp.write(chunk)

        await proxy_resp.write_eof()
        return proxy_resp


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    host, port, upstream_path = pick_target(
        request,
        request.app["book_port"],
        request.app["voila_port"],
        request.app["icesheet_port"],
    )

    upstream_url = f"http://{host}:{port}{upstream_path}"
    if request.query_string:
        upstream_url += f"?{request.query_string}"

    client_ws = web.WebSocketResponse()
    await client_ws.prepare(request)

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "host"
    }
    headers["Host"] = f"{host}:{port}"

    async with request.app["client"].ws_connect(upstream_url, headers=headers) as upstream_ws:
        async def client_to_upstream():
            async for msg in client_ws:
                if msg.type == WSMsgType.TEXT:
                    await upstream_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await upstream_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await upstream_ws.close()

        async def upstream_to_client():
            async for msg in upstream_ws:
                if msg.type == WSMsgType.TEXT:
                    await client_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await client_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.CLOSE:
                    await client_ws.close()

        await asyncio.gather(client_to_upstream(), upstream_to_client())

    return client_ws


async def dispatch(request: web.Request) -> web.StreamResponse:
    upgrade = request.headers.get("Upgrade", "").lower()
    connection = request.headers.get("Connection", "").lower()
    if upgrade == "websocket" or "upgrade" in connection:
        return await handle_ws(request)
    return await handle_http(request)


async def on_startup(app: web.Application):
    app["client"] = ClientSession()


async def on_cleanup(app: web.Application):
    await app["client"].close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=int, default=8080)
    parser.add_argument("--book-port", type=int, default=8081)
    parser.add_argument("--voila-port", type=int, default=8866)
    parser.add_argument("--icesheet-port", type=int, default=8870)
    args = parser.parse_args()

    app = web.Application()
    app["book_port"] = args.book_port
    app["voila_port"] = args.voila_port
    app["icesheet_port"] = args.icesheet_port
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_route("*", "/{tail:.*}", dispatch)

    web.run_app(app, host="127.0.0.1", port=args.listen_port)


if __name__ == "__main__":
    main()