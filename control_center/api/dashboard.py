# control_center/api/dashboard.py

from __future__ import annotations

from aiohttp import web


async def dashboard_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_dashboard_service"
    ]

    return web.json_response(
        service.get_dashboard()
    )