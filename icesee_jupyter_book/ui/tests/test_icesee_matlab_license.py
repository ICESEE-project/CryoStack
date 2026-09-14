"""ICESEE's own MATLAB license configuration -- closing the gap where
preflight correctly required a MATLAB license for an ICESEE run whose
forecast model is ISSM, but the gateway had no widget to configure it.

Reuses CryoLauncher's own field/save implementation
(cryostack_src.frontend.cryolauncher.cloud_environment.
wire_matlab_license_widgets) -- never a second, ICESEE-only one -- and
visibility is driven exclusively by
cryostack_src.models.workflow_capabilities.resolve_workflow_capabilities,
never a duplicated ``model == "issm"`` check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _find_widget_by_observer(page, handler_name: str):
    found = {}

    def walk(w):
        if handler_name not in found:
            notifiers = getattr(w, "_trait_notifiers", None)
            if notifiers and "value" in notifiers:
                for handlers in notifiers["value"].values():
                    for h in handlers:
                        if getattr(h, "__name__", "") == handler_name:
                            found[handler_name] = (w, h)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found.get(handler_name)


def _build(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _gateway_state(monkeypatch, tmp_path, *, user):
    page = _build(monkeypatch, tmp_path, user=user)
    # _update_icesee_run_plan_summary is observed by several widgets
    # (mode_tabs/exec_backend_choice/example_dd/filter_alg_dd/ens_sl) --
    # whichever one the tree walk finds first, the HANDLER FUNCTION is the
    # same object either way, so its closure has every widget we need.
    _matched_widget, update_summary = _find_widget_by_observer(
        page, "_update_icesee_run_plan_summary")
    assert update_summary is not None, "_update_icesee_run_plan_summary not wired"
    return {
        "page": page,
        "example_dd": _freevar(update_summary, "example_dd"),
        "update_summary": update_summary,
        "icesee_cloud_environment": _freevar(update_summary, "icesee_cloud_environment"),
    }


LORENZ = "Lorenz-96 (fully runnable locally)"
ISSM_EXAMPLE = "ISSM (fully runable in Remote)"
ICEPACK_EXAMPLE = "Icepack (under development)"


# ── visibility: driven exclusively by the workflow-capability resolver ───
def test_lorenz96_hides_matlab_license(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-lorenz-user")
    assert state["example_dd"].value == LORENZ
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == "none"


def test_icepack_example_hides_matlab_license(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-icepack-user")
    state["example_dd"].value = ICEPACK_EXAMPLE
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == "none"


def test_issm_example_shows_matlab_license(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-issm-user")
    state["example_dd"].value = ISSM_EXAMPLE
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == ""


def test_coupled_issm_icepack_forecast_model_shows_matlab_license(monkeypatch, tmp_path):
    """A forecast model naming BOTH ISSM and Icepack (a coupled ICESEE run)
    must still require MATLAB -- the resolver, not a specific example,
    decides this. No bundled example currently declares a coupled
    forecast_model, so the identity is stubbed at the exact point ICESEE's
    own Run Plan already computes it (single source of truth)."""
    import icesee_jupyter_book.ui.icesee_gateway as icesee_gw
    from icesee_jupyter_book.core.run_records import DAIdentity

    state = _gateway_state(monkeypatch, tmp_path, user="icesee-coupled-user")
    monkeypatch.setattr(
        icesee_gw, "da_identity_from_params",
        lambda _cfg: DAIdentity(forecast_model="issm+icepack coupled"))
    state["update_summary"]()
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == ""


def test_visibility_is_independent_of_basic_or_advanced_infra_mode(monkeypatch, tmp_path):
    """ICESEE has no Basic/Advanced infra toggle of its own, but the switch
    that DOES exist for it -- the mode Tab (Local/Remote/Cloud) -- must
    never affect MATLAB visibility either; only the workflow does."""
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-mode-indep-user")
    state["example_dd"].value = ISSM_EXAMPLE
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == ""

    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(state["page"])
    assert mode_tabs is not None
    for idx in (0, 1, 2, 0):
        mode_tabs.selected_index = idx
        assert ce.matlab_license_box.layout.display == ""


# ── persistence across workflow changes ───────────────────────────────────
def test_matlab_license_value_survives_switching_to_a_non_matlab_example(monkeypatch, tmp_path):
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-persist-user")
    ce = state["icesee_cloud_environment"]

    state["example_dd"].value = ISSM_EXAMPLE
    assert ce.matlab_license_box.layout.display == ""
    arn = "arn:aws:secretsmanager:us-east-2:774888247882:secret:cryostack/issm-matlab-Ab1"
    ce.matlab_license_arn.value = arn

    state["example_dd"].value = LORENZ
    assert ce.matlab_license_box.layout.display == "none"
    assert ce.matlab_license_arn.value == arn      # never cleared

    state["example_dd"].value = ISSM_EXAMPLE
    assert ce.matlab_license_box.layout.display == ""
    assert ce.matlab_license_arn.value == arn


# ── save behavior reuses the exact shared implementation ──────────────────
def test_save_button_uses_the_shared_wire_matlab_license_widgets_helper():
    src = Path(
        _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"
    ).read_text()
    assert "wire_matlab_license_widgets(" in src
    # never a second, ICESEE-only save/prefill implementation
    assert "_save_matlab_license_arn" not in src
    assert "assert_not_a_license_value" not in src


# ── preflight enforces the requirement independent of UI visibility ──────
def test_icesee_review_blocks_launch_without_a_license_even_though_ui_agrees(
    monkeypatch, tmp_path
):
    """The UI correctly SHOWS the field for an ISSM forecast model; but
    preflight -- not the UI -- is what must actually refuse to launch when
    no ARN has been configured. Proves the two never disagree."""
    state = _gateway_state(monkeypatch, tmp_path, user="icesee-preflight-user")
    state["example_dd"].value = ISSM_EXAMPLE
    ce = state["icesee_cloud_environment"]
    assert ce.matlab_license_box.layout.display == ""   # UI agrees it's needed
    assert ce.matlab_license_arn.value == ""             # nothing configured

    from icesee_jupyter_book.core.cloud_review import build_icesee_cloud_review
    from cryostack_src.cloud.review import InfrastructureReadiness

    review = build_icesee_cloud_review(
        forecast_model="issm", filter_alg="EnKF", ensemble_size=30,
        parallel_processes=1, account_id="774888247882", region="us-east-2",
        infrastructure=InfrastructureReadiness(
            account=True, storage=True, container=True, compute=True),
        account_freshly_verified=True, example_name="lorenz96",
        matlab_license_configured=bool(ce.matlab_license_arn.value.strip()),
    )
    assert review.can_launch is False
    assert any("MATLAB license" in r for r in review.blocked_reasons)
