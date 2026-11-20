"""Control Center registration review: ``/control/registrations``.

Viewing needs a Control Center role or an explicit owner-granted registration
review permission. Delegates approve/reject pending ordinary accounts only;
owner management and operational retries retain their separate role checks.
Mutations use same-origin POSTs. Reviewer emails open this page (a GET that changes
nothing) behind the usual sign-in.
"""

from __future__ import annotations

from urllib.parse import quote

from aiohttp import web

from icesee_auth.approval import DecisionError

from ..services.registrations import RegistrationService
from ..templates import control_layout
from ..templates_registrations import registrations_content
from .users import _private, require_same_origin

NOTICES = {
    "approve": "Account approved. A notification is queued and their workspace is being prepared.",
    "reject": "Registration rejected. A notification is queued.",
    "suspend": "Account suspended. Its sessions and live connections were ended.",
    "reinstate": "Account reinstated. A notification is queued.",
    "provisioning": "Workspace provisioning queued again.",
    "email": "Email queued again.",
    "approver_added": "Registration approver added. They can review new registrations from their email notices.",
    "approver_removed": "Registration approver removed.",
}
MAX_FORM_BYTES = 8 * 1024


def _service(request: web.Request) -> RegistrationService:
    return RegistrationService(request.app["control_auth"], request.app["control_access_service"])


async def _render(request: web.Request, *, message: str | None = None,
                  error: str | None = None, status: int = 200) -> web.Response:
    actor = request["cryostack_user"]
    overview = _service(request).overview(
        actor_user_id=actor.id, focus_user_id=request.query.get("user") or None)
    return _private(web.Response(
        text=control_layout(
            title="Registrations",
            active="registrations",
            content=registrations_content(overview=overview, message=message, error=error),
            registration_only=overview["registration_only"],
        ),
        content_type="text/html",
        status=status,
    ))


async def registrations_page(request: web.Request) -> web.Response:
    return await _render(request, message=NOTICES.get(request.query.get("notice", "")))


async def registrations_api(request: web.Request) -> web.Response:
    actor = request["cryostack_user"]
    return _private(web.json_response(_service(request).overview(actor_user_id=actor.id)))


async def _form(request: web.Request):
    require_same_origin(request)
    if (request.content_length or 0) > MAX_FORM_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_FORM_BYTES,
                                            actual_size=request.content_length)
    return await request.post()


async def decision_handler(request: web.Request) -> web.StreamResponse:
    form = await _form(request)
    actor = request["cryostack_user"]
    user_id = request.match_info["user_id"]
    decision = str(form.get("decision", "")).strip().lower()
    try:
        _service(request).decide(actor_user_id=actor.id, target_user_id=user_id,
                                 decision=decision, reason=str(form.get("reason", "")))
    except LookupError:
        raise web.HTTPNotFound(text="User not found.")
    except PermissionError as error:
        return await _render(request, error=str(error), status=403)
    except (DecisionError, ValueError) as error:
        return await _render(request, error=str(error), status=400)
    raise web.HTTPSeeOther(
        f"/control/registrations?notice={quote(decision)}&user={quote(user_id)}")


async def provisioning_retry_handler(request: web.Request) -> web.StreamResponse:
    await _form(request)
    actor = request["cryostack_user"]
    user_id = request.match_info["user_id"]
    try:
        _service(request).retry_provisioning(actor_user_id=actor.id, target_user_id=user_id)
    except PermissionError as error:
        return await _render(request, error=str(error), status=403)
    except DecisionError as error:
        return await _render(request, error=str(error), status=400)
    raise web.HTTPSeeOther("/control/registrations?notice=provisioning")


async def notification_retry_handler(request: web.Request) -> web.StreamResponse:
    await _form(request)
    actor = request["cryostack_user"]
    try:
        _service(request).retry_notification(actor_user_id=actor.id,
                                             row_id=request.match_info["row_id"])
    except PermissionError as error:
        return await _render(request, error=str(error), status=403)
    raise web.HTTPSeeOther("/control/registrations?notice=email")


async def approver_add_handler(request: web.Request) -> web.StreamResponse:
    form = await _form(request)
    actor = request["cryostack_user"]
    service = _service(request)
    try:
        changed = service.approvers.grant(
            actor_user_id=actor.id, email=str(form.get("email", "")),
            reason=str(form.get("reason", "")))
        if changed:
            service.notify_waiting_reviewers()
    except PermissionError as error:
        return await _render(request, error=str(error), status=403)
    except (LookupError, ValueError) as error:
        return await _render(request, error=str(error), status=400)
    raise web.HTTPSeeOther("/control/registrations?notice=approver_added")


async def approver_remove_handler(request: web.Request) -> web.StreamResponse:
    form = await _form(request)
    actor = request["cryostack_user"]
    try:
        _service(request).approvers.revoke(
            actor_user_id=actor.id, target_user_id=request.match_info["user_id"],
            reason=str(form.get("reason", "")))
    except PermissionError as error:
        return await _render(request, error=str(error), status=403)
    except ValueError as error:
        return await _render(request, error=str(error), status=400)
    raise web.HTTPSeeOther("/control/registrations?notice=approver_removed")


def install_registrations(app: web.Application, *, control_access) -> None:
    # Delegates receive access to these registration handlers alone. The
    # normal role gates on every other Control Center route stay unchanged.
    def registration_access(handler):
        async def checked(request):
            actor = request["cryostack_user"]
            if not _service(request).can_view(actor_user_id=actor.id):
                raise web.HTTPForbidden(text="You do not have permission to review registrations.")
            return await handler(request)
        return app["control_auth"].require_login(checked)

    app.router.add_get("/control/registrations", registration_access(registrations_page))
    app.router.add_get("/api/control/registrations", registration_access(registrations_api))
    app.router.add_post("/control/registrations/{user_id}/decision",
                        registration_access(decision_handler))
    app.router.add_post("/control/registrations/{user_id}/provisioning",
                        registration_access(provisioning_retry_handler))
    app.router.add_post("/control/registrations/notifications/{row_id}/retry",
                        registration_access(notification_retry_handler))
    app.router.add_post("/control/registrations/approvers/add",
                        registration_access(approver_add_handler))
    app.router.add_post("/control/registrations/approvers/{user_id}/remove",
                        registration_access(approver_remove_handler))
