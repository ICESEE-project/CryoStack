# control_center/templates.py

from __future__ import annotations

from datetime import datetime, timezone
from html import escape


def _date(
    value: float | None,
) -> str:

    if value is None:
        return "—"

    return (
        datetime
        .fromtimestamp(
            value,
            tz=timezone.utc,
        )
        .strftime(
            "%b %d, %Y %H:%M"
        )
    )


def control_layout(
    *,
    title: str,
    active: str,
    content: str,
) -> str:

    def nav_item(
        label: str,
        href: str,
        key: str,
    ) -> str:

        active_class = (
            " active"
            if active == key
            else ""
        )

        return f"""
        <a
          class="control-nav-item{active_class}"
          href="{escape(href)}"
        >
          {escape(label)}
        </a>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">

  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >

  <title>{escape(title)} | CryoStack Control Center</title>

  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: #f8fafc;
      color: #0f172a;
      font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    }}

    .control-shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns:
        245px minmax(0, 1fr);
    }}

    .control-sidebar {{
      padding: 1.35rem 1rem;
      border-right: 1px solid #e2e8f0;
      background: #ffffff;
    }}

    .control-brand {{
      display: block;
      margin-bottom: 0.2rem;
      color: #0f172a;
      font-size: 1.25rem;
      font-weight: 850;
      text-decoration: none;
    }}

    .control-brand span {{
      color: #2563eb;
    }}

    .control-subtitle {{
      margin-bottom: 1.6rem;
      color: #94a3b8;
      font-size: 0.73rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}

    .control-nav {{
      display: grid;
      gap: 0.25rem;
    }}

    .control-nav-item {{
      padding: 0.68rem 0.75rem;
      border-radius: 9px;
      color: #475569;
      font-size: 0.84rem;
      font-weight: 650;
      text-decoration: none;
    }}

    .control-nav-item:hover {{
      background: #f8fafc;
    }}

    .control-nav-item.active {{
      background: #eff6ff;
      color: #1d4ed8;
    }}

    .nav-section {{
      margin:
        1.25rem 0
        0.4rem;
      padding: 0 0.75rem;
      color: #94a3b8;
      font-size: 0.67rem;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}

    .control-main {{
      min-width: 0;
    }}

    .control-header {{
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 2rem;
      border-bottom: 1px solid #e2e8f0;
      background: #ffffff;
    }}

    .control-header-title {{
      font-size: 0.9rem;
      font-weight: 750;
    }}

    .control-header a {{
      color: #2563eb;
      font-size: 0.8rem;
      font-weight: 700;
      text-decoration: none;
    }}

    .control-content {{
      width: min(
        100%,
        1320px
      );
      padding: 2rem;
    }}

    h1 {{
      margin: 0 0 0.35rem;
      font-size: 1.75rem;
      letter-spacing: -0.035em;
    }}

    .page-subtitle {{
      margin: 0 0 1.5rem;
      color: #64748b;
      font-size: 0.88rem;
    }}

    .metric-grid {{
      display: grid;
      grid-template-columns:
        repeat(
          4,
          minmax(0, 1fr)
        );
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}

    .metric-card,
    .panel {{
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      background: #ffffff;
      box-shadow:
        0 6px 18px
        rgba(15, 23, 42, 0.035);
    }}

    .metric-card {{
      padding: 1.1rem;
    }}

    .metric-label {{
      color: #64748b;
      font-size: 0.75rem;
      font-weight: 700;
    }}

    .metric-value {{
      margin-top: 0.4rem;
      font-size: 1.65rem;
      font-weight: 850;
    }}

    .metric-detail {{
      margin-top: 0.25rem;
      color: #94a3b8;
      font-size: 0.72rem;
    }}

    .panel {{
      margin-bottom: 1rem;
      overflow: hidden;
    }}

    .panel-header {{
      padding: 1rem 1.1rem;
      border-bottom: 1px solid #e2e8f0;
      font-size: 0.9rem;
      font-weight: 750;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
    }}

    th,
    td {{
      padding: 0.8rem 1rem;
      border-bottom: 1px solid #f1f5f9;
      text-align: left;
      vertical-align: top;
      font-size: 0.78rem;
    }}

    th {{
      color: #64748b;
      background: #f8fafc;
      font-size: 0.7rem;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }}

    td {{
      color: #334155;
    }}

    .status-pill {{
      display: inline-flex;
      padding: 0.28rem 0.5rem;
      border-radius: 999px;
      background: #f1f5f9;
      color: #475569;
      font-size: 0.68rem;
      font-weight: 750;
    }}

    .identity-ok {{
      color: #15803d;
      font-weight: 750;
    }}

    .identity-none {{
      color: #94a3b8;
    }}

    .page-heading-row {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    }}

    .page-count {{
    padding: 0.45rem 0.7rem;
    border: 1px solid #e2e8f0;
    border-radius: 999px;
    background: #ffffff;
    color: #64748b;
    font-size: 0.72rem;
    font-weight: 750;
    }}

    .user-toolbar {{
    display: flex;
    margin-bottom: 1rem;
    }}

    .search-box {{
    width: min(100%, 470px);
    min-height: 42px;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0 0.85rem;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    background: #ffffff;
    }}

    .search-box span {{
    color: #94a3b8;
    }}

    .search-box input {{
    width: 100%;
    border: 0;
    outline: 0;
    background: transparent;
    color: #0f172a;
    font: inherit;
    font-size: 0.82rem;
    }}

    .user-table-panel {{
    overflow-x: auto;
    }}

    .user-row {{
    cursor: pointer;
    transition:
        background 0.12s ease;
    }}

    .user-row:hover {{
    background: #f8fafc;
    }}

    .user-cell {{
    display: flex;
    align-items: center;
    gap: 0.7rem;
    }}

    .user-avatar {{
    width: 34px;
    height: 34px;
    flex: 0 0 34px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 0.76rem;
    font-weight: 850;
    }}

    .user-name {{
    color: #0f172a;
    font-weight: 750;
    }}

    .user-institution {{
    margin-top: 0.15rem;
    color: #94a3b8;
    font-size: 0.68rem;
    }}

    .provider-list {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    }}

    .provider-pill {{
    display: inline-flex;
    align-items: center;
    min-height: 23px;
    padding: 0 0.45rem;
    border-radius: 999px;
    font-size: 0.63rem;
    font-weight: 800;
    }}

    .provider-pill.github {{
    background: #f1f5f9;
    color: #334155;
    }}

    .provider-pill.orcid {{
    background: #f0fdf4;
    color: #15803d;
    }}

    .provider-pill.password {{
    background: #eff6ff;
    color: #1d4ed8;
    }}

    .presence {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: #64748b;
    font-size: 0.7rem;
    font-weight: 700;
    }}

    .presence span {{
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #cbd5e1;
    }}

    .presence.active {{
    color: #15803d;
    }}

    .presence.active span {{
    background: #22c55e;
    }}

    .table-empty {{
    padding: 2.5rem;
    color: #64748b;
    font-size: 0.82rem;
    text-align: center;
    }}

    .detail-breadcrumb {{
    margin-bottom: 1.2rem;
    }}

    .detail-breadcrumb a,
    .table-link {{
    color: #2563eb;
    font-size: 0.78rem;
    font-weight: 700;
    text-decoration: none;
    }}

    .user-profile-header {{
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.5rem;
    }}

    .large-avatar {{
    width: 58px;
    height: 58px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 1.2rem;
    font-weight: 850;
    }}

    .detail-grid {{
    display: grid;
    grid-template-columns:
        minmax(0, 2fr)
        minmax(260px, 1fr);
    gap: 1rem;
    }}

    .detail-list {{
    display: grid;
    }}

    .detail-row {{
    min-height: 52px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #f1f5f9;
    color: #64748b;
    font-size: 0.76rem;
    }}

    .detail-row:last-child {{
    border-bottom: 0;
    }}

    .detail-row strong {{
    color: #334155;
    font-weight: 700;
    text-align: right;
    }}

    .detail-primary {{
    color: #0f172a;
    font-weight: 750;
    }}

    .detail-secondary {{
    margin-top: 0.15rem;
    color: #64748b;
    font-size: 0.7rem;
    }}

    .small-button {{
    display: inline-flex;
    align-items: center;
    min-height: 30px;
    padding: 0 0.65rem;
    border: 1px solid #bfdbfe;
    border-radius: 7px;
    background: #eff6ff;
    color: #1d4ed8;
    font-size: 0.68rem;
    font-weight: 750;
    text-decoration: none;
    }}

    .panel-empty {{
    padding: 2rem 1rem;
    color: #94a3b8;
    font-size: 0.78rem;
    text-align: center;
    }}

    .mono-box {{
    margin: 1rem;
    padding: 0.75rem;
    border-radius: 8px;
    background: #f8fafc;
    color: #475569;
    font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        Monaco,
        Consolas,
        monospace;
    font-size: 0.7rem;
    word-break: break-all;
    }}

    .placeholder-state {{
    min-height: 360px;
    display: grid;
    place-items: center;
    align-content: center;
    padding: 3rem;
    text-align: center;
    }}

    .placeholder-icon {{
    width: 54px;
    height: 54px;
    display: grid;
    place-items: center;
    margin-bottom: 1rem;
    border-radius: 14px;
    background: #eff6ff;
    color: #2563eb;
    font-size: 1.45rem;
    font-weight: 800;
    }}

    .placeholder-state h2 {{
    margin: 0 0 0.45rem;
    font-size: 1.1rem;
    }}

    .placeholder-state p {{
    width: min(100%, 470px);
    margin: 0;
    color: #64748b;
    font-size: 0.82rem;
    line-height: 1.55;
    }}

    @media (max-width: 900px) {{
    .detail-grid {{
        grid-template-columns: 1fr;
    }}
    }}

    @media (max-width: 1050px) {{
    .metric-grid {{
        grid-template-columns:
        repeat(
            2,
            minmax(0, 1fr)
        );
    }}
    }}

    .health-ok {{
      color: #15803d;
      font-size: 0.72rem;
      font-weight: 750;
    }}

    .health-muted {{
      color: #94a3b8;
      font-size: 0.72rem;
      font-weight: 700;
    }}

    .provider-mode {{
      display: inline-flex;
      margin-left: 0.4rem;
      padding: 0.18rem 0.38rem;
      border-radius: 999px;
      background: #fef3c7;
      color: #92400e;
      font-size: 0.58rem;
      font-weight: 800;
    }}

    .diagnostic-status {{
      font-size: 0.72rem;
      font-weight: 750;
    }}

    .diagnostic-status.healthy,
    .diagnostic-status.configured {{
      color: #15803d;
    }}

    .diagnostic-status.failed {{
      color: #dc2626;
    }}

    .diagnostic-status.unknown {{
      color: #d97706;
    }}

    .diagnostic-status.disabled {{
      color: #94a3b8;
    }}

    @media (max-width: 760px) {{
      .control-shell {{
        grid-template-columns: 1fr;
      }}

      .control-sidebar {{
        display: none;
      }}

      .control-content {{
        padding: 1.25rem;
      }}

      .metric-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>

<body>
  <div class="control-shell">

    <aside class="control-sidebar">

      <a
        class="control-brand"
        href="/index.html"
      >
        Cryo<span>Stack</span>
      </a>

      <div class="control-subtitle">
        Control Center
      </div>

      <nav class="control-nav">

        {nav_item(
            "Dashboard",
            "/control/",
            "dashboard",
        )}

        {nav_item(
            "Users",
            "/control/users",
            "users",
        )}

        {nav_item(
            "Experiments",
            "/control/experiments",
            "experiments",
        )}

        <div class="nav-section">
          Compute
        </div>

        {nav_item(
            "HPC",
            "/control/hpc",
            "hpc",
        )}

        {nav_item(
            "Cloud",
            "/control/cloud",
            "cloud",
        )}

        <div class="nav-section">
          Platform
        </div>

        {nav_item(
            "Authentication",
            "/control/authentication",
            "authentication",
        )}

        {nav_item(
            "Analytics",
            "/control/analytics",
            "analytics",
        )}

        {nav_item(
            "Diagnostics",
            "/control/diagnostics",
            "diagnostics",
        )}

        {nav_item(
            "Settings",
            "/control/settings",
            "settings",
        )}

      </nav>

    </aside>

    <main class="control-main">

      <header class="control-header">

        <div class="control-header-title">
          {escape(title)}
        </div>

        <a href="/index.html">
          Return to CryoStack
        </a>

      </header>

      <section class="control-content">
        {content}
      </section>

    </main>

  </div>
</body>
</html>
"""


