# control_center/operations.py

"""Wire the Control Center operations pages: Analytics, Diagnostics,
Settings.

:func:`install_operations` is called once by
:func:`control_center.install_control_center` while the gateway application
is assembled. It

* opens the operations store (:mod:`control_center.ops_store`);
* applies stored settings to the gateway environment -- before the Voila
  services and Frozen Legacies workers are started, so they inherit them;
* installs the aggregate application-usage counter middleware;
* registers the settings change handler (maintainer|admin|owner) and the
  JSON APIs. The page routes ``/control/analytics``, ``/control/diagnostics``
  and ``/control/settings`` are registered by the Control Center itself.
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .ops_store import OpsStore, default_ops_database
from .pages import ops as pages
from .services.analytics import AnalyticsService, UsageCounter
from .services.diagnostics import DiagnosticsService
from .services.settings import SettingsService
from .storage import ControlStorage


def install_operations(
    app: web.Application,
    *,
    auth,
    storage: ControlStorage,
    control_access,
    ops_database: Path | None = None,
) -> None:
    store = OpsStore(ops_database or default_ops_database(storage.database_path))

    settings = SettingsService(store)
    settings.apply_at_startup()

    counter = UsageCounter(store)
    app.middlewares.append(counter.middleware())

    async def _flush(_app) -> None:
        counter.flush()

    app.on_cleanup.append(_flush)

    app[pages.AUTH_KEY] = auth
    app[pages.SETTINGS_KEY] = settings
    app[pages.ANALYTICS_KEY] = AnalyticsService(
        auth_database=storage.database_path, store=store, counter=counter)
    app[pages.DIAGNOSTICS_KEY] = DiagnosticsService(storage, ops_database=store.path)
    app["control_ops_store"] = store

    app.router.add_post("/control/settings", control_access(pages.settings_update_handler))
    app.router.add_get("/api/control/analytics", control_access(pages.analytics_api))
    app.router.add_get("/api/control/diagnostics", control_access(pages.diagnostics_api))
    app.router.add_get("/api/control/settings", control_access(pages.settings_api))
