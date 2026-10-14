"""HTML for the Control Center compute pages (HPC, Cloud, Experiments)."""

from __future__ import annotations

from html import escape

from .templates import (
    _date,
    control_layout,
)


STYLE = """
<style>
  [hidden] { display: none !important; }

  .status-pill.ok { background: #dcfce7; color: #166534; }
  .status-pill.warn { background: #fef3c7; color: #92400e; }
  .status-pill.bad { background: #fee2e2; color: #991b1b; }
  .status-pill.info { background: #eff6ff; color: #1d4ed8; }
  .status-pill.muted { background: #f1f5f9; color: #64748b; }

  .cc-table-wrap { width: 100%; overflow-x: auto; }
  .cc-table-wrap table { min-width: 640px; }

  .cc-body { padding: 1rem 1.1rem; }
  .cc-body > * + * { margin-top: 0.85rem; }

  .cc-resource + .cc-resource { border-top: 1px solid #e2e8f0; }
  .cc-resource h3 {
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
    margin: 0 0 0.75rem; font-size: 1rem;
  }
  .cc-resource h3 small { color: #64748b; font-size: 0.72rem; font-weight: 650; }

  .cc-kv {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem 1.25rem; margin: 0;
  }
  .cc-kv.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cc-kv div { min-width: 0; }
  .cc-kv dt {
    color: #94a3b8; font-size: 0.67rem; font-weight: 800;
    letter-spacing: 0.05em; text-transform: uppercase;
  }
  .cc-kv dd {
    margin: 0.2rem 0 0; color: #0f172a; font-size: 0.82rem; font-weight: 600;
    overflow-wrap: anywhere;
  }
  .cc-kv dd .cc-muted { font-weight: 500; }

  .cc-muted { color: #94a3b8; }
  .cc-mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.74rem; overflow-wrap: anywhere;
  }
  .cc-error { color: #991b1b; font-size: 0.76rem; overflow-wrap: anywhere; }

  .cc-notice {
    margin: 0; padding: 0.7rem 0.9rem; border-radius: 10px;
    border: 1px solid #bfdbfe; border-left: 4px solid #2563eb;
    background: #eff6ff; color: #1e3a8a; font-size: 0.8rem; line-height: 1.5;
  }
  .cc-notice.warn {
    border-color: #fde68a; border-left-color: #d97706;
    background: #fffbeb; color: #78350f;
  }

  .cc-split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
  .cc-split .panel { margin-bottom: 0; }
  .cc-split + .panel, .cc-split + .cc-split { margin-top: 1rem; }
  .cc-list { margin: 0; padding-left: 1.1rem; color: #334155; font-size: 0.8rem; line-height: 1.7; }

  .cc-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
  .cc-btn {
    display: inline-flex; align-items: center; justify-content: center;
    min-height: 34px; padding: 0 0.8rem;
    border: 1px solid #2563eb; border-radius: 8px;
    background: #2563eb; color: #ffffff;
    font: inherit; font-size: 0.78rem; font-weight: 700; cursor: pointer;
  }
  .cc-btn.secondary { border-color: #cbd5e1; background: #ffffff; color: #334155; }
  .cc-btn:disabled { opacity: 0.55; cursor: not-allowed; }
  .cc-btn:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }

  .cc-log-form { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; }
  .cc-log-form label {
    display: grid; gap: 0.25rem; color: #64748b; font-size: 0.7rem; font-weight: 750;
  }
  .cc-log-form select {
    min-height: 34px; padding: 0 0.5rem; border: 1px solid #cbd5e1;
    border-radius: 8px; background: #ffffff; color: #0f172a; font: inherit; font-size: 0.8rem;
  }
  .cc-log {
    margin: 0; max-height: 420px; overflow: auto; padding: 0.85rem 1rem;
    border-radius: 10px; background: #0f172a; color: #e2e8f0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.72rem; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere;
  }

  .cc-statements { display: grid; gap: 0.4rem; margin: 0; padding: 0; list-style: none; }
  .cc-statements li { font-size: 0.78rem; color: #334155; }
  .cc-statements strong { color: #0f172a; }

  .cc-stale { display: block; margin-top: 0.3rem; }
  .detail-grid > * { min-width: 0; }
  .detail-grid pre { max-width: 100%; overflow-x: auto; }
  .timeline-heading { flex-wrap: wrap; }
  .cc-run-facts { color: #475569; font-size: 0.74rem; margin-top: 0.15rem; }
  .cc-failure { border-left: 4px solid #dc2626; }
  .cc-failure .cc-log { max-height: 260px; }

  @media (max-width: 1050px) {
    .cc-kv { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  @media (max-width: 760px) {
    .cc-kv, .cc-kv.two, .cc-split { grid-template-columns: 1fr; }
    .cc-log-form { align-items: stretch; }
    .cc-log-form label, .cc-log-form select { width: 100%; }
  }
</style>
"""


_STATUS_TONE = {
    "completed": "ok",
    "healthy": "ok",
    "running": "info",
    "preparing": "info",
    "queued": "muted",
    "cancelled": "muted",
    "failed": "bad",
    "disabled": "muted",
    "requires_session": "warn",
}

