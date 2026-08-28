"""CryoLauncher "Software versions" panel (container backend only).

Default is ``Stack profile: Tested`` — the image's validated stack, no network
resolution and no source overrides. ``Custom`` exposes only the technically
valid choices for the selected model; locked components stay visible but
disabled.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

import ipywidgets as W

from cryostack_src.models.stack import (
    COMPONENTS,
    MODE_IMAGE,
    MODE_REF,
    MODEL_COMPONENTS,
    ComponentSelection,
    offered_options,
)

_PROFILE_TESTED = "tested"
_PROFILE_CUSTOM = "custom"


@dataclass
class SoftwareStackPanel:
    container: W.VBox
    _state: dict

    def profile(self) -> str:
        return self._state["profile"].value

    def selections(self) -> dict:
        """Non-image selections, keyed by component. Empty under 'Tested'."""
        if self.profile() != _PROFILE_CUSTOM:
            return {}
        out: dict[str, ComponentSelection] = {}
        for key, (dd, ref) in self._state["rows"].items():
            mode, opt_ref = dd.value
            if mode == MODE_IMAGE:
                continue
            chosen_ref = (ref.value.strip() or None) if mode == MODE_REF else opt_ref
            out[key] = ComponentSelection(key, mode, chosen_ref)
        return out

    def set_model(self, model: str) -> None:
        self._state["build"]((model or "issm").strip().lower())

    def set_visible(self, visible: bool) -> None:
        self.container.layout.display = "" if visible else "none"


def _row_label(comp) -> str:
    if comp.locked:
        ver = comp.baked_version or "image"
        return (
            f"<b>{html.escape(comp.label)}</b>"
            f"<span class='cryostack-stack-lock'> &nbsp;{html.escape(ver)} · image version 🔒</span>"
        )
    return f"<b>{html.escape(comp.label)}</b>"


def build_software_stack_panel() -> SoftwareStackPanel:
    profile = W.ToggleButtons(
        options=[("Tested", _PROFILE_TESTED), ("Custom", _PROFILE_CUSTOM)],
        value=_PROFILE_TESTED,
        layout=W.Layout(width="auto"),
    )
    rows_box = W.VBox(layout=W.Layout(gap="6px"))
    hint = W.HTML()
    container = W.VBox(
        [
            W.HTML("<div class='cryostack-section-label'>Software versions</div>"),
            profile,
            rows_box,
            hint,
        ],
        layout=W.Layout(width="100%", gap="8px"),
    )

    state: dict = {"profile": profile, "model": "issm", "rows": {}}

    def _apply_profile(*_):
        custom = profile.value == _PROFILE_CUSTOM
        for key, (dd, ref) in state["rows"].items():
            dd.disabled = COMPONENTS[key].locked or not custom
            if not custom:
                dd.value = dd.options[0][1]           # back to image
                ref.layout.display = "none"
            else:
                mode = dd.value[0]
                ref.layout.display = "" if mode == MODE_REF else "none"
        hint.value = (
            "<span class='icesee-subtle'>Custom: only validated overrides are offered. "
            "Refs are resolved to an exact commit before submission.</span>"
            if custom
            else "<span class='icesee-subtle'>Runs the image's validated stack exactly "
            "(no network resolution, no source overrides).</span>"
        )

    def _build(model: str) -> None:
        state["model"] = model
        rows = []
        state["rows"] = {}
        for key in MODEL_COMPONENTS.get(model, ()):
            comp = COMPONENTS[key]
            opts = offered_options(key)
            dd = W.Dropdown(
                options=[(o.label, (o.mode, o.ref)) for o in opts],
                value=(opts[0].mode, opts[0].ref),
                layout=W.Layout(width="220px"),
            )
            ref = W.Text(
                placeholder="tag / branch / 40-char commit",
                layout=W.Layout(width="260px", display="none"),
            )

            def _on_change(change, _ref=ref):
                _ref.layout.display = "" if change["new"][0] == MODE_REF else "none"

            dd.observe(_on_change, names="value")
            state["rows"][key] = (dd, ref)
            rows.append(
                W.HBox(
                    [W.HTML(_row_label(comp), layout=W.Layout(width="150px")), dd, ref],
                    layout=W.Layout(align_items="center", gap="10px"),
                )
            )
        rows_box.children = tuple(rows)
        _apply_profile()

    state["build"] = _build
    profile.observe(_apply_profile, names="value")
    _build("issm")

    return SoftwareStackPanel(container=container, _state=state)
