"""The IceSheets gateway wires the Basic-mode Icepack override path (I1)
without disturbing the ISSM Basic-mode path."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesheets_gateway.py"


def test_gateway_has_a_separate_icepack_basic_panel_and_toggle():
    src = _GW.read_text()
    assert "build_icepack_basic_panel()" in src
    assert 'icepack_config_panel.layout.display = "" if (model_dd.value == "icepack" and not is_agent) else "none"' in src
    assert 'icepack_config_panel.set_title(0, "⚙️ Icepack configuration (Basic)")' in src
    # the ISSM panel toggle is model-gated (and hidden in Agent mode)
    assert 'md_config_panel.layout.display = "" if (model_dd.value == "issm" and not is_agent) else "none"' in src


def test_basic_mode_staging_uses_the_adapter_transform_and_fails_closed():
    src = _GW.read_text()
    lo = src.index('elif model_dd.value == "icepack" and not test_mode:')
    block = src[lo: src.index("# CLOUD  (AWS Batch)", lo)]
    assert "icepack_basic_panel.validate()" in block
    assert "entrypoint_transform_for(" in block
    assert "IcepackOverrideError" in block and "IcepackParameterError" in block
    assert "stage_example_for_run(" in block
    # provenance is recorded under a neutral key (not md_overrides)
    assert '"parameter_overrides"' in block
    # canonical example is never the source-of-truth for the transform
    assert "source_example=example_dir.value" in block


@pytest.mark.parametrize("builder", ["build_icesheets_ui"])
def test_gateway_still_builds_with_icepack_basic_wiring(builder, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "ip-basic-test")
    monkeypatch.setenv("USER", "ip-basic-svc")
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    import ipywidgets as W

    page = build_icesheets_ui()
    titles = []

    def walk(w):
        if isinstance(w, W.Accordion):
            titles.extend(w.get_title(i) for i in range(len(w.children)))
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    assert "⚙️ Icepack configuration (Basic)" in titles
    assert "⚙️ ISSM configuration (Basic)" in titles
