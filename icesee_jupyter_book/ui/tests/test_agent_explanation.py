"""Explanations inspect provenance and shared capabilities without side effects."""
import copy
import pytest
import ipywidgets as W
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent
from icesee_jupyter_book.ui.tests.test_agent_diagnosis import configuration
from icesee_jupyter_book.ui.tests.test_agent_interaction import contents, button, walk, gateway


def fixture(data=None):
    data = configuration() if data is None else data
    writes, validations = [], []
    def apply(values):
        writes.append(copy.deepcopy(values)); data['current'].update(values)
    def validate():
        validations.append(True); return []
    panel = build_configuration_agent(catalog=lambda: copy.deepcopy(data),
        snapshot=lambda: copy.deepcopy(data['current']), apply_values=apply, validate=validate)
    return panel, data, writes, validations


def ask(panel, text):
    next(w for w in walk(panel.container) if isinstance(w, W.Textarea)).value = text
    button(panel, 'Create plan').click()


def test_from_request_readonly_and_no_apply():
    panel, data, writes, checks = fixture()
    ask(panel, 'Change the CPUs to 8')
    before = copy.deepcopy(data)
    ask(panel, 'Why did you change this?')
    assert 'CPUs: 4 → 8 · From request' in contents(panel)
    assert 'explicitly requested' in contents(panel)
    assert data == before and not writes and not checks
    panel.apply(); assert not writes
    assert button(panel, 'Apply to configuration').disabled


def test_suggested_uses_reason_recorded_by_repair():
    panel, _, writes, checks = fixture()
    panel.ask('Fix my configuration')
    count = len(checks)
    ask(panel, 'Why is this Suggested?')
    assert 'Time limit: Not set →' in contents(panel)
    assert 'Suggested' in contents(panel) and 'resource supplies this default time limit' in contents(panel)
    assert not writes and len(checks) == count


def test_suggested_resource_dependency():
    data = configuration(); data['current'].update(mode='cloud', wall_time='01:00:00')
    panel, _, _, _ = fixture(data)
    panel.ask('Keep everything but run this on PACE')
    ask(panel, 'Why is this Suggested?')
    assert 'Cloud → Remote · Suggested' in contents(panel)
    assert 'resource uses Remote execution' in contents(panel)


def test_retained_context_is_compact():
    panel, _, _, _ = fixture()
    panel.ask('Change the CPUs to 8')
    ask(panel, 'Why did you retain this?')
    assert 'Retained settings' in contents(panel) and 'Icepack' in contents(panel)
    assert 'already in the controls' in contents(panel)
    assert '<table' not in contents(panel) and '<pre' not in contents(panel)


@pytest.mark.parametrize('text,expected', [
    ("Why can't I use GPU?", 'does not support GPU'),
    ("Why can't I use multi-node?", 'cloud runtime does not support multi-node'),
    ('Why do I need MATLAB?', 'does not require MATLAB'),
    ('Explain this configuration', 'Current experiment'),
    ('What did you change?', 'No current proposal'),
])
def test_without_active_proposal_and_zero_mutations(text, expected):
    panel, data, writes, checks = fixture(); before = copy.deepcopy(data)
    ask(panel, text)
    assert expected in contents(panel)
    assert data == before and not writes and not checks
    assert 'run_target' not in contents(panel) and '/scratch' not in contents(panel)


@pytest.mark.parametrize('app', ['icesheets', 'icesee'])
def test_matlab_requirement_uses_selected_workflow(app):
    data = configuration(); data['application'] = app
    data['current'].update(model='issm', example='shelf')
    panel, _, _, checks = fixture(data)
    ask(panel, 'Why do I need MATLAB?')
    assert 'uses ISSM, which requires MATLAB' in contents(panel) and not checks


def test_capability_explanation_tracks_metadata(monkeypatch):
    from dataclasses import replace
    from cryostack_src.models import workflow_capabilities
    original = workflow_capabilities.resolve_workflow_capabilities
    monkeypatch.setattr(workflow_capabilities, 'resolve_workflow_capabilities',
        lambda **kw: replace(original(**kw), supports_gpu=True, supports_multinode=True))
    panel, _, _, _ = fixture()
    ask(panel, "Why can't I use GPU?")
    assert 'GPU capability is available' in contents(panel)
    ask(panel, "Why can't I use multi-node?")
    assert 'Multi-node cloud capability is available' in contents(panel)


def test_rejected_proposal_explains_blocking_findings():
    panel, _, writes, checks = fixture()
    panel.ask('Switch this to Cloud using a GPU')
    ask(panel, "Why can't this be applied?")
    assert 'GPU execution is not supported' in contents(panel)
    assert not writes and not checks


def test_capability_uses_proposed_model_then_stale_controls():
    panel, data, _, _ = fixture()
    panel.ask('Run SquareIceShelf with ISSM on PACE')
    ask(panel, 'Why do I need MATLAB?')
    assert 'requires MATLAB' in contents(panel)
    data['current']['cpus'] = 12
    ask(panel, 'Why do I need MATLAB?')
    assert 'Stale proposal' in contents(panel)
    assert 'does not require MATLAB' in contents(panel)


def test_after_apply_and_manual_edits():
    panel, data, writes, checks = fixture()
    panel.ask('Change the CPUs to 8'); panel.apply()
    count = len(checks)
    ask(panel, 'What did you change?')
    assert 'Applied changes' in contents(panel) and '4 → 8' in contents(panel)
    assert len(writes) == 1 and len(checks) == count
    data['current']['cpus'] = 16
    ask(panel, 'What did you change?')
    assert 'Stale proposal' in contents(panel) and '16 CPUs' in contents(panel)
    assert '4 → 8' not in contents(panel)


def test_tampered_proposal_not_explained_as_genuine():
    panel, _, writes, _ = fixture()
    proposal = panel.ask('Change the CPUs to 8'); proposal.values['cpus'] = 200
    ask(panel, 'Why did you change this?')
    assert 'Proposal changed' in contents(panel) and '200' not in contents(panel)
    assert not writes


def test_explanation_does_not_swallow_an_execution_instruction():
    panel, _, writes, _ = fixture()
    panel.ask('Why did you change this? Submit it.')
    panel.apply(); assert not writes


@pytest.mark.parametrize('app', ['icesheets', 'icesee'])
def test_real_gateways_explanation_never_calls_cloud_review(gateway, app):
    host = gateway(app); panel = host['panel']
    if app == 'icesheets':
        host['mode'].value = 'cloud'
    else:
        host['mode_tabs'].selected_index = 2
    before = {k:w.value for k,w in host['fields'].items()}
    for text in ('Explain this configuration', "Why can't I use GPU?", 'Why do I need MATLAB?'):
        ask(panel, text)
        assert not host['checks']
        assert {k:w.value for k,w in host['fields'].items()} == before
        assert button(panel, 'Apply to configuration').disabled
        assert '<pre' not in contents(panel)