_STATUS_LABEL = {
    "requires_session": "Requires a connected session",
    "healthy": "Reachable",
    "failed": "Failed",
    "disabled": "Not configured",
}


def _pill(
    status: str,
    label: str | None = None,
) -> str:

    tone = _STATUS_TONE.get(status, "muted")

    text = label or _STATUS_LABEL.get(
        status,
        (status or "unknown").replace("_", " ").title(),
    )

    return (
        f'<span class="status-pill {tone}">'
        f"{escape(text)}</span>"
    )


def _yes_no(
    value: bool,
    *,
    yes: str = "Yes",
    no: str = "No",
) -> str:

    return escape(yes if value else no)


def _value(
    value,
    *,
    empty: str = "Not set",
) -> str:

    if value in (None, "", [], ()):
        return f'<span class="cc-muted">{escape(empty)}</span>'

    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value)

    return escape(str(value))


def _kv(
    items: list[tuple[str, str]],
    *,
    columns: str = "",
) -> str:

    cells = "".join(
        f"<div><dt>{escape(label)}</dt><dd>{html}</dd></div>"
        for label, html in items
    )

    return f'<dl class="cc-kv {columns}">{cells}</dl>'


def _duration(
    seconds: int | None,
) -> str:

    if seconds is None:
        return "—"

    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)

    if hours:
        return f"{hours}h {minutes:02d}m"

    if minutes:
        return f"{minutes}m {secs:02d}s"

    return f"{secs}s"


def _metrics(
    summary: dict,
    *,
    first_label: str,
    first_value,
    first_detail: str,
) -> str:

    rate = summary.get("failure_rate")

    cards = [
        (first_label, first_value, first_detail),
        (
            "Active jobs",
            summary["active"],
            (
                f'{summary["status_unknown"]} with status unknown'
                if summary.get("status_unknown")
                else "Queued, preparing or running"
            ),
        ),
        (
            "Failed",
            summary["failed"],
            (
                f"{rate * 100:.0f}% of finished runs"
                if rate is not None
                else "No finished runs recorded"
            ),
        ),
        ("Completed", summary["completed"], f'{summary["total"]} recorded runs'),
    ]

    return '<div class="metric-grid">' + "".join(
        f"""
        <div class="metric-card">
          <div class="metric-label">{escape(label)}</div>
          <div class="metric-value">{escape(str(value))}</div>
          <div class="metric-detail">{escape(detail)}</div>
        </div>
        """
        for label, value, detail in cards
    ) + "</div>"


def _resources_text(
    resources: dict,
) -> str:

    if not resources:
        return '<span class="cc-muted">Not recorded</span>'

    return "<br>".join(
        f'<span class="cc-muted">{escape(key.replace("_", " "))}</span> '
        f"{escape(str(value))}"
        for key, value in resources.items()
    )


def _status_cell(
    item: dict,
) -> str:

    html = _pill(item["status"])

    since = item.get("status_unknown_since")

    if since:
        html += (
            '<span class="status-pill warn cc-stale" '
            'title="No update from the application that owns this run">'
            f"Status unknown since {escape(_date(since))}</span>"
        )

    if item.get("exit_code") not in (None, ""):
        html += (
            f'<div class="cc-muted">exit {escape(str(item["exit_code"]))}</div>'
        )

    return html


def _run_facts(
    overview: dict | None,
) -> str:
    """``EnKF · ensemble 30 · 2 nodes · 64 MPI ranks`` from a record."""

    overview = overview or {}
    requested = overview.get("requested") or {}

    facts = []

    if overview.get("filter"):
        facts.append(str(overview["filter"]))

    if overview.get("ensemble_size"):
        facts.append(f'ensemble {overview["ensemble_size"]}')

    if requested.get("nodes"):
        nodes = requested["nodes"]
        facts.append(f"{nodes} node{'s' if nodes != 1 else ''}")

    if requested.get("mpi_ranks"):
        facts.append(f'{requested["mpi_ranks"]} MPI ranks')

    if requested.get("vcpu"):
        facts.append(f'{requested["vcpu"]} vCPU')

    if not facts:
        return ""

    return (
        '<div class="cc-run-facts">'
        + escape(" · ".join(facts))
        + "</div>"
    )


