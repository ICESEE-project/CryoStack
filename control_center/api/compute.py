"""
Control Center compute JSON API and route installation.

    GET  /api/control/hpc                 resources, checks, executions
    GET  /api/control/cloud               cloud configuration, executions
    GET  /api/control/compute/logs        one redacted, bounded log excerpt
    POST /api/control/hpc/relay-check     live Connector relay probe
                                          (maintainer | admin | owner, audited)

Reads are open to every Control Center role; the POST additionally needs an
operator role, a same-origin JSON request, and is written to the control
audit log.
"""

from __future__ import annotations

import asyncio
import functools
from urllib.parse import urlsplit

from aiohttp import web

from ..services.compute import ComputeService
from ..storage import ControlStorage


def _error(
    status: int,
    message: str,
) -> web.Response:

    return web.json_response(
        {"error": message},
        status=status,
    )


async def _blocking(
    func,
    *args,
    **kwargs,
):

    loop = asyncio.get_running_loop()

    return await loop.run_in_executor(
        None,
        functools.partial(func, *args, **kwargs),
    )


def _service(
    request: web.Request,
) -> ComputeService:

    return request.app[
        "control_compute_service"
    ]


async def hpc_api(
    request: web.Request,
) -> web.Response:

    data = await _blocking(
        _service(request).hpc_overview
    )

    return web.json_response(data)


async def cloud_api(
    request: web.Request,
) -> web.Response:

    data = await _blocking(
        _service(request).cloud_overview
    )

    return web.json_response(data)


async def compute_logs_api(
    request: web.Request,
) -> web.Response:

    service = _service(request)

    source = request.query.get("source", "")

    if not source:
        return web.json_response(
            {"sources": service.log_sources()}
        )

    try:
        lines = int(request.query.get("lines", "80"))
    except ValueError:
        return _error(400, "lines must be an integer.")

    try:
        excerpt = await _blocking(
            service.log_excerpt,
            source=source,
            topic=request.query.get("topic", "all"),
            level=request.query.get("level", "all"),
            lines=lines,
        )
    except KeyError:
        return _error(404, "Unknown log source.")
    except ValueError as error:
        return _error(400, str(error))

    return web.json_response(excerpt)


def _same_origin_json(
    request: web.Request,
) -> web.Response | None:
    """
    Refuse cross-site state-changing requests: a foreign ``Origin`` is
    rejected and the body must be JSON, which a plain HTML form cannot send.
    """

    origin = request.headers.get("Origin")

    if origin is not None and urlsplit(origin).netloc != request.host:
        return _error(403, "Cross-origin request refused.")

    if request.content_type != "application/json":
        return _error(415, "A JSON request body is required.")

    return None


async def relay_check_api(
    request: web.Request,
) -> web.Response:

    refused = _same_origin_json(request)

    if refused is not None:
        return refused

    actor = request.get("cryostack_user")

    if actor is None:
        return _error(401, "Authentication required.")

    service = _service(request)

    try:
        result = await _blocking(
            service.run_relay_check,
            actor_user_id=actor.id,
        )
    except PermissionError as error:
        return _error(403, str(error))

    return web.json_response(result)


def install_compute_routes(
    app: web.Application,
    *,
    auth,
    storage: ControlStorage,
    service: ComputeService | None = None,
) -> ComputeService:
    """
    Create the compute service and register the compute JSON API. The
    /control/hpc and /control/cloud pages stay registered by
    install_control_center; their handlers read ``control_compute_service``.
    """

    service = service or ComputeService(
        storage,
        access=app.get("access_service"),
    )

    app["control_compute_service"] = service

    control_access = auth.require_roles(
        "developer",
        "maintainer",
        "admin",
        "owner",
    )

    app.router.add_get(
        "/api/control/hpc",
        control_access(hpc_api),
    )

    app.router.add_get(
        "/api/control/cloud",
        control_access(cloud_api),
    )

    app.router.add_get(
        "/api/control/compute/logs",
        control_access(compute_logs_api),
    )

    # Control Center access first; the handler then requires an operator role.
    app.router.add_post(
        "/api/control/hpc/relay-check",
        control_access(relay_check_api),
    )

    return service
