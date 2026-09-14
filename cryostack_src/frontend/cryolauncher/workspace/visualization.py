"""CryoLauncher Results visualization -- a compact, deterministic field viewer.

Model-neutral shell: the panel only knows *solution -> field -> timestep* and
delegates every scientific decision to the model adapter's renderer
(``cryostack_src.visualization``) via :class:`WorkspaceManager`. No AI.

The boundary is preserved:

    execution backend fetches / synchronises   (refresh_results / sync_cloud_results)
            -> <managed-run>/cache/outputs/     (one backend-neutral local shape)
            -> ResultPackage reads local structured outputs   (no SSH/S3 here)
            -> this controller populates Solution / Field / Timestep

The controller never fetches by itself: it calls an injected ``fetch_results``
callback (which the gateway wires to the right backend) and then re-reads the
local package. Legacy runs (``status == "legacy"``) keep their existing PNGs and
``md_final.mat``; the structured selector is disabled with a clear note.
"""
from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass
from pathlib import Path

import ipywidgets as W
from IPython.display import HTML, Image, clear_output, display

#: figures larger than this are NOT base64-embedded for inline preview -- the
#: card shows a "too large to preview" note instead and the file stays fully
#: available through Download results. 12 MiB raw -> ~16 MiB base64.
_MAX_INLINE_FIGURE_BYTES = 12 * 1024 * 1024

_IMG_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "gif": "image/gif", "svg": "image/svg+xml"}

from cryostack_src.workspace.manager import WorkspaceManager

_LEGACY_NOTE = (
    "Structured field visualization is unavailable for this legacy run. "
    "Existing figures and model outputs are still available."
)
_NO_RUN_NOTE = "Select a run to visualize its results."
_NOT_FETCHED_NOTE = "Results have not been fetched yet."
_ARTIFACTS_NOTE = (
    "Structured field visualization is not yet available for this model. "
    "The figures and native output files this run produced are shown below."
)
_EMPTY_NOTE = (
    "This run completed but produced no figures or output files to collect."
)


@dataclass
class VisualizationPanel:
    container: W.VBox
    controller: "VisualizationController"


