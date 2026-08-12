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
            "users": service.list_users()
        }
    )


async def user_detail_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_user_service"
    ]

    user = service.get_user(
        user_id=request.match_info[
            "user_id"
        ]
    )

    if user is None:
        raise web.HTTPNotFound(
            text="User not found."
        )

    return web.json_response(
        {
            "user": user
        }
    )