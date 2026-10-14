"""Control Center access administration: events, audit trail, workspaces.

``install_access_admin`` registers the routes behind the same Control Center
role gate as every other ``/control`` page.
"""

from __future__ import annotations

import asyncio
import time

from aiohttp import web

from icesee_auth.access_log import EVENT_TYPES, retention_days

from ..services.workspaces import LIST_ENTRY_LIMIT, WorkspaceInspector
from ..templates import control_layout
from ..templates_access import access_events_content, workspaces_content
from .users import _int, _private, user_sessions_revoke_handler

PAGE_SIZE = 50
WORKSPACE_PAGE_SIZE = 25


def _event_filters(request: web.Request) -> dict:
    event_type = request.query.get("type", "")
    outcome = request.query.get("outcome", "")
    days = _int(request.query.get("days"), 7)
    return {
        "type": event_type if event_type in EVENT_TYPES else "",
        "outcome": outcome if outcome in ("success", "failure", "denied") else "",
        "user": request.query.get("user", "").strip()[:200],
        "days": min(max(days, 1), retention_days()),
    }


def _resolve_user(storage, value: str) -> str:
    """An account id, or the id behind an exact email; never a pattern."""
    if not value:
        return ""
    if "@" in value:
        with storage._connect() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE email = ? COLLATE NOCASE",
                (value,),
            ).fetchone()
        return row["id"] if row is not None else "-"
    return value


def _paged(rows_total: tuple[list, int], page: int, per_page: int) -> dict:
    rows, total = rows_total
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": max((total + per_page - 1) // per_page, 1),
    }


def _query_events(request: web.Request) -> tuple[dict, dict, dict]:
    storage = request.app["control_storage"]
    filters = _event_filters(request)
    page = max(_int(request.query.get("page")), 1)
    audit_page = max(_int(request.query.get("audit_page")), 1)
    user_id = _resolve_user(storage, filters["user"])

    events = _paged(
        storage.list_access_events(
            event_type=filters["type"],
            outcome=filters["outcome"],
            user_id=user_id,
            since=time.time() - filters["days"] * 86400,
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
        ),
        page,
        PAGE_SIZE,
    )
    audit = _paged(
        storage.list_access_audit(
            target_user_id=user_id,
            limit=PAGE_SIZE,
            offset=(audit_page - 1) * PAGE_SIZE,
        ),
        audit_page,
        PAGE_SIZE,
    )
    return filters, events, audit


def _public_event(event: dict) -> dict:
    keys = ("created_at", "event_type", "outcome", "category", "provider", "path",
            "user_id", "user_email", "actor_user_id", "actor_email")
    return {key: event.get(key) for key in keys}


async def access_events_page_handler(request: web.Request) -> web.Response:
    storage = request.app["control_storage"]
    filters, events, audit = _query_events(request)
    categories = storage.failure_category_counts(since=time.time() - 7 * 86400)
    return _private(web.Response(
        text=control_layout(
            title="Access Events",
            active="access",
            content=access_events_content(
                events=events,
                audit=audit,
                filters=filters,
                categories=categories,
                retention_days=retention_days(),
            ),
        ),
        content_type="text/html",
    ))


async def access_events_api(request: web.Request) -> web.Response:
    filters, events, audit = _query_events(request)
    return _private(web.json_response({
        "filters": filters,
        "events": {**events, "rows": [_public_event(e) for e in events["rows"]]},
        "audit": audit,
        "retention_days": retention_days(),
    }))


def _workspace_report(request: web.Request) -> tuple[WorkspaceInspector, dict, dict, int, int]:
    storage = request.app["control_storage"]
    inspector = WorkspaceInspector.for_app(request.app)
    ownership = inspector.ownership(storage.account_index())
    page = max(_int(request.query.get("page")), 1)
    total = len(ownership["mapped"])
    pages = max((total + WORKSPACE_PAGE_SIZE - 1) // WORKSPACE_PAGE_SIZE, 1)
    start = (page - 1) * WORKSPACE_PAGE_SIZE
    ownership["mapped_page"] = ownership["mapped"][start:start + WORKSPACE_PAGE_SIZE]
    statuses = {
        row["user_id"]: inspector.status(
            row["user_id"], entry_limit=LIST_ENTRY_LIMIT, time_budget=0.3)
        for row in ownership["mapped_page"]
        if not row.get("unexpected")
    }
    return inspector, ownership, statuses, page, pages


async def workspaces_page_handler(request: web.Request) -> web.Response:
    loop = asyncio.get_running_loop()
    inspector, ownership, statuses, page, pages = await loop.run_in_executor(
        None, _workspace_report, request)
    return _private(web.Response(
        text=control_layout(
            title="Workspace Ownership",
            active="workspaces",
            content=workspaces_content(
                ownership=ownership,
                statuses=statuses,
                workspace_root=str(inspector.workspace_root),
                page=page,
                pages=pages,
                total=len(ownership["mapped"]),
            ),
        ),
        content_type="text/html",
    ))


async def workspaces_api(request: web.Request) -> web.Response:
    loop = asyncio.get_running_loop()
    _inspector, ownership, statuses, page, pages = await loop.run_in_executor(
        None, _workspace_report, request)
    return _private(web.json_response({
        "users_root_exists": ownership["users_root_exists"],
        "mapped": [
            {**row, "status": statuses.get(row["user_id"])}
            for row in ownership["mapped_page"]
        ],
        "mapped_total": len(ownership["mapped"]),
        "page": page,
        "pages": pages,
        "without_workspace": ownership["without_workspace"],
        "orphaned": ownership["orphaned"],
        "truncated": ownership["truncated"],
    }))


def install_access_admin(app: web.Application, *, control_access) -> None:
    """Register access-administration routes behind ``control_access``."""
    app.router.add_post(
        "/control/users/{user_id}/sessions/revoke",
        control_access(user_sessions_revoke_handler),
    )
    app.router.add_get("/control/access", control_access(access_events_page_handler))
    app.router.add_get("/control/workspaces", control_access(workspaces_page_handler))
    app.router.add_get("/api/control/access/events", control_access(access_events_api))
    app.router.add_get("/api/control/workspaces", control_access(workspaces_api))