def dashboard_page(
    *,
    data: dict,
) -> str:

    users = data["users"]
    experiments = data["experiments"]
    resources = data["resources"]
    applications = data["applications"]

    content = f"""
    <h1>Platform Overview</h1>

    <p class="page-subtitle">
      Operational status and activity across CryoStack.
    </p>

    <div class="metric-grid">

      <div class="metric-card">
        <div class="metric-label">
          Users
        </div>

        <div class="metric-value">
          {users["total"]}
        </div>

        <div class="metric-detail">
          {users["active_sessions"]} active sessions
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          Experiments
        </div>

        <div class="metric-value">
          {experiments["total"]}
        </div>

        <div class="metric-detail">
          {experiments["running"]} running
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          GitHub
        </div>

        <div class="metric-value">
          {users["github"]}
        </div>

        <div class="metric-detail">
          linked identities
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          ORCID
        </div>

        <div class="metric-value">
          {users["orcid"]}
        </div>

        <div class="metric-detail">
          linked identities
        </div>
      </div>

    </div>

    <div class="panel">

      <div class="panel-header">
        Experiment Status
      </div>

      <table>
        <thead>
          <tr>
            <th>Running</th>
            <th>Queued</th>
            <th>Completed</th>
            <th>Failed</th>
            <th>Cancelled</th>
          </tr>
        </thead>

        <tbody>
          <tr>
            <td>{experiments["running"]}</td>
            <td>{experiments["queued"]}</td>
            <td>{experiments["completed"]}</td>
            <td>{experiments["failed"]}</td>
            <td>{experiments["cancelled"]}</td>
          </tr>
        </tbody>
      </table>

    </div>

    <div class="panel">

      <div class="panel-header">
        Applications
      </div>

      <table>
        <thead>
          <tr>
            <th>CryoLauncher</th>
            <th>ICESEE</th>
            <th>LIVIST</th>
          </tr>
        </thead>

        <tbody>
          <tr>
            <td>{applications.get("cryolauncher", 0)}</td>
            <td>{applications.get("icesee", 0)}</td>
            <td>{applications.get("livist", 0)}</td>
          </tr>
        </tbody>
      </table>

    </div>

    <div class="panel">

      <div class="panel-header">
        Platform Resources
      </div>

      <table>
        <thead>
          <tr>
            <th>Configurations</th>
            <th>Workspaces</th>
            <th>Experiment Events</th>
          </tr>
        </thead>

        <tbody>
          <tr>
            <td>{resources["configurations"]}</td>
            <td>{resources["workspaces"]}</td>
            <td>{resources["events"]}</td>
          </tr>
        </tbody>
      </table>

    </div>
    """

    return control_layout(
        title="Dashboard",
        active="dashboard",
        content=content,
    )


