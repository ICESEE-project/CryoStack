from __future__ import annotations

from aiohttp import web

from ..templates import (
    experiments_page,
    experiment_detail_page,
)


async def experiments_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_experiment_service"
    ]

    return web.Response(
        text=experiments_page(
            experiments=(
                service.list_experiments()
            )
        ),
        content_type="text/html",
    )


async def experiment_detail_page_handler(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_experiment_service"
    ]

    experiment = service.get_experiment(
        experiment_id=request.match_info[
            "experiment_id"
        ]
    )

    if experiment is None:
        raise web.HTTPNotFound(
            text="Experiment not found."
        )

    return web.Response(
        text=experiment_detail_page(
            experiment=experiment
        ),
        content_type="text/html",
    )