def _execution_table(
    items: list[dict],
    *,
    empty: str,
    show_error: bool = False,
) -> str:

    if not items:
        return f'<p class="panel-empty">{escape(empty)}</p>'

    rows = []

    for item in items:

        error = (
            f'<div class="cc-error">{escape(item["error"])}</div>'
            if show_error and item.get("error")
            else ""
        )

        rows.append(
            f"""
            <tr>
              <td>
                <a class="table-link" href="/control/experiments/{escape(item["id"])}">
                  <strong>{escape(item["name"] or item["application"])}</strong>
                </a>
                <div class="cc-muted">{escape(item["user_name"])} · {escape(item["application"])}</div>
                {_run_facts(item.get("overview"))}
                {error}
              </td>
              <td>{_status_cell(item)}</td>
              <td>
                <div>{_value(item["cluster"] or item["backend"], empty="—")}</div>
                <div class="cc-mono cc-muted">{escape(item["job_id"] or "—")}</div>
              </td>
              <td>{_resources_text(item["resources"])}</td>
              <td>{escape(_duration(item["runtime_seconds"]))}</td>
              <td>{escape(_date(item["created_at"]))}</td>
            </tr>
            """
        )

    return f"""
    <div class="cc-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Target / job</th>
            <th>Requested resources</th>
            <th>Runtime</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def _executions_panels(
    executions: dict,
    *,
    noun: str,
) -> str:

    return f"""
    <section class="panel" id="active-jobs">
      <div class="panel-header">Active {escape(noun)} jobs</div>
      {_execution_table(executions["active"], empty=f"No {noun} jobs are queued or running.")}
    </section>

    <section class="panel" id="failures">
      <div class="panel-header">Recent failures</div>
      {_execution_table(executions["failures"], empty=f"No failed {noun} runs are recorded.", show_error=True)}
    </section>

    <section class="panel" id="recent">
      <div class="panel-header">Recent {escape(noun)} runs</div>
      {_execution_table(executions["recent"], empty=f"No {noun} runs are recorded yet.", show_error=True)}
    </section>
    """


def _log_panel(
    *,
    page: str,
    sources: list[dict],
    excerpt: dict | None,
) -> str:

    if not sources:
        return """
        <section class="panel" id="logs">
          <div class="panel-header">Operational logs</div>
          <p class="panel-empty">No service logs are declared in the deployment registry.</p>
        </section>
        """

    selected = excerpt["source"] if excerpt else sources[0]["key"]
    topic = excerpt["topic"] if excerpt else page
    level = excerpt["level"] if excerpt else "all"
    lines = len(excerpt["lines"]) if excerpt else 0

    source_options = "".join(
        f'<option value="{escape(source["key"])}"'
        f'{" selected" if source["key"] == selected else ""}>'
        f'{escape(source["label"])}'
        f'{"" if source["available"] else " (no log file)"}</option>'
        for source in sources
    )

    topic_options = "".join(
        f'<option value="{value}"{" selected" if value == topic else ""}>{label}</option>'
        for value, label in (
            (page, f"{page.upper()} related"),
            ("all", "All lines"),
        )
    )

    level_options = "".join(
        f'<option value="{value}"{" selected" if value == level else ""}>{label}</option>'
        for value, label in (
            ("all", "All levels"),
            ("errors", "Errors and failures"),
        )
    )

    if excerpt is None:
        body = '<p class="cc-muted">Select a log to view its newest lines.</p>'
    elif not excerpt["available"]:
        body = '<p class="cc-muted">This log file does not exist on this server.</p>'
    elif not excerpt["lines"]:
        body = '<p class="cc-muted">No matching lines in the newest part of this log.</p>'
    else:
        body = (
            '<pre class="cc-log" aria-label="Log excerpt">'
            + escape("\n".join(excerpt["lines"]))
            + "</pre>"
        )

    note = (
        f"Newest {lines} matching lines; secrets, tokens and license servers are redacted."
        if excerpt and excerpt["lines"]
        else "Lines are bounded and redacted before display."
    )

    return f"""
    <section class="panel" id="logs">
      <div class="panel-header">Operational logs</div>
      <div class="cc-body">
        <form class="cc-log-form" method="get" action="/control/{escape(page)}#logs">
          <label>Log
            <select name="log">{source_options}</select>
          </label>
          <label>Show
            <select name="topic">{topic_options}</select>
          </label>
          <label>Level
            <select name="level">{level_options}</select>
          </label>
          <button class="cc-btn secondary" type="submit">Show log</button>
        </form>
        {body}
        <p class="cc-muted" style="margin:0;font-size:0.72rem">{escape(note)}</p>
      </div>
    </section>
    """


def _heading(
    title: str,
    subtitle: str,
) -> str:

    return f"""
    <h1>{escape(title)}</h1>
    <p class="page-subtitle">{escape(subtitle)}</p>
    """


# ============================================================
# HPC
# ============================================================

def _resource_card(
    resource: dict,
) -> str:

    scheduler = resource["scheduler"]
    license_ = resource["matlab_license"]
    software = resource["software_environment"]

    aliases = ", ".join(
        alias for alias in resource["aliases"]
        if alias != resource["name"]
    )

    license_text = (
        f'{_pill("completed", "Configured")} '
        f'<span class="cc-muted">via {escape(license_["environment_variable"])}; value withheld</span>'
        if license_["configured"]
        else _pill("disabled", "Not configured")
    )

    portal = (
        f'{escape(resource["portal_name"] or "Portal")} · '
        f'<span class="cc-mono">{escape(resource["portal_url"])}</span>'
        if resource["portal_url"]
        else '<span class="cc-muted">None</span>'
    )

    return f"""
    <div class="cc-body cc-resource">
      <h3>
        {escape(resource["name"].upper())}
        {f"<small>aliases: {escape(aliases)}</small>" if aliases else ""}
      </h3>
      {_kv([
          ("Login host", f'<span class="cc-mono">{_value(resource["login_host"])}</span>'),
          ("SSH port", escape(str(resource["ssh_port"]))),
          ("VPN / MFA", f'{_yes_no(resource["requires_vpn"], yes="VPN required", no="No VPN")} · '
                        f'{_yes_no(resource["requires_mfa"], yes="MFA required", no="No MFA")}'),
          ("Scheduler", escape(scheduler["type"])),
          ("Default partition / queue", _value(scheduler["default_partition"])),
          ("Default wall time", _value(scheduler["default_wall_time"])),
          ("Allocation required", _yes_no(resource["account_required"])),
          ("Container runtime", escape(resource["container_runtime"])),
          ("Software environment",
           f'{escape(software["name"])} <span class="cc-muted">({escape(", ".join(software["models"]))})</span>'),
          ("Environment modules", _value(resource["modules"], empty="Not declared by profile")),
          ("Access modes", _value(resource["access_modes"])),
          ("Authentication", _value(resource["auth_modes"])),
          ("Key registration", escape(resource["key_registration_method"])),
          ("Registration portal", portal),
          ("Direct SSH trust", escape(resource["direct_ssh_trust"].replace("_", " "))),
          ("MATLAB license", license_text),
          ("Cloud license tunnel", _yes_no(license_["cloud_requires_tunnel"],
                                           yes="Required (via Connector)", no="Not required")),
      ])}
    </div>
    """


_RELAY_SCRIPT = """
<script>
(() => {
  const button = document.getElementById("cc-relay-check");
  if (!button) return;
  const status = document.getElementById("cc-relay-result");
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "Checking…";
    try {
      const response = await fetch("/api/control/hpc/relay-check", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: "{}",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        status.textContent = body.error || ("Check failed (HTTP " + response.status + ").");
      } else {
        const ms = body.latency_ms == null ? "" : " · " + body.latency_ms + " ms";
        status.textContent = (body.status === "healthy" ? "Reachable" : "Not reachable")
          + " — " + (body.detail || "") + ms;
      }
    } catch (error) {
      status.textContent = "Check failed: the Control Center did not answer.";
    } finally {
      button.disabled = false;
    }
  });
})();
</script>
"""


def _relay_row(
    relay: dict,
    *,
    can_operate: bool,
) -> str:

    last = relay.get("last_check")

    if last:
        state = _pill(last["status"])
        detail = (
            f'{escape(last.get("detail") or "")} '
            f'<span class="cc-muted">· checked {escape(_date(last.get("checked_at")))}</span>'
        )
    elif relay.get("configured"):
        state = _pill("queued", "Not checked")
        detail = '<span class="cc-muted">Not checked since the gateway started.</span>'
    else:
        state = _pill("disabled")
        detail = '<span class="cc-muted">No relay URL is configured.</span>'

    if can_operate and relay.get("configured"):
        action = (
            '<div class="cc-actions" style="margin-top:0.5rem">'
            '<button class="cc-btn" id="cc-relay-check" type="button">Run live check</button>'
            '<span id="cc-relay-result" class="cc-muted" role="status" aria-live="polite"></span>'
            "</div>"
        )
    elif relay.get("configured"):
        action = (
            '<div class="cc-muted" style="margin-top:0.4rem">'
            "Live checks require a maintainer, admin or owner role.</div>"
        )
    else:
        action = ""

    return f"""
    <tr>
      <td>
        <strong>Connector relay</strong>
        <div class="cc-mono cc-muted">{escape(relay.get("endpoint") or "—")}</div>
      </td>
      <td>{state}</td>
      <td>{detail}{action}</td>
    </tr>
    """


def hpc_page(
    *,
    data: dict,
    can_operate: bool,
    log_sources: list[dict],
    log_excerpt: dict | None,
) -> str:

    executions = data["executions"]

    checks = "".join(
        f"""
        <tr>
          <td><strong>{escape(check["resource"].upper())}</strong>
            <div class="cc-muted">Slurm scheduler</div></td>
          <td>{_pill(check["status"])}</td>
          <td>{escape(check["detail"])}</td>
        </tr>
        """
        for check in data["scheduler_checks"]
    )

    resources = "".join(
        _resource_card(resource)
        for resource in data["resources"]
    ) or '<p class="panel-empty">No compute profiles are registered.</p>'

    ownership = data["ownership"]

    role_note = (
        "You can view HPC configuration and run allowlisted live checks."
        if can_operate
        else "View-only: live checks require a maintainer, admin or owner role."
    )

    content = (
        STYLE
        + _heading(
            "HPC",
            "Registered HPC resources, scheduler reachability, job execution "
            "and HPC-related service logs.",
        )
        + _metrics(
            executions["summary"],
            first_label="Registered resources",
            first_value=len(data["resources"]),
            first_detail="Compute profiles on this installation",
        )
        + f"""
    <section class="panel" id="resources">
      <div class="panel-header">Registered resources</div>
      {resources}
      <div class="cc-body" style="padding-top:0">
        <p class="cc-notice">Resource facts come from the installation's compute
        profiles (<span class="cc-mono">cryostack_src/resources/profiles.py</span>) and are
        changed by a code release, not from this page. {escape(role_note)}</p>
      </div>
    </section>

    <section class="panel" id="availability">
      <div class="panel-header">Scheduler availability</div>
      <div class="cc-table-wrap">
        <table>
          <thead><tr><th>Target</th><th>Status</th><th>Details</th></tr></thead>
          <tbody>
            {checks}
            {_relay_row(data["relay"], can_operate=can_operate)}
          </tbody>
        </table>
      </div>
    </section>

    <div class="cc-split">
      <section class="panel">
        <div class="panel-header">Installation-wide (shown here)</div>
        <div class="cc-body"><ul class="cc-list">
          {''.join(f"<li>{escape(item)}</li>" for item in ownership["installation"])}
        </ul></div>
      </section>
      <section class="panel">
        <div class="panel-header">Per researcher (never shown)</div>
        <div class="cc-body"><ul class="cc-list">
          {''.join(f"<li>{escape(item)}</li>" for item in ownership["per_user"])}
        </ul></div>
      </section>
    </div>
    <div style="height:1rem"></div>
    """
        + _executions_panels(executions, noun="HPC")
        + _log_panel(page="hpc", sources=log_sources, excerpt=log_excerpt)
        + (_RELAY_SCRIPT if can_operate else "")
    )

    return control_layout(
        title="HPC",
        active="hpc",
        content=content,
    )


# ============================================================
# Cloud
# ============================================================

def _configured(
    flag: bool,
    *,
    yes: str = "Configured",
    no: str = "Not configured",
) -> str:

    return _pill("completed", yes) if flag else _pill("failed", no)


def cloud_page(
    *,
    data: dict,
    can_operate: bool,
    log_sources: list[dict],
    log_excerpt: dict | None,
) -> str:

    platform = data["platform"]
    executions = data["executions"]
    principal = platform["principal"]
    template = platform["template_url"]
    role = platform["execution_role_template"]
    fargate = platform["fargate_default"]
    guard = platform["guardrails"]

    principal_text = _configured(principal["configured"] and principal["valid"])
    if principal["configured"] and not principal["valid"]:
        principal_text = _pill("failed", "Invalid ARN")
    if principal["display"]:
        principal_text += f'<div class="cc-mono">{escape(principal["display"])}</div>'

    template_text = _configured(template["configured"])
    if template["host"]:
        template_text += f'<div class="cc-mono">{escape(template["host"])}</div>'

    deployment = _kv([
        ("Providers", _value(platform["providers"])),
        ("Default region", escape(platform["default_region"])),
        ("Server AWS region", _value(platform["server_region"], empty="Not set")),
        (f'CryoStack principal ({principal["variable"]})', principal_text),
        (f'Quick Create template ({template["variable"]})', template_text),
        ("Supported cloud models", _value([m["model"] for m in platform["models"]])),
    ])

    modes = []
    for mode in platform["compute_modes"]:
        extra = ""
        if mode["mode"] == "ec2":
            extra = (
                f'<div class="cc-muted">Spot queue <span class="cc-mono">{escape(mode["spot_job_queue"])}</span>; '
                f'capacity {escape(", ".join(mode["capacities"]))}; '
                f'accelerator {escape(", ".join(mode["accelerators"]))}; '
                f'topology {escape(", ".join(mode["topologies"]))}; '
                f'instances {escape(", ".join(mode["instance_types"]))}</div>'
            )
        modes.append(f"""
        <tr>
          <td><strong>{escape(mode["mode"].upper())}</strong>
            <div class="cc-muted">{"Default" if mode["default"] else "Advanced, opt-in"}</div></td>
          <td class="cc-mono">{escape(mode["compute_environment"])}</td>
          <td class="cc-mono">{escape(mode["job_queue"])}{extra}</td>
        </tr>""")

    models = "".join(
        f"""
        <tr>
          <td><strong>{escape(model["model"].upper())}</strong></td>
          <td class="cc-mono">{escape(model["job_definition"])}<br>{escape(model["job_definition_ec2"])}</td>
          <td class="cc-mono">{escape(model["ecr_repository"])}</td>
          <td class="cc-mono">{escape(model["log_group"])}</td>
        </tr>"""
        for model in platform["models"]
    )

    shape = _kv([
        ("vCPU", escape(str(fargate["vcpu"]))),
        ("Memory", f'{fargate["memory_mib"] // 1024} GiB'),
        ("Ephemeral storage", f'{fargate["ephemeral_gib"]} GiB'),
        ("Timeout", escape(_duration(fargate["timeout_seconds"]))),
        ("Attempts", escape(str(fargate["attempts"]))),
        ("Platform", f'{escape(fargate["platform_version"])} · {escape(fargate["cpu_architecture"])}'),
        ("Shape valid for Fargate", _configured(fargate["valid"], yes="Valid", no="Invalid")),
        ("Max concurrent vCPUs", escape(str(guard["max_vcpus"]))),
        ("Log retention", f'{guard["log_retention_days"]} days'),
        ("Runs bucket", f'<span class="cc-mono">{escape(guard["runs_bucket_pattern"])}</span>'),
    ])

    licenses = "".join(
        f"<li><strong>{escape(item['resource'].upper())}</strong>: "
        f"{'site license configured' if item['configured'] else 'no site license'}"
        f"{'; cloud runs reach it through the researcher’s Connector' if item['cloud_requires_tunnel'] else ''}"
        f"</li>"
        for item in platform["matlab_license"]
    )

    if role.get("available"):
        sync = role.get("in_sync_with_code")
        sync_pill = (
            _pill("completed", "Matches code")
            if sync
            else _pill("failed", "Differs from code")
            if sync is False
            else _pill("queued", "Not verified")
        )
        statements = "".join(
            f"<li><strong>{escape(s['sid'])}</strong> "
            f"<span class=\"cc-muted\">{escape(s['effect'])}</span> "
            f"<span class=\"cc-mono\">{escape(', '.join(s['actions']))}</span></li>"
            for s in role["statements"]
        )
        role_html = f"""
        <div class="cc-body">
          {_kv([
              ("Template", f'<span class="cc-mono">{escape(role["file"])}</span>'),
              ("Generated template", sync_pill),
              ("Parameters", _value(role["parameters"])),
              ("Session limit", escape(_duration(role.get("max_session_seconds")))),
              ("Statements", escape(str(len(role["statements"])))),
              ("Allowed actions", escape(str(role["action_count"]))),
          ])}
          <details>
            <summary class="cc-muted" style="cursor:pointer;font-size:0.78rem">Show permission statements</summary>
            <ul class="cc-statements" style="margin-top:0.6rem">{statements}</ul>
          </details>
        </div>"""
    else:
        role_html = '<p class="panel-empty">The execution role template is not present.</p>'

    view_note = (
        "Your role may run operational checks, but no cloud setting is editable here."
        if can_operate
        else "View-only access."
    )

    content = (
        STYLE
        + _heading(
            "Cloud",
            "Approved AWS Batch execution configuration, cloud runs, "
            "failures and cloud-related service logs.",
        )
        + _metrics(
            executions["summary"],
            first_label="Cloud models",
            first_value=len(platform["models"]),
            first_detail="Models with a cloud runtime",
        )
        + f"""
    <section class="panel" id="deployment">
      <div class="panel-header">Deployment configuration</div>
      <div class="cc-body">
        {deployment}
        <p class="cc-notice">{escape(data["configuration_changes"]["detail"])} {escape(view_note)}</p>
      </div>
    </section>

    <section class="panel" id="compute">
      <div class="panel-header">Approved compute configurations</div>
      <div class="cc-table-wrap">
        <table>
          <thead><tr><th>Mode</th><th>Compute environment</th><th>Job queue</th></tr></thead>
          <tbody>{''.join(modes)}</tbody>
        </table>
      </div>
      <div class="cc-table-wrap">
        <table>
          <thead><tr><th>Model</th><th>Job definitions</th><th>Image repository</th><th>Log group</th></tr></thead>
          <tbody>{models}</tbody>
        </table>
      </div>
    </section>

    <section class="panel" id="shape">
      <div class="panel-header">Default Fargate job shape and guardrails</div>
      <div class="cc-body">{shape}</div>
    </section>

    <div class="cc-split">
      <section class="panel" id="role">
        <div class="panel-header">Researcher execution role (CloudFormation)</div>
        {role_html}
      </section>
      <section class="panel" id="accounts">
        <div class="panel-header">Researcher AWS accounts and MATLAB licensing</div>
        <div class="cc-body">
          <p class="cc-notice warn">{escape(data["researcher_accounts"]["detail"])}</p>
          <ul class="cc-list">{licenses}</ul>
          <p class="cc-muted" style="margin:0;font-size:0.76rem">ISSM cloud runs read the MATLAB
          license from a Secrets Manager secret in the researcher's own account; CryoStack stores
          only its ARN and never the value.</p>
        </div>
      </section>
    </div>
    <div style="height:1rem"></div>
    """
        + _executions_panels(executions, noun="cloud")
        + _log_panel(page="cloud", sources=log_sources, excerpt=log_excerpt)
    )

    return control_layout(
        title="Cloud",
        active="cloud",
        content=content,
    )


# ============================================================
# Experiments
# ============================================================

_READ_ONLY_NOTE = (
    "Execution records are read-only here. The Control Center does not hold "
    "researchers' SSH or Connector sessions or their AWS roles, so a run is "
    "cancelled or resubmitted from the application that submitted it."
)

_REQUESTED_LABELS = (
    ("nodes", "Nodes"),
    ("mpi_ranks", "MPI ranks (Slurm tasks)"),
    ("tasks_per_node", "Tasks per node"),
    ("time", "Wall time"),
    ("memory", "Memory"),
    ("partition", "Partition"),
    ("vcpu", "vCPU"),
    ("memory_mib", "Memory (MiB)"),
)

_MEASURED_LABELS = (
    ("elapsed_seconds", "Elapsed (s)"),
    ("cpu_seconds", "CPU time (s)"),
    ("max_rss_mib", "Peak memory (MiB)"),
    ("nodes", "Nodes"),
    ("tasks", "Tasks"),
    ("vcpu", "vCPU"),
    ("memory_mib", "Memory (MiB)"),
)


def experiments_page(
    *,
    experiments: list[dict],
) -> str:

    rows = []

    for item in experiments:

        overview = item.get("overview") or {}
        requested = overview.get("requested") or {}

        rows.append(
            f"""
            <tr>
              <td>
                <a class="table-link" href="/control/experiments/{escape(item["id"])}">
                  <strong>{escape(item["name"] or item["application"])}</strong>
                </a>
                <div class="cc-muted">{escape(item["application"])} · {escape(item["backend"])}</div>
                {f'<div class="cc-error">{escape(item["error"])}</div>' if item.get("error") else ""}
              </td>
              <td>{escape(item.get("user_name") or "—")}</td>
              <td>{_status_cell(item)}</td>
              <td>{_value(overview.get("filter"), empty="—")}</td>
              <td>{_value(overview.get("ensemble_size"), empty="—")}</td>
              <td>{_value(requested.get("nodes"), empty="—")}
                  <span class="cc-muted">/</span>
                  {_value(requested.get("mpi_ranks") or requested.get("vcpu"), empty="—")}</td>
              <td>
                <div>{_value(item.get("cluster"), empty="—")}</div>
                <div class="cc-mono cc-muted">{escape(item.get("job_id") or "—")}</div>
              </td>
              <td>{escape(_date(item["created_at"]))}</td>
            </tr>
            """
        )

    body = (
        f"""
        <div class="cc-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>User</th>
                <th>Status</th>
                <th>Filter</th>
                <th>Ensemble</th>
                <th>Nodes / ranks</th>
                <th>Cluster / job</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
        if rows
        else '<p class="panel-empty">No experiments are recorded yet.</p>'
    )

    content = (
        STYLE
        + _heading(
            "Experiments",
            "Experiments across CryoLauncher, ICESEE, local, HPC, and cloud backends.",
        )
        + f"""
    <section class="panel">
      {body}
      <div class="cc-body">
        <p class="cc-notice">{escape(_READ_ONLY_NOTE)} "Status unknown" means the
        record has stopped receiving updates; it is not a failure.</p>
      </div>
    </section>
    """
    )

    return control_layout(
        title="Experiments",
        active="experiments",
        content=content,
    )


