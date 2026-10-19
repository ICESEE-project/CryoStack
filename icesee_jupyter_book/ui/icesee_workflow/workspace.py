"""The right-hand workspace: one selected run is the shared context for
Run (overview, lifecycle, provenance, actions), Files, Logs and Results; the
Editor works on the experiment being configured for the next run.

Every pane shows a loading skeleton while it fetches, an explicit empty
state when there is nothing to show, and never blocks the page: discovery,
rendering and packaging run on worker threads and stale answers (the user
selected another run meanwhile) are dropped.
"""
from __future__ import annotations

import html
import io
import json
import re
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import ipywidgets as W
import yaml

from icesee_jupyter_book.core import provenance as prov
from icesee_jupyter_book.core import results_service as rs
from icesee_jupyter_book.core import run_lifecycle as lc
from icesee_jupyter_book.core.experiment_files import (
    ExperimentFileError, ExperimentFiles, config_text, validate,
)
from icesee_jupyter_book.core.local_jobs import LOG_FILE, LocalJob, clean_log
from icesee_jupyter_book.core.results_package import _categorize

from .components import (
    BusyButton, ConfirmAction, badge, button, callout, code, empty_state, esc, human_duration, human_size,
    image_html, issues_html, kv, offer_download, skeleton, state_badge,
)

TABS = ("Run", "Files", "Editor", "Logs", "Results")
TAB_ICONS = ("play-circle", "folder-open", "pencil", "terminal", "line-chart")
_MODE_LABEL = {"local": "Local", "remote": "Remote HPC", "cluster": "Remote HPC", "cloud": "Cloud"}
_HIDDEN_FILES = {".icesee-results", "__pycache__", ".ipynb_checkpoints"}
#: dataset roles from ICESEE's own dataset names (core/results_package.py)
_DA_ROLE = {"forecast": "Forecast / truth", "ensemble": "Ensemble", "observations": "Observations",
            "model_native": "Other"}


