"""Container image selector for the ICESEE-Container backend (Docker/OCI source).

For a Docker/OCI source the user picks from a curated list of CryoStack-tested
images (:data:`cryostack_src.models.stack.TESTED_IMAGES`) instead of typing an
OCI reference by hand. Only tested images whose registry entry supports the
currently selected model are offered.

Stack-profile behaviour:

* ``tested``  -- curated tested-image selection only; no ``Custom image…`` entry,
  so an empty Docker URI can never reach submission.
* ``custom``  -- tested images stay selectable and ``Custom image…`` is offered;
  choosing it reveals a free-text OCI reference field and a small warning that
  CryoStack has not validated the custom image against the selected stack.

Git / Local SIF sources do not use this panel — the gateway keeps its existing
free-text Image field for those (``.def`` name / SIF path).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

import ipywidgets as W

from cryostack_src.models.stack import (
    TestedImage,
    default_tested_image_for_model,
    get_tested_image,
    tested_images_for_model,
)

_MODE_CUSTOM = "__custom__"

# Loose OCI reference shape: registry/name[:tag][@sha256:...]; no whitespace.
_OCI_RE = re.compile(r"\A[A-Za-z0-9][\w./:@-]*\Z")


@dataclass(frozen=True)
class ContainerImageSelection:
    mode: str                     # "tested" | "custom"
    tested_key: str | None
    custom_uri: str | None

    @property
    def image_uri(self) -> str:
        """The reference to hand to submission (empty only for an unset custom)."""
        if self.mode == "tested" and self.tested_key:
            return get_tested_image(self.tested_key).reference
        return (self.custom_uri or "").strip()

    @property
    def tested_image(self) -> TestedImage | None:
        if self.mode == "tested" and self.tested_key:
            return get_tested_image(self.tested_key)
        return None


@dataclass
class ContainerImagePanel:
    container: W.VBox
    _state: dict

    # ── read side ─────────────────────────────────────────────────────────
    def selection(self) -> ContainerImageSelection:
        dd = self._state["dropdown"]
        if dd.value == _MODE_CUSTOM:
            return ContainerImageSelection("custom", None, self._state["custom_uri"].value)
        return ContainerImageSelection("tested", dd.value, None)

    def validate(self) -> str | None:
        """Return a blocking message, or ``None`` when the selection is submittable.

        Only meaningful when the Docker/OCI source is active; the gateway calls
        it in that case.
        """
        sel = self.selection()
        if sel.mode == "tested":
            if not sel.tested_key:
                return (
                    f"No CryoStack-tested image is available for "
                    f"'{self._state['model']}'. Switch the stack profile to "
                    f"Custom to supply your own OCI image."
                )
            return None
        uri = (sel.custom_uri or "").strip()
        if not uri:
            return (
                "Enter a custom OCI image reference, or choose a "
                "CryoStack-tested image."
            )
        bare = uri.split("://", 1)[-1] if "://" in uri else uri
        if not bare or not _OCI_RE.match(bare):
            return f"'{uri}' is not a valid OCI image reference."
        return None

    # ── write side ───────────────────────────────────────────────────────
    def set_model(self, model: str) -> None:
        self._state["model"] = (model or "issm").strip().lower()
        self._state["rebuild"]()

    def set_profile(self, profile: str) -> None:
        self._state["profile"] = (profile or "tested").strip().lower()
        self._state["rebuild"]()

    def set_visible(self, visible: bool) -> None:
        self.container.layout.display = "" if visible else "none"

    def on_change(self, callback) -> None:
        self._state["listeners"].append(callback)


def _tested_note_html(img: TestedImage) -> str:
    return (
        "<div class='icesee-subtle' style='line-height:1.5;'>"
        "<span style='color:#1a7f37;font-weight:600;'>&#10003; CryoStack-tested image</span>"
        f" &nbsp;<code>{html.escape(img.reference)}</code>"
        f" &nbsp;<span style='color:#66758d;'>{html.escape(img.short_digest)}</span>"
        "</div>"
    )


_CUSTOM_WARNING_HTML = (
    "<div class='icesee-subtle' style='line-height:1.5;color:#9a6700;'>"
    "&#9888; CryoStack has not validated this custom image against the selected "
    "software/model stack."
    "</div>"
)


def build_container_image_panel() -> ContainerImagePanel:
    dropdown = W.Dropdown(options=[], layout=W.Layout(width="320px"))
    custom_uri = W.Text(
        placeholder="e.g. ghcr.io/my-org/my-image:tag  or  repo/image@sha256:…",
        layout=W.Layout(width="100%", display="none"),
    )
    tested_note = W.HTML()
    custom_warning = W.HTML(layout=W.Layout(display="none"))

    image_row = W.HBox(
        [W.HTML("<div class='icesee-lbl'>Image:</div>", layout=W.Layout(width="120px", min_width="120px")),
         dropdown],
        layout=W.Layout(gap="10px", width="100%", align_items="center"),
    )
    custom_row = W.HBox(
        [W.HTML("<div class='icesee-lbl'>Custom image URI:</div>",
                layout=W.Layout(width="120px", min_width="120px")),
         custom_uri],
        layout=W.Layout(gap="10px", width="100%", align_items="center", display="none"),
    )

    container = W.VBox(
        [image_row, tested_note, custom_row, custom_warning],
        layout=W.Layout(width="100%", gap="6px"),
    )

    state: dict = {
        "dropdown": dropdown,
        "custom_uri": custom_uri,
        "model": "issm",
        "profile": "tested",
        "listeners": [],
    }

    def _notify(*_):
        for cb in state["listeners"]:
            cb()

    def _apply(*_):
        is_custom = dropdown.value == _MODE_CUSTOM
        custom_row.layout.display = "none" if not is_custom else "flex"
        custom_uri.layout.display = "none" if not is_custom else ""
        custom_warning.layout.display = "" if is_custom else "none"
        if is_custom:
            tested_note.value = ""
        else:
            try:
                tested_note.value = _tested_note_html(get_tested_image(dropdown.value))
            except KeyError:
                tested_note.value = ""
        _notify()

    def _rebuild(*_):
        model = state["model"]
        profile = state["profile"]
        compatible = tested_images_for_model(model)
        options: list[tuple[str, str]] = [
            (f"{img.label} — Tested", img.key) for img in compatible
        ]
        if profile == "custom":
            options.append(("Custom image…", _MODE_CUSTOM))

        prev = dropdown.value
        dropdown.options = options
        valid_values = {v for _l, v in options}
        if prev in valid_values:
            dropdown.value = prev
        else:
            default = default_tested_image_for_model(model)
            dropdown.value = (
                default.key if default is not None
                else (_MODE_CUSTOM if _MODE_CUSTOM in valid_values else None)
            )
        _apply()

    dropdown.observe(_apply, names="value")
    custom_uri.observe(_notify, names="value")
    state["rebuild"] = _rebuild
    _rebuild()

    return ContainerImagePanel(container=container, _state=state)
