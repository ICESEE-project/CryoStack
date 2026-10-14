"""Results-tab panel for an ICESEE run's DA progress, checkpoints and phase
timings -- a pure HTML rendering of
:class:`icesee_jupyter_book.core.run_monitor.RunProgressReport`. Every value
is HTML-escaped; anything the run did not report is shown as such.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from icesee_jupyter_book.core.run_monitor import (
    NOT_REPORTED,
    RunProgressReport,
    inspect_run_progress,
)

_TABLE = "width:100%;border-collapse:collapse;font-size:12.5px;margin:4px 0 10px"
_CELL = "padding:3px 8px;border-bottom:1px solid rgba(127,127,127,.25);text-align:left;vertical-align:top"


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def _when(ts: float | None) -> str:
    if ts is None:
        return NOT_REPORTED
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return NOT_REPORTED


def _table(header: tuple, rows: list) -> str:
    head = "".join(f"<th style='{_CELL}'>{escape(str(h))}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td style='{_CELL}'>{escape(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f"<table style='{_TABLE}'><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _heading(text: str) -> str:
    return f"<div style='font-weight:600;margin-top:8px'>{escape(text)}</div>"


def _step_range(steps: tuple) -> str:
    if not steps:
        return "none"
    first, last = steps[0].step, steps[-1].step
    return f"{len(steps)} files, steps {first}..{last}"


def render_run_progress_html(report: RunProgressReport) -> str:
    parts = ["<div class='icesee-card' style='padding:10px 12px'>",
             "<div style='font-weight:700'>Data assimilation progress</div>",
             "<div class='icesee-subtle'>Read from files this run wrote; "
             "nothing here is estimated.</div>"]
    parts.append(_table(("Item", "Value"), report.summary_rows()))

    checkpoints = report.checkpoints()
    parts.append(_heading("Checkpoints"))
    if checkpoints:
        rows = []
        for ckpt in checkpoints:
            step = (f"last_done_k={ckpt.last_done_k}" if ckpt.last_done_k is not None
                    else ckpt.problem or ckpt.state)
            rows.append((ckpt.file.path, ckpt.state, step, _size(ckpt.file.size),
                         _when(ckpt.timestamp if ckpt.timestamp is not None else ckpt.file.mtime)))
            if ckpt.crash_message:
                rows.append(("", "crash", ckpt.crash_message, "", ""))
        parts.append(_table(("File", "State", "Step", "Size", "Saved"), rows))
    else:
        parts.append(f"<div class='icesee-subtle'>No ICESEE checkpoint: {NOT_REPORTED}.</div>")

    if report.dataset_dirs:
        rows = []
        for d in report.dataset_dirs:
            history = (f"{_size(d.ensemble_history.size)}"
                       + (f", shape {list(d.ensemble_history_shape)}" if d.ensemble_history_shape else "")
                       if d.ensemble_history else "none")
            rows.append((d.path, _step_range(d.resume_steps), _step_range(d.io_steps),
                         history, len(d.member_files)))
        parts.append(_heading("ICESEE data directories"))
        parts.append(_table(("Directory", "Step files (resume)", "Step files (I/O)",
                             "Ensemble history", "Member files"), rows))

    parts.append(_heading("Phase timings"))
    timings = report.timings
    if timings is not None:
        wall = timings.seconds("Wall-Clock Time (max)")
        rows = []
        for label, seconds in timings.phases:
            share = f"{100.0 * seconds / wall:.1f}%" if wall else ""
            if label.startswith("Computational"):
                share = "sum over ranks"
            rows.append((label, f"{seconds:.3f}", share))
        parts.append(_table(("Phase", "Seconds", "Share of wall clock"), rows))
        ranks = f"; ICESEE-reported ranks {timings.reported_ranks}" if timings.reported_ranks else ""
        parts.append(
            f"<div class='icesee-subtle'>Source: {escape(timings.source)}{escape(ranks)}. "
            "Phase times are the maximum over ranks; MPI communication is not "
            "timed separately by ICESEE.</div>"
        )
    else:
        parts.append(f"<div class='icesee-subtle'>Phase timings: {NOT_REPORTED}.</div>")

    notes = list(report.resume.notes)
    if report.log.error_lines:
        notes.append("Last error lines: " + " | ".join(report.log.error_lines))
    if report.log.truncated:
        notes.append("Log larger than the read limit; only its tail was parsed.")
    if report.walk_truncated:
        notes.append("Run directory larger than the scan limit; the listing is partial.")
    if report.skipped:
        notes.append("Skipped links outside the run directory: " + ", ".join(report.skipped[:10]))
    if notes:
        parts.append("<ul class='icesee-subtle' style='margin:6px 0 0 16px;padding:0'>"
                     + "".join(f"<li>{escape(n)}</li>" for n in notes) + "</ul>")
    parts.append("</div>")
    return "".join(parts)


def run_progress_html(run_dir: "Path | str") -> str:
    """Inspect + render; an unexpected failure renders a notice, never raises."""
    try:
        return render_run_progress_html(inspect_run_progress(run_dir))
    except Exception as exc:  # noqa: BLE001 - must never break the Results tab
        return ("<div class='icesee-subtle'>Data assimilation progress unavailable: "
                f"{escape(type(exc).__name__)}.</div>")
