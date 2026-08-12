# control_center/api/users.py

from __future__ import annotations

from aiohttp import web


async def users_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_user_service"
    ]

    return web.json_response(
        {
            "users": (
                service.list_users()
            )
        }
    )