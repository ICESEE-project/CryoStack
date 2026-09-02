"""Basic-mode "Icepack configuration" panel.

Deliberately minimal (unlike the ISSM ``md`` panel): only the two curated
``safe_basic`` parameters from
:data:`cryostack_src.models.icepack.parameters.BASIC_MODE_PARAMETERS` --
ice temperature and the timestep count. Every row is opt-in; an untouched row
keeps the example's own value. Validation and the actual source substitution
(and its fail-closed behaviour) live in the model adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W

from cryostack_src.models.icepack.parameters import (
    BASIC_MODE_PARAMETERS,
    validate_icepack_config,
)


@dataclass
class IcepackBasicPanel:
    container: W.VBox
    _rows: dict = field(default_factory=dict)

    def set_example(self, example_path: str) -> None:  # noqa: ARG002
        """No per-example gating here -- the adapter fail-closes at staging time
        if the selected example does not expose a parameter as a plain literal."""

    def overrides(self) -> dict:
        out: dict = {}
        for name, (enable, control) in self._rows.items():
            if enable.value:
                out[name] = control.value
        return out

    def validate(self):
        result = validate_icepack_config(self.overrides())

        @dataclass
        class _V:
            ok: bool
            errors: list
            normalized: dict

        return _V(result["ok"], result["errors"], result["normalized"])

    def set_visible(self, visible: bool) -> None:
        self.container.layout.display = "" if visible else "none"


def _control_for(spec) -> W.Widget:
    lo = spec.minimum
    hi = spec.maximum
    if spec.kind == "int":
        return W.BoundedIntText(
            value=int(lo if lo is not None else 1),
            min=int(lo) if lo is not None else 1,
            max=int(hi) if hi is not None else 10**9,
            layout=W.Layout(width="160px"),
        )
    return W.BoundedFloatText(
        value=float(lo if lo is not None else 0.0),
        min=float(lo) if lo is not None else -1e12,
        max=float(hi) if hi is not None else 1e12,
        step=0.0,
        layout=W.Layout(width="160px"),
    )


def build_icepack_basic_panel() -> IcepackBasicPanel:
    header = W.HTML("<div class='cryostack-section-label'>Icepack configuration</div>")
    note = W.HTML(
        "<div class='cryostack-help'>Only parameters every Icepack flow example "
        "sets the same way are offered. If the selected example does not set one "
        "as a plain value, the run is blocked with a clear message — use Advanced "
        "mode for that example.</div>"
    )
    rows: dict = {}
    row_boxes: list[W.Widget] = []
    for spec in BASIC_MODE_PARAMETERS:
        enable = W.Checkbox(value=False, indent=False, layout=W.Layout(width="24px"))
        control = _control_for(spec)
        control.disabled = True
        enable.observe(
            lambda ch, c=control: setattr(c, "disabled", not ch["new"]), names="value"
        )
        unit = f" <span class='cryostack-help'>{spec.units}</span>" if spec.units else ""
        label = W.HTML(f"<b>{spec.label}</b>{unit}")
        row_boxes.append(W.HBox([enable, label, control],
                                layout=W.Layout(width="100%", gap="10px",
                                                align_items="center")))
        rows[spec.name] = (enable, control)

    container = W.VBox([header, note, *row_boxes],
                       layout=W.Layout(width="100%", gap="6px"))
    container.add_class("cryostack-icepack-basic-panel")
    return IcepackBasicPanel(container=container, _rows=rows)
