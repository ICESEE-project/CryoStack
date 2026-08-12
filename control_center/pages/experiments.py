# control_center/pages/experiments.py

from __future__ import annotations

from aiohttp import web

from ..templates import experiments_page


async def experiments_page_handler(
    request: web.Request,
) -> web.Response:

    storage = request.app[
        "control_storage"
    ]

    return web.Response(
        text=experiments_page(
            experiments=(
                storage.list_experiments()
            )
        ),
        content_type="text/html",
    )