def users_page(
    *,
    users: list[dict],
) -> str:

    rows = []

    for user in users:

        identities = user.get(
            "identities",
            {},
        )

        github = identities.get(
            "github"
        )

        orcid = identities.get(
            "orcid"
        )

        identity_parts = []

        if github:
            identity_parts.append(
                """
                <span class="provider-pill github">
                  GitHub
                </span>
                """
            )

        if orcid:
            identity_parts.append(
                """
                <span class="provider-pill orcid">
                  ORCID
                </span>
                """
            )

        if not identity_parts:
            identity_parts.append(
                """
                <span class="provider-pill password">
                  Password
                </span>
                """
            )

        is_active = (
            user["active_sessions"] > 0
        )

        rows.append(
            f"""
            <tr
              class="user-row"
              data-user-search="
                {escape(user["display_name"])}
                {escape(user["email"])}
                {escape(user["institution"] or "")}
              "
              onclick="
                window.location.href=
                '/control/users/{escape(user["id"])}'
              "
            >

              <td>
                <div class="user-cell">

                  <div class="user-avatar">
                    {
                        escape(
                            user["display_name"][0]
                            .upper()
                        )
                        if user["display_name"]
                        else "?"
                    }
                  </div>

                  <div>
                    <div class="user-name">
                      {escape(user["display_name"])}
                    </div>

                    <div class="user-institution">
                      {
                          escape(
                              user["institution"]
                              or "No institution"
                          )
                      }
                    </div>
                  </div>

                </div>
              </td>

              <td>
                {escape(user["email"])}
              </td>

              <td>
                <div class="provider-list">
                  {''.join(identity_parts)}
                </div>
              </td>

              <td>
                {user["experiments"]}
              </td>

              <td>
                {user["configurations"]}
              </td>

              <td>
                {
                    f'''
                    <span class="presence active">
                      <span></span>
                      Active
                    </span>
                    '''
                    if is_active
                    else '''
                    <span class="presence">
                      <span></span>
                      Offline
                    </span>
                    '''
                }
              </td>

              <td>
                {
                    _date(user["last_seen_at"])
                    if user["last_seen_at"]
                    else "Never"
                }
              </td>

            </tr>
            """
        )

    content = f"""
    <div class="page-heading-row">

      <div>
        <h1>Users</h1>

        <p class="page-subtitle">
          Registered accounts, identities and platform activity.
        </p>
      </div>

      <div class="page-count">
        {len(users)} users
      </div>

    </div>

    <div class="user-toolbar">

      <div class="search-box">
        <span>⌕</span>

        <input
          id="user-search"
          type="search"
          placeholder="
            Search users by name, email or institution
          "
          autocomplete="off"
        >
      </div>

    </div>

    <div class="panel user-table-panel">

      <table>

        <thead>
          <tr>
            <th>User</th>
            <th>Email</th>
            <th>Identity</th>
            <th>Experiments</th>
            <th>Configs</th>
            <th>Status</th>
            <th>Last Seen</th>
          </tr>
        </thead>

        <tbody id="users-table-body">
          {''.join(rows)}
        </tbody>

      </table>

      <div
        id="user-search-empty"
        class="table-empty"
        hidden
      >
        No users match your search.
      </div>

    </div>

    <script>
      (() => {{
        const input =
          document.getElementById(
            "user-search"
          );

        const rows = [
          ...document.querySelectorAll(
            ".user-row"
          )
        ];

        const empty =
          document.getElementById(
            "user-search-empty"
          );

        input?.addEventListener(
          "input",
          () => {{

            const query =
              input.value
              .trim()
              .toLowerCase();

            let visible = 0;

            for (const row of rows) {{

              const haystack = (
                row.dataset.userSearch || ""
              ).toLowerCase();

              const show =
                !query ||
                haystack.includes(query);

              row.hidden = !show;

              if (show) {{
                visible += 1;
              }}
            }}

            if (empty) {{
              empty.hidden =
                visible !== 0;
            }}
          }}
        );
      }})();
    </script>
    """

    return control_layout(
        title="Users",
        active="users",
        content=content,
    )

