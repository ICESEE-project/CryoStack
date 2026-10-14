from __future__ import annotations

from aiohttp import web


def _int(
    value,
    default: int = 1,
) -> int:

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def users_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_user_service"
    ]

    result = service.search_users(
        query=request.query.get(
            "q",
            "",
        ),
        role=request.query.get(
            "role",
            "",
        ),
        page=_int(
            request.query.get("page")
        ),
        per_page=_int(
            request.query.get("per_page"),
            50,
        ),
    )

    response = web.json_response(
        result
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


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

    response = web.json_response(
        {
            "user": user
        }
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response
