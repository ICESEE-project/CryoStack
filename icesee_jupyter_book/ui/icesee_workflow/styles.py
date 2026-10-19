"""Visual language of the ICESEE workflow UI.

One stylesheet, scoped to ``.icw`` (the workflow page root), with design
tokens for colour, spacing and motion. Motion is used only to explain a state
change (a pane appearing, a run starting, a validation error arriving) and is
switched off for users who ask for reduced motion.
"""
from __future__ import annotations

import ipywidgets as W

CSS = r"""
<style>
.icw {
  --ic-primary: #1d5fb8; --ic-primary-hover: #174d96; --ic-primary-press: #123f7b;
  --ic-primary-soft: #e8f0fb; --ic-ink: #142033; --ic-text: #2c3a4f; --ic-muted: #5d6b80;
  --ic-faint: #8a96a8; --ic-border: #dbe3ee; --ic-border-strong: #c3cfdf; --ic-surface: #ffffff;
  --ic-subtle: #f5f8fc; --ic-canvas: #eef2f7;
  --ic-success: #1d7f46; --ic-success-soft: #e5f4eb; --ic-warn: #9a6200; --ic-warn-soft: #fdf3dc;
  --ic-danger: #b42318; --ic-danger-soft: #fdecea; --ic-info: #1d5fb8; --ic-info-soft: #e8f0fb;
  --ic-radius: 12px; --ic-radius-sm: 8px; --ic-shadow: 0 1px 2px rgba(16,24,40,.05), 0 6px 18px rgba(16,24,40,.05);
  --ic-ease: cubic-bezier(.2,.8,.2,1); --ic-fast: 140ms; --ic-med: 220ms;
  color: var(--ic-text);
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  max-width: 1680px; margin: 0 auto;
}
.icw * { box-sizing: border-box; }
/* layout.display = "none" must win over the layout classes below */
.icw [style*="display: none"] { display: none !important; }

/* ── page header + stepper ─────────────────────────────────────────── */
.icw-hero { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap; margin: 4px 0 10px; }
.icw-hero h1 { margin:0; font-size:22px; line-height:1.25; color:var(--ic-ink); font-weight:750; letter-spacing:-.01em; }
.icw-hero p { margin:4px 0 0; color:var(--ic-muted); font-size:13.5px; max-width:760px; }
.icw-bar { position: sticky; top: 0; z-index: 50; display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;
  padding: 8px 10px; margin: 0 0 12px; border-radius: 12px; background: rgba(255,255,255,.92); backdrop-filter: blur(6px);
  border:1px solid var(--ic-border); box-shadow: 0 4px 14px rgba(16,24,40,.06); }
.icw-stepper { display:flex; gap:4px; flex-wrap:wrap; list-style:none; padding:0; margin:0; counter-reset: step; }
.icw-step { cursor:pointer; } .icw-step:hover { border-color: var(--ic-border-strong); }
.icw-step:focus-visible { outline: 3px solid rgba(29,95,184,.45); outline-offset: 2px; }
.icw-live { display:flex; align-items:center; gap:8px; font-size:12.5px; color: var(--ic-muted); font-variant-numeric: tabular-nums; }
.icw-step { display:flex; align-items:center; gap:7px; padding:6px 11px 6px 7px; border-radius:999px; font-size:12.5px;
  color:var(--ic-muted); background:var(--ic-surface); border:1px solid var(--ic-border); transition: all var(--ic-med) var(--ic-ease); }
.icw-step .n { width:20px; height:20px; border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
  font-size:11px; font-weight:700; background:var(--ic-subtle); color:var(--ic-muted); border:1px solid var(--ic-border); }
.icw-step.done { color:var(--ic-success); border-color:#cfe8d8; }
.icw-step.done .n { background:var(--ic-success); color:#fff; border-color:var(--ic-success); }
.icw-step.current { color:var(--ic-primary); border-color:var(--ic-primary); background:var(--ic-primary-soft); font-weight:650; box-shadow:0 0 0 3px rgba(29,95,184,.10); }
.icw-step.current .n { background:var(--ic-primary); color:#fff; border-color:var(--ic-primary); }
.icw-step.attention { color:var(--ic-warn); border-color:#f1d79b; background:var(--ic-warn-soft); }
.icw-step.attention .n { background:var(--ic-warn); color:#fff; border-color:var(--ic-warn); }
.icw-step.active .n { animation: icw-pulse 1.6s ease-in-out infinite; }

/* ── layout ────────────────────────────────────────────────────────── */
.icw-shell { display:grid !important; grid-template-columns: minmax(380px, 5fr) minmax(460px, 7fr); gap:16px; align-items:start; width:100%; }
.icw-col { display:flex !important; flex-direction:column; gap:12px; min-width:0; }
@media (max-width: 1100px) { .icw-shell { grid-template-columns: 1fr; } }
.icw-card { background:var(--ic-surface); border:1px solid var(--ic-border); border-radius:var(--ic-radius); box-shadow:var(--ic-shadow);
  padding:14px 16px 16px; min-width:0; }
.icw-card.icw-emph { border-color:#b9cbe6; box-shadow: 0 0 0 1px rgba(29,95,184,.06), var(--ic-shadow); }
.icw-card-head { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:10px; }
.icw-card-title { display:flex; align-items:center; gap:9px; font-size:14.5px; font-weight:700; color:var(--ic-ink); }
.icw-card-title .num { width:22px; height:22px; border-radius:7px; display:inline-flex; align-items:center; justify-content:center;
  background:var(--ic-primary-soft); color:var(--ic-primary); font-size:12px; font-weight:800; }
.icw-card-sub { color:var(--ic-muted); font-size:12.5px; margin-top:2px; line-height:1.45; }
.icw-right { position: sticky; top: 8px; }
.icw .widget-label { color: var(--ic-text); }

/* ── form rows ─────────────────────────────────────────────────────── */
.icw-field { display:grid !important; grid-template-columns: 132px minmax(0,1fr); align-items:center; gap:10px; }
.icw-field > .widget-html:first-child { color:var(--ic-text); font-size:13px; font-weight:600; }
.icw-field .icw-help { color:var(--ic-faint); font-weight:400; font-size:11.5px; display:block; line-height:1.3; }
.icw-grid2 { display:grid !important; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px 14px; }
@media (max-width: 760px) { .icw-grid2 { grid-template-columns: 1fr; } .icw-field { grid-template-columns: 1fr; } }
.icw .widget-text input, .icw .widget-inttext input, .icw .widget-floattext input, .icw select, .icw textarea {
  border-radius: var(--ic-radius-sm) !important; border-color: var(--ic-border-strong) !important; transition: border-color var(--ic-fast), box-shadow var(--ic-fast); }
.icw input:focus, .icw select:focus, .icw textarea:focus { border-color: var(--ic-primary) !important; box-shadow: 0 0 0 3px rgba(29,95,184,.16) !important; outline:none; }
.icw-invalid input, .icw-invalid select, .icw-invalid textarea { border-color: var(--ic-danger) !important; }

/* ── buttons: primary / secondary / quiet / danger ─────────────────── */
.icw .jupyter-button { border-radius: var(--ic-radius-sm); font-weight:600; font-size:13px; height:34px; padding:0 14px;
  flex-shrink:0; min-width:max-content;
  transition: background var(--ic-fast) var(--ic-ease), box-shadow var(--ic-fast), transform var(--ic-fast), color var(--ic-fast), border-color var(--ic-fast); }
.icw .jupyter-button:focus-visible { outline: 3px solid rgba(29,95,184,.45); outline-offset: 2px; }
.icw .jupyter-button:active:not(:disabled) { transform: translateY(1px) scale(.99); }
.icw .jupyter-button:disabled { opacity:.5; cursor:not-allowed; }
.icw .icw-btn-primary { background: var(--ic-primary) !important; color:#fff !important; border:1px solid var(--ic-primary) !important;
  box-shadow: 0 1px 2px rgba(16,24,40,.12); }
.icw .icw-btn-primary:hover:not(:disabled) { background: var(--ic-primary-hover) !important; box-shadow: 0 4px 12px rgba(29,95,184,.25); }
.icw .icw-btn-primary:active:not(:disabled) { background: var(--ic-primary-press) !important; }
.icw .icw-btn-hero { height:44px; font-size:15px; padding:0 22px; border-radius:10px; min-width: 220px; }
.icw .icw-btn-secondary { background: var(--ic-surface) !important; color: var(--ic-ink) !important; border:1px solid var(--ic-border-strong) !important; }
.icw .icw-btn-secondary:hover:not(:disabled) { background: var(--ic-subtle) !important; border-color:#9fb1c9 !important; }
.icw .icw-btn-quiet { background: transparent !important; color: var(--ic-primary) !important; border:1px solid transparent !important; }
.icw .icw-btn-quiet:hover:not(:disabled) { background: var(--ic-primary-soft) !important; }
.icw .icw-btn-danger { background: var(--ic-surface) !important; color: var(--ic-danger) !important; border:1px solid #efb7b0 !important; }
.icw .icw-btn-danger:hover:not(:disabled) { background: var(--ic-danger-soft) !important; border-color: var(--ic-danger) !important; }
.icw .icw-btn-danger-solid { background: var(--ic-danger) !important; color:#fff !important; border:1px solid var(--ic-danger) !important; }
.icw .icw-btn-busy { position: relative; color: transparent !important; pointer-events:none; }
.icw .icw-btn-busy::after { content:""; position:absolute; inset:0; margin:auto; width:16px; height:16px; border-radius:50%;
  border:2px solid rgba(255,255,255,.55); border-top-color:#fff; animation: icw-spin .8s linear infinite; }
.icw .icw-btn-secondary.icw-btn-busy::after { border-color: rgba(29,95,184,.25); border-top-color: var(--ic-primary); }
.icw-actions { display:flex !important; gap:8px; flex-wrap:wrap; align-items:center; }
.icw-actions.end { justify-content:flex-end; }

/* ── badges / status ───────────────────────────────────────────────── */
.icw-badge { display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:650;
  border:1px solid transparent; white-space:nowrap; line-height:1.4; transition: background var(--ic-med), color var(--ic-med); }
.icw-badge .dot { width:7px; height:7px; border-radius:50%; background: currentColor; }
.icw-badge.neutral { background: var(--ic-subtle); color: var(--ic-muted); border-color: var(--ic-border); }
.icw-badge.info, .icw-badge.preparing, .icw-badge.submitted { background: var(--ic-info-soft); color: var(--ic-info); border-color:#c9daf3; }
.icw-badge.queued { background: #f1edfb; color:#5b3fb0; border-color:#dcd2f5; }
.icw-badge.running { background: var(--ic-info-soft); color: var(--ic-info); border-color:#c9daf3; }
.icw-badge.running .dot, .icw-badge.preparing .dot, .icw-badge.submitted .dot, .icw-badge.queued .dot { animation: icw-pulse 1.4s ease-in-out infinite; }
.icw-badge.ok, .icw-badge.completed { background: var(--ic-success-soft); color: var(--ic-success); border-color:#c6e6d2; }
.icw-badge.warn { background: var(--ic-warn-soft); color: var(--ic-warn); border-color:#f1d79b; }
.icw-badge.bad, .icw-badge.failed { background: var(--ic-danger-soft); color: var(--ic-danger); border-color:#f3c6c1; }
.icw-badge.cancelled { background: #f2f4f7; color:#475467; border-color:#d0d5dd; }
.icw-badges { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.icw-spinner { width:14px; height:14px; border-radius:50%; border:2px solid rgba(29,95,184,.22); border-top-color: var(--ic-primary);
  display:inline-block; animation: icw-spin .8s linear infinite; vertical-align:-2px; }

/* ── mode selector ─────────────────────────────────────────────────── */
.icw-modes .widget-toggle-buttons, .icw-modes .widget-toggle-buttons > div { width:100% !important; }
.icw-modes .widget-toggle-buttons > div { display:grid !important; grid-template-columns: repeat(3, minmax(0,1fr)); gap:8px; width:100%; }
.icw-modes .widget-toggle-button { height:auto !important; min-height:58px; width:100% !important; margin:0 !important; padding:10px 14px !important;
  display:flex; flex-direction:row-reverse; align-items:center; justify-content:flex-end; gap:10px; text-align:left; white-space:normal;
  background: var(--ic-surface) !important; border:1px solid var(--ic-border-strong) !important; border-radius:10px !important;
  color: var(--ic-ink) !important; font-size:14px; font-weight:700; box-shadow:none !important;
  transition: border-color var(--ic-fast), box-shadow var(--ic-med) var(--ic-ease), background var(--ic-med); }
.icw-modes .widget-toggle-button:hover { border-color: #8fa7c7 !important; background: var(--ic-subtle) !important; }
.icw-modes .widget-toggle-button.mod-active { border-color: var(--ic-primary) !important; background: var(--ic-primary-soft) !important;
  box-shadow: 0 0 0 3px rgba(29,95,184,.14) !important; color: var(--ic-primary) !important; }
.icw-modes .widget-toggle-button i { font-size:18px; width:34px; height:34px; border-radius:9px; display:inline-flex; align-items:center;
  justify-content:center; background: var(--ic-subtle); color: var(--ic-muted); transition: background var(--ic-med), color var(--ic-med); }
.icw-modes .widget-toggle-button.mod-active i { background: var(--ic-primary); color:#fff; }
.icw-tabs .widget-toggle-button, .icw-segment .widget-toggle-button { display:inline-flex !important; flex-direction:row-reverse; align-items:center; gap:7px; }
.icw-tabs .widget-toggle-button i { font-size:13px; opacity:.85; }
.icw-mode-note { margin-top:2px; font-size:12.5px; line-height:1.5; color: var(--ic-muted); animation: icw-fade var(--ic-med) var(--ic-ease); }

/* ── tabs (workspace) ──────────────────────────────────────────────── */
.icw-tabs .widget-toggle-buttons > div { display:flex !important; gap:2px; border-bottom:1px solid var(--ic-border); width:100%; flex-wrap:wrap; }
.icw-tabs .widget-toggle-button { background: transparent !important; border:0 !important; border-bottom: 2px solid transparent !important;
  border-radius: 0 !important; box-shadow:none !important; color: var(--ic-muted) !important; font-weight:650; font-size:13.5px;
  height:38px !important; width:auto !important; padding: 0 14px !important; margin:0 !important; transition: color var(--ic-fast), border-color var(--ic-med) var(--ic-ease); }
.icw-tabs .widget-toggle-button:hover { color: var(--ic-ink) !important; background: var(--ic-subtle) !important; }
.icw-tabs .widget-toggle-button.mod-active { color: var(--ic-primary) !important; border-bottom-color: var(--ic-primary) !important; }
.icw-pane { animation: icw-rise var(--ic-med) var(--ic-ease); padding-top: 12px; min-width:0; width:100%; }
.icw .widget-stack, .icw .lm-StackedPanel { width:100%; }
.icw-segment .widget-toggle-buttons > div { display:inline-flex !important; background: var(--ic-subtle); border:1px solid var(--ic-border); border-radius:9px; padding:2px; gap:2px; }
.icw-segment .widget-toggle-button { height:28px !important; width:auto !important; padding:0 12px !important; margin:0 !important; border:0 !important; border-radius:7px !important;
  background: transparent !important; box-shadow:none !important; color: var(--ic-muted) !important; font-size:12.5px; font-weight:650; }
.icw-segment .widget-toggle-button.mod-active { background: var(--ic-surface) !important; color: var(--ic-ink) !important; box-shadow: 0 1px 2px rgba(16,24,40,.12) !important; }

/* ── context bar ───────────────────────────────────────────────────── */
.icw-context { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;
  padding:10px 12px; border-radius:10px; background: var(--ic-subtle); border:1px solid var(--ic-border); }
.icw-context .name { font-weight:700; color: var(--ic-ink); font-size:13.5px; }
.icw-context .meta { color: var(--ic-muted); font-size:12px; margin-top:1px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

/* ── summary / key-value / tables ──────────────────────────────────── */
.icw dl.icw-kv { display:grid !important; grid-template-columns: max-content minmax(0,1fr); gap:4px 14px; font-size:13px; margin:0; line-height:1.45; }
.icw dl.icw-kv dt { color: var(--ic-muted); float:none !important; width:auto !important; clear:none !important; text-align:left !important; margin:0 !important; font-weight:500; }
.icw dl.icw-kv dd { margin:0 !important; color: var(--ic-ink); font-weight:600; overflow-wrap:anywhere; }
.icw dl.icw-kv dd code, .icw code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; background: var(--ic-subtle);
  border:1px solid var(--ic-border); border-radius:5px; padding:1px 5px; font-weight:500; }
.icw-table { width:100%; border-collapse: collapse; font-size:12.5px; }
.icw-table th { text-align:left; color: var(--ic-muted); font-weight:650; padding:6px 8px; border-bottom:1px solid var(--ic-border); position:sticky; top:0; background:var(--ic-surface); }
.icw-table td { padding:6px 8px; border-bottom:1px solid #edf1f6; vertical-align:top; }
.icw-table td.num { text-align:right; font-variant-numeric: tabular-nums; font-family: ui-monospace, Menlo, monospace; }
.icw-table tr:hover td { background: #fafcff; }
.icw-scroll { max-height: 420px; overflow:auto; border:1px solid var(--ic-border); border-radius:10px; }

/* ── callouts, validation, empty states, skeletons ─────────────────── */
.icw-callout { display:flex; gap:10px; padding:10px 12px; border-radius:10px; font-size:13px; line-height:1.45; border:1px solid; animation: icw-rise var(--ic-med) var(--ic-ease); }
.icw-callout .ico { font-size:15px; line-height:1.2; }
.icw-callout.info { background: var(--ic-info-soft); border-color:#c9daf3; color:#18427f; }
.icw-callout.ok { background: var(--ic-success-soft); border-color:#c6e6d2; color:#145c33; }
.icw-callout.warn { background: var(--ic-warn-soft); border-color:#f1d79b; color:#6f4700; }
.icw-callout.bad { background: var(--ic-danger-soft); border-color:#f3c6c1; color:#8c1d14; }
.icw-issues { list-style:none; margin:6px 0 0; padding:0; display:flex; flex-direction:column; gap:4px; }
.icw-issues li { display:flex; gap:8px; align-items:flex-start; font-size:12.5px; padding:6px 9px; border-radius:8px; animation: icw-rise var(--ic-med) var(--ic-ease) both; }
.icw-issues li.error { background: var(--ic-danger-soft); color:#8c1d14; }
.icw-issues li.warning { background: var(--ic-warn-soft); color:#6f4700; }
.icw-issues li.info { background: var(--ic-subtle); color: var(--ic-muted); }
.icw-issues li .ln { font-family: ui-monospace, Menlo, monospace; font-size:11px; opacity:.8; white-space:nowrap; }
.icw-empty { text-align:center; padding:34px 18px; color: var(--ic-muted); border:1px dashed var(--ic-border-strong); border-radius:12px; background: linear-gradient(180deg, #fbfcfe, #f6f8fb); }
.icw-empty .ico { font-size:26px; opacity:.6; } .icw-empty h4 { margin:8px 0 4px; color: var(--ic-ink); font-size:14.5px; } .icw-empty p { margin:0 auto; max-width:440px; font-size:12.8px; line-height:1.5; }
.icw-skel { display:flex; flex-direction:column; gap:9px; padding:6px 0; }
.icw-skel i { display:block; height:12px; border-radius:6px; background: linear-gradient(90deg, #eef2f7 25%, #e2e8f0 37%, #eef2f7 63%); background-size: 400% 100%; animation: icw-shimmer 1.3s ease infinite; }
.icw-skel i.tall { height: 260px; border-radius:10px; }
.icw-flash { animation: icw-flash 1.6s var(--ic-ease); }

/* ── run panel / progress / timeline ───────────────────────────────── */
.icw-progress { height:8px; border-radius:999px; background: #e6ecf4; overflow:hidden; position:relative; }
.icw-progress > span { display:block; height:100%; border-radius:999px; background: linear-gradient(90deg, #2c74d6, #1d5fb8); transition: width .6s var(--ic-ease); }
.icw-progress.indeterminate > span { width:35% !important; animation: icw-indet 1.4s ease-in-out infinite; }
.icw-runhead { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.icw-runhead .big { font-size:20px; font-weight:750; color: var(--ic-ink); font-variant-numeric: tabular-nums; }
.icw-timeline { list-style:none; margin:0; padding:0 0 0 2px; display:flex; flex-direction:column; gap:0; }
.icw-timeline li { position:relative; padding: 0 0 10px 18px; font-size:12.5px; color: var(--ic-text); }
.icw-timeline li::before { content:""; position:absolute; left:3px; top:5px; width:8px; height:8px; border-radius:50%; background: var(--ic-border-strong); }
.icw-timeline li::after { content:""; position:absolute; left:6px; top:15px; bottom:0; width:2px; background: var(--ic-border); }
.icw-timeline li:last-child::after { display:none; }
.icw-timeline li.completed::before { background: var(--ic-success); } .icw-timeline li.failed::before { background: var(--ic-danger); }
.icw-timeline li.running::before, .icw-timeline li.queued::before, .icw-timeline li.submitted::before, .icw-timeline li.preparing::before { background: var(--ic-primary); }
.icw-timeline .at { color: var(--ic-faint); font-family: ui-monospace, Menlo, monospace; font-size:11px; margin-left:6px; }
.icw-timeline .why { display:block; color: var(--ic-muted); font-size:12px; }

/* ── runs list ─────────────────────────────────────────────────────── */
.icw-runlist .widget-select select, .icw-runlist select { font-family: ui-monospace, Menlo, monospace; font-size:12.5px; border-radius:10px !important; padding:4px; }

/* ── logs / editor ─────────────────────────────────────────────────── */
.icw-log { background:#0f1726; color:#dbe5f3; border-radius:10px; padding:10px 12px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  max-height: 520px; min-height: 160px; overflow:auto; white-space: pre-wrap; word-break: break-word; margin:0; }
.icw-log .err { color:#ff9b91; } .icw-log .warn { color:#f5cf7a; } .icw-log .ok { color:#8fe0a8; } .icw-log .mute { color:#8a9ab3; }
.icw .icw-activity .output_area pre, .icw .icw-activity pre { font-size:12px !important; }
.icw-activity { max-height: 360px; overflow:auto; border:1px solid var(--ic-border); border-radius:10px; padding:6px 10px; background: var(--ic-subtle); }
.icw-editor textarea { font: 12.5px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace !important; min-height: 380px; background:#fbfcfe !important; tab-size: 2; }
.icw-editor.readonly textarea { background: #f4f6f9 !important; color:#3b4659 !important; }
.icw-filelist .widget-select select { font-size:12.5px; border-radius:10px !important; }
.icw-files-head { display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; }

/* ── results ───────────────────────────────────────────────────────── */
.icw-viewpick .widget-toggle-buttons > div { display:flex !important; flex-wrap:wrap; gap:6px; }
.icw-viewpick .widget-toggle-button { width:auto !important; height:auto !important; min-height:32px; padding:5px 12px !important; margin:0 !important;
  border-radius:999px !important; border:1px solid var(--ic-border-strong) !important; background: var(--ic-surface) !important; box-shadow:none !important;
  color: var(--ic-text) !important; font-size:12.5px; font-weight:600; white-space:normal; transition: all var(--ic-fast); }
.icw-viewpick .widget-toggle-button:hover { border-color:#8fa7c7 !important; }
.icw-viewpick .widget-toggle-button.mod-active { background: var(--ic-primary) !important; color:#fff !important; border-color: var(--ic-primary) !important; }
.icw-figure { border:1px solid var(--ic-border); border-radius:12px; overflow:hidden; background:#fff; animation: icw-rise var(--ic-med) var(--ic-ease); }
.icw-figure header { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; padding:10px 12px; border-bottom:1px solid var(--ic-border); background: var(--ic-subtle); }
.icw-figure header h4 { margin:0; font-size:14px; color: var(--ic-ink); } .icw-figure header .src { font-size:11.5px; color: var(--ic-muted); margin-top:2px; }
.icw-figure .plot { padding:10px; text-align:center; background:#fff; }
.icw-figure .plot img { max-width:100%; height:auto; cursor: zoom-in; transition: transform var(--ic-med) var(--ic-ease); }
.icw-figure footer { padding:8px 12px 10px; font-size:12px; color: var(--ic-muted); border-top:1px solid #eef2f6; }
.icw-figure footer ul { margin:0; padding-left:18px; }
.icw-chiprow { display:flex; gap:6px; flex-wrap:wrap; }
.icw-chip { font-size:11.5px; padding:2px 8px; border-radius:6px; background: var(--ic-subtle); border:1px solid var(--ic-border); color: var(--ic-text); }
.icw-chip b { color: var(--ic-ink); }
.icw-lightbox { position:fixed; inset:0; background: rgba(15,23,38,.82); display:flex; align-items:center; justify-content:center; z-index:9999; animation: icw-fade var(--ic-fast); cursor: zoom-out; padding:24px; }
.icw-lightbox img { max-width: 96vw; max-height: 92vh; background:#fff; border-radius:8px; }

/* ── accordion (params) ────────────────────────────────────────────── */
.icw .lm-Collapse-contents, .icw .p-Collapse-contents { animation: icw-rise var(--ic-med) var(--ic-ease); }
.icw .lm-Collapse-header, .icw .p-Collapse-header { border-radius: 8px; transition: background var(--ic-fast); }

/* ── motion ────────────────────────────────────────────────────────── */
@keyframes icw-spin { to { transform: rotate(360deg); } }
@keyframes icw-fade { from { opacity:0 } to { opacity:1 } }
@keyframes icw-rise { from { opacity:0; transform: translateY(4px) } to { opacity:1; transform:none } }
@keyframes icw-pulse { 0%,100% { opacity:1 } 50% { opacity:.35 } }
@keyframes icw-shimmer { 0% { background-position: 100% 50% } 100% { background-position: 0 50% } }
@keyframes icw-indet { 0% { margin-left:-35% } 100% { margin-left:100% } }
@keyframes icw-flash { 0% { box-shadow: 0 0 0 0 rgba(29,127,70,.0) } 20% { box-shadow: 0 0 0 4px rgba(29,127,70,.25) } 100% { box-shadow: 0 0 0 0 rgba(29,127,70,0) } }
@media (prefers-reduced-motion: reduce) {
  .icw *, .icw *::before, .icw *::after { animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; }
}
</style>
"""


def stylesheet() -> W.HTML:
    return W.HTML(CSS)
