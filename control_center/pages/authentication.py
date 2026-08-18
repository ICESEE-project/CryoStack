from __future__ import annotations

from aiohttp import web

from ..templates import (
    authentication_page,
)


async def authentication_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_authentication_service"
    ]

    return web.Response(
        text=authentication_page(
            data=service.get_overview()
        ),
        content_type="text/html",
    )