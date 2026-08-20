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

    return _page(
        title="HPC",
        active="hpc",
        description=(
            "Clusters, Slurm jobs, queues, "
            "connectors and HPC diagnostics."
        ),
    )


async def cloud_page_handler(
    request: web.Request,
) -> web.Response:

    return _page(
        title="Cloud",
        active="cloud",
        description=(
            "AWS Batch jobs, queues, S3 outputs, "
            "compute resources and cloud usage."
        ),
    )


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

    return _page(
        title="Analytics",
        active="analytics",
        description=(
            "Platform usage, experiment throughput, "
            "backend activity and trends."
        ),
    )


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

    return _page(
        title="Settings",
        active="settings",
        description=(
            "Control Center and platform-wide "
            "configuration."
        ),
    )