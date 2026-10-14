"""Stateless refinements always read and preserve the current manual baseline."""
import copy
import pytest

from cryostack_src.agents.intent import infer_request
from icesee_jupyter_book.ui.tests.test_agent_diagnosis import configuration, panel_fixture
from icesee_jupyter_book.ui.tests.test_agent_interaction import contents, button, gateway


@pytest.mark.parametrize('prompt,delta', [
    ('Change the CPUs to 8', {'cpus': 8}),
    ('Keep everything but run this on PACE', {'profile': 'pace', 'mode': 'remote'}),
    ('Switch this to Cloud', {'mode': 'cloud'}),
    ('Change only the backend to spack', {'backend': 'spack'}),
])
def test_single_dimension_retains_current_values(prompt, delta):
    data = configuration(); original = copy.deepcopy(data)
    proposal = infer_request(prompt, data)
    assert proposal.applicable, proposal
    assert proposal.refinement
    assert {k: v for k, v in proposal.values.items() if k not in ('model', 'example')} == delta
    assert proposal.values['example'] == data['current']['example']
    assert proposal.values['model'] == data['current']['model']
    assert data == original


def test_keep_explicit_model_and_example():
    data = configuration(); data['current'].update(model='issm', example='shelf')
    proposal = infer_request('Keep ISSM and the current example but use 16 CPUs', data)
    assert proposal.applicable and proposal.values['example'] == 'shelf'
    assert proposal.values['cpus'] == 16 and 'tasks_per_node' not in proposal.values
    assert 'model' in proposal.retained and 'example' in proposal.retained
    data['current'].update(model='icepack', example='sheet')
    assert not infer_request('Keep ISSM and the current example but use 16 CPUs', data).applicable


def test_resource_implies_remote_and_explains_suggestion():
    data = configuration(); data['current'].update(mode='cloud', wall_time='01:00:00')
    panel, writes, _ = panel_fixture(data)
    proposal = panel.ask('Keep everything but run this on PACE')
    assert proposal.applicable and proposal.suggested == ['mode']
    assert 'Suggested' in contents(panel) and 'uses Remote execution' in contents(panel)
    assert not writes
    panel.apply(); assert data['current']['mode'] == 'remote'


def test_cpu_decrease_requires_clarification_instead_of_overwriting_tasks():
    data = configuration(); data['current'].update(cpus=16, tasks_per_node=16)
    proposal = infer_request('Change the CPUs to 8', data)
    assert not proposal.applicable and 'tasks_per_node' not in proposal.values
    assert any('cannot exceed' in message for message in proposal.unresolved)
    proposal = infer_request('Change the CPUs to 8 and use 8 tasks per node', data)
    assert proposal.applicable and proposal.values['tasks_per_node'] == 8


@pytest.mark.parametrize('prompt', [
    'Change only the filter to EnKF and use 8 CPUs',
    'Switch this to Cloud with 2 nodes',
    'Switch this to Cloud using a GPU',
    'Keep everything but run this on PACE or ub-ccr',
    'Change the CPUs to -8',
    'Change the CPUs to 8 and submit',
])
def test_unsupported_or_conflicting_refinement_has_no_apply(prompt):
    data = configuration(); data['application'] = 'icesee'; data['filters'] = ['EnKF', 'DEnKF']
    panel, writes, _ = panel_fixture(data)
    proposal = panel.ask(prompt)
    assert not proposal.applicable
    panel.apply(); assert not writes
    assert button(panel, 'Apply to configuration').disabled


def test_repeated_apply_manual_edit_staleness_and_matching_request():
    data = configuration(); data['current']['wall_time'] = '01:00:00'
    panel, writes, checks = panel_fixture(data)
    panel.ask('Change the CPUs to 8'); panel.apply()
    assert data['current']['cpus'] == 8 and data['current']['tasks_per_node'] == 4
    data['current']['memory'] = '128G'
    panel.ask('Change the CPUs to 12'); panel.apply()
    assert data['current']['cpus'] == 12 and data['current']['memory'] == '128G'
    panel.ask('Change the CPUs to 16')
    data['current']['cpus'] = 20
    panel.apply(); assert len(writes) == 2 and data['current']['cpus'] == 20
    panel.ask('Change the CPUs to 20')
    assert 'No changes needed' in contents(panel)
    panel.apply(); assert len(writes) == 2 and checks[-1]['cpus'] == 20


def test_tampered_refinement_refused():
    data = configuration(); panel, writes, _ = panel_fixture(data)
    proposal = panel.ask('Change the CPUs to 8')
    proposal.values['backend'] = 'spack'
    panel.apply(); assert not writes


@pytest.mark.parametrize('prompt,expected', [
    ('Use the same configuration with 50 ensemble members', {'ensemble_size': 50}),
    ('Change only the filter to EnKF', {'filter': 'EnKF'}),
])
def test_icesee_filter_and_ensemble_are_independent(prompt, expected):
    data = configuration(); data['application'] = 'icesee'
    data['filters'] = ['EnKF', 'DEnKF']; data['current'].update(ensemble_size=20, filter='DEnKF')
    p = infer_request(prompt, data)
    assert p.applicable
    assert {k:v for k,v in p.values.items() if k not in ('model', 'example')} == expected


@pytest.mark.parametrize('app', ['icesheets', 'icesee'])
def test_real_manual_controls_remain_authoritative(gateway, app):
    host = gateway(app); panel = host['panel']; fields = host['fields']
    if app == 'icesheets':
        host['mode'].value = 'remote'
    else:
        host['mode_tabs'].selected_index = 1
    for key, value in dict(profile='pace', cpus=4, tasks_per_node=4, nodes=1,
                           wall_time='01:00:00', memory='64G', account='project',
                           user='scientist', directory='/scratch/science').items():
        fields[key].value = value
    before = {k:w.value for k,w in fields.items()}
    example = host['example'].value
    assert panel.ask('Change the CPUs to 8').applicable
    panel.apply()
    assert {k:w.value for k,w in fields.items()} == dict(before, cpus=8)
    assert host['example'].value == example
    if app == 'icesee':
        old_filter = host['filter_widget'].value
        panel.ask('Use the same configuration with 50 ensemble members'); panel.apply()
        assert host['ensemble'].value == 50 and host['filter_widget'].value == old_filter
        panel.ask('Change only the filter to EnKF'); panel.apply()
        assert host['ensemble'].value == 50 and host['filter_widget'].value == 'EnKF'
    else:
        backends = [value for _, value in host['backend'].options]
        target = next(value for value in backends if value != host['backend'].value)
        assert panel.ask('Change only the backend to ' + target).applicable
        panel.apply(); assert host['backend'].value == target
        assert fields['cpus'].value == 8 and host['example'].value == example
    fields['memory'].value = '128G'
    panel.ask('Change the CPUs to 12'); panel.apply()
    assert fields['memory'].value == '128G' and fields['cpus'].value == 12
    panel.ask('Switch this to Cloud'); panel.apply()
    assert not host['checks']  # Refinement never invokes credential-resolving Cloud Review.
    assert 'Cloud readiness has not been checked here' in contents(panel)
    assert panel.ask('Keep everything but run this on PACE').applicable
    panel.apply()
    assert fields['memory'].value == '128G' and fields['cpus'].value == 12


def test_resource_identity_reload_is_not_silently_applied():
    data = configuration(); data['current']['profile'] = 'ub-ccr'
    data['resource_switch_requires_review'] = True
    panel, writes, _ = panel_fixture(data)
    assert not panel.ask('Keep everything but run this on PACE').applicable
    assert 'saved connection' in contents(panel)
    panel.apply(); assert not writes
