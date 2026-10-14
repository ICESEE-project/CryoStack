from __future__ import annotations

from aiohttp import web

from ..templates_compute import (
    cloud_page,
    hpc_page,
)


def _service(
    request: web.Request,
):

    return request.app[
        "control_compute_service"
    ]


def _can_operate(
    request: web.Request,
) -> bool:

    user = request.get("cryostack_user")

    if user is None:
        return False

    return _service(request).can_operate(
        user_id=user.id,
    )


def _log_excerpt(
    request: web.Request,
    *,
    page: str,
) -> dict | None:
    """
    The log excerpt selected through the page's query string, or ``None``
    when no (or an unknown) log was selected.
    """

    service = _service(request)

    source = request.query.get("log", "")

    if not source:
        return None

    try:
        return service.log_excerpt(
            source=source,
            topic=request.query.get("topic", page),
            level=request.query.get("level", "all"),
        )
    except (KeyError, ValueError):
        return None


async def hpc_page_handler(
    request: web.Request,
) -> web.Response:

    service = _service(request)

    return web.Response(
        text=hpc_page(
            data=service.hpc_overview(),
            can_operate=_can_operate(request),
            log_sources=service.log_sources(),
            log_excerpt=_log_excerpt(request, page="hpc"),
        ),
        content_type="text/html",
    )


async def cloud_page_handler(
    request: web.Request,
) -> web.Response:

    service = _service(request)

    return web.Response(
        text=cloud_page(
            data=service.cloud_overview(),
            can_operate=_can_operate(request),
            log_sources=service.log_sources(),
            log_excerpt=_log_excerpt(request, page="cloud"),
        ),
        content_type="text/html",
    )
