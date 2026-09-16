import copy
import ipywidgets as W
from cryostack_src.agents.tests.test_configuration_intent import catalog
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent, set_fields, remote_findings


def panel_fixture():
    c = catalog()
    applied = []
    checks = []
    def validate():
        checks.append(True)
        return ["Enter your HPC username."]
    panel = build_configuration_agent(catalog=lambda: copy.deepcopy(c),
        apply_values=lambda v: applied.append(v), snapshot=lambda: c["current"], validate=validate)
    return panel, c, applied, checks


def test_prepare_does_not_apply_or_validate_execution():
    panel, c, applied, checks = panel_fixture()
    assert panel.ask("Run SquareIceShelf on PACE with 4 CPUs").applicable
    assert applied == [] and checks == []
    assert panel.apply() == ["Enter your HPC username."]
    assert len(applied) == len(checks) == 1
    panel.apply()
    assert len(applied) == 1


def test_stale_proposal_refused():
    panel, c, applied, checks = panel_fixture()
    panel.ask("Run SquareIceShelf on PACE")
    c["current"]["nodes"] = 2
    assert panel.apply() is None
    assert not applied and not checks


def test_mutated_proposal_refused():
    panel, c, applied, checks = panel_fixture()
    p = panel.ask("Run SquareIceShelf on PACE")
    p.values["cpus"] = 999
    assert panel.apply() is None and not applied


def test_revision_and_unsupported_request_clear_previous_plan():
    panel, c, applied, checks = panel_fixture()
    panel.ask("Run SquareIceShelf on PACE")
    panel.ask("Run SquareIceShelf on cloud GPU")
    panel.apply()
    assert not applied


def test_widget_bounds_never_silently_clamp():
    import pytest
    w = W.IntSlider(value=30, min=1, max=200)
    with pytest.raises(ValueError):
        set_fields({"ensemble_size": 500}, {"ensemble_size": w})
    assert w.value == 30


def test_shared_slurm_validation_is_called(monkeypatch):
    from icesee_jupyter_book.ui import shared_validation
    calls = []
    def validate(**kw):
        calls.append(kw)
        return ["resource error"]
    monkeypatch.setattr(shared_validation, "validate_slurm_resources", validate)
    fields = {k: W.Text(value=v) for k,v in dict(profile="pace",wall_time="01:00:00",memory="64G",account="",user="",directory="").items()}
    fields.update({k: W.IntText(value=v) for k,v in dict(nodes=1,cpus=4,tasks_per_node=4).items()})
    errors = remote_findings(fields)
    assert calls[0]["tasks"] == 4 and "resource error" in errors
    assert any("HPC username" in e for e in errors)


def test_no_approval_or_submission_controls():
    panel, *_ = panel_fixture()
    def walk(w):
        yield w
        for child in getattr(w, "children", ()):
            yield from walk(child)
    labels = [w.description for w in walk(panel.container) if isinstance(w, W.Button)]
    assert labels == ["Create plan", "Apply to configuration"]


def test_actual_icesheets_controls_receive_proposal(monkeypatch):
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui import configuration_agent as module
    from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
    monkeypatch.setenv("CRYOSTACK_AGENT_PANEL", "1")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "agent-integration")
    captured = {}
    original = module.build_icesheets_configuration_agent
    def capture(**kw):
        captured.update(kw)
        panel = original(**kw)
        captured["panel"] = panel
        return panel
    monkeypatch.setattr(module, "build_icesheets_configuration_agent", capture)
    page = build_icesheets_ui()
    assert page is not None and "panel" in captured
    p = captured["panel"].ask("Run SquareIceShelf with ISSM on PACE using 4 CPUs")
    assert p is not None and p.applicable, p
    captured["panel"].apply()
    assert captured["model"].value == "issm"
    assert captured["fields"]["cpus"].value == 4
    assert captured["fields"]["tasks_per_node"].value == 4
    assert captured["mode"].value == "remote"
    p = captured["panel"].ask("Run 01-synthetic-ice-sheet with Icepack on PACE using ice temperature 255")
    assert p is not None and p.applicable, p
    captured["panel"].apply()
    assert captured["model"].value == "icepack"
    assert captured["icepack_panel"].overrides() == {"ice_temperature": 255.0}
    assert captured["icepack_panel"].validate().ok


def test_actual_icesee_controls_receive_proposal(monkeypatch):
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui import configuration_agent as module
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    monkeypatch.setenv("CRYOSTACK_AGENT_PANEL", "1")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "agent-icesee-integration")
    captured = {}
    original = module.build_icesee_configuration_agent
    def capture(**kw):
        captured.update(kw)
        panel = original(**kw)
        captured["panel"] = panel
        return panel
    monkeypatch.setattr(module, "build_icesee_configuration_agent", capture)
    page = build_icesee_ui()
    assert page is not None and "panel" in captured
    p = captured["panel"].ask("Prepare Lorenz96 locally with ensemble size 20 and DEnKF")
    assert p is not None and p.applicable, p
    captured["panel"].apply()
    assert captured["ensemble"].value == 20
    assert captured["filter_widget"].value == "DEnKF"
    assert captured["mode_tabs"].selected_index == 0
    params = captured["params_snapshot"]()
    assert any(isinstance(section, dict) and section.get("Nens") == 20 for section in params.values())
