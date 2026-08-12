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

    @media (max-width: 1050px) {{
      .metric-grid {{
        grid-template-columns:
          repeat(
            2,
            minmax(0, 1fr)
          );
      }}
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

        rows.append(
            f"""
            <tr>

              <td>
                <strong>
                  {escape(user["display_name"])}
                </strong>
              </td>

              <td>
                {escape(user["email"])}
              </td>

              <td>
                {
                    escape(
                        github.get(
                            "provider_username",
                            "Connected",
                        )
                    )
                    if github
                    else '<span class="identity-none">—</span>'
                }
              </td>

              <td>
                {
                    escape(
                        orcid.get(
                            "provider_subject",
                            "Connected",
                        )
                    )
                    if orcid
                    else '<span class="identity-none">—</span>'
                }
              </td>

              <td>
                {user["experiments"]}
              </td>

              <td>
                {user["configurations"]}
              </td>

              <td>
                {user["sessions"]}
              </td>

              <td>
                {_date(user["created_at"])}
              </td>

            </tr>
            """
        )

    content = f"""
    <h1>Users</h1>

    <p class="page-subtitle">
      Registered CryoStack accounts and linked identities.
    </p>

    <div class="panel">

      <table>

        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>GitHub</th>
            <th>ORCID</th>
            <th>Experiments</th>
            <th>Configurations</th>
            <th>Sessions</th>
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