def _timeline(
    events: list[dict],
) -> str:

    rows = []

    for event in events:

        label = str(event["event_type"]).replace("_", " ").title()

        meta = "".join(
            f"""
            <div class="timeline-meta-item">
              <span>{escape(str(key).replace("_", " ").title())}</span>
              <strong>{escape(str(value))}</strong>
            </div>
            """
            for key, value in (event.get("metadata") or {}).items()
            if value is not None
        )

        rows.append(
            f"""
            <div class="timeline-event timeline-{escape(str(event["event_type"]))}">
              <div class="timeline-marker"></div>
              <div class="timeline-body">
                <div class="timeline-heading">
                  <strong>{escape(label)}</strong>
                  <span>{escape(_date(event["created_at"]))}</span>
                </div>
                {f'<p>{escape(event["message"])}</p>' if event.get("message") else ""}
                {f'<div class="timeline-metadata">{meta}</div>' if meta else ""}
              </div>
            </div>
            """
        )

    return "".join(rows) or (
        '<div class="panel-empty">No experiment events have been recorded.</div>'
    )


def _failure_panel(
    experiment: dict,
) -> str:

    failure = experiment.get("failure") or {}
    error = experiment.get("error") or ""

    if not failure and not (
        error and experiment.get("status") in {"failed", "cancelled"}
    ):
        return ""

    items = [
        ("Scheduler", _value(
            {"slurm": "Slurm", "aws-batch": "AWS Batch"}.get(
                failure.get("scheduler", ""), failure.get("scheduler")),
            empty="—")),
        ("Scheduler state", _value(failure.get("state"), empty="—")),
        ("Exit code", _value(
            failure.get("exit_code", experiment.get("exit_code")), empty="—")),
        ("Signal", _value(failure.get("signal"), empty="—")),
    ]

    reason = failure.get("reason") or error

    tail = failure.get("log_tail") or []

    log_html = (
        '<pre class="cc-log">' + escape("\n".join(tail)) + "</pre>"
        if tail
        else ""
    )

    return f"""
    <section class="panel cc-failure" id="failure">
      <div class="panel-header">Failure summary</div>
      <div class="cc-body">
        {_kv(items)}
        {f'<p class="cc-error">{escape(reason)}</p>' if reason else ""}
        {log_html}
        <p class="cc-muted" style="margin:0;font-size:0.74rem">Recorded by the
        submitting application; secret-looking text is redacted and the summary is
        bounded. Full logs stay with the run.</p>
      </div>
    </section>
    """


