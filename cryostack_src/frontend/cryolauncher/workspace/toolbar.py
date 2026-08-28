from __future__ import annotations

import ipywidgets as W


def build_workspace_toolbar(
    controls,
    *,
    justify_content: str | None = None,
    margin: str | None = None,
) -> W.HBox:
    layout = W.Layout(
        width="100%",
        gap="8px" if justify_content is None else "10px",
        flex_wrap="wrap",
        align_items="center",
    )
    if justify_content is not None:
        layout.justify_content = justify_content
    if margin is not None:
        layout.margin = margin
    return W.HBox(list(controls), layout=layout)
