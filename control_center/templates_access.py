# control_center/templates_access.py

"""Control Center views for accounts, access control and workspace status.

Content builders only; pages are wrapped by ``templates.control_layout``.
Nothing rendered here includes session ids, tokens, password hashes, OAuth
codes or secrets, or any file name or content below a workspace owner root.
"""

from __future__ import annotations

import json
from html import escape
from urllib.parse import urlencode

from .templates import _date, role_badge


ACCESS_STYLE = """
<style>
  .access-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
    margin-bottom: 1rem;
  }

  .access-filters select,
  .access-form select,
  .access-filters input[type="search"],
  .access-form textarea,
  .access-form input[type="text"] {
    min-height: 38px;
    padding: 0.5rem 0.65rem;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
    color: #0f172a;
    font: inherit;
    font-size: 0.8rem;
  }

  .access-filters input[type="search"] {
    width: min(100%, 360px);
  }

  .access-button {
    min-height: 38px;
    padding: 0 0.9rem;
    border: 1px solid #1d4ed8;
    border-radius: 8px;
    background: #2563eb;
    color: #ffffff;
    font: inherit;
    font-size: 0.78rem;
    font-weight: 750;
    cursor: pointer;
  }

  .access-button.secondary {
    border-color: #cbd5e1;
    background: #ffffff;
    color: #334155;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
  }

  .access-button.danger {
    border-color: #b91c1c;
    background: #dc2626;
  }

  .access-table-wrap {
    overflow-x: auto;
  }

  .access-table-wrap table {
    min-width: 640px;
  }

  .access-pager {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
    justify-content: space-between;
    padding: 0.8rem 1rem;
    color: #64748b;
    font-size: 0.75rem;
  }

  .access-pager a {
    color: #1d4ed8;
    font-weight: 700;
    text-decoration: none;
  }

  .access-notice {
    margin-bottom: 1rem;
    padding: 0.75rem 0.9rem;
    border: 1px solid #bbf7d0;
    border-radius: 10px;
    background: #f0fdf4;
    color: #166534;
    font-size: 0.8rem;
  }

  .access-notice.error {
    border-color: #fecaca;
    background: #fef2f2;
    color: #991b1b;
  }

  .access-form {
    display: grid;
    gap: 0.7rem;
    padding: 1rem;
  }

  .access-form label {
    display: grid;
    gap: 0.35rem;
    color: #475569;
    font-size: 0.74rem;
    font-weight: 700;
  }

  .access-form textarea {
    min-height: 64px;
    resize: vertical;
  }

  .access-hint {
    color: #64748b;
    font-size: 0.72rem;
    line-height: 1.45;
  }

  .access-tag {
    display: inline-flex;
    margin: 0 0.25rem 0.25rem 0;
    padding: 0.2rem 0.45rem;
    border-radius: 999px;
    background: #f1f5f9;
    color: #475569;
    font-size: 0.66rem;
    font-weight: 750;
  }

  .access-tag.failure,
  .access-tag.denied {
    background: #fef2f2;
    color: #b91c1c;
  }

  .access-tag.success {
    background: #f0fdf4;
    color: #15803d;
  }

  .access-links {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  @media (max-width: 760px) {
    .page-heading-row {
      flex-wrap: wrap;
    }

    .access-filters > * {
      flex: 1 1 100%;
    }

    .access-filters input[type="search"] {
      width: 100%;
    }
  }
</style>
"""

ERROR_MESSAGES = {
    "reason_required": "A reason of at least 4 characters is required.",
    "last_owner": "CryoStack must retain at least one owner.",
    "not_permitted": "You do not have permission to make this change.",
    "invalid_role": "That role is not a supported CryoStack role.",
    "cross_origin": "Request refused: it did not come from this site.",
}

NOTICE_MESSAGES = {
    "role_updated": "Access updated and recorded in the audit trail.",
    "sessions_revoked": "Sessions revoked and recorded in the audit trail.",
    "developer_docs_updated": "Developer Guide access updated and recorded in the audit trail.",
}