class VisualizationController:
    def __init__(self, *, manager: WorkspaceManager, selected_run_id, log_output,
                 solution_dd: W.Dropdown, field_dd: W.Dropdown,
                 timestep_dd: W.Dropdown, render_btn: W.Button,
                 fetch_btn: W.Button, status: W.HTML, meta: W.HTML,
                 plot_out: W.Output, fetch_results=None,
                 field_controls: W.Widget | None = None) -> None:
        self.manager = manager
        self._selected_run_id = selected_run_id
        self.log_output = log_output
        self.solution_dd = solution_dd
        self.field_dd = field_dd
        self.timestep_dd = timestep_dd
        self.render_btn = render_btn
        self.fetch_btn = fetch_btn
        self.status = status
        self.meta = meta
        self.plot_out = plot_out
        #: the Solution / Field / Timestep / Render block -- hidden entirely
        #: (not just disabled) for a run with no structured fields, so an
        #: artifacts-only run never implies fields exist.
        self.field_controls = field_controls
        self._fetch_results = fetch_results
        self._pkg = None
        self._suppress = False
        self._auto_rendered_run: str | None = None

        solution_dd.observe(self._on_solution, names="value")
        field_dd.observe(self._on_field, names="value")
        render_btn.on_click(lambda _=None: self.render())
        fetch_btn.on_click(lambda _=None: self.fetch())

    # -- helpers ---------------------------------------------------------
    def _log(self, *parts):
        if self.log_output is not None:
            with self.log_output:
                print(*parts)

    def _run_id(self) -> str:
        return (self._selected_run_id() or "") if callable(self._selected_run_id) \
            else (self._selected_run_id or "")

    def _set_enabled(self, enabled: bool):
        self.solution_dd.disabled = not enabled
        self.field_dd.disabled = not enabled
        self.timestep_dd.disabled = not enabled
        self.render_btn.disabled = not enabled

    def _show_field_controls(self, show: bool):
        if self.field_controls is not None:
            self.field_controls.layout.display = "" if show else "none"

    def _show_fetch(self, show: bool):
        can_fetch = show and self._fetch_results is not None and bool(self._run_id())
        self.fetch_btn.layout.display = "" if can_fetch else "none"
        self.fetch_btn.disabled = not can_fetch

    def _field_info(self):
        sol, fld = self.solution_dd.value, self.field_dd.value
        if not self._pkg or not sol or not fld:
            return None
        try:
            return self._pkg.field_metadata(sol, fld)
        except Exception:  # noqa: BLE001 - metadata gaps must not break the UI
            return None

    # -- fetch (delegated to the execution backend) -------------------
    def fetch(self, _=None):
        """Ask the backend to synchronise this run's outputs locally, then
        re-read the package. The controller performs no SSH / S3 itself."""
        if self._fetch_results is None or not self._run_id():
            return
        self.fetch_btn.disabled = True
        self.status.value = "<span class='icesee-subtle'>Fetching results…</span>"
        try:
            self._fetch_results()
        except Exception as err:  # noqa: BLE001 - surfaced, never raised into the UI
            self._log("[viz][fetch]", type(err).__name__, err)
        finally:
            self.fetch_btn.disabled = False
        self._auto_rendered_run = None            # a fresh package -> re-preview
        self.refresh()

    def preview(self, _=None):
        """The *Preview Results* entry point for this panel.

        The execution backend has usually just synchronised the run's outputs
        into the local cache (``preview_results`` / ``sync_cloud_results``). This
        re-reads the local :class:`ResultPackage` for the currently selected
        run, rebuilds the Solution / Field / Timestep selectors, and renders an
        initial recommended plot. If nothing is local yet and a fetch callback
        is available, it falls back to fetching first.
        """
        run_id = self._run_id()
        if not run_id:
            self.refresh()
            return
        package = self.manager.result_package_for_run(run_id)
        if package.status == "missing" and self._fetch_results is not None:
            self.fetch()
            return
        self._auto_rendered_run = None            # force a fresh initial preview
        self.refresh()

    # -- lifecycle -----------------------------------------------------
    def refresh(self, _=None):
        run_id = self._run_id()
        if not run_id:
            self._pkg = None
            self._set_enabled(False)
            self._show_field_controls(False)
            self._show_fetch(False)
            self.solution_dd.options = ()
            self.field_dd.options = ()
            self.status.value = f"<span class='icesee-subtle'>{_NO_RUN_NOTE}</span>"
            self.meta.value = ""
            with self.plot_out:
                clear_output()
            return

        self._pkg = self.manager.result_package_for_run(run_id)
        status = self._pkg.status

        # "legacy"   -- a run that predates the neutral package
        # "artifacts"-- a run whose model has no structured field reader yet
        #               (Icepack today): figures + native output files only
        if status in ("legacy", "artifacts", "empty"):
            self._set_enabled(False)
            self._show_field_controls(False)
            self._show_fetch(status != "legacy")   # a re-fetch can still help
            # artifact-aware: never show empty Solution/Field dropdowns for a
            # run that produced no structured fields.
            self.solution_dd.options = ()
            self.field_dd.options = ()
            arts = self._pkg.legacy_artifacts()
            figs = arts.get("figures") or []
            _seen: set = set()
            natives = []
            for p in ([arts["model_mat"]] if arts.get("model_mat") else []) \
                    + (arts.get("native") or []) + (arts.get("mats") or []) \
                    + (arts.get("other") or []):
                if p and p not in _seen:
                    _seen.add(p)
                    natives.append(p)

            # "No structured visualizer" and "No results" are different
            # conditions -- say which one this is. The count is explicit about
            # WHAT was found (figures vs other output files), never a vague
            # "N files".
            if figs or natives:
                note = _LEGACY_NOTE if status == "legacy" else _ARTIFACTS_NOTE
                parts = []
                if figs:
                    parts.append(f"{len(figs)} figure{'s' if len(figs) != 1 else ''}")
                if natives:
                    parts.append(
                        f"{len(natives)} other output file"
                        f"{'s' if len(natives) != 1 else ''}")
                note += (
                    " &nbsp;·&nbsp; " + " and ".join(parts)
                    + " found — use <b>Download results</b> to export "
                    + ("them." if (len(figs) + len(natives)) != 1 else "it.")
                )
            else:
                note = (
                    _EMPTY_NOTE if status == "empty"
                    else "This run's outputs are not available locally. "
                         "Use <b>Fetch results</b> to retrieve them."
                )
            self.status.value = f"<span class='icesee-subtle'>{note}</span>"
            self.meta.value = ""
            self._show_native_outputs(figs, natives)
            return

        if status == "missing" or not self._pkg.is_readable():
            self._set_enabled(False)
            self._show_field_controls(False)
            self.solution_dd.options = ()
            self.field_dd.options = ()
            if status == "missing":
                note = _NOT_FETCHED_NOTE
                self._show_fetch(True)
            else:
                note = f"Results are not renderable (status: {html.escape(status)})."
                self._show_fetch(True)         # a re-fetch may repair a partial sync
            self.status.value = f"<span class='icesee-subtle'>{note}</span>"
            self.meta.value = ""
            with self.plot_out:
                clear_output()
            return

        solutions = self._pkg.available_solutions()
        self._set_enabled(bool(solutions))
        self._show_field_controls(bool(solutions))
        self._show_fetch(True)                  # keep a re-fetch affordance
        self.fetch_btn.description = "Re-fetch results"
        self._suppress = True
        self.solution_dd.options = solutions
        if solutions:
            self.solution_dd.value = solutions[0]
        self._suppress = False
        n = len(solutions)
        self.status.value = (
            f"<span class='icesee-subtle'>{n} solution{'s' if n != 1 else ''} "
            "in this run</span>")
        self._populate_fields()
        self._maybe_auto_preview(run_id)

    def _maybe_auto_preview(self, run_id: str):
        """Show something immediately: render the first recommended selection
        once per run so the panel is never just empty dropdowns."""
        if self._auto_rendered_run == run_id:
            return
        if not (self.solution_dd.value and self.field_dd.value):
            return
        self._auto_rendered_run = run_id
        self.render()

    def _populate_fields(self):
        sol = self.solution_dd.value
        if not self._pkg or not sol:
            self.field_dd.options = ()
            return
        fields = self._pkg.available_fields(sol)          # preference order
        self._suppress = True
        self.field_dd.options = fields
        if fields:
            self.field_dd.value = fields[0]
        self._suppress = False
        self._populate_timesteps()

    def _populate_timesteps(self):
        info = self._field_info()
        if info is None or not info.transient:
            self.timestep_dd.options = [("Final", None)]
            self.timestep_dd.value = None
            self.timestep_dd.layout.display = "none"
            return
        sol = self._pkg.solution(self.solution_dd.value)
        available = list(info.available_timesteps) if info.available_timesteps \
            else list(range(sol.timesteps))
        opts = [("Final", None)] + [
            (f"{i + 1} / {sol.timesteps}", i) for i in available]
        self.timestep_dd.options = opts
        self.timestep_dd.value = None
        self.timestep_dd.layout.display = ""

    def _on_solution(self, _=None):
        if self._suppress:
            return
        self._populate_fields()

    def _on_field(self, _=None):
        if self._suppress:
            return
        self._populate_timesteps()

    # -- render ------------------------------------------------------
    def render(self, _=None):
        run_id = self._run_id()
        sol, fld = self.solution_dd.value, self.field_dd.value
        if not run_id or not sol or not fld:
            return
        info = self._field_info()
        kind = "timeseries" if (info is not None and info.location == "scalar"
                                and info.transient) else "map"
        result = self.manager.render_run_plot(
            run_id, solution=sol, field=fld,
            timestep=self.timestep_dd.value, kind=kind)

        with self.plot_out:
            clear_output(wait=True)
            if result.ok and result.path is not None:
                display(Image(filename=str(result.path)))
        if result.ok:
            self.meta.value = (
                "<div class='cryostack-plot-meta'>"
                + "<br>".join(html.escape(line)
                              for line in result.caption.splitlines())
                + "</div>")
            self._log(f"[viz] rendered {result.path}")
        else:
            self.meta.value = (
                f"<span class='icesee-subtle'>Cannot render "
                f"{html.escape(sol)} · {html.escape(fld)}: "
                f"{html.escape(result.reason or 'unsupported')}</span>")
            self._log(f"[viz] {sol}.{fld}: {result.reason}")

    @staticmethod
    def _figure_heading(name: str, meta: dict) -> str:
        """Human-readable heading for one gallery figure. The name comes
        straight from the figure ITSELF -- never inferred from the image, the
        filename, or the example's identity. Priority (the collector already
        folds 1-3 into ``title``; the extra fallbacks here cover metadata
        written by another path):

          1. explicit figure label   2. suptitle   3. primary axes title
          4. -> neutral "Figure N"

        A figure the script gave no name at all gets "Figure N"; anything
        else is labelled by its own filename stem."""
        for key in ("title", "label", "suptitle"):
            v = (meta.get(key) or "").strip()
            if v:
                return v
        for t in (meta.get("axes_titles") or []):
            if t and t.strip():
                return t.strip()
        m = re.match(r"figure-0*(\d+)\.[a-z0-9]+$", name, re.IGNORECASE)
        if m:
            return f"Figure {int(m.group(1))}"
        return Path(name).stem

    @staticmethod
    def _fmt_size(n: int) -> str:
        step = 1024.0
        val = float(max(0, n))
        for unit in ("B", "KB", "MB", "GB"):
            if val < step:
                return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
            val /= step
        return f"{val:.1f} TB"

    def _native_file_rows(self, natives: list) -> str:
        base = getattr(self._pkg, "outputs", None)
        rows = []
        for p in natives:
            path = Path(p)
            try:
                rel = str(path.relative_to(base)) if base else path.name
            except ValueError:
                rel = path.name
            try:
                size = self._fmt_size(path.stat().st_size)
            except OSError:
                size = "—"
            ext = path.suffix.lstrip(".").lower() or "—"
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(path.name)}</code></td>"
                f"<td>{html.escape(rel)}</td>"
                f"<td>{html.escape(ext)}</td>"
                f"<td style='text-align:right'>{html.escape(size)}</td>"
                "</tr>"
            )
        if not rows:
            return ""
        return (
            "<div class='cryostack-section-label'>Native output files</div>"
            "<table class='cryostack-native-files'>"
            "<thead><tr><th>File</th><th>Path</th><th>Type</th>"
            "<th style='text-align:right'>Size</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>"
        )

    def _show_native_outputs(self, figs: list, natives: list):
        """The native-output fallback: render any recognisable figure files as
        an inline gallery, and list every other native output file (name /
        relative path / type / size). Never fabricates a plot.

        Figures are emitted as ``<img src="data:image/…;base64,…">`` inside an
        ``IPython.display.HTML`` payload -- the SAME transport ``render()`` and
        the download helper already use. A bare ``ipywidgets`` image/box
        display()'d into an ``Output`` does not render reliably in Voilà (the
        live "large blank area" symptom); a data-URI ``<img>`` is browser-native
        and works identically for Local, HPC and Cloud figures, which all land
        in the same local ``outputs/figures/``.
        """
        gallery_html, oversized = self._figure_gallery_html(figs)
        native_html = self._native_file_rows(natives)
        with self.plot_out:
            clear_output(wait=True)
            if gallery_html or native_html:
                display(HTML(gallery_html + native_html))
            else:
                display(HTML(
                    "<div class='icesee-subtle'>No output files were found "
                    "for this run.</div>"))
        rendered = gallery_html.count("data:image/")
        if gallery_html or native_html:
            self._log(
                f"[viz] native outputs: {rendered} figure(s) previewed"
                + (f", {oversized} too large for inline preview" if oversized else "")
                + f", {len(natives)} other file(s)")

    def _figure_gallery_html(self, figures: list) -> tuple[str, int]:
        """``(gallery_html, oversized_count)``. Each recognisable image file
        becomes a card: heading + base64 data-URI ``<img>`` + filename/labels.
        A figure over :data:`_MAX_INLINE_FIGURE_BYTES` is not embedded (card
        says so, file still downloadable)."""
        captions: dict = {}
        try:
            if hasattr(self._pkg, "figure_captions"):
                captions = self._pkg.figure_captions() or {}
        except Exception:  # noqa: BLE001 - caption gaps never break the gallery
            captions = {}

        cards: list[str] = []
        oversized = 0
        for path in figures:
            p = Path(path)
            ext = p.suffix.lower().lstrip(".")
            if ext not in _IMG_MIME:
                continue
            name = p.name
            meta = captions.get(name) or {}
            heading = html.escape(self._figure_heading(name, meta))

            sub_bits = [f"<code>{html.escape(name)}</code>"]
            if meta.get("xlabel"):
                sub_bits.append("x: " + html.escape(str(meta["xlabel"])))
            if meta.get("ylabel"):
                sub_bits.append("y: " + html.escape(str(meta["ylabel"])))
            extra_titles = [t for t in (meta.get("axes_titles") or [])
                            if t and t != meta.get("title")]
            sub_html = " &nbsp;·&nbsp; ".join(sub_bits)
            if extra_titles:
                sub_html += ("<br>" + " · ".join(html.escape(str(t)) for t in extra_titles))

            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size > _MAX_INLINE_FIGURE_BYTES:
                oversized += 1
                body = ("<div class='icesee-subtle'>Figure is "
                        f"{self._fmt_size(size)} — too large to preview inline. "
                        "Use <b>Download results</b>.</div>")
            else:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                b64 = base64.b64encode(data).decode("ascii")
                body = (f"<img src='data:{_IMG_MIME[ext]};base64,{b64}' "
                        f"alt='{heading}'>")

            cards.append(
                "<div class='cryostack-figure-card'>"
                f"<div class='cryostack-figure-title'>{heading}</div>"
                f"{body}"
                f"<div class='cryostack-figure-sub'>{sub_html}</div>"
                "</div>"
            )
        if not cards:
            return "", oversized
        return (
            "<div class='cryostack-figure-gallery'>" + "".join(cards) + "</div>",
            oversized,
        )


