# control_center/routes.py

from __future__ import annotations

import os
from pathlib import Path

from aiohttp import web

from .storage import ControlStorage

from .services import (
    DashboardService,
    UserService,
)

from .api import (
    dashboard_api,
    users_api,
    user_detail_api,
    experiments_api,
)

from .pages import (
    dashboard_page_handler,
    users_page_handler,
    user_detail_page_handler,
    experiment_detail_page_handler,
    experiments_page_handler,
    hpc_page_handler,
    cloud_page_handler,
    authentication_page_handler,
    analytics_page_handler,
    diagnostics_page_handler,
    settings_page_handler,
)

from .services import (
    DashboardService,
    UserService,
    AuthenticationService,
    ExperimentService,
)

from .api import (
    authentication_api,
    experiments_api,
    experiment_detail_api,

)

async def user_role_update_handler(
    request: web.Request,
) -> web.StreamResponse:

    actor = request[
        "cryostack_user"
    ]

    target_user_id = request.match_info[
        "user_id"
    ]

    form = await request.post()

    # print(
    #     "[control][role] form:",
    #     dict(form),
    # )

    new_role = str(
        form.get(
            "control_role",
            "",
        )
    ).strip().lower()

    # print(
    #     "[control][role] parsed:",
    #     repr(new_role),
    # )

    service = request.app[
        "control_access_service"
    ]

    try:
        service.set_control_role(
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


def install_control_center(
    app: web.Application,
    *,
    auth,
    database_path: Path | None = None,
) -> None:

    default_database = (
        Path(__file__)
        .resolve()
        .parent
        .parent
        / "var"
        / "cryostack_auth.db"
    )

    access_service = app[
        "access_service"
    ]

    database = (
        database_path
        or Path(
            os.environ.get(
                "CRYOSTACK_AUTH_DATABASE",
                default_database,
            )
        )
    )

    storage = ControlStorage(
        database
    )

    dashboard_service = (
        DashboardService(
            storage
        )
    )

    user_service = UserService(
        storage,
        access_service,
    )

    authentication_service = (
        AuthenticationService(
            storage
        )
    )

    control_access = auth.require_roles(
        "developer",
        "maintainer",
        "admin",
        "owner",
    )

    experiment_service = (
        ExperimentService(
            storage
        )
    )

    app[
        "control_access_service"
    ] = access_service

    app[
        "control_experiment_service"
    ] = experiment_service
        
    app[
        "control_authentication_service"
    ] = authentication_service

    app["control_storage"] = storage

    app[
        "control_dashboard_service"
    ] = dashboard_service

    app[
        "control_user_service"
    ] = user_service

    # --------------------------------------------------------
    # Control Center pages
    # --------------------------------------------------------

    app.router.add_get(
        "/control/",
        control_access(
            dashboard_page_handler
        ),
    )

    app.router.add_get(
        "/control/users",
        control_access(
            users_page_handler
        ),
    )

    app.router.add_get(
        "/control/users/{user_id}",
        control_access(
            user_detail_page_handler
        ),
    )

    app.router.add_post(
        "/control/users/{user_id}/role",
        control_access(
            user_role_update_handler
        ),
    )

    app.router.add_get(
        "/control/experiments",
        control_access(
            experiments_page_handler
        ),
    )

    app.router.add_get(
        "/control/experiments/{experiment_id}",
        control_access(
            experiment_detail_page_handler
        ),
    )

    app.router.add_get(
        "/control/hpc",
        control_access(
            hpc_page_handler
        ),
    )

    app.router.add_get(
        "/control/cloud",
        control_access(
            cloud_page_handler
        ),
    )

    app.router.add_get(
        "/control/authentication",
        control_access(
            authentication_page_handler
        ),
    )

    app.router.add_get(
        "/control/analytics",
        control_access(
            analytics_page_handler
        ),
    )

    app.router.add_get(
        "/control/diagnostics",
        control_access(
            diagnostics_page_handler
        ),
    )

    app.router.add_get(
        "/control/settings",
        control_access(
            settings_page_handler
        ),
    )

    # --------------------------------------------------------
    # Control Center APIs
    # --------------------------------------------------------

    app.router.add_get(
        "/api/control/dashboard",
        control_access(
            dashboard_api
        ),
    )

    app.router.add_get(
        "/api/control/users",
        control_access(
            users_api
        ),
    )

    app.router.add_get(
        "/api/control/users/{user_id}",
        control_access(
            user_detail_api
        ),
    )

    app.router.add_get(
        "/api/control/experiments",
        control_access(
            experiments_api
        ),
    )

    app.router.add_get(
        "/api/control/experiments/{experiment_id}",
        control_access(
            experiment_detail_api
        ),
    )

    app.router.add_get(
        "/api/control/authentication",
        control_access(
            authentication_api
        ),
    )