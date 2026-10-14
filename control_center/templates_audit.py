# control_center/templates_audit.py

"""Control Center view of the append-only access audit trail.

Content builder only; the page is wrapped by ``templates.control_layout``.
Rows show the account id and the label recorded when the change was made,
never session ids, tokens, password hashes or OAuth material.
"""

from __future__ import annotations

from html import escape

from .services.audit import ACTION_LABELS, EXPORT_MAX_ROWS, detail_text
from .templates import _date
from .templates_access import ACCESS_STYLE, pager


AUDIT_STYLE = """
<style>
  .audit-filters input[type="date"] {
    min-height: 38px;
    padding: 0.45rem 0.6rem;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
    color: #0f172a;
    font: inherit;
    font-size: 0.8rem;
  }

  .audit-filters label {
    display: inline-flex;
    gap: 0.4rem;
    align-items: center;
    color: #475569;
    font-size: 0.74rem;
    font-weight: 700;
  }

  .audit-filters input[type="search"] {
    width: min(100%, 240px);
  }

  .audit-export {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    padding: 0.9rem 1rem;
  }

  .audit-reason {
    min-width: 220px;
    max-width: 420px;
    overflow-wrap: anywhere;
  }

  .audit-when {
    white-space: nowrap;
  }

  .audit-account small {
    display: block;
    color: #94a3b8;
    font-size: 0.66rem;
  }

  @media (max-width: 760px) {
    .audit-filters label {
      flex: 1 1 100%;
      justify-content: space-between;
    }

    .audit-filters input[type="date"] {
      flex: 1 1 auto;
      min-width: 0;
    }

    .audit-export > * {
      flex: 1 1 100%;
    }
  }
</style>
"""


def _who(user_id: str | None, label: str | None, exists: bool) -> str:
    text = escape(label or (user_id[:12] if user_id else "") or "—")
    if user_id and exists:
        return (f'<span class="audit-account"><a class="table-link" '
                f'href="/control/users/{escape(user_id)}">{text}</a></span>')
    if user_id:
        return f'<span class="audit-account">{text}<small>account no longer exists</small></span>'
    return f'<span class="audit-account">{text}</span>'


def _change(row: dict) -> str:
    previous, new = row.get("previous_value"), row.get("new_value")
    if previous is None and new is None:
        return "—"
    if previous is None:
        return escape(new)
    return f"{escape(previous)} → {escape(new or '—')}"


def audit_log_content(*, result: dict, filters: dict, actions: list[str],
                      can_export: bool, error: str | None = None) -> str:
    rows = "".join(
        f"""
        <tr>
          <td class="audit-when"><span title="UTC">{_date(r["created_at"])}</span></td>
          <td>{_who(r.get("actor_user_id"), r.get("actor_label"), r["actor_exists"])}</td>
          <td><span class="access-tag">{escape(ACTION_LABELS.get(r["action"], r["action"].replace("_", " ")))}</span></td>
          <td>{_who(r.get("target_user_id"), r.get("target_label"), r["target_exists"])
               if r.get("target_user_id") or r.get("target_label") else "—"}</td>
          <td>{_change(r)}</td>
          <td class="audit-reason">{escape(r.get("reason") or "—")}
            {f'<div class="access-hint">{escape(detail_text(r["metadata"]))}</div>'
             if r.get("metadata") and r["action"] == "audit_exported" else ""}</td>
        </tr>
        """
        for r in result["rows"]
    )

    action_options = "".join(
        f'<option value="{escape(value)}"{" selected" if filters["action"] == value else ""}>'
        f'{escape(label)}</option>'
        for value, label in [("", "All actions"),
                             *((a, ACTION_LABELS.get(a, a.replace("_", " "))) for a in actions)]
    )

    params = {key: filters[key] for key in ("from", "to", "action", "actor", "target")
              if filters.get(key)}
    hidden = "".join(
        f'<input type="hidden" name="{key}" value="{escape(value)}">'
        for key, value in params.items()
    )

    if can_export:
        export_panel = f"""
    <div class="panel" id="export">
      <div class="panel-header">Export</div>
      <form class="audit-export" method="post" action="/control/audit/export">
        {hidden}
        <select name="format" aria-label="Export format">
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
        </select>
        <button class="access-button" type="submit">Export {result["total"]} matching rows</button>
        <span class="access-hint">
          Exports the rows matching the current filters, newest first, up to
          {EXPORT_MAX_ROWS:,} rows. The export itself is recorded in this audit trail.
        </span>
      </form>
    </div>
    """
    else:
        export_panel = """
    <div class="panel" id="export">
      <div class="panel-header">Export</div>
      <div class="panel-empty">Exporting the audit trail requires the maintainer, admin or owner role.</div>
    </div>
    """

    error_html = (f'<div class="access-notice error" role="alert">{escape(error)}</div>'
                  if error else "")

    return f"""
    {ACCESS_STYLE}
    {AUDIT_STYLE}
    <div class="page-heading-row">
      <div>
        <h1>Audit Log</h1>
        <p class="page-subtitle">
          Who changed whose access, what changed, when and why. The trail is
          append-only: rows cannot be edited or deleted. Times are UTC.
        </p>
      </div>
      <div class="page-count">{result["total"]} entries</div>
    </div>

    {error_html}

    <form class="access-filters audit-filters" method="get" action="/control/audit">
      <label>From <input type="date" name="from" value="{escape(filters["from"])}"></label>
      <label>To <input type="date" name="to" value="{escape(filters["to"])}"></label>
      <select name="action" aria-label="Action">{action_options}</select>
      <input type="search" name="actor" value="{escape(filters["actor"])}"
             placeholder="Actor: id, exact email or label" aria-label="Actor">
      <input type="search" name="target" value="{escape(filters["target"])}"
             placeholder="Target: id, exact email or label" aria-label="Target account">
      <button class="access-button" type="submit">Filter</button>
      <a class="access-button secondary" href="/control/audit">Reset</a>
    </form>

    <div class="panel">
      <div class="panel-header">Audit entries</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>When (UTC)</th><th>Who</th><th>What</th><th>Whom</th>
        <th>Change</th><th>Reason</th></tr></thead>
        <tbody>{rows}</tbody></table></div>'''
        if rows else '<div class="panel-empty">No audit entries match these filters.</div>'}
      {pager(path="/control/audit", params=params, page=result["page"],
             pages=result["pages"], total=result["total"], noun="entries")}
    </div>

    {export_panel}
    """
