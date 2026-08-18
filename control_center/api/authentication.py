from __future__ import annotations

from aiohttp import web


async def authentication_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_authentication_service"
    ]

    return web.json_response(
        service.get_overview()
    )