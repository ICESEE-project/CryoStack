# control_center/templates_ops.py

"""HTML of the Control Center Analytics, Diagnostics and Settings pages.

Built on the Control Center layout and components (``control_layout``,
``panel``, ``metric-card``, ``status-pill``) and the shared Frozen Legacies
control styles for buttons, notices, forms and tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from icesee_jupyter_book.applications.frozen_legacies.control_style import STYLE

from .templates import control_layout
from .services.diagnostics import human_bytes


_STATUS = {
    "healthy": ("ok", "Healthy"),
    "configured": ("info", "Configured"),
    "degraded": ("warn", "Degraded"),
    "failed": ("bad", "Failed"),
    "unknown": ("warn", "Unknown"),
    "disabled": ("muted", "Disabled"),
}

_JOB_COLORS = {
    "completed": "#16a34a",
    "failed": "#dc2626",
    "cancelled": "#64748b",
    "running": "#2563eb",
    "preparing": "#60a5fa",
    "queued": "#d97706",
}

OPS_STYLE = STYLE + """
.ops-kind { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.22rem 0.5rem;
  border-radius: 999px; font-size: 0.64rem; font-weight: 800; letter-spacing: 0.04em;
  text-transform: uppercase; white-space: nowrap; }
.ops-kind.live { background: #dcfce7; color: #166534; }
.ops-kind.historical { background: #f1f5f9; color: #475569; }
.ops-kind.configuration { background: #eff6ff; color: #1d4ed8; }
.ops-kind.mixed { background: #fef9c3; color: #854d0e; }
.ops-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 0.5rem; padding: 0.9rem 1.1rem; border-bottom: 1px solid #e2e8f0; }
.ops-head h2 { margin: 0; font-size: 0.9rem; font-weight: 750; }
.ops-head small { color: #64748b; font-size: 0.72rem; }
.ops-note { margin: 0; padding: 0.7rem 1.1rem; border-bottom: 1px solid #f1f5f9;
  color: #64748b; font-size: 0.74rem; line-height: 1.5; }
.ops-checks { list-style: none; margin: 0; padding: 0; }
.ops-check { display: grid; grid-template-columns: minmax(0, 15rem) 7rem minmax(0, 1fr) auto;
  gap: 0.35rem 1rem; align-items: start; padding: 0.75rem 1.1rem; border-bottom: 1px solid #f1f5f9;
  font-size: 0.78rem; }
.ops-check:last-child { border-bottom: 0; }
.ops-check strong { color: #0f172a; overflow-wrap: anywhere; }
.ops-check .detail { color: #334155; overflow-wrap: anywhere; }
.ops-check .action { display: block; margin-top: 0.3rem; color: #92400e; font-size: 0.72rem; }
.ops-check .kind { justify-self: end; }
.ops-summary { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0 0 1rem; }
.ops-bars { display: grid; gap: 0.3rem; padding: 0.9rem 1.1rem; }
.ops-bar-row { display: grid; grid-template-columns: 5.5rem minmax(0, 1fr) 3rem; gap: 0.6rem;
  align-items: center; font-size: 0.72rem; color: #475569; }
.ops-bar { display: flex; height: 12px; border-radius: 4px; background: #f1f5f9; overflow: hidden; }
.ops-bar span { display: block; height: 100%; }
.ops-legend { display: flex; flex-wrap: wrap; gap: 0.8rem; padding: 0 1.1rem 0.9rem;
  color: #64748b; font-size: 0.7rem; }
.ops-legend i { display: inline-block; width: 10px; height: 10px; margin-right: 0.3rem;
  border-radius: 2px; vertical-align: -1px; }
.ops-meter { height: 10px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }
.ops-meter span { display: block; height: 100%; background: #2563eb; }
.ops-meter.warn span { background: #d97706; }
.ops-grid-2 .fl-table-wrap table { min-width: 420px; }
.ops-grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.ops-setting { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 22rem); gap: 1rem;
  padding: 1rem 1.1rem; border-bottom: 1px solid #f1f5f9; }
.ops-setting:last-child { border-bottom: 0; }
.ops-setting h3 { margin: 0 0 0.3rem; font-size: 0.86rem; }
.ops-setting p { margin: 0 0 0.5rem; color: #64748b; font-size: 0.76rem; line-height: 1.5; }
.ops-meta { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.ops-value { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; margin-bottom: 0.6rem;
  font-size: 0.8rem; }
.ops-value strong { font-size: 1rem; }
.ops-form { display: grid; gap: 0.5rem; }
.ops-form .fl-field input, .ops-form .fl-field select { min-height: 34px; }
.ops-inline { display: inline; }
.ops-muted { color: #94a3b8; }
@media (max-width: 900px) {
  .ops-grid-2, .ops-setting { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .ops-check { grid-template-columns: minmax(0, 1fr) auto; }
  .ops-check .detail { grid-column: 1 / -1; }
  .ops-check .kind { grid-column: 1 / -1; justify-self: start; }
  .page-heading-row { flex-wrap: wrap; }
}
"""


def _utc(value: float | None, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    if value is None:
        return "—"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime(fmt)


def status_pill(status: str) -> str:
    variant, label = _STATUS.get(status, ("muted", status.title()))
    return f'<span class="status-pill {variant}">{escape(label)}</span>'


def kind_badge(kind: str, measured_at: float | None = None) -> str:
    if kind == "live":
        when = f" · {_utc(measured_at, '%H:%M:%S UTC')}" if measured_at else ""
        return f'<span class="ops-kind live" title="Measured now">Live{escape(when)}</span>'
    if kind == "historical":
        return '<span class="ops-kind historical" title="From recorded data">Historical</span>'
    if kind == "configuration":
        return '<span class="ops-kind configuration">Configuration</span>'
    return '<span class="ops-kind mixed">Live + historical</span>'


def _page(title: str, active: str, content: str) -> str:
    return control_layout(title=title, active=active,
                          content=f"<style>{OPS_STYLE}</style>{content}")


def _pct(value) -> str:
    return "—" if value is None else f"{value:.0%}"


# ── Analytics ───────────────────────────────────────────────────────
def analytics_page(*, data: dict) -> str:
    usage = data["usage"]
    jobs = data["jobs"]
    indexing = data["indexing"]
    storage = data["storage"]
    apps = usage["applications"]

    total_opens = sum(usage["totals"].values())
    finished = sum(jobs["by_status"].get(s, 0) for s in ("completed", "failed", "cancelled"))
    failed = jobs["by_status"].get("failed", 0)
    cache = storage.get("working_cache") or {}
    cache_fraction = (cache["usage_bytes"] / cache["limit_bytes"]
                      if cache.get("limit_bytes") else None)

    metrics = f"""
    <div class="metric-grid">
      <div class="metric-card"><div class="metric-label">Application opens</div>
        <div class="metric-value">{total_opens}</div>
        <div class="metric-detail">last {len(usage['days'])} days · historical</div></div>
      <div class="metric-card"><div class="metric-label">Jobs</div>
        <div class="metric-value">{jobs.get('total', 0)}</div>
        <div class="metric-detail">last {data['window_days']} days · historical</div></div>
      <div class="metric-card"><div class="metric-label">Job failure rate</div>
        <div class="metric-value">{_pct(failed / finished if finished else None)}</div>
        <div class="metric-detail">{failed} failed of {finished} finished</div></div>
      <div class="metric-card"><div class="metric-label">Working cache</div>
        <div class="metric-value">{_pct(cache_fraction)}</div>
        <div class="metric-detail">{human_bytes(cache.get('usage_bytes'))} of
          {human_bytes(cache.get('limit_bytes'))} · live</div></div>
    </div>"""

    # application opens
    head = "".join(f'<th class="num">{escape(t)}</th>' for t in apps.values())
    rows = []
    for item in reversed(usage["days"]):
        cells = "".join(f'<td class="num">{item["counts"].get(a, 0)}</td>' for a in apps)
        rows.append(f"<tr><td>{escape(item['day'])}</td>{cells}</tr>")
    totals = "".join(f'<td class="num"><strong>{usage["totals"].get(a, 0)}</strong></td>'
                     for a in apps)
    since = (f"Counting since {escape(usage['counting_since'])}."
             if usage.get("counting_since") else "No application opens recorded yet.")
    usage_panel = f"""
    <section class="panel">
      <div class="ops-head"><h2>Application opens per day</h2>{kind_badge('historical')}</div>
      <p class="ops-note">Successful loads of each application's entry page, aggregated per
        application and UTC day. No user, address or browsing history is stored. Health-check
        probes are excluded. {since}</p>
      <div class="fl-table-wrap"><table>
        <thead><tr><th>Day</th>{head}</tr></thead>
        <tbody>{''.join(rows)}<tr><td><strong>Total</strong></td>{totals}</tr></tbody>
      </table></div>
    </section>"""

    # jobs over time
    if jobs["available"]:
        statuses = [s for s in _JOB_COLORS if any(d["counts"].get(s) for d in jobs["per_day"])]
        others = sorted({s for d in jobs["per_day"] for s in d["counts"]} - set(_JOB_COLORS))
        peak = max([sum(d["counts"].values()) for d in jobs["per_day"]] + [1])
        bars = []
        for item in jobs["per_day"]:
            count = sum(item["counts"].values())
            segments = "".join(
                f'<span style="width:{item["counts"].get(s, 0) / peak * 100:.2f}%;'
                f'background:{_JOB_COLORS.get(s, "#94a3b8")}" '
                f'title="{escape(s)}: {item["counts"].get(s, 0)}"></span>'
                for s in statuses + others if item["counts"].get(s))
            bars.append(
                f'<div class="ops-bar-row"><span>{escape(item["day"][5:])}</span>'
                f'<div class="ops-bar" role="img" aria-label="{count} jobs on {escape(item["day"])}">'
                f'{segments}</div><span class="num">{count}</span></div>')
        legend = "".join(f'<span><i style="background:{_JOB_COLORS.get(s, "#94a3b8")}"></i>'
                         f'{escape(s)}</span>' for s in statuses + others)
        jobs_body = (f'<div class="ops-bars">{"".join(bars)}</div>'
                     f'<div class="ops-legend">{legend or "No jobs in this window."}</div>')
    else:
        jobs_body = f'<p class="panel-empty">{escape(jobs.get("error") or "No job records.")}</p>'
    jobs_panel = f"""
    <section class="panel">
      <div class="ops-head"><h2>Jobs per day by state</h2>{kind_badge('historical')}</div>
      <p class="ops-note">Experiment records (CryoLauncher, ICESEE, LIVIST runs on every backend),
        by creation day. States are the current state of each job.</p>
      {jobs_body}
    </section>"""

    def outcome_table(title: str, items: list[dict]) -> str:
        body = "".join(
            f"<tr><td>{escape(i['name'])}</td><td class='num'>{i['total']}</td>"
            f"<td class='num'>{i['completed']}</td><td class='num'>{i['failed']}</td>"
            f"<td class='num'>{i['cancelled']}</td><td class='num'>{_pct(i['failure_rate'])}</td></tr>"
            for i in items) or '<tr><td colspan="6" class="table-empty">No jobs.</td></tr>'
        return f"""
        <section class="panel">
          <div class="ops-head"><h2>{escape(title)}</h2>{kind_badge('historical')}</div>
          <div class="fl-table-wrap"><table>
            <thead><tr><th>Name</th><th class="num">Jobs</th><th class="num">Completed</th>
              <th class="num">Failed</th><th class="num">Cancelled</th>
              <th class="num">Failure rate</th></tr></thead>
            <tbody>{body}</tbody></table></div>
        </section>"""

    wall_rows = "".join(
        f"<tr><td>{escape(i['backend'])}</td><td class='num'>{i['jobs']}</td>"
        f"<td class='num'>{i['seconds'] / 3600:.1f}</td></tr>"
        for i in jobs.get("wall_time", [])) or (
        '<tr><td colspan="3" class="table-empty">No job with recorded start and end.</td></tr>')
    wall_panel = f"""
    <section class="panel">
      <div class="ops-head"><h2>Recorded run time</h2>{kind_badge('historical')}</div>
      <p class="ops-note">Wall-clock time between recorded start and finish. CPU, memory and cloud
        cost are not recorded per job today, so they are not shown.</p>
      <div class="fl-table-wrap"><table>
        <thead><tr><th>Backend</th><th class="num">Jobs</th><th class="num">Hours</th></tr></thead>
        <tbody>{wall_rows}</tbody></table></div>
    </section>"""

    # indexing
    if indexing["available"]:
        chips = "".join(f'<span class="fl-chip">{escape(s)} <strong>{n}</strong></span>'
                        for s, n in sorted(indexing["runs_by_status"].items())) or \
            '<span class="ops-muted">No runs in this window.</span>'
        files = "".join(f'<span class="fl-chip">{escape(s)} <strong>{n}</strong></span>'
                        for s, n in sorted(indexing["files"].items())) or \
            '<span class="ops-muted">No files indexed.</span>'
        totals = indexing.get("run_totals", {})
        sources = "".join(
            f"<tr><td>{escape(s['source_id'])}</td><td>{escape(s['name'] or '')}</td>"
            f"<td>{escape(s['status'])}</td><td>{escape(s['last_index_status'] or '—')}</td>"
            f"<td>{_utc(s['last_index_at'], '%Y-%m-%d %H:%M')}</td></tr>"
            for s in indexing["sources"]) or '<tr><td colspan="5" class="table-empty">No sources.</td></tr>'
        failures = "".join(
            f"<li>{_utc(f['started_at'], '%Y-%m-%d %H:%M')} · {escape(f['source_id'])} · "
            f"{escape(f['status'])}{': ' + escape(f['error']) if f['error'] else ''}</li>"
            for f in indexing["recent_failures"])
        index_body = f"""
        <div class="fl-kv-grid">
          <div class="fl-kv"><span>Runs ({data['window_days']} days)</span><div class="fl-chips">{chips}</div></div>
          <div class="fl-kv"><span>Catalog files by status</span><div class="fl-chips">{files}</div></div>
          <div class="fl-kv"><span>Files discovered / added</span>
            <strong>{totals.get('discovered', 0)} / {totals.get('added', 0)}</strong>
            <small>{totals.get('invalid', 0)} invalid · {totals.get('missing', 0)} missing</small></div>
        </div>
        <div class="fl-table-wrap"><table>
          <thead><tr><th>Source</th><th>Name</th><th>Status</th><th>Last run</th><th>Last run at</th></tr></thead>
          <tbody>{sources}</tbody></table></div>
        {f'<div class="fl-card-section"><div class="fl-section-label">Recent failures</div><ul class="fl-list">{failures}</ul></div>' if failures else ''}"""
    else:
        index_body = f'<p class="panel-empty">{escape(indexing.get("error") or "Not available.")}</p>'
    index_panel = f"""
    <section class="panel">
      <div class="ops-head"><h2>Frozen Legacies indexing</h2>{kind_badge('historical')}</div>
      {index_body}
    </section>"""

    # storage
    workspaces = storage.get("workspaces") or {}
    databases = storage.get("databases") or {}
    meter = ""
    if cache_fraction is not None:
        meter = (f'<div class="ops-meter{" warn" if cache_fraction > 0.9 else ""}">'
                 f'<span style="width:{min(cache_fraction, 1) * 100:.1f}%"></span></div>')
    storage_panel = f"""
    <section class="panel">
      <div class="ops-head"><h2>Storage and caches</h2>{kind_badge('live', storage.get('measured_at'))}</div>
      <div class="fl-kv-grid">
        <div class="fl-kv"><span>Working cache</span>
          <strong>{human_bytes(cache.get('usage_bytes'))} of {human_bytes(cache.get('limit_bytes'))}</strong>
          {meter}</div>
        <div class="fl-kv"><span>User workspaces</span>
          <strong>{workspaces.get('users', 0)} users · {human_bytes(workspaces.get('bytes'))}</strong>
          <small>{workspaces.get('files', 0)} files{' · partial scan (limit reached)' if workspaces.get('partial') else ''}
          · measured {_utc(workspaces.get('measured_at'), '%H:%M UTC')} (cached 10 min)</small></div>
        <div class="fl-kv"><span>Databases</span>
          <strong>{human_bytes(databases.get('auth_database'))} auth</strong>
          <small>catalog {human_bytes(databases.get('catalog'))} ·
            operations {human_bytes(databases.get('operations'))} (including WAL)</small></div>
      </div>
    </section>"""

    content = f"""
    <div class="page-heading-row">
      <div>
        <h1>Analytics</h1>
        <p class="page-subtitle">Aggregate platform activity. Historical figures come from recorded
          data; live figures are measured when the page loads ({_utc(data['generated_at'])}).</p>
      </div>
      <a class="small-button" href="/api/control/analytics">JSON</a>
    </div>
    {metrics}
    {usage_panel}
    {jobs_panel}
    <div class="ops-grid-2">
      {outcome_table('Outcomes by application', jobs.get('by_application', []))}
      {outcome_table('Outcomes by backend', jobs.get('by_backend', []))}
    </div>
    {wall_panel}
    {index_panel}
    {storage_panel}
    """
    return _page("Analytics", "analytics", content)


# ── Diagnostics ─────────────────────────────────────────────────────
def diagnostics_page(*, data: dict) -> str:
    summary = "".join(
        f'{status_pill(status)} <span class="ops-muted">×{count}</span>'
        for status, count in sorted(data["summary"].items(),
                                    key=lambda i: list(_STATUS).index(i[0]) if i[0] in _STATUS else 99))
    panels = []
    for section in data["sections"]:
        items = []
        for check in section["checks"]:
            action = (f'<span class="action">→ {escape(check["action"])}</span>'
                      if check.get("action") else "")
            items.append(f"""
            <li class="ops-check" data-status="{escape(check['status'])}">
              <strong>{escape(check['name'])}</strong>
              <span>{status_pill(check['status'])}</span>
              <span class="detail">{escape(str(check['detail']))}{action}</span>
              <span class="kind">{kind_badge(check.get('kind', 'live'), check.get('measured_at'))}</span>
            </li>""")
        note = f'<p class="ops-note">{escape(section["note"])}</p>' if section.get("note") else ""
        panels.append(f"""
        <section class="panel" id="diag-{escape(section['id'])}">
          <div class="ops-head"><h2>{escape(section['title'])}</h2>
            {kind_badge(section.get('kind', 'live'), data['measured_at'] if section.get('kind') == 'live' else None)}</div>
          {note}
          <ul class="ops-checks">{''.join(items)}</ul>
        </section>""")
    cached = " (cached)" if data.get("cached") else ""
    content = f"""
    <div class="page-heading-row">
      <div>
        <h1>Diagnostics</h1>
        <p class="page-subtitle">Operational health of CryoStack services. Live checks were measured
          at <strong>{_utc(data['measured_at'])}</strong>{cached}; snapshots are reused for up to
          {data['cache_seconds']:.0f} s. Historical checks summarise recorded runs.</p>
      </div>
      <div class="fl-actions">
        <a class="fl-btn primary" href="/control/diagnostics?refresh=1">Measure again</a>
        <a class="small-button" href="/api/control/diagnostics">JSON</a>
      </div>
    </div>
    <div class="ops-summary">{summary}</div>
    {''.join(panels)}
    """
    return _page("Diagnostics", "diagnostics", content)


# ── Settings ────────────────────────────────────────────────────────
_SOURCE = {
    "environment": ("warn", "Environment"),
    "stored": ("info", "Stored"),
    "default": ("muted", "Default"),
}


def _display(setting: dict, value) -> str:
    if value is None:
        return "—"
    if setting["type"] == "bool":
        return "on" if value is True else ("off" if value is False else str(value))
    unit = f" {setting['unit']}" if setting.get("unit") else ""
    return f"{value}{unit}"


def _setting_form(setting: dict) -> str:
    key = escape(setting["key"])
    current = setting["configured_value"]
    if setting["type"] == "choice":
        options = "".join(
            f'<option value="{escape(c)}"{" selected" if c == current else ""}>{escape(c)}</option>'
            for c in setting["choices"])
        field = f'<select name="value" id="v-{key}">{options}</select>'
    elif setting["type"] == "bool":
        field = (f'<select name="value" id="v-{key}">'
                 f'<option value="true"{" selected" if current is True else ""}>on</option>'
                 f'<option value="false"{" selected" if current is not True else ""}>off</option>'
                 f'</select>')
    else:
        field = (f'<input type="number" name="value" id="v-{key}" required step="1" '
                 f'min="{setting["minimum"]}" max="{setting["maximum"]}" '
                 f'value="{escape(str(current))}">')
    reset = ""
    if setting["stored_value"] is not None:
        reset = (f'<button class="fl-btn quiet" type="submit" name="op" value="reset" '
                 f'formnovalidate>Remove stored value</button>')
    return f"""
    <form class="ops-form" method="post" action="/control/settings">
      <input type="hidden" name="key" value="{key}">
      <label class="fl-field" for="v-{key}">New value {field}</label>
      <label class="fl-field" for="r-{key}">Reason (recorded in the audit log)
        <input type="text" name="reason" id="r-{key}" maxlength="500" required
               placeholder="Why is this changing?"></label>
      <div class="fl-actions">
        <button class="fl-btn primary" type="submit" name="op" value="save">Save</button>
        {reset}
      </div>
    </form>"""


def settings_page(*, settings: list[dict], audit: list[dict], applications: list[dict],
                  storage_sources: dict, can_write: bool, message: str | None = None,
                  error: str | None = None) -> str:
    notices = []
    if error:
        notices.append(f'<p class="fl-notice bad" role="alert"><strong>Not saved.</strong> {escape(error)}</p>')
    if message:
        notices.append(f'<p class="fl-notice ok" role="status">{escape(message)}</p>')
    if not can_write:
        notices.append('<p class="fl-notice info">You can view these settings. Changing them '
                       'requires the maintainer, admin or owner role.</p>')

    groups: dict[str, list[dict]] = {}
    for setting in settings:
        groups.setdefault(setting["group"], []).append(setting)
    panels = []
    for group, items in groups.items():
        rows = []
        for s in items:
            variant, label = _SOURCE[s["source"]]
            flags = [f'<span class="status-pill {variant}">{label}</span>']
            if s["pending_restart"]:
                flags.append('<span class="status-pill warn">Restart pending</span>')
            if s["shadowed"]:
                flags.append('<span class="status-pill muted">Stored value shadowed</span>')
            range_text = (f"{s['minimum']}–{s['maximum']} {s['unit']}".strip()
                          if s["type"] == "int" else
                          (" / ".join(s["choices"]) if s["type"] == "choice" else "on / off"))
            restart = ("Applies immediately" if not s["restart_required"]
                       else "Gateway restart required")
            pending = ""
            if s["pending_restart"]:
                pending = (f'<p class="fl-help">Running value {escape(_display(s, s["running_value"]))}; '
                           f'{escape(_display(s, s["configured_value"]))} applies after the next '
                           f'gateway restart.</p>')
            shadow = ""
            if s["shadowed"] or s["source"] == "environment":
                shadow = (f'<p class="fl-help">Set by the service environment '
                          f'(<code>{escape(s["env"])}</code>), which takes precedence. '
                          + (f'Stored value {escape(_display(s, s["stored_value"]))} applies only '
                             f'once the variable is removed.' if s["shadowed"] else
                             'A value saved here applies only once the variable is removed.')
                          + '</p>')
            control = _setting_form(s) if can_write else ""
            rows.append(f"""
            <div class="ops-setting" id="setting-{escape(s['key'])}">
              <div>
                <h3>{escape(s['label'])}</h3>
                <p>{escape(s['description'])}</p>
                <div class="ops-meta">
                  <span class="fl-chip">Read by <strong>{escape(s['reader'])}</strong></span>
                  <span class="fl-chip">Range <strong>{escape(range_text)}</strong></span>
                  <span class="fl-chip">Default <strong>{escape(_display(s, s['default']))}</strong></span>
                  <span class="fl-chip">{escape(restart)}</span>
                  <span class="fl-chip fl-mono">{escape(s['env'])}</span>
                </div>
                {f'<p class="fl-help">{escape(s["restart_note"])}</p>' if s['restart_note'] else ''}
              </div>
              <div>
                <div class="ops-value">Effective <strong>{escape(_display(s, s['configured_value']))}</strong>
                  {''.join(flags)}</div>
                {pending}{shadow}{control}
              </div>
            </div>""")
        panels.append(f"""
        <section class="panel">
          <div class="ops-head"><h2>{escape(group)}</h2></div>
          {''.join(rows)}
        </section>""")

    app_rows = "".join(
        f"<tr><td><strong>{escape(a['title'])}</strong></td><td>{escape(a['type'])}</td>"
        f"<td>{escape(', '.join(a['routes']) or '—')}</td><td>{escape(a['health'] or '—')}</td></tr>"
        for a in applications) or '<tr><td colspan="4" class="table-empty">No applications.</td></tr>'

    audit_rows = []
    for entry in audit:
        rollback = ""
        if can_write:
            rollback = f"""
            <form method="post" action="/control/settings" class="ops-inline">
              <input type="hidden" name="op" value="rollback">
              <input type="hidden" name="audit_id" value="{entry['id']}">
              <button class="fl-btn quiet" type="submit"
                title="Restore the value from before this change">Roll back</button>
            </form>"""
        old = "default" if entry["old_value"] is None else str(entry["old_value"])
        new = "default" if entry["new_value"] is None else str(entry["new_value"])
        suffix = f" (of #{entry['rollback_of']})" if entry.get("rollback_of") else ""
        audit_rows.append(
            f"<tr><td>#{entry['id']}</td><td>{_utc(entry['created_at'], '%Y-%m-%d %H:%M')}</td>"
            f"<td>{escape(entry['label'])}</td><td>{escape(entry['action'])}{escape(suffix)}</td>"
            f"<td>{escape(old)} → {escape(new)}</td>"
            f"<td>{escape(entry.get('actor_label') or entry['actor_id'])}</td>"
            f"<td>{escape(entry['reason'])}</td><td>{rollback}</td></tr>")

    content = f"""
    <div class="page-heading-row">
      <div>
        <h1>Settings</h1>
        <p class="page-subtitle">Supported platform settings only. Every value is validated on the
          server and every change is recorded with who, when, the old and new value and the reason.</p>
      </div>
      <a class="small-button" href="/api/control/settings">JSON</a>
    </div>
    <div class="fl-stack" style="margin-bottom:1rem">
      {''.join(notices)}
      <p class="fl-notice info"><strong>Precedence:</strong> a variable set in the service
        environment when the gateway started wins over a stored value, which wins over the
        built-in default. Stored values are exported to the gateway environment at start-up (and
        immediately for settings marked “Applies immediately”).</p>
    </div>
    {''.join(panels)}
    <section class="panel">
      <div class="ops-head"><h2>Applications</h2>{kind_badge('configuration')}</div>
      <p class="ops-note">Registered in <code>deployment/applications.yaml</code>. The registry has no
        enable/disable switch and the gateway serves every registered application, so this list is
        read-only.</p>
      <div class="fl-table-wrap"><table>
        <thead><tr><th>Application</th><th>Type</th><th>Routes</th><th>Health target</th></tr></thead>
        <tbody>{app_rows}</tbody></table></div>
    </section>
    <section class="panel">
      <div class="ops-head"><h2>Approved storage sources</h2>{kind_badge('configuration')}</div>
      <p class="ops-note">{storage_sources['local_roots']} approved local data root(s) and
        {storage_sources['s3_approvals']} approved S3 location(s) are configured for Frozen Legacies.
        Data sources are managed on their own page.</p>
      <div class="fl-actions" style="padding:0 1.1rem 1rem">
        <a class="fl-btn" href="/control/frozen-legacies">Frozen Legacies data sources →</a>
      </div>
    </section>
    <section class="panel" id="settings-audit">
      <div class="ops-head"><h2>Change history</h2>{kind_badge('historical')}</div>
      <div class="fl-table-wrap"><table>
        <thead><tr><th>#</th><th>When (UTC)</th><th>Setting</th><th>Action</th><th>Change</th>
          <th>By</th><th>Reason</th><th></th></tr></thead>
        <tbody>{''.join(audit_rows) or '<tr><td colspan="8" class="table-empty">No changes yet.</td></tr>'}</tbody>
      </table></div>
    </section>
    """
    return _page("Settings", "settings", content)
