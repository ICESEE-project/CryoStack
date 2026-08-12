# control_center/api/experiments.py

from __future__ import annotations

from aiohttp import web


async def experiments_api(
    request: web.Request,
) -> web.Response:

    storage = request.app[
        "control_storage"
    ]

    experiments = (
        storage.list_experiments()
    )

    return web.json_response(
        {
            "experiments": experiments
        }
    )