"""CryoLauncher Results visualization -- a compact, deterministic field viewer.

Model-neutral shell: the panel only knows *solution -> field -> timestep* and
delegates every scientific decision to the model adapter's renderer
(``cryostack_src.visualization``) via :class:`WorkspaceManager`. No AI.

Legacy runs (``ResultPackage.status == "legacy"``) keep their existing PNGs and
``md_final.mat`` listing; the structured selector is disabled with a clear note.
Existing *Preview results* / *Download results* / *Download figures* controls are
untouched and live elsewhere.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

import ipywidgets as W
from IPython.display import Image, clear_output, display

from cryostack_src.workspace.manager import WorkspaceManager

_LEGACY_NOTE = (
    "Structured field visualization is unavailable for this legacy run. "
    "Existing figures and model outputs are still available."
)
_NO_RUN_NOTE = "Select a run to visualize its results."
_NO_RESULTS_NOTE = (
    "No structured results for this run yet. Use <b>Preview results</b> to "
    "fetch the run outputs."
)


@dataclass
class VisualizationPanel:
    container: W.VBox
    controller: "VisualizationController"


class VisualizationController:
    def __init__(self, *, manager: WorkspaceManager, selected_run_id, log_output,
                 solution_dd: W.Dropdown, field_dd: W.Dropdown,
                 timestep_dd: W.Dropdown, render_btn: W.Button,
                 status: W.HTML, meta: W.HTML, plot_out: W.Output) -> None:
        self.manager = manager
        self._selected_run_id = selected_run_id
        self.log_output = log_output
        self.solution_dd = solution_dd
        self.field_dd = field_dd
        self.timestep_dd = timestep_dd
        self.render_btn = render_btn
        self.status = status
        self.meta = meta
        self.plot_out = plot_out
        self._pkg = None
        self._suppress = False

        solution_dd.observe(self._on_solution, names="value")
        field_dd.observe(self._on_field, names="value")
        render_btn.on_click(lambda _=None: self.render())

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

    def _field_info(self):
        sol, fld = self.solution_dd.value, self.field_dd.value
        if not self._pkg or not sol or not fld:
            return None
        try:
            return self._pkg.field_metadata(sol, fld)
        except Exception:  # noqa: BLE001 - metadata gaps must not break the UI
            return None

    # -- lifecycle -----------------------------------------------------
    def refresh(self, _=None):
        run_id = self._run_id()
        if not run_id:
            self._pkg = None
            self._set_enabled(False)
            self.solution_dd.options = ()
            self.field_dd.options = ()
            self.status.value = f"<span class='icesee-subtle'>{_NO_RUN_NOTE}</span>"
            self.meta.value = ""
            with self.plot_out:
                clear_output()
            return

        self._pkg = self.manager.result_package_for_run(run_id)
        status = self._pkg.status

        if status == "legacy":
            self._set_enabled(False)
            self.solution_dd.options = ()
            self.field_dd.options = ()
            arts = self._pkg.legacy_artifacts()
            extra = ""
            if arts.get("model_mat"):
                extra = " &nbsp;·&nbsp; model: <code>md_final.mat</code>"
            self.status.value = (
                f"<span class='icesee-subtle'>{_LEGACY_NOTE}{extra}</span>")
            self.meta.value = ""
            self._show_legacy_figures(arts)
            return

        if status == "missing" or not self._pkg.is_readable():
            self._set_enabled(False)
            self.solution_dd.options = ()
            self.field_dd.options = ()
            note = _NO_RESULTS_NOTE if status == "missing" else (
                f"Results are not renderable (status: {html.escape(status)}).")
            self.status.value = f"<span class='icesee-subtle'>{note}</span>"
            self.meta.value = ""
            with self.plot_out:
                clear_output()
            return

        solutions = self._pkg.available_solutions()
        self._set_enabled(bool(solutions))
        self._suppress = True
        self.solution_dd.options = solutions
        if solutions:
            self.solution_dd.value = solutions[0]
        self._suppress = False
        self.status.value = (
            f"<span class='icesee-subtle'>{len(solutions)} solution"
            f"{'s' if len(solutions) != 1 else ''} in this run</span>")
        self._populate_fields()

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

    def _show_legacy_figures(self, arts: dict):
        figures = arts.get("figures") or []
        with self.plot_out:
            clear_output(wait=True)
            for path in figures:
                if str(path).lower().endswith(".png"):
                    display(Image(filename=str(path)))
        if figures:
            self._log(f"[viz] legacy run: showing {len(figures)} existing figure(s)")


def build_visualization_panel(*, manager: WorkspaceManager, selected_run_id,
                              log_output) -> VisualizationPanel:
    solution_dd = W.Dropdown(options=(), layout=W.Layout(width="auto"))
    field_dd = W.Dropdown(options=(), layout=W.Layout(width="auto"))
    timestep_dd = W.Dropdown(options=[("Final", None)],
                             layout=W.Layout(width="auto", display="none"))
    render_btn = W.Button(description="Render", icon="area-chart",
                          button_style="primary", layout=W.Layout(width="auto"))
    status = W.HTML()
    meta = W.HTML()
    plot_out = W.Output()

    controller = VisualizationController(
        manager=manager, selected_run_id=selected_run_id, log_output=log_output,
        solution_dd=solution_dd, field_dd=field_dd, timestep_dd=timestep_dd,
        render_btn=render_btn, status=status, meta=meta, plot_out=plot_out)

    def _lbl(text):
        return W.HTML(f"<div class='icesee-lbl'>{text}</div>",
                      layout=W.Layout(min_width="64px"))

    container = W.VBox(
        [
            W.HTML("<div class='cryostack-section-label'>Field visualization</div>"),
            status,
            W.HBox([_lbl("Solution:"), solution_dd],
                   layout=W.Layout(align_items="center", gap="6px", flex_wrap="wrap")),
            W.HBox([_lbl("Field:"), field_dd],
                   layout=W.Layout(align_items="center", gap="6px", flex_wrap="wrap")),
            W.HBox([_lbl("Timestep:"), timestep_dd],
                   layout=W.Layout(align_items="center", gap="6px", flex_wrap="wrap")),
            W.HBox([render_btn], layout=W.Layout(gap="6px")),
            meta,
            plot_out,
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    controller.refresh()
    return VisualizationPanel(container=container, controller=controller)
