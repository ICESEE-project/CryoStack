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
    experiments_api,
)

from .pages import (
    dashboard_page_handler,
    users_page_handler,
    experiments_page_handler,
)


def install_control_center(
    app: web.Application,
    *,
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