def experiments_page(
    *,
    experiments: list[dict],
) -> str:

    rows = []

    for experiment in experiments:

        rows.append(
            f"""
            <tr>

              <td>
                <strong>
                  {escape(experiment["name"])}
                </strong>
              </td>

              <td>
                {escape(experiment["application"])}
              </td>

              <td>
                {escape(experiment["user_name"])}
              </td>

              <td>
                {escape(experiment["backend"])}
              </td>

              <td>
                <span class="status-pill">
                  {escape(experiment["status"])}
                </span>
              </td>

              <td>
                {escape(experiment["job_id"] or "—")}
              </td>

              <td>
                {escape(experiment["cluster"] or "—")}
              </td>

              <td>
                {_date(experiment["created_at"])}
              </td>

            </tr>
            """
        )

    content = f"""
    <h1>Experiments</h1>

    <p class="page-subtitle">
      Experiments across CryoLauncher, ICESEE,
      local, HPC, and cloud backends.
    </p>

    <div class="panel">

      <table>

        <thead>
          <tr>
            <th>Name</th>
            <th>Application</th>
            <th>User</th>
            <th>Backend</th>
            <th>Status</th>
            <th>Job</th>
            <th>Cluster</th>
            <th>Created</th>
          </tr>
        </thead>

        <tbody>
          {''.join(rows)}
        </tbody>

      </table>

    </div>
    """

    return control_layout(
        title="Experiments",
        active="experiments",
        content=content,
    )

