"""Shared styles of the Frozen Legacies Control Center pages (data sources,
scientific review).

They extend the Control Center's own components (``panel``,
``panel-header``, ``status-pill``, ``small-button``, ``metric-card``,
``placeholder-state`` in :mod:`control_center.templates`) with the few
pieces those pages need and the Control Center does not have: buttons,
form fields, notices, status variants, filter tabs and a progress bar --
in the Control Center's palette (slate text, ``#2563eb`` accent,
``#e2e8f0`` borders), radii and type scale.
"""

STYLE = """
[hidden] { display: none !important; }

/* buttons */
.fl-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.35rem;
  min-height: 34px; padding: 0 0.8rem;
  border: 1px solid #cbd5e1; border-radius: 8px;
  background: #ffffff; color: #334155;
  font: inherit; font-size: 0.78rem; font-weight: 700; line-height: 1;
  text-decoration: none; cursor: pointer; white-space: nowrap;
}
.fl-btn:hover { border-color: #94a3b8; background: #f8fafc; }
.fl-btn:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.fl-btn.primary { border-color: #2563eb; background: #2563eb; color: #ffffff; }
.fl-btn.primary:hover { background: #1d4ed8; }
.fl-btn.danger { border-color: #fecaca; color: #b91c1c; }
.fl-btn.danger:hover { background: #fef2f2; }
.fl-btn.quiet { border-color: transparent; background: transparent; color: #2563eb; padding: 0 0.4rem; }
.fl-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.fl-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }

/* status variants of the Control Center's status-pill */
.status-pill.ok { background: #dcfce7; color: #166534; }
.status-pill.warn { background: #fef3c7; color: #92400e; }
.status-pill.bad { background: #fee2e2; color: #991b1b; }
.status-pill.info { background: #eff6ff; color: #1d4ed8; }
.status-pill.muted { background: #f1f5f9; color: #64748b; }

/* notices */
.fl-notice {
  margin: 0; padding: 0.7rem 0.9rem; border-radius: 10px;
  border: 1px solid #e2e8f0; border-left-width: 4px;
  background: #f8fafc; color: #334155; font-size: 0.8rem; line-height: 1.5;
}
.fl-notice.info { border-color: #bfdbfe; border-left-color: #2563eb; background: #eff6ff; }
.fl-notice.warn { border-color: #fde68a; border-left-color: #d97706; background: #fffbeb; color: #78350f; }
.fl-notice.bad { border-color: #fecaca; border-left-color: #dc2626; background: #fef2f2; color: #7f1d1d; }
.fl-notice.ok { border-color: #bbf7d0; border-left-color: #16a34a; background: #f0fdf4; color: #14532d; }
.fl-notice strong { font-weight: 750; }
.fl-stack { display: grid; gap: 0.75rem; }

/* forms */
.fl-form { display: grid; gap: 1.25rem; padding: 1.1rem; }
.fl-fieldset { display: grid; gap: 0.9rem; margin: 0; padding: 0; border: 0; min-width: 0; }
.fl-fieldset > legend, .fl-section-label {
  margin-bottom: 0.5rem; padding: 0;
  color: #94a3b8; font-size: 0.67rem; font-weight: 800;
  letter-spacing: 0.06em; text-transform: uppercase;
}
.fl-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.9rem 1rem; }
.fl-fields.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.fl-field { display: grid; gap: 0.35rem; align-content: start; color: #475569; font-size: 0.76rem; font-weight: 700; }
.fl-field.wide { grid-column: 1 / -1; }
.fl-field input, .fl-field select, .fl-field textarea {
  width: 100%; min-height: 38px; padding: 0.5rem 0.65rem;
  border: 1px solid #cbd5e1; border-radius: 8px;
  background: #ffffff; color: #0f172a; font: inherit; font-size: 0.82rem; font-weight: 500;
}
.fl-field textarea { min-height: 76px; resize: vertical; }
.fl-field input:focus, .fl-field select:focus, .fl-field textarea:focus {
  outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);
}
.fl-field input[aria-invalid="true"] { border-color: #dc2626; }
.fl-help { color: #64748b; font-size: 0.72rem; font-weight: 500; line-height: 1.45; }
.fl-field-error { color: #b91c1c; font-size: 0.72rem; font-weight: 600; }
.fl-field code, .fl-help code, .fl-notice code {
  padding: 0.05rem 0.3rem; border-radius: 4px; background: #f1f5f9; font-size: 0.72rem;
}
.fl-check { display: flex; gap: 0.5rem; align-items: flex-start; color: #334155; font-size: 0.8rem; font-weight: 600; }
.fl-check input { margin-top: 0.15rem; }

/* provider choice */
.fl-choice { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.75rem; }
.fl-choice label {
  display: grid; grid-template-columns: auto 1fr; gap: 0.15rem 0.6rem; align-items: start;
  padding: 0.8rem 0.9rem; border: 1px solid #e2e8f0; border-radius: 10px;
  background: #ffffff; cursor: pointer;
}
.fl-choice label:has(input:checked) { border-color: #2563eb; background: #eff6ff; }
.fl-choice label:has(input:disabled) { cursor: not-allowed; opacity: 0.6; }
.fl-choice input { grid-row: span 2; margin-top: 0.2rem; }
.fl-choice strong { color: #0f172a; font-size: 0.82rem; }
.fl-choice span { color: #64748b; font-size: 0.72rem; font-weight: 500; line-height: 1.4; }

/* filter tabs */
.fl-tabs { display: flex; flex-wrap: wrap; gap: 0.4rem; padding: 0.9rem 1.1rem; border-bottom: 1px solid #e2e8f0; }
.fl-tab {
  display: inline-flex; align-items: center; gap: 0.4rem; min-height: 32px; padding: 0 0.75rem;
  border: 1px solid #e2e8f0; border-radius: 999px; background: #ffffff;
  color: #475569; font: inherit; font-size: 0.76rem; font-weight: 700; cursor: pointer;
}
.fl-tab .count { min-width: 1.4rem; padding: 0.05rem 0.4rem; border-radius: 999px; background: #f1f5f9; color: #64748b; font-size: 0.68rem; text-align: center; }
.fl-tab.active { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.fl-tab.active .count { background: #dbeafe; color: #1d4ed8; }

/* key/value grids and cards */
.fl-kv-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.9rem 1.25rem; padding: 1rem 1.1rem; }
.fl-kv { display: grid; gap: 0.2rem; min-width: 0; }
.fl-kv > span { color: #94a3b8; font-size: 0.67rem; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; }
.fl-kv > strong { color: #0f172a; font-size: 0.82rem; font-weight: 700; overflow-wrap: anywhere; }
.fl-kv > small { color: #64748b; font-size: 0.72rem; overflow-wrap: anywhere; }
.fl-card-head {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem;
  padding: 1rem 1.1rem; border-bottom: 1px solid #e2e8f0;
}
.fl-card-title { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; min-width: 0; }
.fl-card-title h2 { margin: 0; font-size: 1rem; letter-spacing: -0.01em; }
.fl-card-title small { color: #64748b; font-size: 0.74rem; }
.fl-card-section { padding: 1rem 1.1rem; border-top: 1px solid #f1f5f9; }
.fl-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.fl-chip { display: inline-flex; gap: 0.3rem; padding: 0.25rem 0.55rem; border-radius: 999px; background: #f8fafc; border: 1px solid #e2e8f0; color: #475569; font-size: 0.72rem; }
.fl-chip strong { color: #0f172a; }
.fl-list { margin: 0; padding-left: 1.1rem; color: #475569; font-size: 0.76rem; line-height: 1.6; }
.fl-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.72rem; }

/* progress */
.fl-progress { display: grid; gap: 0.4rem; }
.fl-progress-bar { height: 8px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }
.fl-progress-bar span { display: block; height: 100%; border-radius: 999px; background: #2563eb; transition: width 0.4s; }
.fl-progress-bar.indeterminate span { width: 30% !important; animation: fl-slide 1.4s infinite ease-in-out; }
@keyframes fl-slide { 0% { margin-left: -30%; } 100% { margin-left: 100%; } }
.fl-progress small { color: #64748b; font-size: 0.72rem; }

/* tables inside panels */
.fl-table-wrap { overflow-x: auto; }
.fl-table-wrap table { min-width: 640px; }
.fl-table-wrap th.unit { text-transform: none; letter-spacing: normal; }
tr.fl-row-differs td { background: #fffbeb; }
tr.fl-row-active td { background: #eff6ff; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }

.page-heading-row > .small-button { flex: 0 0 auto; white-space: nowrap; }
.fl-kv > strong small { display: block; flex-basis: 100%; color: #64748b; font-size: 0.72rem; font-weight: 500; }

@media (max-width: 760px) {
  .page-heading-row { flex-wrap: wrap; }
  .fl-fields, .fl-fields.three, .fl-choice { grid-template-columns: 1fr; }
  .fl-card-head { align-items: flex-start; }
}
"""
