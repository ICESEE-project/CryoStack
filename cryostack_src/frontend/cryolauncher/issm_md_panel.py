"""Basic-mode "ISSM configuration" panel: a guided, validated md layer.

Only the curated parameters in
:data:`cryostack_src.models.issm.md_config.CURATED_MD_PARAMETERS` are exposed,
and only the ones relevant to the solver(s) the selected example actually runs.
There is no raw ``md.*`` field and no free MATLAB expression. Every row is
opt-in: unless the user ticks a row, the example's own default is kept.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import ipywidgets as W

from cryostack_src.models.issm.md_config import (
    CURATED_MD_PARAMETERS,
    CuratedParam,
    curated_parameters_for,
    detect_solvers,
    validate_md_config,
)

_SOLVER_LABELS = {
    "stressbalance": "Stress balance", "transient": "Transient", "thermal": "Thermal",
    "steadystate": "Steady state", "masstransport": "Mass transport",
    "balancethickness": "Balance thickness", "hydrology": "Hydrology",
    "esa": "ESA", "slr": "Sea-level", "damageevolution": "Damage",
    "levelset": "Level set",
}


@dataclass
class IssmMdPanel:
    container: W.VBox
    _state: dict

    def set_example(self, example_path: str) -> None:
        self._state["build"](example_path)

    def solvers(self) -> tuple[str, ...]:
        return tuple(self._state["solvers"])

    def overrides(self) -> dict:
        """Raw ``{param_key: value}`` for every enabled, non-default row."""
        out: dict = {}
        for key, (enable, control, param) in self._state["rows"].items():
            if not enable.value:
                continue
            value = control.value
            if param.kind == "multiplier" and float(value) == 1.0:
                continue
            if param.kind == "outputs" and not value:
                continue
            out[key] = list(value) if param.kind == "outputs" else value
        return out

    def validate(self):
        return validate_md_config(self.overrides(), solvers=self._state["solvers"])

    def set_visible(self, visible: bool) -> None:
        self.container.layout.display = "" if visible else "none"


def _control_for(param: CuratedParam) -> W.Widget:
    if param.kind in {"float", "multiplier"}:
        return W.BoundedFloatText(
            value=float(param.default if param.default is not None
                        else (param.min if param.min is not None else 0.0)),
            min=param.min if param.min is not None else -1e12,
            max=param.max if param.max is not None else 1e12,
            step=0.0,
            layout=W.Layout(width="150px"),
        )
    if param.kind == "int":
        return W.BoundedIntText(
            value=int(param.default if param.default is not None
                      else (param.min if param.min is not None else 0)),
            min=int(param.min) if param.min is not None else -(10**9),
            max=int(param.max) if param.max is not None else 10**9,
            layout=W.Layout(width="150px"),
        )
    if param.kind == "bool":
        return W.Dropdown(options=[("On", True), ("Off", False)], value=True,
                          layout=W.Layout(width="150px"))
    if param.kind == "outputs":
        return W.SelectMultiple(options=list(param.output_choices), value=(),
                                rows=min(5, len(param.output_choices)),
                                layout=W.Layout(width="260px"))
    raise ValueError(f"unsupported curated kind: {param.kind!r}")  # pragma: no cover


def _read_runme(example_path: str) -> str:
    try:
        p = Path(example_path or "").expanduser()
    except Exception:
        return ""
    if not p.exists():
        return ""
    entry = (p / "runme.m") if p.is_dir() else p
    try:
        return entry.read_text(encoding="utf-8", errors="ignore") if entry.is_file() else ""
    except OSError:
        return ""


def build_issm_md_panel() -> IssmMdPanel:
    header = W.HTML("<div class='cryostack-section-label'>ISSM configuration</div>")
    solver_line = W.HTML()
    rows_box = W.VBox(layout=W.Layout(gap="4px"))
    hint = W.HTML(
        "<span class='icesee-subtle'>Curated, validated parameters. Enable a row "
        "only to change it — the example's own defaults are kept otherwise. "
        "Spatial fields are scaled by a factor, never replaced.</span>"
    )
    container = W.VBox([header, solver_line, rows_box, hint],
                       layout=W.Layout(width="100%", gap="8px"))

    state: dict = {"solvers": (), "rows": {}}

    def _build(example_path: str) -> None:
        text = _read_runme(example_path)
        solvers = detect_solvers(text)
        state["solvers"] = solvers

        if solvers:
            names = ", ".join(_SOLVER_LABELS.get(s, s.title()) for s in solvers)
            solver_line.value = (
                f"<span class='icesee-subtle'>Solvers in this example: "
                f"<b>{html.escape(names)}</b></span>"
            )
        else:
            solver_line.value = (
                "<span class='icesee-subtle'>No <code>solve(...)</code> call "
                "detected — no curated parameters apply.</span>"
            )

        applicable = curated_parameters_for(solvers)
        rows: dict = {}
        widgets: list[W.Widget] = []
        for param in applicable:
            enable = W.Checkbox(value=False, indent=False,
                                layout=W.Layout(width="24px"))
            control = _control_for(param)
            control.disabled = True

            def _toggle(change, _c=control):
                _c.disabled = not change["new"]

            enable.observe(_toggle, names="value")

            label = W.HTML(
                f"<div title='{html.escape(param.help)}'><b>{html.escape(param.label)}</b>"
                f"<span class='icesee-subtle'> &nbsp;{html.escape(param.key)}</span></div>",
                layout=W.Layout(width="260px"),
            )
            rows[param.key] = (enable, control, param)
            widgets.append(W.HBox([enable, label, control],
                                  layout=W.Layout(align_items="center", gap="8px")))

        state["rows"] = rows
        rows_box.children = tuple(widgets) if widgets else (
            W.HTML("<span class='icesee-subtle'>Nothing to configure for this example.</span>"),
        )

    state["build"] = _build
    _build("")
    return IssmMdPanel(container=container, _state=state)