def user_detail_page(
    *,
    user: dict,
) -> str:

    identities = user.get(
        "identities",
        [],
    )

    sessions = user.get(
        "sessions_detail",
        [],
    )

    experiments = user.get(
        "recent_experiments",
        [],
    )

    configurations = user.get(
        "recent_configurations",
        [],
    )

    identity_rows = []

    for identity in identities:

        provider = (
            identity["provider"]
            .strip()
            .title()
        )

        identifier = (
            identity.get(
                "provider_username"
            )
            or identity.get(
                "provider_subject"
            )
            or "Connected"
        )

        profile_url = identity.get(
            "provider_profile_url"
        )

        identity_rows.append(
            f"""
            <div class="detail-row">

              <div>
                <div class="detail-primary">
                  {escape(provider)}
                </div>

                <div class="detail-secondary">
                  {escape(identifier)}
                </div>
              </div>

              {
                  f'''
                  <a
                    class="small-button"
                    href="{escape(profile_url)}"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    View profile
                  </a>
                  '''
                  if profile_url
                  else ""
              }

            </div>
            """
        )

    session_rows = []

    for session in sessions[:8]:

        session_rows.append(
            f"""
            <tr>
              <td>
                <code>
                  {escape(session["id"][:12])}…
                </code>
              </td>

              <td>
                {_date(session["last_seen_at"])}
              </td>

              <td>
                {
                    '<span class="presence active">'
                    '<span></span>Active</span>'
                    if session["active"]
                    else '<span class="presence">'
                         '<span></span>Expired</span>'
                }
              </td>

              <td>
                {_date(session["expires_at"])}
              </td>
            </tr>
            """
        )

    experiment_rows = []

    for experiment in experiments:

        experiment_rows.append(
            f"""
            <tr>
              <td>
                <a
                  class="table-link"
                  href="/experiments/{escape(experiment["id"])}"
                >
                  {escape(experiment["name"])}
                </a>
              </td>

              <td>
                {escape(experiment["application"])}
              </td>

              <td>
                {escape(experiment["backend"])}
              </td>

              <td>
                <span class="status-pill">
                  {escape(experiment["status"])}
                </span>
              </td>

              <td>
                {_date(experiment["created_at"])}
              </td>
            </tr>
            """
        )

    content = f"""
    <div class="detail-breadcrumb">
      <a href="/control/users">
        ← Users
      </a>
    </div>

    <div class="user-profile-header">

      <div class="large-avatar">
        {
            escape(
                user["display_name"][0].upper()
            )
            if user["display_name"]
            else "?"
        }
      </div>

      <div>
        <h1>
          {escape(user["display_name"])}
        </h1>

        <p class="page-subtitle">
          {escape(user["email"])}
        </p>
      </div>

    </div>

    <div class="metric-grid">

      <div class="metric-card">
        <div class="metric-label">
          Experiments
        </div>

        <div class="metric-value">
          {user["experiment_count"]}
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          Configurations
        </div>

        <div class="metric-value">
          {user["configuration_count"]}
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          Workspaces
        </div>

        <div class="metric-value">
          {user["workspace_count"]}
        </div>
      </div>

      <div class="metric-card">
        <div class="metric-label">
          Sessions
        </div>

        <div class="metric-value">
          {user["session_count"]}
        </div>
      </div>

    </div>

    <div class="detail-grid">

      <section>

        <div class="panel">
          <div class="panel-header">
            Account
          </div>

          <div class="detail-list">

            <div class="detail-row">
              <span>Email</span>
              <strong>
                {escape(user["email"])}
              </strong>
            </div>

            <div class="detail-row">
              <span>Institution</span>
              <strong>
                {escape(user["institution"] or "—")}
              </strong>
            </div>

            <div class="detail-row">
              <span>Research role</span>
              <strong>
                {escape(user["research_role"] or "—")}
              </strong>
            </div>

            <div class="detail-row">
              <span>Country</span>
              <strong>
                {escape(user["country"] or "—")}
              </strong>
            </div>

            <div class="detail-row">
              <span>Default application</span>
              <strong>
                {
                    escape(
                        user["default_application"]
                        or "—"
                    )
                }
              </strong>
            </div>

            <div class="detail-row">
              <span>Registered</span>
              <strong>
                {_date(user["created_at"])}
              </strong>
            </div>

          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            Recent Experiments
          </div>

          {
              f'''
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Application</th>
                    <th>Backend</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(experiment_rows)}
                </tbody>
              </table>
              '''
              if experiment_rows
              else '''
              <div class="panel-empty">
                No experiments for this user.
              </div>
              '''
          }
        </div>

        <div class="panel">
          <div class="panel-header">
            Sessions
          </div>

          {
              f'''
              <table>
                <thead>
                  <tr>
                    <th>Session</th>
                    <th>Last Seen</th>
                    <th>Status</th>
                    <th>Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(session_rows)}
                </tbody>
              </table>
              '''
              if session_rows
              else '''
              <div class="panel-empty">
                No sessions recorded.
              </div>
              '''
          }
        </div>

      </section>

      <aside>

        <div class="panel">
          <div class="panel-header">
            Linked Identities
          </div>

          <div class="detail-list">
            {
                ''.join(identity_rows)
                if identity_rows
                else '''
                <div class="panel-empty">
                  No external identities linked.
                </div>
                '''
            }
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            User ID
          </div>

          <div class="mono-box">
            {escape(user["id"])}
          </div>
        </div>

      </aside>

    </div>
    """

    return control_layout(
        title=user["display_name"],
        active="users",
        content=content,
    )

