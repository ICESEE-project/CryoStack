from __future__ import annotations

from aiohttp import web

from ..templates import (
    users_page,
    user_detail_page,
)


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


async def user_detail_page_handler(
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

    return web.Response(
        text=user_detail_page(
            user=user
        ),
        content_type="text/html",
    )