def _resources_panel(
    overview: dict,
) -> str:

    requested = overview.get("requested") or {}
    measured = overview.get("measured")

    requested_items = [
        (label, _value(requested.get(key), empty="—"))
        for key, label in _REQUESTED_LABELS
        if requested.get(key) not in (None, "")
    ]

    requested_html = (
        _kv(requested_items, columns="two")
        if requested_items
        else '<p class="cc-muted" style="margin:0">Not recorded</p>'
    )

    measured_html = (
        _kv(
            [
                (label, _value(measured.get(key), empty="—"))
                for key, label in _MEASURED_LABELS
                if measured.get(key) is not None
            ],
            columns="two",
        )
        if measured
        else (
            '<p class="cc-muted" style="margin:0">Not recorded. Only what the '
            "run reported is shown; nothing is estimated.</p>"
        )
    )

    return f"""
    <div class="cc-split">
      <section class="panel" id="requested">
        <div class="panel-header">Requested resources</div>
        <div class="cc-body">{requested_html}</div>
      </section>
      <section class="panel" id="measured">
        <div class="panel-header">Measured resources</div>
        <div class="cc-body">{measured_html}</div>
      </section>
    </div>
    <div style="height:1rem"></div>
    """


def experiment_detail_page(
    *,
    experiment: dict,
) -> str:

    import json

    overview = experiment.get("overview") or {}

    since = experiment.get("status_unknown_since")

    stale_html = (
        f"""
        <p class="cc-notice warn">Status unknown since {escape(_date(since))}: this
        record has not been updated by the application that owns the run. It has
        not been marked failed. The owner's application updates it the next time it
        checks the job.</p>
        """
        if since
        else ""
    )

    run_items = [
        ("Execution mode", _value(overview.get("execution_mode"), empty="—")),
        ("Model", _value(overview.get("model"), empty="—")),
        ("Example", _value(overview.get("example"), empty="—")),
        ("Preset", _value(overview.get("preset"), empty="—")),
        ("Filter", _value(overview.get("filter"), empty="—")),
        ("Ensemble size", _value(overview.get("ensemble_size"), empty="—")),
    ]

    execution_items = [
        ("Created", escape(_date(experiment.get("created_at")))),
        ("Started", escape(_date(experiment.get("started_at")))),
        ("Finished", escape(_date(experiment.get("finished_at")))),
        ("Last update", escape(_date(experiment.get("updated_at")))),
        ("Working directory", _value(experiment.get("working_directory"), empty="—")),
        ("Output directory", _value(experiment.get("output_directory"), empty="—")),
        ("Log path", _value(experiment.get("log_path"), empty="—")),
        ("Exit code", _value(experiment.get("exit_code"), empty="—")),
    ]

    configuration_text = json.dumps(
        experiment.get("configuration", {}),
        indent=2,
        sort_keys=True,
    )

    metadata_text = json.dumps(
        experiment.get("metadata", {}),
        indent=2,
        sort_keys=True,
    )

    cards = [
        ("User", experiment.get("user_name") or "—"),
        ("Job ID", experiment.get("job_id") or "—"),
        ("Cluster", experiment.get("cluster") or "—"),
        ("Runtime", _duration(experiment.get("runtime_seconds"))),
    ]

    content = (
        STYLE
        + f"""
    <div class="detail-breadcrumb">
      <a href="/control/experiments">← Experiments</a>
    </div>

    <div class="page-heading-row">
      <div>
        <h1>{escape(experiment["name"])}</h1>
        <p class="page-subtitle">{escape(experiment["application"])} · {escape(experiment["backend"])}</p>
      </div>
      <div>{_status_cell({**experiment, "exit_code": None})}</div>
    </div>

    {stale_html}

    <div class="metric-grid">
      {''.join(
          f'''
          <div class="metric-card">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-detail">{escape(str(value))}</div>
          </div>
          '''
          for label, value in cards
      )}
    </div>

    {_failure_panel(experiment)}

    <section class="panel" id="run">
      <div class="panel-header">Run configuration</div>
      <div class="cc-body">{_kv(run_items)}</div>
    </section>

    {_resources_panel(overview)}

    <div class="detail-grid">
      <section>
        <div class="panel">
          <div class="panel-header">Activity Timeline</div>
          <div class="experiment-timeline">{_timeline(experiment.get("events") or [])}</div>
        </div>

        <div class="panel">
          <div class="panel-header">Execution</div>
          <div class="cc-body">{_kv(execution_items, columns="two")}</div>
        </div>

        <div class="panel">
          <div class="panel-header">Configuration Snapshot</div>
          <pre>{escape(configuration_text)}</pre>
        </div>
      </section>

      <aside>
        <div class="panel">
          <div class="panel-header">Experiment</div>
          <div class="cc-body">{_kv([
              ("Application", _value(experiment.get("application"), empty="—")),
              ("Backend", _value(experiment.get("backend"), empty="—")),
              ("Status", _value(experiment.get("status"), empty="—")),
              ("Email", _value(experiment.get("user_email"), empty="—")),
          ], columns="two")}</div>
        </div>

        <div class="panel">
          <div class="panel-header">Metadata</div>
          <pre>{escape(metadata_text)}</pre>
        </div>

        <div class="panel">
          <div class="panel-header">Experiment ID</div>
          <div class="mono-box">{escape(experiment["id"])}</div>
        </div>

        <p class="cc-notice">{escape(_READ_ONLY_NOTE)}</p>
      </aside>
    </div>
    """
    )

    return control_layout(
        title=experiment["name"],
        active="experiments",
        content=content,
    )