def placeholder_page(
    *,
    title: str,
    active: str,
    description: str,
    badge: str = "Coming next",
) -> str:

    content = f"""
    <div class="page-heading-row">

      <div>
        <h1>{escape(title)}</h1>

        <p class="page-subtitle">
          {escape(description)}
        </p>
      </div>

      <div class="page-count">
        {escape(badge)}
      </div>

    </div>

    <div class="panel">

      <div class="placeholder-state">

        <div class="placeholder-icon">
          ◇
        </div>

        <h2>
          {escape(title)}
        </h2>

        <p>
          This Control Center module is connected
          and ready for its operational services.
        </p>

      </div>

    </div>
    """

    return control_layout(
        title=title,
        active=active,
        content=content,
    )

def authentication_page(
    *,
    data: dict,
) -> str:

    providers = data["providers"]
    identities = data["identities"]

    provider_rows = []

    labels = {
        "password": "Email / Password",
        "github": "GitHub",
        "orcid": "ORCID",
        "google": "Google",
        "university_sso": "University SSO",
    }

    for key, provider in providers.items():

        configured = provider[
            "configured"
        ]

        extra = ""

        if (
            key == "orcid"
            and provider.get("sandbox")
        ):
            extra = (
                '<span class="provider-mode">'
                'Sandbox'
                '</span>'
            )

        provider_rows.append(
            f"""
            <tr>
              <td>
                <strong>
                  {escape(labels.get(key, key.title()))}
                </strong>
                {extra}
              </td>

              <td>
                {
                    '<span class="health-ok">● Configured</span>'
                    if configured
                    else '<span class="health-muted">● Not configured</span>'
                }
              </td>

              <td>
                {provider["linked"]}
              </td>
            </tr>
            """
        )

    identity_rows = []

    for identity in identities:

        identity_rows.append(
            f"""
            <tr>

              <td>
                {escape(
                    identity["provider"].title()
                )}
              </td>

              <td>
                <a
                  class="table-link"
                  href="/control/users/{escape(identity["user_id"])}"
                >
                  {escape(identity["user_name"])}
                </a>
              </td>

              <td>
                {
                    escape(
                        identity["provider_username"]
                        or identity["provider_subject"]
                        or "—"
                    )
                }
              </td>

              <td>
                {
                    escape(
                        identity["provider_email"]
                        or "—"
                    )
                }
              </td>

              <td>
                {_date(identity["created_at"])}
              </td>

            </tr>
            """
        )

    content = f"""
    <div class="page-heading-row">

      <div>
        <h1>Authentication</h1>

        <p class="page-subtitle">
          Identity providers, account links and
          authentication configuration.
        </p>
      </div>

      <div class="page-count">
        {len(identities)} linked identities
      </div>

    </div>

    <div class="panel">

      <div class="panel-header">
        Identity Providers
      </div>

      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>Status</th>
            <th>Linked Accounts</th>
          </tr>
        </thead>

        <tbody>
          {''.join(provider_rows)}
        </tbody>
      </table>

    </div>

    <div class="panel">

      <div class="panel-header">
        Linked External Identities
      </div>

      <table>
        <thead>
          <tr>
            <th>Provider</th>
            <th>CryoStack User</th>
            <th>Username / Identifier</th>
            <th>Provider Email</th>
            <th>Linked</th>
          </tr>
        </thead>

        <tbody>
          {''.join(identity_rows)}
        </tbody>
      </table>

    </div>

    <div class="metric-grid">

      <div class="metric-card">
        <div class="metric-label">
          OAuth Transactions
        </div>

        <div class="metric-value">
          {data["oauth_flows"]}
        </div>

        <div class="metric-detail">
          currently stored OAuth flows
        </div>
      </div>

    </div>
    """

    return control_layout(
        title="Authentication",
        active="authentication",
        content=content,
    )

def diagnostics_page(
    *,
    data: dict,
) -> str:

    rows = []

    labels = {
        "healthy": "Healthy",
        "configured": "Configured",
        "disabled": "Disabled",
        "unknown": "Unknown",
        "failed": "Failed",
    }

    for check in data["checks"]:

        status = check["status"]

        rows.append(
            f"""
            <tr>

              <td>
                <strong>
                  {escape(check["name"])}
                </strong>
              </td>

              <td>
                <span class="diagnostic-status {escape(status)}">
                  ●
                  {escape(labels.get(status, status.title()))}
                </span>
              </td>

              <td>
                {escape(check["detail"])}
              </td>

            </tr>
            """
        )

    content = f"""
    <h1>Diagnostics</h1>

    <p class="page-subtitle">
      Operational health of CryoStack platform services.
    </p>

    <div class="panel">

      <div class="panel-header">
        Service Health
      </div>

      <table>

        <thead>
          <tr>
            <th>Service</th>
            <th>Status</th>
            <th>Details</th>
          </tr>
        </thead>

        <tbody>
          {''.join(rows)}
        </tbody>

      </table>

    </div>
    """

    return control_layout(
        title="Diagnostics",
        active="diagnostics",
        content=content,
    )