def build_visualization_panel(*, manager: WorkspaceManager, selected_run_id,
                              log_output, fetch_results=None) -> VisualizationPanel:
    solution_dd = W.Dropdown(options=(), layout=W.Layout(width="auto"))
    field_dd = W.Dropdown(options=(), layout=W.Layout(width="auto"))
    timestep_dd = W.Dropdown(options=[("Final", None)],
                             layout=W.Layout(width="auto", display="none"))
    render_btn = W.Button(description="Render", icon="area-chart",
                          button_style="primary", layout=W.Layout(width="auto"))
    fetch_btn = W.Button(description="Fetch results", icon="cloud-download",
                         button_style="info",
                         layout=W.Layout(width="auto", display="none"))
    status = W.HTML()
    meta = W.HTML()
    # The figure viewer: controls / metadata sit above it. It has a useful
    # minimum height, grows with the figure, and only scrolls internally once
    # it reaches the usable viewport bottom (max-height set by the scoped
    # viewer-sizing script; relaxed on narrow screens -- see theme CSS).
    plot_out = W.Output(layout=W.Layout(width="100%", min_height="300px",
                                        overflow="auto"))
    plot_out.add_class("cryostack-results-viewer")

    def _lbl(text):
        return W.HTML(f"<div class='icesee-lbl'>{text}</div>",
                      layout=W.Layout(min_width="64px"))

    def _field_row(label, control):
        row = W.HBox([_lbl(label), control],
                     layout=W.Layout(align_items="center", gap="6px", flex_wrap="wrap"))
        row.add_class("cryostack-field-row")
        return row

    # Solution / Field / Timestep / Render -- one block, hidden entirely (not
    # just disabled) when the selected run has no structured fields, so an
    # artifacts-only run (e.g. 00-meshes-functions) never implies fields exist.
    field_controls = W.VBox(
        [
            _field_row("Solution:", solution_dd),
            _field_row("Field:", field_dd),
            _field_row("Timestep:", timestep_dd),
            W.HBox([render_btn], layout=W.Layout(gap="6px")),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    controller = VisualizationController(
        manager=manager, selected_run_id=selected_run_id, log_output=log_output,
        solution_dd=solution_dd, field_dd=field_dd, timestep_dd=timestep_dd,
        render_btn=render_btn, fetch_btn=fetch_btn, status=status, meta=meta,
        plot_out=plot_out, fetch_results=fetch_results,
        field_controls=field_controls)

    container = W.VBox(
        [
            W.HTML("<div class='cryostack-section-label'>Field visualization</div>"),
            W.HBox([status, fetch_btn],
                   layout=W.Layout(align_items="center", gap="10px", flex_wrap="wrap")),
            field_controls,
            meta,
            plot_out,
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    controller.refresh()
    return VisualizationPanel(container=container, controller=controller)
