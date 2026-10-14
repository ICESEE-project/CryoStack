"""Read access to the append-only ``access_audit_log`` and its export.

Filters are normalised here so the page, the JSON API and the export apply
exactly the same rules. Rows carry who (account id and the label recorded at
the time), whom, what changed, the reason and when. They never carry session
ids, password hashes, tokens or OAuth material; only allowlisted metadata
keys leave this module.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone

from icesee_auth import access_log

PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
#: an export never holds more than this many rows (newest first)
EXPORT_MAX_ROWS = 5000
EXPORT_FORMATS = ("csv", "json")
EXPORT_ACTION = "audit_exported"

#: actions written by the platform; the action filter also offers any
#: other well-formed action already present in the table
KNOWN_ACTIONS = (
    "role_changed",
    "role_granted",
    "role_revoked",
    "sessions_revoked",
    EXPORT_ACTION,
)

ACTION_LABELS = {
    "role_changed": "Role changed",
    "role_granted": "Role granted (CLI)",
    "role_revoked": "Role revoked (CLI)",
    "sessions_revoked": "Sessions revoked",
    EXPORT_ACTION: "Audit log exported",
}

#: metadata keys that may be shown or exported
METADATA_KEYS = ("format", "rows", "truncated", "filters")

EXPORT_COLUMNS = (
    "id",
    "created_at_utc",
    "actor_user_id",
    "actor_label",
    "action",
    "target_user_id",
    "target_label",
    "previous_value",
    "new_value",
    "reason",
    "detail",
)

_ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_TEXT_LIMIT = 200


def _int(value, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date(value) -> str:
    """A ``YYYY-MM-DD`` string, or empty when the value is not one."""
    text = str(value or "").strip()[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return ""
    return text


def _day_start(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def parse_filters(values) -> dict:
    """Normalise filters from a query string or a form (unknown keys ignored)."""
    since = _date(values.get("from"))
    until = _date(values.get("to"))
    if since and until and since > until:
        since, until = until, since
    action = str(values.get("action") or "").strip().lower()
    return {
        "from": since,
        "to": until,
        "action": action if _ACTION_PATTERN.match(action) else "",
        "actor": str(values.get("actor") or "").strip()[:_TEXT_LIMIT],
        "target": str(values.get("target") or "").strip()[:_TEXT_LIMIT],
    }


def filter_summary(filters: dict) -> str:
    parts = [f"{key}={filters[key]}" for key in ("from", "to", "action", "actor", "target")
             if filters.get(key)]
    return ", ".join(parts) or "none"


def safe_cell(value) -> str:
    """A CSV cell that spreadsheet software will not evaluate as a formula."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def public_metadata(metadata_json: str | None) -> dict:
    try:
        metadata = json.loads(metadata_json or "{}")
    except ValueError:
        return {}
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in METADATA_KEYS if key in metadata}


def detail_text(metadata: dict) -> str:
    return "; ".join(f"{key}={metadata[key]}" for key in METADATA_KEYS if key in metadata)