def _ts(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("T", " ")


def run_label(run) -> str:
    state = lc.current_state(run)
    mark = {"completed": "✓", "failed": "✕", "cancelled": "–", "running": "●", "queued": "◷",
            "submitted": "◷", "preparing": "◌"}.get(state, "·")
    meta = run.metadata or {}
    example = re.sub(r"\s*\(.*\)$", "", str(meta.get("example") or "run"))
    when = run.created.strftime("%b %d %H:%M") if isinstance(run.created, datetime) else ""
    return f"{mark} {when}  {example} · {_MODE_LABEL.get(run.execution_mode, run.execution_mode)} · {lc.LABELS.get(state, run.status)}"


class RunWorkspace:
    """Builds and drives the workspace. ``host`` is the gateway adapter
    (see WorkflowHost in __init__)."""

    def __init__(self, host):
        self.host = host
        self.manager = host.runs_manager
        self.selected = None
        self._gen = 0
        self._log_follow = True
        self._results = None
        self._result_gen = 0
        self._busy_threads: set = set()

        # ── context bar ──────────────────────────────────────────────────
        self.context = W.HTML()
        self.context.add_class("icw-context-wrap")

        # ── tabs ─────────────────────────────────────────────────────────
        self.tabs = W.ToggleButtons(options=list(TABS), value="Run", icons=list(TAB_ICONS),
                                    tooltips=["Selected run: status, provenance and actions",
                                              "Files the selected run produced", "Edit the experiment's configuration",
                                              "Model output and launcher activity", "Scientific results of the selected run"],
                                    style={"button_width": "auto"})
        tabbar = W.Box([self.tabs])
        tabbar.add_class("icw-tabs")
        self.tabbar = tabbar
        self.run_pane = self._build_run_pane()
        self.files_pane = self._build_files_pane()
        self.editor_pane = self._build_editor_pane()
        self.logs_pane = self._build_logs_pane()
        self.results_pane = self._build_results_pane()
        panes = [self.run_pane, self.files_pane, self.editor_pane, self.logs_pane, self.results_pane]
        for p in panes:
            p.add_class("icw-pane")
            p.layout.width = "100%"
        self.stack = W.Stack(panes, selected_index=0, layout=W.Layout(width="100%"))
        self.tabs.observe(self._on_tab, names="value")
        self.downloader = W.Output(layout=W.Layout(height="0px", overflow="hidden"))

        head = W.HTML('<div class="icw-card-head"><div><div class="icw-card-title">Workspace</div>'
                      '<div class="icw-card-sub">Everything below follows the selected run.</div></div></div>')
        self.container = W.VBox([head, self.context, tabbar, self.stack, self.downloader],
                                layout=W.Layout(width="100%", gap="10px"))
        self.container.add_class("icw-card")
        self.container.add_class("icw-right")
        self.container.add_class("cryostack-output-workspace")
        self._render_context()

    # ── navigation ─────────────────────────────────────────────────────────
    def show(self, tab: str) -> None:
        if tab in TABS:
            self.tabs.value = tab

    def _on_tab(self, change) -> None:
        self.stack.selected_index = TABS.index(change["new"])
        self._refresh_visible()

    def _refresh_visible(self) -> None:
        tab = self.tabs.value
        if tab == "Files":
            self.refresh_files()
        elif tab == "Results":
            self.refresh_results()
        elif tab == "Logs":
            self.refresh_log()
        elif tab == "Editor":
            self.editor_refresh_list()
        self.host.on_workspace_tab(tab)

    # ── run selection ──────────────────────────────────────────────────────
    def refresh_runs(self, select: str | None = None) -> None:
        runs = self.manager.refresh()
        for run in runs:                                  # settle local runs whose process ended
            if run.execution_mode == "local" and lc.current_state(run) in lc.ACTIVE:
                self.host.reconcile(run)
        runs = self.manager.refresh()
        options = [(run_label(r), r.id) for r in runs]
        keep = select or (self.selected.id if self.selected else None)
        self.run_list.options = options or [("No runs yet", "")]
        self.run_list.layout.display = "" if options else "none"
        self.primary_actions.layout.display = "" if options else "none"
        self.secondary_actions.layout.display = "" if options else "none"
        values = [v for _l, v in self.run_list.options]
        self.run_list.value = keep if keep in values else (values[0] if values and values[0] else values[0])
        if not runs:
            self._select(None)

    def select_run(self, run_id: str | None, *, tab: str | None = None) -> None:
        if run_id and run_id in [v for _l, v in self.run_list.options]:
            if self.run_list.value != run_id:
                self.run_list.value = run_id          # fires _on_run_list
            else:
                self._select(run_id)
        if tab:
            self.show(tab)

    def _on_run_list(self, change) -> None:
        self._select(change["new"] or None)

    def _select(self, run_id: str | None) -> None:
        self._gen += 1
        self.selected = self.manager.select_run(run_id) if run_id else None
        self._results = None
        self._render_context()
        self._render_run_details()
        self._refresh_visible()
        self.host.on_run_selected(self.selected)

    def reload_selected(self) -> None:
        if self.selected:
            self.manager.refresh()
            self.selected = self.manager.select_run(self.selected.id)
            for i, (_label, value) in enumerate(self.run_list.options):
                if value == self.selected.id:
                    opts = list(self.run_list.options)
                    opts[i] = (run_label(self.selected), value)
                    self.run_list.options = opts
                    self.run_list.value = value
                    break
        self._render_context()
        self._render_run_details()

    def _render_context(self) -> None:
        run = self.selected
        if run is None:
            self.context.value = ('<div class="icw-context" aria-live="polite"><div><div class="name">No run selected</div>'
                                  '<div class="meta">Launch a run or pick one from the Run tab.</div></div>'
                                  f'{badge("Idle", "neutral")}</div>')
            return
        meta = run.metadata or {}
        state = lc.current_state(run)
        mode = _MODE_LABEL.get(run.execution_mode, run.execution_mode)
        chips = " · ".join(x for x in (mode, run.backend, meta.get("assimilation_filter"),
                                        f"N={meta.get('ensemble_size')}" if meta.get("ensemble_size") else "") if x)
        self.context.value = (f'<div class="icw-context" aria-live="polite"><div><div class="name">'
                              f'{esc(str(meta.get("example") or run.name))}</div>'
                              f'<div class="meta">{esc(run.id)} · {esc(chips)}</div></div>'
                              f'{state_badge(state, detail=str(meta.get("final_detail") or ""))}</div>')

    # ═════════════════════════════════════════════════════════════════════
    # Run pane
    # ═════════════════════════════════════════════════════════════════════
    def _build_run_pane(self) -> W.VBox:
        self.run_list = W.Select(options=[("Loading runs…", "")], rows=7, layout=W.Layout(width="100%"))
        self.run_list.add_class("icw-runlist")
        self.run_list.observe(self._on_run_list, names="value")
        self.refresh_btn = button("Refresh", icon="refresh", kind="secondary", tooltip="Reload the run history and statuses")
        self.refresh_btn.on_click(lambda _b: self._refresh_statuses())
        self.details = W.HTML(skeleton(4))
        self.open_results_btn = button("Open results", icon="line-chart", kind="primary")
        self.open_results_btn.on_click(lambda _b: self.show("Results"))
        self.view_logs_btn = button("View logs", icon="terminal", kind="secondary")
        self.view_logs_btn.on_click(lambda _b: self.show("Logs"))
        #: the gateway's Remote / Cloud "Check status" buttons (they act on the selected run)
        self.backend_actions = W.HBox([])
        self.backend_actions.add_class("icw-actions")
        self.rerun_btn = button("Reuse configuration", icon="repeat", kind="secondary",
                                tooltip="Load this run's example, mode and params.yaml into the form for a new run")
        self.rerun_btn.on_click(lambda _b: self.host.reuse_configuration(self.selected))
        self.bundle_btn = button("Reproducibility bundle", icon="download", kind="secondary",
                                 tooltip="params.yaml, provenance.json, manifest, logs and edited inputs (.zip)")
        self.bundle_btn.on_click(lambda _b: self._download_bundle())
        self.cancel_btn = button("Cancel run", icon="stop", kind="danger")
        self.cancel_confirm = ConfirmAction(self.cancel_btn, lambda: self._threaded(self._cancel_selected),
                                            confirm_label="Confirm cancel")
        self.delete_btn = button("Delete run", icon="trash", kind="danger")
        self.delete_confirm = ConfirmAction(self.delete_btn, self._delete_selected, confirm_label="Delete permanently")
        self.run_msg = W.HTML()
        top = W.HBox([W.HTML('<div class="icw-card-sub" style="margin:0">Run history</div>'), self.refresh_btn],
                      layout=W.Layout(justify_content="space-between", align_items="center"))
        self.primary_actions = W.HBox([self.open_results_btn, self.view_logs_btn, self.backend_actions])
        self.primary_actions.add_class("icw-actions")
        self.secondary_actions = W.HBox([self.rerun_btn, self.bundle_btn, self.cancel_confirm.box, self.delete_confirm.box])
        self.secondary_actions.add_class("icw-actions")
        return W.VBox([top, self.run_list, self.primary_actions, self.details, self.secondary_actions, self.run_msg],
                      layout=W.Layout(gap="10px"))

    def _render_run_details(self) -> None:
        run = self.selected
        self.run_msg.value = ""
        for b in (self.open_results_btn, self.view_logs_btn, self.rerun_btn, self.bundle_btn):
            b.disabled = run is None
        if run is None:
            self.details.value = empty_state("No run selected",
                                             "Runs you launch appear here with their status, configuration and "
                                             "provenance. Configure an experiment on the left and launch it.", "▶")
            self.cancel_confirm.box.layout.display = "none"
            self.delete_confirm.box.layout.display = "none"
            return
        state = lc.current_state(run)
        meta = run.metadata or {}
        active = state in lc.ACTIVE
        self.cancel_confirm.box.layout.display = "" if active else "none"
        self.delete_confirm.box.layout.display = "none" if active else ""
        self.open_results_btn.disabled = state not in (lc.COMPLETED, lc.FAILED) and run.execution_mode == "local"

        events = meta.get("lifecycle") or []
        timeline = "".join(
            f'<li class="{esc(e.get("state", ""))}"><b>{esc(lc.LABELS.get(e.get("state"), e.get("state", "")))}</b>'
            f'<span class="at">{esc(_ts(e.get("at")))}</span>'
            + (f'<span class="why">{esc(str(e.get("detail")))}</span>' if e.get("detail") else "") + "</li>"
            for e in events) or f'<li class="{esc(state or "")}"><b>{esc(lc.LABELS.get(state, run.status))}</b></li>'
        started = next((e.get("at") for e in events if e.get("state") == "running"), None)
        duration = ""
        if run.finished and started:
            try:
                duration = human_duration((run.finished - datetime.fromisoformat(started)).total_seconds())
            except (TypeError, ValueError):
                duration = ""
        elif meta.get("elapsed_s"):
            duration = human_duration(meta.get("elapsed_s"))
        p = meta.get("provenance") or {}
        da = meta.get("da") or {}
        cmd = meta.get("command")
        cmd_text = " ".join(cmd) if isinstance(cmd, list) else (cmd or "")
        rows = [
            ("Run ID", code(run.id)),
            ("Job ID", code(run.jobid) if run.jobid else ""),
            ("Mode · backend", esc(f"{_MODE_LABEL.get(run.execution_mode, run.execution_mode)} · {run.backend}")),
            ("Target", esc(str(meta.get("run_target") or ""))),
            ("Created", esc(_ts(run.created))),
            ("Finished", esc(_ts(run.finished))),
            ("Duration", esc(duration)),
            ("Forecast model", esc(str(meta.get("forecast_model") or ""))),
            ("Filter · ensemble", esc(f"{meta.get('assimilation_filter') or '?'} · {meta.get('ensemble_size') or '?'} members")),
            ("Observations", esc(", ".join(map(str, (da.get("observations") or {}).get("observed_vars") or [])))),
            ("Output directory", code(run.workspace_directory)),
            ("Remote directory", code(run.remote_directory) if run.remote_directory else ""),
            ("Command", (f"<details><summary style='cursor:pointer'><code>{esc(cmd_text[:72])}"
                         f"{'…' if len(cmd_text) > 72 else ''}</code></summary><code>{esc(cmd_text[:4000])}</code>"
                         "</details>") if cmd_text else ""),
            ("params.yaml", code((p.get("params_sha256") or "")[:16] + "…") if p.get("params_sha256") else ""),
            ("Edited inputs", esc(", ".join(p.get("edited_inputs") or [])) or ("none" if p else "")),
            ("CryoLauncher", code((p.get("cryolauncher_commit") or "")[:12]) + (" <span class='icw-badge warn'>local changes</span>"
                                                                                  if p.get("cryolauncher_local_changes") else "")
             if p.get("cryolauncher_commit") else ""),
            ("ICESEE", code((p.get("icesee_upstream_commit") or "")[:12]) if p.get("icesee_upstream_commit") else ""),
            ("Environment", esc(str(p.get("image") or p.get("environment") or ""))),
        ]
        warn = ""
        if meta.get("warnings"):
            warn = callout("; ".join(map(str, meta["warnings"])), "warn", title="Note:")
        if state == lc.FAILED and meta.get("final_detail"):
            warn += callout(str(meta["final_detail"]), "bad", title="Failed:")
        params_snip = ""
        params_file = Path(run.workspace_directory) / "params.yaml"
        if params_file.is_file():
            text = params_file.read_text(encoding="utf-8", errors="replace")[:20000]
            params_snip = ('<details style="margin-top:8px"><summary style="cursor:pointer;font-weight:600;font-size:13px">'
                           f'Configuration snapshot (params.yaml)</summary><pre class="icw-log" style="max-height:300px">'
                           f'{esc(text)}</pre></details>')
        no_prov = "" if p else ('<div class="icw-card-sub" style="margin-top:6px">This run predates provenance '
                                'recording; only its manifest is available.</div>')
        extra = ""
        extra_html = getattr(self.host, "run_extra_html", None)
        if extra_html is not None:
            extra = extra_html(run) or ""
        self.details.value = (f'<div style="display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:14px">'
                              f'<div>{kv(rows)}{no_prov}</div><div><div class="icw-card-sub" style="margin:0 0 6px">Lifecycle</div>'
                              f'<ol class="icw-timeline">{timeline}</ol></div></div>{warn}{extra}{params_snip}')

    def _refresh_statuses(self) -> None:
        self.refresh_runs()
        self.run_msg.value = callout("Run history refreshed.", "ok")

    def _cancel_selected(self) -> None:
        run = self.selected
        if run is None:
            return
        self.run_msg.value = callout("Cancelling…", "info")
        ok, message = self.host.cancel_run(run)
        self.run_msg.value = callout(message, "ok" if ok else "bad")
        self.reload_selected()

    def _delete_selected(self) -> None:
        run = self.selected
        if run is None:
            return
        if lc.current_state(run) in lc.ACTIVE:
            self.run_msg.value = callout("Cancel the run before deleting it.", "warn")
            return
        if self.manager.delete_run(run.id):
            self.run_msg.value = callout(f"Deleted run {run.id}.", "ok")
            self.selected = None
            self.refresh_runs()
        else:
            self.run_msg.value = callout("This run could not be deleted (it is outside your workspace).", "bad")

    def _download_bundle(self) -> None:
        run = self.selected
        if run is None:
            return
        rd = Path(run.workspace_directory)
        buf = io.BytesIO()
        names = ["params.yaml", prov.PROVENANCE_FILE, ".cryostack-run.json", LOG_FILE, "postprocess.log"]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name in names:
                if (rd / name).is_file():
                    z.write(rd / name, arcname=name)
            p = prov.load(rd) or {}
            for rel in p.get("edited_inputs") or []:
                for cand in rd.glob(f"example/*/{rel}"):
                    z.write(cand, arcname=f"edited_inputs/{rel}")
        out = rd / ".icesee-results" / f"{run.id}-reproducibility.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(buf.getvalue())
        why = offer_download(self.downloader, out, mime="application/zip")
        self.run_msg.value = callout(why or "Reproducibility bundle downloaded.", "bad" if why else "ok")

    # ═════════════════════════════════════════════════════════════════════
    # Files pane
    # ═════════════════════════════════════════════════════════════════════
    def _build_files_pane(self) -> W.VBox:
        self.files_head = W.HTML()
        self.file_filter = W.Text(placeholder="Filter files…", layout=W.Layout(width="220px"))
        self.file_filter.observe(lambda _c: self.refresh_files(), names="value")
        self.file_list = W.Select(options=[], rows=12, layout=W.Layout(width="100%"))
        self.file_list.add_class("icw-filelist")
        self.file_list.observe(self._on_file, names="value")
        self.file_preview = W.HTML()
        self.file_dl = button("Download file", icon="download", kind="secondary")
        self.file_dl.on_click(lambda _b: self._download_file())
        self.outputs_dl = button("Download outputs (.zip)", icon="file-archive-o", kind="secondary",
                                 tooltip="All files the model wrote (_modelrun_datasets, results, figures)")
        self.outputs_dl_busy = BusyButton(self.outputs_dl)
        self.outputs_dl.on_click(lambda _b: self._threaded(lambda: self.outputs_dl_busy.run(
            self._download_outputs, busy_label="Packaging…", done_label="Ready", fail_label="Too large")))
        self.files_msg = W.HTML()
        head = W.HBox([self.files_head, self.file_filter], layout=W.Layout(justify_content="space-between",
                                                                         align_items="center"))
        actions = W.HBox([self.file_dl, self.outputs_dl])
        actions.add_class("icw-actions")
        return W.VBox([head, self.file_list, actions, self.files_msg, self.file_preview], layout=W.Layout(gap="8px"))

    def refresh_files(self) -> None:
        run = self.selected
        self.file_preview.value = ""
        self.files_msg.value = ""
        if run is None:
            self.files_head.value = '<div class="icw-card-sub" style="margin:0">No run selected</div>'
            self.file_list.options = []
            self.file_preview.value = empty_state("No run selected", "Select a run to browse its files.", "🗀")
            return
        rd = Path(run.workspace_directory)
        needle = (self.file_filter.value or "").strip().lower()
        entries = []
        total = 0
        for path in sorted(rd.rglob("*")):
            rel = path.relative_to(rd)
            if any(part in _HIDDEN_FILES for part in rel.parts) or not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            if needle and needle not in str(rel).lower():
                continue
            entries.append((f"{str(rel):<64}  {human_size(size):>9}", str(rel)))
        self.files_head.value = (f'<div class="icw-card-sub" style="margin:0">{len(entries)} files · '
                                 f'{human_size(total)} in <code>{esc(str(rd))}</code></div>')
        self.file_list.options = entries[:2000]
        if not entries:
            self.file_preview.value = empty_state("No files yet", "The run has not written anything.", "🗀")

    def _on_file(self, change) -> None:
        rel = change.get("new")
        if not rel or self.selected is None:
            self.file_preview.value = ""
            return
        path = Path(self.selected.workspace_directory) / rel
        if not path.resolve().is_relative_to(Path(self.selected.workspace_directory).resolve()):
            return
        size = path.stat().st_size
        if path.suffix.lower() == ".png" and size < 8 * 1024 * 1024:
            self.file_preview.value = f'<div class="icw-figure"><div class="plot">{image_html(path, alt=rel)}</div></div>'
            return
        if path.suffix.lower() in (".h5", ".hdf5"):
            self.file_preview.value = self._h5_summary(path)
            return
        raw = path.read_bytes()[:256 * 1024]
        if b"\x00" in raw[:4096]:
            self.file_preview.value = callout(f"{rel}: binary file ({human_size(size)}).", "info")
            return
        text = raw.decode("utf-8", "replace")
        if rel.endswith(".log"):
            text = clean_log(text)
        more = f"\n… ({human_size(size)} total; download for the rest)" if size > len(raw) else ""
        self.file_preview.value = f'<pre class="icw-log" style="max-height:360px">{esc(text)}{esc(more)}</pre>'

    @staticmethod
    def _h5_summary(path: Path) -> str:
        try:
            import h5py

            rows = []
            with h5py.File(path, "r") as f:
                def walk(group, prefix=""):
                    for key in group.keys():
                        obj = group[key]
                        if isinstance(obj, h5py.Group):
                            walk(obj, f"{prefix}{key}/")
                        else:
                            role = _DA_ROLE.get(_categorize(key), "")
                            rows.append(f"<tr><td>{esc(prefix + key)}</td><td>{esc(role)}</td>"
                                        f"<td class='num'>{esc(str(obj.shape))}</td><td>{esc(str(obj.dtype))}</td></tr>")
                walk(f)
            return ('<div class="icw-scroll"><table class="icw-table"><thead><tr><th>Dataset</th><th>DA role</th>'
                    f'<th>Shape</th><th>Type</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
        except Exception as exc:  # noqa: BLE001
            return callout(f"{path.name} could not be read: {exc}", "bad")

    def _download_file(self) -> None:
        rel = self.file_list.value
        if not rel or self.selected is None:
            self.files_msg.value = callout("Select a file first.", "warn")
            return
        why = offer_download(self.downloader, Path(self.selected.workspace_directory) / rel)
        self.files_msg.value = callout(why, "warn") if why else ""

    def _download_outputs(self):
        run = self.selected
        if run is None:
            return False
        rd = Path(run.workspace_directory)
        files = [p for d in ("_modelrun_datasets", "results", "figures", "outputs") for p in rd.rglob(f"{d}/*")
                 if p.is_file() and ".icesee-results" not in p.parts]
        files += [p for p in rd.glob("example/*/_modelrun_datasets/**/*") if p.is_file()]
        files = sorted(set(files))
        if not files:
            self.files_msg.value = callout("This run has no outputs to download yet.", "warn")
            return False
        total = sum(p.stat().st_size for p in files)
        from .components import MAX_DOWNLOAD_BYTES

        if total > MAX_DOWNLOAD_BYTES * 2:
            self.files_msg.value = callout(
                f"The outputs are {human_size(total)}; that is too large for a browser download. Download single files, "
                f"or copy them from {rd} on the server.", "warn")
            return False
        out = rd / ".icesee-results" / f"{run.id}-outputs.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, arcname=str(p.relative_to(rd)))
        why = offer_download(self.downloader, out, mime="application/zip")
        self.files_msg.value = callout(why, "warn") if why else callout(f"Outputs packaged ({human_size(out.stat().st_size)}).", "ok")
        return not why

    # ═════════════════════════════════════════════════════════════════════
    # Editor pane (experiment scoped)
    # ═════════════════════════════════════════════════════════════════════
    def _build_editor_pane(self) -> W.VBox:
        self.ed_head = W.HTML()
        self.ed_files = W.Dropdown(options=[], layout=W.Layout(width="100%"))
        self.ed_files.observe(self._ed_on_pick, names="value")
        self.ed_text = W.Textarea(layout=W.Layout(width="100%", height="420px"), continuous_update=True)
        self.ed_box = W.Box([self.ed_text], layout=W.Layout(width="100%"))
        self.ed_box.add_class("icw-editor")
        self.ed_text.observe(self._ed_on_type, names="value")
        self.ed_status = W.HTML()
        self.ed_status.add_class("icw-ed-status")
        self.ed_issues = W.HTML()
        self.ed_issues.add_class("icw-ed-issues")
        self.ed_apply = button("Apply to configuration", icon="check", kind="primary",  # noqa: E501
                               tooltip="Validate and load this params.yaml into the run configuration")
        self.ed_apply_busy = BusyButton(self.ed_apply)
        self.ed_apply.on_click(lambda _b: self.ed_apply_busy.run(self._ed_apply, busy_label="Validating…",
                                                                 done_label="Applied", fail_label="Not applied"))
        self.ed_save = button("Save draft", icon="save", kind="primary",
                              tooltip="Keep this edited input for your next Local runs")
        self.ed_save_busy = BusyButton(self.ed_save)
        self.ed_save.on_click(lambda _b: self.ed_save_busy.run(self._ed_save, busy_label="Saving…",
                                                               done_label="Saved", fail_label="Not saved"))
        self.ed_validate = button("Validate", icon="check-square-o", kind="secondary")
        self.ed_validate.on_click(lambda _b: self._ed_run_validation())
        self.ed_revert = button("Discard changes", icon="undo", kind="secondary",
                                tooltip="Reload the file as last saved / applied")
        self.ed_revert.on_click(lambda _b: self._ed_load(self.ed_files.value))
        self.ed_reset = button("Reset to example", icon="history", kind="danger")
        self.ed_reset_confirm = ConfirmAction(self.ed_reset, self._ed_reset, confirm_label="Discard my draft")
        actions = W.HBox([self.ed_apply, self.ed_save, self.ed_validate, self.ed_revert, self.ed_reset_confirm.box])
        actions.add_class("icw-actions")
        self._ed_clean = ""
        self._ed_info = None
        self._ed_suppress = False
        return W.VBox([self.ed_head, self.ed_files, self.ed_status, self.ed_issues, self.ed_box, actions],
                      layout=W.Layout(gap="8px"))

    @property
    def experiment(self) -> ExperimentFiles:
        return self.host.experiment_files()

    def editor_dirty(self) -> bool:
        return self._ed_info is not None and self._ed_info.editable and self.ed_text.value != self._ed_clean

    def editor_refresh_list(self) -> None:
        ex = self.experiment
        files = ex.files()
        icon = {"config": "⚙", "input": "✎", "source": "🔒", "reference": "📖"}
        options = []
        for f in files:
            tag = {"config": "configuration", "input": "input", "source": "code · read-only",
                   "reference": "reference · read-only"}[f.role]
            options.append((f"{icon[f.role]}  {f.path}   ({tag}{' · draft' if f.drafted else ''})", f.path))
        self.ed_head.value = (f'<div class="icw-card-sub" style="margin:0">Editing the <b>{esc(self.host.example_key())}</b> '
                              "experiment for your next run. params.yaml is the run configuration (the same values as "
                              "the form); edited inputs apply to Local runs.</div>")
        current = self.ed_files.value
        self._ed_suppress = True
        try:
            self.ed_files.options = options
            values = [v for _l, v in options]
            self.ed_files.value = current if current in values else (values[0] if values else None)
        finally:
            self._ed_suppress = False
        if not self.editor_dirty():
            self._ed_load(self.ed_files.value)

    def _ed_on_pick(self, change) -> None:
        if self._ed_suppress:
            return
        if self.editor_dirty():
            self.ed_status.value = callout("You have unsaved changes. Apply, save or discard them first.", "warn")
            self._ed_suppress = True
            self.ed_files.value = change["old"]
            self._ed_suppress = False
            return
        self._ed_load(change["new"])

    def _ed_load(self, rel) -> None:
        self.ed_issues.value = ""
        if not rel:
            self._ed_info = None
            self.ed_text.value = ""
            self.ed_status.value = empty_state("No files", "This experiment has no editable files.")
            return
        try:
            opened = self.experiment.open(rel)
        except ExperimentFileError as exc:
            self.ed_status.value = callout(str(exc), "bad")
            return
        info = opened.file
        if info.role == "config":
            text = config_text(self.host.current_config())
            origin = "current run configuration (form)"
        else:
            text = opened.text
            origin = "your draft" if opened.origin == "draft" else "the example"
        self._ed_info = info
        self._ed_suppress = True
        self.ed_text.value = text
        self._ed_suppress = False
        self._ed_clean = text
        self.ed_text.disabled = not info.editable
        if info.editable:
            self.ed_box.remove_class("readonly")
        else:
            self.ed_box.add_class("readonly")
        is_config = info.role == "config"
        self.ed_apply.layout.display = "" if is_config else "none"
        self.ed_save.layout.display = "" if (info.editable and not is_config) else "none"
        self.ed_validate.layout.display = "" if info.editable else "none"
        self.ed_revert.layout.display = "" if info.editable else "none"
        self.ed_reset_confirm.box.layout.display = "" if info.drafted else "none"
        self._ed_status(origin)

    def _ed_status(self, origin: str = "") -> None:
        info = self._ed_info
        if info is None:
            return
        role = {"config": badge("Configuration", "info", dot=False), "input": badge("Editable input", "ok", dot=False),
                "source": badge("Read-only code", "neutral", dot=False),
                "reference": badge("Read-only reference", "neutral", dot=False)}[info.role]
        state = ""
        if info.editable:
            state = badge("Unsaved changes", "warn") if self.editor_dirty() else badge("No changes", "neutral", dot=False)
        if info.drafted and info.role != "config":
            state += " " + badge("Using your draft", "info", dot=False)
        why = f'<div class="icw-card-sub">{esc(info.reason)}</div>' if info.reason else ""
        src = f'<div class="icw-card-sub">Showing {esc(origin)} · {human_size(info.size)}</div>' if origin else ""
        self.ed_status.value = f'<div class="icw-badges"><b style="font-size:13px">{esc(info.path)}</b> {role} {state}</div>{src}{why}'

    def _ed_on_type(self, _change) -> None:
        if self._ed_suppress:
            return
        self._ed_status()

    def _ed_run_validation(self):
        info = self._ed_info
        if info is None:
            return []
        issues = validate(info.path, self.ed_text.value, template=self.host.template())
        if issues:
            self.ed_issues.value = issues_html(issues)
        else:
            self.ed_issues.value = callout("No problems found.", "ok")
        return issues

    def _ed_apply(self):
        issues = self._ed_run_validation()
        if any(i.level == "error" for i in issues):
            return False
        try:
            data = yaml.safe_load(self.ed_text.value)
            self.host.apply_config(data)
        except Exception as exc:  # noqa: BLE001
            self.ed_issues.value = callout(f"Could not apply: {exc}", "bad")
            return False
        text = config_text(self.host.current_config())
        self._ed_suppress = True
        self.ed_text.value = text
        self._ed_suppress = False
        self._ed_clean = text
        self._ed_status("current run configuration (form)")
        self.ed_issues.value = issues_html([i for i in issues if i.level != "info"]) or callout(
            "Applied to the run configuration. The form shows the new values.", "ok")
        return True

    def _ed_save(self):
        info = self._ed_info
        if info is None:
            return False
        try:
            issues = self.experiment.save(info.path, self.ed_text.value, template=self.host.template())
        except ExperimentFileError as exc:
            self.ed_issues.value = callout(str(exc), "bad")
            return False
        if any(i.level == "error" for i in issues):
            self.ed_issues.value = issues_html(issues)
            return False
        self._ed_clean = self.ed_text.value
        self.editor_refresh_list()
        self.host.on_drafts_changed()
        self.ed_issues.value = callout(f"Draft saved. Local runs of this experiment will use your {info.path}.", "ok")
        return True

    def _ed_reset(self) -> None:
        info = self._ed_info
        if info is None:
            return
        self.experiment.reset(info.path)
        self._ed_clean = ""
        self._ed_info = None
        self.editor_refresh_list()
        self.ed_issues.value = callout(f"{info.path} is back to the example's version.", "ok")
        self.host.on_drafts_changed()

    def editor_sync_from_form(self) -> None:
        """The form changed: refresh the shown params.yaml unless the user is editing it."""
        if self._ed_info is not None and self._ed_info.role == "config" and not self.editor_dirty():
            self._ed_load(self._ed_info.path)

    def open_in_editor(self, rel: str = "params.yaml") -> None:
        self.show("Editor")
        if rel in [v for _l, v in self.ed_files.options] and not self.editor_dirty():
            self.ed_files.value = rel

    # ═════════════════════════════════════════════════════════════════════
    # Logs pane
    # ═════════════════════════════════════════════════════════════════════
    def _build_logs_pane(self) -> W.VBox:
        self.log_kind = W.ToggleButtons(options=["Run output", "Launcher activity"], value="Run output",
                                        style={"button_width": "auto"})
        seg = W.Box([self.log_kind])
        seg.add_class("icw-segment")
        self.log_kind.observe(lambda _c: self._log_switch(), names="value")
        self.log_follow = W.Checkbox(value=True, description="Follow", indent=False, layout=W.Layout(width="auto"))
        self.log_refresh = button("Refresh", icon="refresh", kind="quiet")
        self.log_refresh.on_click(lambda _b: self.refresh_log())
        self.log_dl = button("Download log", icon="download", kind="quiet")
        self.log_dl.on_click(lambda _b: self._download_log())
        self.log_meta = W.HTML()
        self.log_view = W.HTML(skeleton(5))
        self.activity_box = W.Box([self.host.activity_output], layout=W.Layout(width="100%"))
        self.activity_box.add_class("icw-activity")
        self.activity_box.layout.display = "none"
        self.clear_activity = button("Clear", icon="eraser", kind="quiet")
        self.clear_activity.on_click(lambda _b: self.host.activity_output.clear_output())
        self.clear_activity.layout.display = "none"
        self.log_controls_extra = W.HBox([])               # gateway: remote/cloud tail controls
        self.log_controls_extra.add_class("icw-actions")
        self.log_controls_extra.layout.display = "none"
        head = W.HBox([seg, W.HBox([self.log_follow, self.log_refresh, self.log_dl, self.clear_activity])],
                      layout=W.Layout(justify_content="space-between", align_items="center"))
        return W.VBox([head, self.log_meta, self.log_view, self.activity_box, self.log_controls_extra],
                      layout=W.Layout(gap="8px"))

    def _log_switch(self) -> None:
        run_output = self.log_kind.value == "Run output"
        self.log_view.layout.display = "" if run_output else "none"
        self.log_meta.layout.display = "" if run_output else "none"
        self.activity_box.layout.display = "none" if run_output else ""
        self.clear_activity.layout.display = "none" if run_output else ""
        self.log_controls_extra.layout.display = "none" if run_output else ""
        for w in (self.log_follow, self.log_refresh, self.log_dl):
            w.layout.display = "" if run_output else "none"
        if run_output:
            self.refresh_log()

    def show_activity(self) -> None:
        self.show("Logs")
        self.log_kind.value = "Launcher activity"

    def refresh_log(self, *, status=None) -> None:
        run = self.selected
        if run is None:
            self.log_meta.value = ""
            self.log_view.value = empty_state("No run selected", "The model's output appears here while it runs.", "▤")
            return
        path = Path(run.workspace_directory) / LOG_FILE
        if not path.is_file():
            where = {"remote": "on the cluster — use “Tail log” below to fetch it",
                     "cloud": "in AWS CloudWatch — use the log controls below"}.get(run.execution_mode,
                                                                                 "not written yet")
            self.log_meta.value = ""
            self.log_view.value = empty_state("No local log", f"This run's output is {where}.", "▤")
            return
        text = clean_log(LocalJob(run.workspace_directory).tail(192 * 1024))
        lines = text.splitlines()[-600:]
        size = path.stat().st_size
        state = lc.current_state(run)
        live = state in lc.ACTIVE
        self.log_meta.value = (f'<div class="icw-badges">{state_badge(state)}'
                               f'<span class="icw-card-sub" style="margin:0">{human_size(size)} · last {len(lines)} lines'
                               f'{" · updating live" if live else ""}</span></div>')
        colored = []
        for ln in lines:
            e = esc(ln)
            if re.search(r"Traceback|Error|ERROR|Exception|FAILED", ln):
                colored.append(f'<span class="err">{e}</span>')
            elif re.search(r"WARN|Warning", ln):
                colored.append(f'<span class="warn">{e}</span>')
            elif ln.startswith("[launcher]"):
                colored.append(f'<span class="mute">{e}</span>')
            elif "successfully" in ln or "completed" in ln.lower():
                colored.append(f'<span class="ok">{e}</span>')
            else:
                colored.append(e)
        direction = "column-reverse" if self.log_follow.value else "column"
        self.log_view.value = (f'<div class="icw-log" style="display:flex;flex-direction:{direction}" '
                               f'role="log" aria-live="off" tabindex="0"><div>{"<br>".join(colored)}</div></div>')

    def _download_log(self) -> None:
        if self.selected is None:
            return
        why = offer_download(self.downloader, Path(self.selected.workspace_directory) / LOG_FILE,
                             filename=f"{self.selected.id}-run.log", mime="text/plain")
        if why:
            self.log_meta.value = callout(why, "warn")

    # ═════════════════════════════════════════════════════════════════════
    # Results pane
    # ═════════════════════════════════════════════════════════════════════
    def _build_results_pane(self) -> W.VBox:
        self.res_head = W.HTML()
        self.res_views = W.ToggleButtons(options=[], style={"button_width": "auto"})
        self.res_views_box = W.Box([self.res_views])
        self.res_views_box.add_class("icw-viewpick")
        self.res_views.observe(self._res_on_view, names="value")
        self.res_options = W.VBox([], layout=W.Layout(gap="6px"))
        self.res_apply = button("Update figure", icon="refresh", kind="primary")
        self.res_apply.on_click(lambda _b: self._res_render(use_options=True))
        self.res_reset = button("Notebook defaults", icon="undo", kind="secondary",
                                tooltip="Back to the options read_results.ipynb uses")
        self.res_reset.on_click(lambda _b: self._res_on_view({"new": self.res_views.value}))
        self.res_refresh = button("Re-scan", icon="refresh", kind="quiet", tooltip="Look for new or changed output files")
        self.res_refresh.on_click(lambda _b: self.refresh_results(force=True))
        self.res_png_dl = button("Download PNG", icon="download", kind="quiet")
        self.res_png_dl.on_click(lambda _b: self._res_download())
        self.res_opts_row = W.HBox([self.res_apply, self.res_reset, self.res_png_dl])
        self.res_opts_row.add_class("icw-actions")
        self.res_body = W.HTML()
        self.res_footer = W.HTML()
        self._res_option_widgets = {}
        self._res_last = None
        top = W.HBox([self.res_head, self.res_refresh], layout=W.Layout(justify_content="space-between",
                                                                       align_items="flex-start"))
        return W.VBox([top, self.res_views_box, self.res_options, self.res_opts_row, self.res_body, self.res_footer],
                      layout=W.Layout(gap="10px"))

    def _res_controls_visible(self, visible: bool) -> None:
        for w in (self.res_views_box, self.res_options, self.res_opts_row):
            w.layout.display = "" if visible else "none"

    def refresh_results(self, *, force: bool = False) -> None:
        run = self.selected
        self._result_gen += 1
        gen = self._result_gen
        if run is None:
            self._res_controls_visible(False)
            self.res_head.value = ""
            self.res_footer.value = ""
            self.res_body.value = empty_state("No run selected", "Select a completed run to see its scientific results.", "📈")
            return
        if self._results is not None and not force:
            return
        self._res_controls_visible(False)
        self.res_head.value = f'<div class="icw-badges"><span class="icw-spinner"></span><span class="icw-card-sub" style="margin:0">Finding this run\'s outputs…</span></div>'
        self.res_body.value = skeleton(2, tall=True, label="Discovering results")
        self.res_footer.value = ""

        def work():
            if force:
                for f in (Path(run.workspace_directory) / rs.CACHE_DIR).glob("describe-*.json"):
                    f.unlink(missing_ok=True)
            try:
                results = rs.discover(run, lifecycle_state=lc.current_state(run))
            except Exception as exc:  # noqa: BLE001
                results = rs.RunResults(rs.ERROR, f"Results could not be discovered: {exc}")
            if gen != self._result_gen or self.selected is None or self.selected.id != run.id:
                return
            self._results = results
            self._res_show(results)
        self._threaded(work)

    def _res_show(self, results) -> None:
        tone = {rs.READY: "ok", rs.PARTIAL: "warn", rs.PENDING: "info", rs.NO_OUTPUTS: "neutral",
                rs.UNSUPPORTED: "neutral", rs.ERROR: "bad"}[results.status]
        label = {rs.READY: "Results ready", rs.PARTIAL: "Partly available", rs.PENDING: "Waiting for outputs",
                 rs.NO_OUTPUTS: "No outputs", rs.UNSUPPORTED: "No result views", rs.ERROR: "Problem"}[results.status]
        info = results.run
        chips = ""
        if info:
            chips = '<div class="icw-chiprow" style="margin-top:6px">' + "".join(
                f'<span class="icw-chip">{esc(k)} <b>{esc(str(v))}</b></span>' for k, v in (
                    ("model", info.get("model")), ("filter", info.get("filter")),
                    ("members", info.get("ensemble_size")), ("time steps", info.get("time_steps")),
                    ("t", f"{info.get('t_start'):g}–{info.get('t_end'):g}" if info.get("t_end") is not None else None),
                    ("observation times", info.get("observation_times")), ("state size", info.get("state_size")))
                if v not in (None, "")) + "</div>"
        self.res_head.value = f'<div>{badge(label, tone)}{chips}</div>'
        if not results.views:
            self._res_controls_visible(False)
            icon = {rs.PENDING: "◷", rs.UNSUPPORTED: "∅", rs.ERROR: "⚠"}.get(results.status, "📈")
            title = {rs.PENDING: "The run is still producing its outputs",
                     rs.UNSUPPORTED: "This example has no result views",
                     rs.ERROR: "The outputs could not be read"}.get(results.status, "No outputs yet")
            self.res_body.value = empty_state(title, results.message, icon) if results.status != rs.ERROR else \
                callout(results.message, "bad")
            self.res_footer.value = ""
            return
        options = []
        for v in results.views:
            label = v["title"] + (" (supplementary)" if v.get("supplementary") else "") + ("" if v["available"] else " — unavailable")
            options.append((label, v["id"]))
        self._res_controls_visible(True)
        notes = "".join(f"<li>{esc(w)}</li>" for w in results.warnings)
        nr = "".join(f"<li>cell {esc(str(n.get('cell')))}: {esc(str(n.get('reason')))}</li>" for n in results.not_reproduced)
        self.res_footer.value = (
            (callout(f"<ul style='margin:0;padding-left:16px'>{notes}</ul>", "warn", title="Output warnings:",
                     html_body=True) if notes else "")
            + (f'<details class="icw-card-sub" style="margin-top:6px"><summary style="cursor:pointer">Notebook cells '
               f'not reproduced here ({esc(results.notebook)})</summary><ul>{nr}</ul></details>' if nr else ""))
        first = next((v["id"] for v in results.views if v["available"]), results.views[0]["id"])
        if self.res_views.options != tuple(options) and list(self.res_views.options) != options:
            self.res_views.options = options
        if self.res_views.value == first:
            self._res_on_view({"new": first})
        else:
            self.res_views.value = first

    def _res_on_view(self, change) -> None:
        view_id = change.get("new")
        results = self._results
        if not view_id or results is None:
            return
        view = results.view(view_id)
        if view is None:
            return
        widgets = {}
        rows = []
        for opt in view["options"]:
            if opt["kind"] == "choice":
                w = W.Dropdown(options=opt["choices"], value=opt["default"])
            elif opt["kind"] == "int":
                w = W.BoundedIntText(value=int(opt["default"] or 0), min=int(opt["minimum"] or 0),
                                     max=int(opt["maximum"]) if opt["maximum"] is not None else 10**9)
            elif opt["kind"] == "float":
                w = W.FloatText(value=float(opt["default"] or 0))
            else:
                w = W.Text(value=", ".join(f"{x:g}" for x in (opt["default"] or [])))
            w.tooltip = opt.get("help") or opt["label"]
            widgets[opt["name"]] = (opt, w)
            from .components import field

            rows.append(field(opt["label"], w, opt.get("help") or ""))
        self._res_option_widgets = widgets
        self.res_options.children = rows
        self.res_apply.layout.display = "" if rows else "none"
        self.res_reset.layout.display = "" if rows else "none"
        self._res_render(use_options=False)

    def _res_options(self) -> dict:
        out = {}
        for name, (opt, w) in self._res_option_widgets.items():
            value = w.value
            if opt["kind"] == "float_list":
                value = [v for v in str(value).replace(",", " ").split() if v]
            out[name] = value
        return out

    def _res_render(self, *, use_options: bool) -> None:
        results = self._results
        view_id = self.res_views.value
        if results is None or not view_id:
            return
        view = results.view(view_id)
        self._result_gen += 1
        gen = self._result_gen
        options = self._res_options() if use_options else {}
        if not view["available"]:
            self.res_body.value = callout(view["reason"] or "This view is not available for this run.", "warn",
                                          title=view["title"] + ":")
            self.res_opts_row.layout.display = "none"
            return
        self.res_opts_row.layout.display = ""
        self.res_apply.disabled = True
        self.res_body.value = (f'<div class="icw-figure"><header><div><h4>{esc(view["title"])}</h4>'
                               f'<div class="src">Drawing… {esc(view["source"])}</div></div>'
                               f'<span class="icw-spinner"></span></header><div class="plot">{skeleton(1, tall=True, label="Drawing figure")}</div></div>')

        def work():
            started = time.time()
            try:
                outcome = rs.render(results, view_id, options)
            except Exception as exc:  # noqa: BLE001
                outcome = rs.RenderOutcome(False, view_id, title=view["title"], message=str(exc))
            self.res_apply.disabled = False
            if gen != self._result_gen:
                return
            self._res_last = outcome
            self.res_body.value = self._figure_html(view, outcome, time.time() - started)
        self._threaded(work)

    def _figure_html(self, view: dict, outcome, seconds: float) -> str:
        if not outcome.ok:
            return callout(outcome.message or "The view could not be drawn.", "bad", title=view["title"] + ":")
        badge_html = badge("supplementary", "warn", dot=False) if outcome.supplementary else badge("notebook view", "info", dot=False)
        timing = "cached" if outcome.cached else f"drawn in {seconds:.1f} s"
        opts = ", ".join(f"{k} = {v}" for k, v in (outcome.options or {}).items())
        body = ""
        if outcome.png:
            body += f'<div class="plot">{image_html(outcome.png, alt=view["title"])}</div>'
        if outcome.table:
            t = outcome.table
            head = "".join(f"<th>{esc(str(c))}</th>" for c in t["columns"])
            rows = "".join("<tr>" + "".join(
                f'<td class="{"num" if re.fullmatch(r"-?[0-9.]+(e-?[0-9]+)?", str(c)) else ""}">{esc(str(c))}</td>'
                for c in r) + "</tr>" for r in t["rows"])
            body += (f'<div style="padding:10px"><div class="icw-card-sub">{esc(t.get("caption", ""))}</div>'
                     f'<div class="icw-scroll"><table class="icw-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody>'
                     "</table></div></div>")
        notes = "".join(f"<li>{esc(n)}</li>" for n in outcome.notes)
        return (f'<figure class="icw-figure" style="margin:0"><header><div><h4>{esc(outcome.title)}</h4>'
                f'<div class="src">{esc(outcome.source)}{" · " + esc(opts) if opts else ""}</div></div>'
                f'<div class="icw-badges">{badge_html}<span class="icw-card-sub" style="margin:0">{timing}</span></div></header>'
                f'{body}<footer>{f"<ul>{notes}</ul>" if notes else ""}<div>{esc(view["description"])}'
                f'{" Click the figure to enlarge." if outcome.png else ""}</div></footer></figure>')

    def _res_download(self) -> None:
        out = self._res_last
        if out is None or not out.png:
            return
        offer_download(self.downloader, out.png, filename=f"{self.selected.id}-{out.view}.png", mime="image/png")

    # ── helpers ────────────────────────────────────────────────────────────
    def _threaded(self, fn) -> None:
        def wrapper():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                try:
                    with self.host.activity_output:
                        print(f"[workspace][ERROR] {type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    pass
        t = threading.Thread(target=wrapper, daemon=True)
        t.start()
