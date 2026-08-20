from __future__ import annotations

from aiohttp import web


async def experiments_api(
    request: web.Request,
) -> web.Response:

    service = request.app[
        "control_experiment_service"
    ]

    return web.json_response(
        {
            "experiments":
                service.list_experiments()
        }
    )


async def experiment_detail_api(
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

    return web.json_response(
        {
            "experiment": experiment
        }
    )