from __future__ import annotations

from aiohttp import web
import time

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
            users=service.list_users(
                now=time.time(),
            )
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

    access = request.app[
    "control_access_service"
    ]

    actor = request[
        "cryostack_user"
    ]

    allowed_roles = (
        access.allowed_role_assignments(
            actor_user_id=actor.id,
        )
    )

    if user is None:
        raise web.HTTPNotFound(
            text="User not found."
        )

    return web.Response(
        text=user_detail_page(
            user=user,
            allowed_roles=allowed_roles,
        ),
        content_type="text/html",
    )

async def user_role_update_handler(
    request: web.Request,
) -> web.StreamResponse:

    actor = request.get(
        "cryostack_user"
    )

    if actor is None:
        raise web.HTTPUnauthorized(
            text="Authentication required."
        )

    access = request.app[
        "control_access_service"
    ]

    target_user_id = request.match_info[
        "user_id"
    ]

    form = await request.post()

    new_role = str(
        form.get(
            "control_role",
            "",
        )
    ).strip().lower()

    try:
        access.set_control_role(
            actor_user_id=actor.id,
            target_user_id=target_user_id,
            new_role=new_role,
        )

    except PermissionError as error:
        raise web.HTTPForbidden(
            text=str(error)
        )

    except ValueError as error:
        raise web.HTTPBadRequest(
            text=str(error)
        )

    raise web.HTTPFound(
        f"/control/users/{target_user_id}"
    )