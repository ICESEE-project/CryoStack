"""Control Center audit log: browse and export ``access_audit_log``.

Every Control Center role may browse (developers already see the same rows
in the audit panel of ``/control/access``). Export is a bulk copy, so it is
limited to maintainer, admin and owner, is a same-origin POST, is bounded
by ``EXPORT_MAX_ROWS`` and is itself appended to the audit trail.
"""

from __future__ import annotations

import time

from aiohttp import web

from ..services.audit import (
    EXPORT_FORMATS,
    EXPORT_MAX_ROWS,
    AuditLogService,
    parse_filters,
)
from ..templates import control_layout
from ..templates_audit import audit_log_content
from .users import (
    MUTATION_ROLES,
    _int,
    _private,
    require_mutation_role,
    require_same_origin,
)

MAX_FORM_BYTES = 8 * 1024


def _service(request: web.Request) -> AuditLogService:
    return AuditLogService(request.app["control_storage"])


def _can_export(request: web.Request) -> bool:
    return bool(set(request.get("cryostack_roles") or ()) & MUTATION_ROLES)


def _public_row(row: dict) -> dict:
    return AuditLogService.export_record(row) | {"created_at": row["created_at"]}


async def audit_page_handler(request: web.Request) -> web.Response:
    service = _service(request)
    filters = parse_filters(request.query)
    result = service.page(filters, page=_int(request.query.get("page")))
    return _private(web.Response(
        text=control_layout(
            title="Audit Log",
            active="audit",
            content=audit_log_content(
                result=result,
                filters=filters,
                actions=service.actions(),
                can_export=_can_export(request),
            ),
        ),
        content_type="text/html",
    ))


async def audit_api(request: web.Request) -> web.Response:
    filters = parse_filters(request.query)
    result = _service(request).page(
        filters,
        page=_int(request.query.get("page")),
        per_page=_int(request.query.get("per_page"), 50),
    )
    return _private(web.json_response({
        "filters": filters,
        **result,
        "rows": [_public_row(row) for row in result["rows"]],
        "can_export": _can_export(request),
        "export_max_rows": EXPORT_MAX_ROWS,
    }))


async def audit_export_handler(request: web.Request) -> web.StreamResponse:
    require_same_origin(request)
    actor = request.get("cryostack_user")
    if actor is None:
        raise web.HTTPUnauthorized(text="Authentication required.")
    require_mutation_role(request)

    if (request.content_length or 0) > MAX_FORM_BYTES:
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_FORM_BYTES, actual_size=request.content_length)
    form = await request.post()
    export_format = str(form.get("format") or "csv").strip().lower()
    if export_format not in EXPORT_FORMATS:
        raise web.HTTPBadRequest(text="Unsupported export format.")
    filters = parse_filters(form)

    service = _service(request)
    rows, total = service.export_rows(filters)
    truncated = total > len(rows)
    if export_format == "csv":
        body = service.to_csv(rows)
        content_type = "text/csv"
    else:
        body = service.to_json(rows, filters=filters, total=total)
        content_type = "application/json"

    service.record_export(actor=actor, export_format=export_format, filters=filters,
                          rows=len(rows), truncated=truncated)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    response = web.Response(text=body, content_type=content_type, charset="utf-8")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="cryostack-audit-{stamp}.{export_format}"')
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-CryoStack-Export-Rows"] = str(len(rows))
    response.headers["X-CryoStack-Export-Truncated"] = "true" if truncated else "false"
    return _private(response)


def install_audit(app: web.Application, *, control_access) -> None:
    """Register the audit-log routes behind ``control_access``."""
    app.router.add_get("/control/audit", control_access(audit_page_handler))
    app.router.add_post("/control/audit/export", control_access(audit_export_handler))
    app.router.add_get("/api/control/audit", control_access(audit_api))
