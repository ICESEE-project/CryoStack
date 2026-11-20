"""Loopback-only gateway routes a Voila kernel uses for hosted-pilot runs.

Same trust model as ``kernel_workspace_state`` in ``bin/icesee_app.py``:
loopback caller, never through nginx (which adds X-Forwarded-For /
X-Real-IP), and a per-user HMAC grant that only the proxy can mint. The grant
has its own purpose string, so a workspace grant cannot be replayed here. The
user id proven by the grant is the ONLY identity passed to the service.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys

from aiohttp import web

from icesee_auth.kernel_access import KERNEL_PILOT_PATH, PILOT_GRANT_HEADER, pilot_grant_matches

from .service import HostedRunError, SubmissionUncertainError

LOG = logging.getLogger("cryostack.pilot")
_LOOPBACK = {"127.0.0.1", "::1"}
MAX_BODY_BYTES = 16 * 1024
MAX_LICENSE_BODY_BYTES = 4 * 1024
RECONCILE_SECONDS = 180.0
_NO_STORE = {"Cache-Control": "no-store"}
_ARN_RE = re.compile(r"arn:aws[a-z-]*:[^\s'\"]+")
_PATH_RE = re.compile(r"(?<![A-Za-z0-9:])/(?:[^\s'\"/]+/)+[^\s'\"]*")


def safe_message(error: BaseException, default: str) -> str:
    """An error's text with any ARN or filesystem path removed."""
    text = " ".join(str(error).split())[:300]
    text = _PATH_RE.sub("[path]", _ARN_RE.sub("[resource]", text))
    return text or default


def _json(payload, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, headers=_NO_STORE)


def _authorize(request: web.Request, grant_key_provider, auth) -> str:
    if request.remote not in _LOOPBACK or "X-Forwarded-For" in request.headers \
            or "X-Real-IP" in request.headers:
        raise web.HTTPNotFound()
    user_id = (request.headers.get("X-CryoStack-User-Id") or "").strip()
    if not pilot_grant_matches(user_id, request.headers.get(PILOT_GRANT_HEADER),
                               grant_key_provider()):
        raise web.HTTPForbidden(text="invalid pilot grant")
    # a kernel outlives its browser tab; an account suspended since keeps nothing
    if not auth.user_is_active(user_id):
        raise web.HTTPForbidden(text="account not approved")
    return user_id


async def _body(request: web.Request, limit: int) -> dict:
    length = request.content_length
    if length is not None and length > limit:
        raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=length)
    data = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        data += chunk
        if len(data) > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(data))
    try:
        payload = json.loads(bytes(data).decode("utf-8")) if data else {}
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="invalid JSON body") from None
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="invalid JSON body")
    return payload


def _field(payload: dict, name: str, *, limit: int = 4096) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"Field {name!r} is required.")
    return value


async def _call(function, *args, **kwargs) -> web.Response:
    try:
        result = await asyncio.to_thread(function, *args, **kwargs)
    except PermissionError as error:
        return _json({"error": safe_message(error, "Not permitted.")}, 403)
    except ValueError as error:
        return _json({"error": safe_message(error, "Invalid request.")}, 400)
    except SubmissionUncertainError as error:
        return _json({"error": safe_message(error, "The run may have started."), "uncertain": True}, 409)
    except HostedRunError as error:
        return _json({"error": safe_message(error, "The hosted run service failed.")}, 502)
    except Exception as error:  # noqa: BLE001 - never echo an unknown failure
        LOG.error("pilot route failed (%s)", type(error).__name__)
        return _json({"error": "The hosted run service failed."}, 500)
    return _json(result if isinstance(result, dict) else {"text": result})


