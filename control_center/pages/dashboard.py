# control_center/pages/dashboard.py

from __future__ import annotations

from aiohttp import web

from ..templates import dashboard_page


async def dashboard_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_dashboard_service"
    ]

    data = service.get_dashboard()

    return web.Response(
        text=dashboard_page(
            data=data
        ),
        content_type="text/html",
    )