def iso_utc(timestamp: float | None) -> str:
    if timestamp is None:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AuditLogService:
    """Filtered, paged reads of ``access_audit_log`` plus audited export."""

    def __init__(self, storage):
        self.storage = storage

    # -- filters -------------------------------------------------------

    def _account_id(self, connection, value: str) -> str | None:
        if "@" not in value:
            return value
        row = connection.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (value,),
        ).fetchone()
        return row["id"] if row is not None else None

    def _where(self, connection, filters: dict) -> tuple[str, list]:
        where: list[str] = []
        params: list = []
        if filters.get("from"):
            where.append("a.created_at >= ?")
            params.append(_day_start(filters["from"]))
        if filters.get("to"):
            where.append("a.created_at < ?")
            params.append(_day_start(filters["to"]) + timedelta(days=1).total_seconds())
        if filters.get("action"):
            where.append("a.action = ?")
            params.append(filters["action"])
        for key, column in (("actor", "actor"), ("target", "target")):
            value = filters.get(key)
            if not value:
                continue
            # an account id, the id behind an exact email, or the exact
            # label recorded at the time (deleted accounts, CLI actors);
            # never a pattern
            account_id = self._account_id(connection, value)
            where.append(
                f"(a.{column}_user_id = ? OR a.{column}_label = ? COLLATE NOCASE)"
            )
            params += [account_id or "", value]
        return ("WHERE " + " AND ".join(where)) if where else "", params

    def actions(self) -> list[str]:
        with self.storage._connect() as connection:
            if not self.storage._has_table(connection, "access_audit_log"):
                return list(KNOWN_ACTIONS)
            present = [row[0] for row in connection.execute(
                "SELECT DISTINCT action FROM access_audit_log ORDER BY action")]
        extra = [a for a in present if a not in KNOWN_ACTIONS and _ACTION_PATTERN.match(a)]
        return [*KNOWN_ACTIONS, *extra]

    # -- reads ---------------------------------------------------------

    def _select(self, connection, clause: str, params: list, limit: int, offset: int) -> list[dict]:
        rows = connection.execute(
            f"""
            SELECT
                a.id,
                a.created_at,
                a.actor_user_id,
                a.actor_label,
                a.target_user_id,
                a.target_label,
                a.action,
                a.previous_value,
                a.new_value,
                a.reason,
                a.metadata_json,
                au.id AS actor_exists,
                tu.id AS target_exists
            FROM access_audit_log a
            LEFT JOIN users au ON au.id = a.actor_user_id
            LEFT JOIN users tu ON tu.id = a.target_user_id
            {clause}
            ORDER BY a.created_at DESC, a.id
            LIMIT ? OFFSET ?
            """,
            [*params, int(limit), int(offset)],
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["metadata"] = public_metadata(item.pop("metadata_json"))
            item["actor_exists"] = item["actor_exists"] is not None
            item["target_exists"] = item["target_exists"] is not None
            result.append(item)
        return result

    def page(self, filters: dict, *, page: int = 1, per_page: int = PAGE_SIZE) -> dict:
        per_page = min(max(_int(per_page, PAGE_SIZE), 1), MAX_PAGE_SIZE)
        page = max(_int(page), 1)
        with self.storage._connect() as connection:
            if not self.storage._has_table(connection, "access_audit_log"):
                return {"rows": [], "total": 0, "page": 1, "pages": 1, "per_page": per_page}
            clause, params = self._where(connection, filters)
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM access_audit_log a {clause}", params).fetchone()[0])
            pages = max((total + per_page - 1) // per_page, 1)
            page = min(page, pages)
            rows = self._select(connection, clause, params, per_page, (page - 1) * per_page)
        return {"rows": rows, "total": total, "page": page, "pages": pages, "per_page": per_page}

    def export_rows(self, filters: dict, *, limit: int | None = None) -> tuple[list[dict], int]:
        """Newest rows first, at most ``EXPORT_MAX_ROWS``; also returns the full match count."""
        limit = min(limit or EXPORT_MAX_ROWS, EXPORT_MAX_ROWS)
        with self.storage._connect() as connection:
            if not self.storage._has_table(connection, "access_audit_log"):
                return [], 0
            clause, params = self._where(connection, filters)
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM access_audit_log a {clause}", params).fetchone()[0])
            rows = self._select(connection, clause, params, limit, 0)
        return rows, total

    # -- export --------------------------------------------------------

    @staticmethod
    def export_record(row: dict) -> dict:
        return {
            "id": row["id"],
            "created_at_utc": iso_utc(row["created_at"]),
            "actor_user_id": row.get("actor_user_id"),
            "actor_label": row.get("actor_label"),
            "action": row["action"],
            "target_user_id": row.get("target_user_id"),
            "target_label": row.get("target_label"),
            "previous_value": row.get("previous_value"),
            "new_value": row.get("new_value"),
            "reason": row.get("reason"),
            "detail": detail_text(row.get("metadata") or {}),
        }

    def to_csv(self, rows: list[dict]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(EXPORT_COLUMNS)
        for row in rows:
            record = self.export_record(row)
            writer.writerow([safe_cell(record[column]) for column in EXPORT_COLUMNS])
        return buffer.getvalue()

    def to_json(self, rows: list[dict], *, filters: dict, total: int) -> str:
        return json.dumps({
            "exported_at_utc": iso_utc(time.time()),
            "filters": filters,
            "matched": total,
            "rows_exported": len(rows),
            "truncated": total > len(rows),
            "max_rows": EXPORT_MAX_ROWS,
            "rows": [self.export_record(row) for row in rows],
        }, indent=2)

    def record_export(self, *, actor, export_format: str, filters: dict,
                      rows: int, truncated: bool) -> str:
        """Append the export itself to the audit trail."""
        summary = filter_summary(filters)
        reason = (f"Exported {rows} audit row(s) as {export_format.upper()}"
                  f"{' (truncated at the export limit)' if truncated else ''}; "
                  f"filters: {summary}")
        with self.storage._connect() as connection:
            return access_log.record_audit(
                connection,
                actor_user_id=actor.id,
                actor_label=getattr(actor, "email", None) or actor.id,
                target_user_id=None,
                target_label=None,
                action=EXPORT_ACTION,
                previous_value=None,
                new_value=f"{rows} rows ({export_format})",
                reason=reason,
                metadata={
                    "format": export_format,
                    "rows": rows,
                    "truncated": truncated,
                    "filters": summary,
                },
            )
