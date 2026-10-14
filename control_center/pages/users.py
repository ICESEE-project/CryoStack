from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from aiohttp import web

from ..services.workspaces import WorkspaceInspector
from ..templates import (
    users_page,
    user_detail_page,
)
from ..templates_access import (
    ERROR_MESSAGES,
    NOTICE_MESSAGES,
)


MUTATION_ROLES = {
    "maintainer",
    "admin",
    "owner",
}


def _int(
    value,
    default: int = 1,
) -> int:

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def require_same_origin(
    request: web.Request,
) -> None:
    """Refuse state-changing requests sent from another site.

    Same rule as the Frozen Legacies handlers: a present ``Origin`` header
    must name this host. Session cookies are ``SameSite=Lax`` as well.
    """

    origin = request.headers.get(
        "Origin"
    )

    if (
        origin is not None
        and urlsplit(origin).netloc
        != request.host
    ):
        raise web.HTTPForbidden(
            text=ERROR_MESSAGES[
                "cross_origin"
            ]
        )


def require_mutation_role(
    request: web.Request,
) -> None:
    """Privileged changes need maintainer, admin or owner."""

    roles = set(
        request.get(
            "cryostack_roles"
        )
        or ()
    )

    if not roles & MUTATION_ROLES:
        raise web.HTTPForbidden(
            text=ERROR_MESSAGES[
                "not_permitted"
            ]
        )


def _private(
    response: web.StreamResponse,
) -> web.StreamResponse:

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


async def users_page_handler(
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
    )

    return _private(
        web.Response(
            text=users_page(
                result=result,
            ),
            content_type="text/html",
        )
    )


async def _render_user_detail(
    request: web.Request,
    *,
    user_id: str,
    message: str | None = None,
    error: str | None = None,
    status: int = 200,
) -> web.Response:

    service = request.app[
        "control_user_service"
    ]

    user = service.get_user(
        user_id=user_id,
    )

    if user is None:
        raise web.HTTPNotFound(
            text="User not found."
        )

    access = request.app[
        "control_access_service"
    ]

    actor = request[
        "cryostack_user"
    ]

    inspector = WorkspaceInspector.for_app(
        request.app
    )

    loop = asyncio.get_running_loop()

    workspace = await loop.run_in_executor(
        None,
        inspector.status,
        user_id,
    )

    return _private(
        web.Response(
            text=user_detail_page(
                user=user,
                allowed_roles=(
                    access.allowed_role_assignments(
                        actor_user_id=actor.id,
                        target_user_id=user_id,
                    )
                ),
                can_revoke=(
                    access.can_revoke_sessions(
                        actor_user_id=actor.id,
                        target_user_id=user_id,
                    )
                ),
                is_self=(
                    actor.id == user_id
                ),
                workspace=workspace,
                message=message,
                error=error,
            ),
            content_type="text/html",
            status=status,
        )
    )


async def user_detail_page_handler(
    request: web.Request,
) -> web.Response:

    return await _render_user_detail(
        request,
        user_id=request.match_info[
            "user_id"
        ],
        message=NOTICE_MESSAGES.get(
            request.query.get(
                "notice",
                "",
            )
        ),
    )


def _error_code(
    error: Exception,
) -> str:

    text = str(error).lower()

    if "owner" in text:
        return "last_owner"

    if "reason" in text:
        return "reason_required"

    if "invalid" in text:
        return "invalid_role"

    return "not_permitted"


async def user_role_update_handler(
    request: web.Request,
) -> web.StreamResponse:

    require_same_origin(request)

    actor = request.get(
        "cryostack_user"
    )

    if actor is None:
        raise web.HTTPUnauthorized(
            text="Authentication required."
        )

    require_mutation_role(request)

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
            reason=str(
                form.get(
                    "reason",
                    "",
                )
            ),
        )

    except LookupError:
        raise web.HTTPNotFound(
            text="User not found."
        )

    except PermissionError as error:
        return await _render_user_detail(
            request,
            user_id=target_user_id,
            error=ERROR_MESSAGES[
                _error_code(error)
            ],
            status=403,
        )

    except ValueError as error:
        return await _render_user_detail(
            request,
            user_id=target_user_id,
            error=ERROR_MESSAGES[
                _error_code(error)
            ],
            status=400,
        )

    raise web.HTTPSeeOther(
        f"/control/users/{target_user_id}"
        "?notice=role_updated"
    )


async def user_sessions_revoke_handler(
    request: web.Request,
) -> web.StreamResponse:

    require_same_origin(request)

    actor = request.get(
        "cryostack_user"
    )

    if actor is None:
        raise web.HTTPUnauthorized(
            text="Authentication required."
        )

    require_mutation_role(request)

    access = request.app[
        "control_access_service"
    ]

    target_user_id = request.match_info[
        "user_id"
    ]

    form = await request.post()

    try:
        access.revoke_sessions(
            actor_user_id=actor.id,
            target_user_id=target_user_id,
            reason=str(
                form.get(
                    "reason",
                    "",
                )
            ),
        )

    except LookupError:
        raise web.HTTPNotFound(
            text="User not found."
        )

    except PermissionError:
        return await _render_user_detail(
            request,
            user_id=target_user_id,
            error=ERROR_MESSAGES[
                "not_permitted"
            ],
            status=403,
        )

    except ValueError as error:
        return await _render_user_detail(
            request,
            user_id=target_user_id,
            error=ERROR_MESSAGES[
                _error_code(error)
            ],
            status=400,
        )

    if target_user_id == actor.id:
        # The actor's own session was just removed.
        raise web.HTTPSeeOther(
            "/auth/login?return_to=/control/users"
        )

    raise web.HTTPSeeOther(
        f"/control/users/{target_user_id}"
        "?notice=sessions_revoked"
    )
