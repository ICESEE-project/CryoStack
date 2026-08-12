# control_center/pages/__init__.py

from .dashboard import dashboard_page_handler

from .users import (
    users_page_handler,
    user_detail_page_handler,
)

from .platform import (
    hpc_page_handler,
    cloud_page_handler,
    authentication_page_handler,
    analytics_page_handler,
    diagnostics_page_handler,
    settings_page_handler,
)

from .experiments import experiments_page_handler

__all__ = [
    "dashboard_page_handler",
    "users_page_handler",
    "experiments_page_handler",
    "user_detail_page_handler",
    "hpc_page_handler",
    "cloud_page_handler",
    "authentication_page_handler",
    "analytics_page_handler",
    "diagnostics_page_handler",
    "settings_page_handler",
]