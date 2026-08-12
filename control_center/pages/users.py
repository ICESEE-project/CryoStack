# control_center/pages/users.py

from __future__ import annotations

from aiohttp import web

from ..templates import users_page


async def users_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_user_service"
    ]

    return web.Response(
        text=users_page(
            users=service.list_users()
        ),
        content_type="text/html",
    )