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

    user_service = (
        UserService(
            storage
        )
    )

    authentication_service = (
        AuthenticationService(
            storage
        )
    )

    control_access = auth.require_roles(
        "developer",
        "administrator",
        "owner",
    )

    experiment_service = (
        ExperimentService(
            storage
        )
    )

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
    # HTML pages
    # --------------------------------------------------------

    app.router.add_get(
        "/control/",
        dashboard_page_handler,
    )

    app.router.add_get(
        "/control/users",
        users_page_handler,
    )

    app.router.add_get(
        "/control/experiments",
        experiments_page_handler,
    )

    # --------------------------------------------------------
    # JSON APIs
    # --------------------------------------------------------

    app.router.add_get(
        "/api/control/dashboard",
        dashboard_api,
    )

    app.router.add_get(
        "/api/control/users",
        users_api,
    )

    app.router.add_get(
        "/api/control/experiments",
        experiments_api,
    )

    app.router.add_get(
        "/control/users/{user_id}",
        user_detail_page_handler,
    )

    app.router.add_get(
        "/api/control/users/{user_id}",
        user_detail_api,
    )

    app.router.add_get(
        "/control/hpc",
        hpc_page_handler,
    )

    app.router.add_get(
        "/control/cloud",
        cloud_page_handler,
    )

    app.router.add_get(
        "/control/authentication",
        authentication_page_handler,
    )

    app.router.add_get(
        "/control/analytics",
        analytics_page_handler,
    )

    app.router.add_get(
        "/control/diagnostics",
        diagnostics_page_handler,
    )

    app.router.add_get(
        "/control/settings",
        settings_page_handler,
    )

    app.router.add_get(
        "/api/control/authentication",
        authentication_api,
    )

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

    app.router.add_get(
        "/control/experiments",
        control_access(
            experiments_page_handler
        ),
    )

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
        "/api/control/experiments/{experiment_id}",
        control_access(
            experiment_detail_api
        ),
    )

    