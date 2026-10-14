from __future__ import annotations

from aiohttp import web

from ..templates import (
    placeholder_page,
)


def _page(
    *,
    title: str,
    active: str,
    description: str,
) -> web.Response:

    return web.Response(
        text=placeholder_page(
            title=title,
            active=active,
            description=description,
        ),
        content_type="text/html",
    )


async def hpc_page_handler(
    request: web.Request,
) -> web.Response:

    from .compute import hpc_page_handler as handler

    return await handler(request)


async def cloud_page_handler(
    request: web.Request,
) -> web.Response:

    from .compute import cloud_page_handler as handler

    return await handler(request)


async def authentication_page_handler(
    request: web.Request,
) -> web.Response:

    return _page(
        title="Authentication",
        active="authentication",
        description=(
            "Identity providers, linked accounts, "
            "sessions and authentication health."
        ),
    )


async def analytics_page_handler(
    request: web.Request,
) -> web.Response:

    from .ops import analytics_page_handler as handler

    return await handler(request)


async def diagnostics_page_handler(
    request: web.Request,
) -> web.Response:

    return _page(
        title="Diagnostics",
        active="diagnostics",
        description=(
            "Database, Voilà, connectors, OAuth, "
            "filesystem and service health."
        ),
    )


async def settings_page_handler(
    request: web.Request,
) -> web.Response:

    from .ops import settings_page_handler as handler

    return await handler(request)