EVENT_LABELS = {
    "login_success": "Sign-in",
    "login_failure": "Sign-in failed",
    "login_rate_limited": "Sign-in throttled",
    "logout": "Sign-out",
    "register": "Registration",
    "control_denied": "Control Center denied",
    "role_changed": "Role changed",
    "role_change_denied": "Role change denied",
    "sessions_revoked": "Sessions revoked",
}


def _size(value: int | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "—"


def _href(path: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", 0)}
    return path + ("?" + urlencode(clean) if clean else "")


def pager(*, path: str, params: dict, page: int, pages: int, total: int, noun: str,
          page_param: str = "page") -> str:
    prev_link = (
        f'<a href="{escape(_href(path, {**params, page_param: page - 1}))}">← Previous</a>'
        if page > 1 else "<span></span>"
    )
    next_link = (
        f'<a href="{escape(_href(path, {**params, page_param: page + 1}))}">Next →</a>'
        if page < pages else "<span></span>"
    )
    return f"""
    <div class="access-pager">
      {prev_link}
      <span>Page {page} of {pages} · {total} {escape(noun)}</span>
      {next_link}
    </div>
    """


def notice(*, message: str | None = None, error: str | None = None) -> str:
    parts = []
    if message:
        parts.append(f'<div class="access-notice" role="status">{escape(message)}</div>')
    if error:
        parts.append(f'<div class="access-notice error" role="alert">{escape(error)}</div>')
    return "".join(parts)


# ----------------------------------------------------------------------
# Users directory
# ----------------------------------------------------------------------

def users_directory_content(*, result: dict) -> str:
    rows = []
    for user in result["users"]:
        providers = user.get("providers") or []
        pills = "".join(
            f'<span class="provider-pill {escape(p)}">{escape(p.title())}</span>'
            for p in providers
        ) or '<span class="provider-pill password">Password</span>'
        active = int(user.get("active_sessions") or 0)
        initial = escape(user["display_name"][0].upper()) if user["display_name"] else "?"
        rows.append(f"""
        <tr class="user-row">
          <td>
            <div class="user-cell">
              <div class="user-avatar">{initial}</div>
              <div>
                <a class="table-link user-name" href="/control/users/{escape(user["id"])}">
                  {escape(user["display_name"])}
                </a>
                <div class="user-institution">{escape(user["institution"] or "No institution")}</div>
              </div>
            </div>
          </td>
          <td>{escape(user["email"])}</td>
          <td>{role_badge(user.get("control_role"))}</td>
          <td><div class="provider-list">{pills}</div></td>
          <td>{int(user.get("experiments") or 0)}</td>
          <td>
            {'<span class="presence active"><span></span>' + str(active) + ' active</span>'
             if active else '<span class="presence"><span></span>Offline</span>'}
          </td>
          <td>{_date(user["last_seen_at"]) if user.get("last_seen_at") else "Never"}</td>
        </tr>
        """)

    role_options = "".join(
        f'<option value="{value}"{" selected" if result["role"] == value else ""}>{label}</option>'
        for value, label in (
            ("", "All roles"),
            ("user", "User (no Control Center access)"),
            ("developer", "Developer"),
            ("maintainer", "Maintainer"),
            ("admin", "Admin"),
            ("owner", "Owner"),
        )
    )

    params = {"q": result["query"], "role": result["role"]}

    table = f"""
      <div class="access-table-wrap">
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Email</th>
              <th>Role</th>
              <th>Identity</th>
              <th>Experiments</th>
              <th>Sessions</th>
              <th>Last Seen</th>
            </tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
      </div>
    """ if rows else '<div class="panel-empty">No accounts match these filters.</div>'

    return f"""
    {ACCESS_STYLE}
    <div class="page-heading-row">
      <div>
        <h1>Users</h1>
        <p class="page-subtitle">Accounts, role assignments and sign-in activity.</p>
      </div>
      <div class="page-count">{result["total"]} accounts</div>
    </div>

    <div class="access-links" style="margin-bottom:1rem">
      <a class="access-button secondary" href="/control/access">Access events &amp; audit</a>
      <a class="access-button secondary" href="/control/workspaces">Workspace ownership</a>
    </div>

    <form class="access-filters" method="get" action="/control/users" role="search">
      <input type="search" name="q" value="{escape(result["query"])}"
             placeholder="Search name, email, institution or account id"
             aria-label="Search accounts" autocomplete="off">
      <select name="role" aria-label="Filter by role">{role_options}</select>
      <button class="access-button" type="submit">Filter</button>
      {'<a class="access-button secondary" href="/control/users">Clear</a>'
       if result["query"] or result["role"] else ''}
    </form>

    <div class="panel user-table-panel">
      {table}
      {pager(path="/control/users", params=params, page=result["page"],
             pages=result["pages"], total=result["total"], noun="accounts")}
    </div>
    """


# ----------------------------------------------------------------------
# User detail: access, sign-in diagnostics, workspace status
# ----------------------------------------------------------------------

ROLE_LABELS = {
    "": "No Control Center access",
    "developer": "Developer",
    "maintainer": "Maintainer",
    "admin": "Admin",
    "owner": "Owner",
}


def access_panel(*, user: dict, allowed_roles: list[str], can_revoke: bool,
                 is_self: bool, can_manage_developer_docs: bool = False) -> str:
    current_role = user.get("control_role") or "user"

    if allowed_roles:
        options = "".join(
            f'<option value="{escape(role)}"'
            f'{" selected" if (role or "user") == current_role else ""}>'
            f'{escape(ROLE_LABELS[role])}</option>'
            for role in allowed_roles
        )
        role_form = f"""
        <form method="post" action="/control/users/{escape(user["id"])}/role" class="access-form">
          <label>
            Control Center role
            <select name="control_role">{options}</select>
          </label>
          <label>
            Reason (recorded in the audit trail)
            <textarea name="reason" required minlength="4" maxlength="500"
                      placeholder="Why is this access changing?"></textarea>
          </label>
          <button type="submit" class="access-button">Update access</button>
        </form>
        """
    else:
        why = (
            "You cannot change your own role."
            if is_self
            else "You do not have permission to modify this account's access."
        )
        role_form = f'<div class="panel-empty">{why}</div>'

    docs_form = ""
    if can_manage_developer_docs and current_role in {"maintainer", "admin"}:
        checked = " checked" if user.get("developer_docs_access") else ""
        docs_form = f"""
        <form method="post" action="/control/users/{escape(user['id'])}/developer-docs"
              class="access-form">
          <label class="access-check">
            <input type="checkbox" name="enabled" value="1"{checked}>
            Allow access to owner documentation and Developer Guides
          </label>
          <label>Reason (recorded in the audit trail)
            <textarea name="reason" required minlength="4" maxlength="500"
                      placeholder="Why is documentation access changing?"></textarea>
          </label>
          <button type="submit" class="access-button">Update Developer Guide access</button>
        </form>"""

    return f"""
    <div class="panel">
      <div class="panel-header">Platform Access</div>
      <div class="detail-list">
        <div class="detail-row">
          <span>Current role</span>
          <strong>{role_badge(current_role)}</strong>
        </div>
      </div>
      {role_form}
      {docs_form}
      <div class="access-form" style="padding-top:0">
        <p class="access-hint">
          Owners assign any role. Admins and maintainers assign only roles below
          their own, to accounts below their own role. Nobody changes their own
          role, and the last owner cannot be removed.
        </p>
      </div>
    </div>
    """


def login_panel(*, user: dict, can_revoke: bool) -> str:
    login = user.get("login") or {}
    failures = login.get("recent_failures") or []

    failure_rows = "".join(
        f"""
        <tr>
          <td>{_date(item["created_at"])}</td>
          <td>{escape(EVENT_LABELS.get(item["event_type"], item["event_type"]))}</td>
          <td><span class="access-tag failure">{escape(item.get("category") or "—")}</span></td>
          <td>{escape(item.get("provider") or item.get("path") or "—")}</td>
        </tr>
        """
        for item in failures
    )

    revoke = ""
    if can_revoke:
        revoke = f"""
        <form method="post" action="/control/users/{escape(user["id"])}/sessions/revoke"
              class="access-form">
          <label>
            Reason for revoking all sessions
            <input type="text" name="reason" required minlength="4" maxlength="500"
                   placeholder="e.g. lost device, suspicious activity">
          </label>
          <button type="submit" class="access-button danger"
                  {"disabled" if not login.get("sessions_total") else ""}>
            Revoke all sessions ({int(login.get("sessions_total") or 0)})
          </button>
          <p class="access-hint">
            Signs the account out of every browser on the next request.
            Running application kernels keep their current identity until they stop.
          </p>
        </form>
        """

    sessions = user.get("sessions_detail") or []
    session_rows = "".join(
        f"""
        <tr>
          <td>{_date(s["created_at"])}</td>
          <td>{_date(s["last_seen_at"])}</td>
          <td>{'<span class="presence active"><span></span>Active</span>' if s["active"]
               else '<span class="presence"><span></span>Expired</span>'}</td>
          <td>{_date(s["expires_at"])}</td>
        </tr>
        """
        for s in sessions[:8]
    )

    return f"""
    <div class="panel">
      <div class="panel-header">Sign-in &amp; Sessions</div>
      <div class="detail-list">
        <div class="detail-row"><span>Active sessions</span>
          <strong>{int(login.get("sessions_active") or 0)} of {int(login.get("sessions_total") or 0)}</strong></div>
        <div class="detail-row"><span>Last sign-in</span>
          <strong>{_date(login.get("last_login_at")) if login.get("last_login_at") else "Not recorded"}
          {f'<span class="access-tag">{escape(login["last_login_provider"])}</span>' if login.get("last_login_provider") else ""}</strong></div>
        <div class="detail-row"><span>Last seen</span>
          <strong>{_date(login.get("last_seen_at")) if login.get("last_seen_at") else "Never"}</strong></div>
        <div class="detail-row"><span>Failures (24 h)</span>
          <strong>{int(login.get("failures_24h") or 0)}</strong></div>
        <div class="detail-row"><span>Sessions last revoked</span>
          <strong>{_date(login.get("last_revoked_at")) if login.get("last_revoked_at") else "Never"}</strong></div>
      </div>
      {f'''
      <div class="access-table-wrap">
        <table>
          <thead><tr><th>Started</th><th>Last Seen</th><th>Status</th><th>Expires</th></tr></thead>
          <tbody>{session_rows}</tbody>
        </table>
      </div>''' if session_rows else '<div class="panel-empty">No sessions recorded.</div>'}
      <div class="panel-header" style="border-top:1px solid #e2e8f0">Recent failures and denials</div>
      {f'''
      <div class="access-table-wrap">
        <table>
          <thead><tr><th>When</th><th>Event</th><th>Category</th><th>Via</th></tr></thead>
          <tbody>{failure_rows}</tbody>
        </table>
      </div>''' if failure_rows else '<div class="panel-empty">No recorded failures.</div>'}
      {revoke}
    </div>
    """


def workspace_panel(*, workspace: dict | None) -> str:
    if workspace is None:
        return ""
    if workspace.get("symlink"):
        body = ('<div class="panel-empty">The owner root is a symbolic link; '
                'it is not followed or measured.</div>')
    elif not workspace.get("exists"):
        body = ('<div class="panel-empty">No workspace yet. One is created the first '
                'time this account uses an application.</div>')
    else:
        areas = "".join(
            f'<span class="access-tag">{escape(a)}</span>' for a in workspace["areas"]
        ) or "None"
        approx = " (approximate: scan limit reached)" if workspace.get("approximate") else ""
        body = f"""
        <div class="detail-list">
          <div class="detail-row"><span>Size</span>
            <strong>{_size(workspace["size_bytes"])}{"+" if workspace.get("approximate") else ""}{escape(approx)}</strong></div>
          <div class="detail-row"><span>Files / folders</span>
            <strong>{int(workspace["files"])} / {int(workspace["directories"])}</strong></div>
          <div class="detail-row"><span>Last activity</span>
            <strong>{_date(workspace["last_activity"]) if workspace.get("last_activity") else "—"}</strong></div>
          <div class="detail-row"><span>Application areas</span><strong>{areas}</strong></div>
          <div class="detail-row"><span>Other top-level entries</span>
            <strong>{int(workspace.get("other_entries") or 0)}</strong></div>
        </div>
        """
    return f"""
    <div class="panel">
      <div class="panel-header">Workspace</div>
      {body}
      <div class="mono-box" title="Owner-root directory name">users/{escape(workspace.get("safe_id") or "")}</div>
    </div>
    """


# ----------------------------------------------------------------------
# Access events and audit trail
# ----------------------------------------------------------------------

def _event_detail(event: dict) -> str:
    try:
        metadata = json.loads(event.get("metadata_json") or "{}")
    except ValueError:
        metadata = {}
    parts = []
    if metadata.get("previous_role") or metadata.get("new_role"):
        parts.append(f'{metadata.get("previous_role") or "user"} → {metadata.get("new_role") or "user"}')
    if "sessions_removed" in metadata:
        parts.append(f'{metadata["sessions_removed"]} session(s)')
    if event.get("path"):
        parts.append(event["path"])
    return escape(" · ".join(str(p) for p in parts)) or "—"


def _account(user_id: str | None, email: str | None) -> str:
    if not user_id:
        return "—"
    label = email or user_id[:12]
    return f'<a class="table-link" href="/control/users/{escape(user_id)}">{escape(label)}</a>'


def access_events_content(*, events: dict, audit: dict, filters: dict,
                          categories: dict, retention_days: int) -> str:
    event_rows = "".join(
        f"""
        <tr>
          <td>{_date(e["created_at"])}</td>
          <td>{escape(EVENT_LABELS.get(e["event_type"], e["event_type"]))}</td>
          <td><span class="access-tag {escape(e["outcome"])}">{escape(e["outcome"])}</span></td>
          <td>{escape(e.get("category") or "—")}</td>
          <td>{_account(e.get("user_id"), e.get("user_email"))}</td>
          <td>{_account(e.get("actor_user_id"), e.get("actor_email"))}</td>
          <td>{escape(e.get("provider") or "—")}</td>
          <td>{_event_detail(e)}</td>
        </tr>
        """
        for e in events["rows"]
    )

    audit_rows = "".join(
        f"""
        <tr>
          <td>{_date(a["created_at"])}</td>
          <td>{_account(a.get("actor_user_id"), a.get("actor_label"))
               if a.get("actor_user_id") else escape(a.get("actor_label") or "—")}</td>
          <td>{_account(a.get("target_user_id"), a.get("target_label"))}</td>
          <td>{escape(a["action"].replace("_", " "))}</td>
          <td>{escape(a.get("previous_value") or "—")} → {escape(a.get("new_value") or "—")}</td>
          <td>{escape(a.get("reason") or "—")}</td>
        </tr>
        """
        for a in audit["rows"]
    )

    type_options = "".join(
        f'<option value="{value}"{" selected" if filters["type"] == value else ""}>{escape(label)}</option>'
        for value, label in [("", "All events"), *EVENT_LABELS.items()]
    )
    outcome_options = "".join(
        f'<option value="{value}"{" selected" if filters["outcome"] == value else ""}>{label}</option>'
        for value, label in (("", "Any outcome"), ("success", "Success"),
                             ("failure", "Failure"), ("denied", "Denied"))
    )
    days_options = "".join(
        f'<option value="{value}"{" selected" if filters["days"] == value else ""}>{label}</option>'
        for value, label in ((1, "Last 24 hours"), (7, "Last 7 days"), (30, "Last 30 days"),
                             (retention_days, f"All retained ({retention_days} days)"))
    )
    category_tags = "".join(
        f'<span class="access-tag failure">{escape(name)}: {count}</span>'
        for name, count in categories.items()
    ) or '<span class="access-hint">No failures or denials in the last 7 days.</span>'

    params = {"type": filters["type"], "outcome": filters["outcome"],
              "user": filters["user"], "days": filters["days"]}

    return f"""
    {ACCESS_STYLE}
    <div class="page-heading-row">
      <div>
        <h1>Access Events</h1>
        <p class="page-subtitle">
          Sign-ins, failures, denied Control Center requests, role changes and
          session revocations. Events are kept for {retention_days} days; the
          access audit trail is append-only and kept indefinitely.
        </p>
      </div>
      <div class="page-count">{events["total"]} events</div>
    </div>

    <div class="panel">
      <div class="panel-header">Failures and denials by category (7 days)</div>
      <div style="padding:0.9rem 1rem">{category_tags}</div>
    </div>

    <form class="access-filters" method="get" action="/control/access">
      <select name="type" aria-label="Event type">{type_options}</select>
      <select name="outcome" aria-label="Outcome">{outcome_options}</select>
      <select name="days" aria-label="Time range">{days_options}</select>
      <input type="search" name="user" value="{escape(filters["user"])}"
             placeholder="Account id or exact email" aria-label="Account">
      <button class="access-button" type="submit">Filter</button>
    </form>

    <div class="panel">
      <div class="panel-header">Events</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>When</th><th>Event</th><th>Outcome</th><th>Category</th>
        <th>Account</th><th>By</th><th>Via</th><th>Detail</th></tr></thead>
        <tbody>{event_rows}</tbody></table></div>'''
        if event_rows else '<div class="panel-empty">No events match these filters.</div>'}
      {pager(path="/control/access", params=params, page=events["page"],
             pages=events["pages"], total=events["total"], noun="events")}
    </div>

    <div class="panel" id="audit">
      <div class="panel-header">Access audit trail
        · <a class="table-link" href="/control/audit">Filter and export in the Audit Log</a></div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>When</th><th>Who</th><th>Whom</th><th>What</th>
        <th>Change</th><th>Reason</th></tr></thead>
        <tbody>{audit_rows}</tbody></table></div>'''
        if audit_rows else '<div class="panel-empty">No access changes recorded yet.</div>'}
      {pager(path="/control/access", params=params, page=audit["page"],
             pages=audit["pages"], total=audit["total"], noun="audit entries",
             page_param="audit_page")}
    </div>
    """


# ----------------------------------------------------------------------
# Workspace ownership review
# ----------------------------------------------------------------------

def workspaces_content(*, ownership: dict, statuses: dict, workspace_root: str,
                       page: int, pages: int, total: int) -> str:
    mapped_rows = []
    for row in ownership["mapped_page"]:
        status = statuses.get(row["user_id"]) or {}
        areas = "".join(f'<span class="access-tag">{escape(a)}</span>'
                        for a in status.get("areas", [])) or "—"
        flag = (f'<span class="access-tag failure">{escape(row["unexpected"])}</span>'
                if row.get("unexpected") else "")
        mapped_rows.append(f"""
        <tr>
          <td>{_account(row["user_id"], row["email"])}</td>
          <td><code>{escape(row["safe_id"])}</code> {flag}</td>
          <td>{_size(status.get("size_bytes"))}{"+" if status.get("approximate") else ""}</td>
          <td>{_date(status["last_activity"]) if status.get("last_activity") else "—"}</td>
          <td>{areas}</td>
        </tr>
        """)

    orphan_rows = "".join(
        f"""
        <tr>
          <td><code>{escape(o["name"])}</code></td>
          <td>{escape(o["kind"])}</td>
          <td><span class="access-tag failure">{escape(o["category"])}</span></td>
        </tr>
        """
        for o in ownership["orphaned"]
    )

    without_rows = "".join(
        f"<tr><td>{_account(w['user_id'], w['email'])}</td>"
        f"<td><code>{escape(w['safe_id'])}</code></td></tr>"
        for w in ownership["without_workspace"][:50]
    )
    hidden = max(len(ownership["without_workspace"]) - 50, 0)
    if hidden:
        without_rows += (f'<tr><td colspan="2" class="access-hint">and {hidden} more '
                         '(new accounts get a workspace on first application use)</td></tr>')

    return f"""
    {ACCESS_STYLE}
    <div class="page-heading-row">
      <div>
        <h1>Workspace Ownership</h1>
        <p class="page-subtitle">
          Read-only mapping of per-user workspace directories to accounts.
          Sizes are bounded scans; no file names or contents are shown.
        </p>
      </div>
      <div class="page-count">{len(ownership["mapped"])} mapped ·
        {len(ownership["orphaned"])} unmatched</div>
    </div>

    <div class="panel">
      <div class="detail-list">
        <div class="detail-row"><span>Workspace root</span>
          <strong><code>{escape(workspace_root)}</code></strong></div>
        <div class="detail-row"><span>Users directory</span>
          <strong>{"Present" if ownership["users_root_exists"] else "Not created yet"}</strong></div>
        <div class="detail-row"><span>Accounts without a workspace</span>
          <strong>{len(ownership["without_workspace"])}</strong></div>
        {'<div class="detail-row"><span>Listing</span><strong>Truncated at scan limit</strong></div>'
         if ownership.get("truncated") else ''}
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">Workspaces mapped to accounts</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>Account</th><th>Owner root</th><th>Size</th>
        <th>Last activity</th><th>Areas</th></tr></thead>
        <tbody>{''.join(mapped_rows)}</tbody></table></div>'''
        if mapped_rows else '<div class="panel-empty">No account has a workspace yet.</div>'}
      {pager(path="/control/workspaces", params={}, page=page, pages=pages,
             total=total, noun="workspaces")}
    </div>

    <div class="panel">
      <div class="panel-header">Directories without a matching account</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>Directory</th><th>Kind</th><th>Finding</th></tr></thead>
        <tbody>{orphan_rows}</tbody></table></div>'''
        if orphan_rows else '<div class="panel-empty">Every workspace directory belongs to an account.</div>'}
    </div>

    <div class="panel">
      <div class="panel-header">Accounts without a workspace</div>
      {f'''<div class="access-table-wrap"><table>
        <thead><tr><th>Account</th><th>Expected owner root</th></tr></thead>
        <tbody>{without_rows}</tbody></table></div>'''
        if without_rows else '<div class="panel-empty">Every account has a workspace.</div>'}
    </div>
    """


# ----------------------------------------------------------------------
# Authentication overview: sign-in health
# ----------------------------------------------------------------------

def sign_in_health(sign_in: dict | None) -> str:
    if not sign_in:
        return ""
    tags = "".join(
        f'<span class="access-tag failure">{escape(name)}: {count}</span>'
        for name, count in (sign_in.get("failure_categories") or {}).items()
    ) or '<span class="access-hint">No failures or denials in the last 24 hours.</span>'
    return f"""
    {ACCESS_STYLE}
    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-label">Sign-ins (24 h)</div>
        <div class="metric-value">{int(sign_in.get("logins_24h") or 0)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Failed sign-ins (24 h)</div>
        <div class="metric-value">{int(sign_in.get("failures_24h") or 0)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Control Center denials (24 h)</div>
        <div class="metric-value">{int(sign_in.get("denials_24h") or 0)}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Active sessions</div>
        <div class="metric-value">{int(sign_in.get("active_sessions") or 0)}</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header">Failure categories (24 h)</div>
      <div style="padding:0.9rem 1rem">{tags}</div>
      <div class="access-form" style="padding-top:0">
        <div class="access-links">
          <a class="access-button secondary" href="/control/access?outcome=failure">Review failures</a>
          <a class="access-button secondary" href="/control/access?type=control_denied">Denied Control Center requests</a>
          <a class="access-button secondary" href="/control/access#audit">Access audit trail</a>
        </div>
      </div>
    </div>
    """