def install_pilot_routes(app: web.Application, *, service, grant_key_provider, auth) -> None:
    """Register the kernel-facing routes for an enabled hosted pilot."""
    base = KERNEL_PILOT_PATH

    def who(request):
        return _authorize(request, grant_key_provider, auth)

    async def summary(request):
        user_id = who(request)
        return await _call(service.summary, user_id)

    async def submit(request):
        user_id = who(request)
        payload = await _body(request, MAX_BODY_BYTES)
        try:
            seconds = payload.get("seconds")
            if seconds is not None and type(seconds) is not int:
                raise ValueError("Field 'seconds' must be a whole number.")
            arguments = dict(
                staged_source=_field(payload, "staged_source"), model=_field(payload, "model", limit=32),
                run_target=_field(payload, "run_target", limit=512),
                request_key=_field(payload, "request_key", limit=200), seconds=seconds)
        except ValueError as error:
            return _json({"error": str(error)}, 400)
        return await _call(service.submit, user_id, **arguments)

    def job_route(method, **extra_fields):
        async def handler(request):
            user_id = who(request)
            payload = await _body(request, MAX_BODY_BYTES)
            try:
                reservation = _field(payload, "reservation_id", limit=64)
                extra = {name: _field(payload, name) for name in extra_fields}
            except ValueError as error:
                return _json({"error": str(error)}, 400)
            return await _call(getattr(service, method), user_id, reservation, **extra)
        return handler

    async def license_set(request):
        user_id = who(request)
        payload = await _body(request, MAX_LICENSE_BODY_BYTES)
        value = payload.get("value")
        if not isinstance(value, str) or not value.strip():
            return _json({"error": "A license value is required."}, 400)
        response = await _call(service.set_matlab_license, user_id, value=value)
        if response.status != 200:
            if value.strip() in (response.text or ""):     # never reflect the value
                return _json({"error": "The MATLAB license could not be stored."}, response.status)
            return response
        return _json({"configured": True})

    async def license_clear(request):
        user_id = who(request)
        await _body(request, MAX_LICENSE_BODY_BYTES)
        return await _call(service.clear_matlab_license, user_id)

    app.router.add_get(f"{base}/summary", summary)
    app.router.add_post(f"{base}/submit", submit)
    app.router.add_post(f"{base}/status", job_route("status"))
    app.router.add_post(f"{base}/logs", job_route("logs"))
    app.router.add_post(f"{base}/terminate", job_route("terminate"))
    app.router.add_post(f"{base}/results", job_route("sync_results", destination=True))
    app.router.add_post(f"{base}/license", license_set)
    app.router.add_post(f"{base}/license/clear", license_clear)


def install_pilot_off(app: web.Application, *, grant_key_provider, auth) -> None:
    """Feature off: one summary route saying so, and nothing else."""
    async def summary(request):
        _authorize(request, grant_key_provider, auth)
        return _json({"enabled": False})

    app.router.add_get(f"{KERNEL_PILOT_PATH}/summary", summary)


def _schedule_reconcile(app: web.Application, service, interval: float) -> None:
    async def loop():
        while True:
            try:
                await asyncio.to_thread(service.reconcile)
            except Exception as error:  # noqa: BLE001
                LOG.error("pilot reconcile failed (%s)", type(error).__name__)
            await asyncio.sleep(interval)

    async def start(_app):
        _app["cryostack_pilot_reconcile"] = asyncio.get_running_loop().create_task(loop())

    async def stop(_app):
        task = _app.get("cryostack_pilot_reconcile")
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.on_startup.append(start)
    app.on_cleanup.append(stop)


def install_pilot(app: web.Application, *, auth, grant_key_provider, config_loader=None,
                  service_factory=None, storage=None,
                  reconcile_seconds: float = RECONCILE_SECONDS):
    """Everything ``make_app`` needs: the hosted pilot when it is configured
    and enabled, otherwise only the "off" summary. A bad configuration (or a
    reviewed binding that does not line up) logs ONE line and leaves the
    gateway starting normally with the feature off -- bring-your-own is
    untouched either way. Returns the service, or ``None`` when off.

    When on, two route sets are installed: the loopback kernel routes, and
    the worker transfer routes (``/api/pilot-transfer/...``) that the job's
    supervisor reaches through the reviewed ``transfer_origin``; those accept
    only a reservation's single-use capability.
    """
    service = None
    try:
        if config_loader is None:
            from .config import load_pilot_config as config_loader
        config = config_loader()
        if config is not None and config.enabled:
            if service_factory is None:
                from .service import HostedPilot
                service = HostedPilot(config, storage if storage is not None else auth.storage)
            else:
                service = service_factory(config)
    except Exception as error:  # noqa: BLE001 - optional feature, never fatal
        service = None
        print(f"[pilot] hosted pilot is OFF: configuration problem "
              f"({type(error).__name__}: {safe_message(error, 'invalid')})",
              file=sys.stderr, flush=True)
    if service is None:
        install_pilot_off(app, grant_key_provider=grant_key_provider, auth=auth)
        return None
    from cryostack_src.cloud.pilot_transfer import install_pilot_transfers

    runtime = service.runtime
    install_pilot_transfers(app, leases=runtime.transfer_leases, read_input=runtime.read_input,
                            admit_output=runtime.stage_output, enabled=True,
                            license_runtime=service.license_runtime, release_license=service.release_license)
    install_pilot_routes(app, service=service, grant_key_provider=grant_key_provider, auth=auth)
    _schedule_reconcile(app, service, reconcile_seconds)
    app["cryostack_pilot_service"] = service
    return service


__all__ = ["install_pilot", "install_pilot_off", "install_pilot_routes", "safe_message"]
