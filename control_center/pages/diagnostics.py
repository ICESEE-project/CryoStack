from aiohttp import web

from ..templates import (
    diagnostics_page,
)


async def diagnostics_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_diagnostics_service"
    ]

    return web.Response(
        text=diagnostics_page(
            data=service.get_diagnostics()
        ),
        content_type="text/html",
    )

