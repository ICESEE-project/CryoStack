"""Diagnosis and repair share manual validators and never execute a workflow."""
import copy
import pytest

from cryostack_src.agents.diagnosis import diagnosis_request, diagnose_configuration
from cryostack_src.agents.tests.test_configuration_intent import catalog
from cryostack_src.resources.profiles import get_compute_profile
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent
from icesee_jupyter_book.ui.tests.test_agent_interaction import contents, button, gateway


def configuration():
    data = catalog()
    data['current'].update(model='icepack', profile='pace', cpus=4, nodes=1,
        tasks_per_node=4, wall_time='', memory='64G', account='project',
        user='scientist', directory='/scratch/science', backend='container')
    return data


def panel_fixture(data, findings=()):
    writes, checks = [], []
    def apply(values):
        writes.append(copy.deepcopy(values))
        data['current'].update(values)
    def validate():
        checks.append(copy.deepcopy(data['current']))
        return list(findings)
    panel = build_configuration_agent(catalog=lambda: copy.deepcopy(data),
        snapshot=lambda: copy.deepcopy(data['current']), apply_values=apply,
        validate=validate)
    return panel, writes, checks


@pytest.mark.parametrize('text,kind', [
    ("Why can't I run this?", 'diagnose'),
    ("What's wrong with my configuration?", 'diagnose'),
    ('Fix my configuration', 'repair'),
    ('Make this configuration runnable', 'repair'),
    ('Please fix my configuration.', 'repair'),
    ('Fix my configuration using GPU', None),
    ('Fix my configuration; submit it', None),
])
def test_request_intent_is_bounded(text, kind):
    assert diagnosis_request(text) == kind


def test_diagnosis_only_reads_and_explains_missing_duration():
    data = configuration(); original = copy.deepcopy(data)
    panel, writes, checks = panel_fixture(data)
    panel.ask("Why can't I run this?")
    assert 'Wall time is required' in contents(panel)
    assert 'Configuration changes' not in contents(panel)
    assert button(panel, 'Apply to configuration').layout.display == 'none'
    panel.apply()
    assert data == original and not writes and len(checks) == 1


def test_deterministic_repair_uses_profile_default_and_validates_after_apply():
    data = configuration(); panel, writes, checks = panel_fixture(data)
    proposal = panel.ask('Fix my configuration')
    default = get_compute_profile('pace').scheduler_defaults.wall_time
    assert proposal.applicable and proposal.values['wall_time'] == default
    assert 'Suggested' in contents(panel) and 'Retained' in contents(panel)
    assert all(title in contents(panel) for title in ('Setting', 'Current', 'Proposed', 'Source'))
    assert not writes and data['current']['wall_time'] == ''
    panel.apply()
    assert len(writes) == 1 and checks[-1]['wall_time'] == default
    assert '1 setting changed' in contents(panel)
    panel.apply(); assert len(writes) == 1


def test_repair_default_is_metadata_not_literal(monkeypatch):
    from dataclasses import replace
    from cryostack_src.agents import diagnosis
    profile = get_compute_profile('pace')
    monkeypatch.setattr(diagnosis, 'get_compute_profile', lambda _: replace(profile,
        scheduler_defaults=replace(profile.scheduler_defaults, wall_time='02:30:00')))
    result = diagnose_configuration(configuration(), [])
    assert result.proposal.values['wall_time'] == '02:30:00'


@pytest.mark.parametrize('prompt', ["What's wrong with my configuration?", 'Make this configuration runnable'])
def test_already_valid_needs_no_changes(prompt):
    data = configuration(); data['current']['wall_time'] = '01:00:00'
    panel, writes, _ = panel_fixture(data)
    panel.ask(prompt)
    assert 'No changes needed' in contents(panel)
    assert button(panel, 'Apply to configuration').disabled
    panel.apply(); assert not writes


@pytest.mark.parametrize('updates,expected', [
    ({'mode': 'local'}, 'remote, cloud'),
    ({'tasks_per_node': 8, 'wall_time': '01:00:00'}, 'cannot exceed'),
    ({'wall_time': 'tomorrow'}, 'Wall time must look'),
    ({'user': ''}, 'HPC username'),
    ({'example': 'missing'}, 'supported example'),
])
def test_ambiguous_or_unsupported_settings_are_not_guessed(updates, expected):
    data = configuration(); data['current'].update(updates)
    panel, writes, _ = panel_fixture(data)
    p = panel.ask('Fix my configuration')
    assert not p.applicable and expected in contents(panel)
    assert 'No deterministic repair' in contents(panel)
    panel.apply(); assert not writes


def test_stale_repair_refuses_manual_edit_and_next_diagnosis_reads_it():
    data = configuration(); panel, writes, _ = panel_fixture(data)
    panel.ask('Fix my configuration')
    data['current']['wall_time'] = '03:00:00'
    panel.apply()
    assert not writes and 'Settings changed' in contents(panel)
    panel.ask('Fix my configuration')
    assert 'No changes needed' in contents(panel)
    assert data['current']['wall_time'] == '03:00:00'


def test_changed_validation_refuses_repair_even_without_control_edits():
    data = configuration(); blockers = []
    panel, writes, _ = panel_fixture(data, blockers)
    panel.ask('Fix my configuration')
    blockers.append('Backend is unavailable.')
    panel.apply()
    assert not writes and 'proposal changed' in contents(panel)


@pytest.mark.parametrize('app', ['icesheets', 'icesee'])
def test_real_gateways_diagnose_and_repair_manual_controls(gateway, app):
    host = gateway(app); panel = host['panel']; fields = host['fields']
    if app == 'icesheets':
        host['mode'].value = 'remote'
    else:
        host['mode_tabs'].selected_index = 1
    for key, value in dict(profile='pace', user='scientist', directory='/scratch/science',
                           account='project', cpus=4, nodes=1, tasks_per_node=4,
                           wall_time='', memory='64G').items():
        fields[key].value = value
    before = {k: w.value for k, w in fields.items()}
    panel.ask("What's wrong with my configuration?")
    assert before == {k: w.value for k, w in fields.items()}
    assert 'Wall time is required' in contents(panel)
    assert panel.ask('Fix my configuration').applicable
    panel.apply()
    assert fields['wall_time'].value == get_compute_profile('pace').scheduler_defaults.wall_time
    fields['wall_time'].value = '03:00:00'
    panel.ask('Fix my configuration')
    assert 'No changes needed' in contents(panel)
    assert fields['wall_time'].value == '03:00:00'
    if app == 'icesheets':
        host['mode'].value = 'cloud'
    else:
        host['mode_tabs'].selected_index = 2
    panel.ask('Fix my configuration')
    assert 'Cloud readiness has not been checked here' in contents(panel)
    assert not host['checks']  # Never call credential-resolving cloud review.
    assert button(panel, 'Apply to configuration').disabled


@pytest.mark.parametrize('app', ['icesheets', 'icesee'])
def test_matlab_requirement_comes_from_workflow_capabilities(app):
    data = configuration(); data['application'] = app
    data['current'].update(example='shelf', model='issm', mode='cloud')
    result = diagnose_configuration(data, ['MATLAB license readiness must be confirmed in Cloud Review.'])
    assert any('requires MATLAB' in note for note in result.notes)
    assert not result.proposal.applicable


@pytest.mark.parametrize('compute', ['gpu', 'multinode'])
def test_capability_blockers_reuse_shared_preflight_without_repairs(compute):
    from cryostack_src.cloud.preflight import cloud_run_preflight
    from cryostack_src.cloud.drivers.aws.batch_config import EC2ComputeConfig
    data = configuration(); data['current'].update(model='issm', example='shelf', mode='cloud')
    ec2 = EC2ComputeConfig(accelerator='gpu') if compute == 'gpu' else EC2ComputeConfig(topology='multi-node')
    findings = cloud_run_preflight(model='issm', matlab_license_configured=False,
                                  compute_mode='ec2', ec2_config=ec2)
    assert any('MATLAB' in issue for issue in findings)
    assert any(('GPU' in issue if compute == 'gpu' else 'multi-node' in issue.lower()) for issue in findings)
    panel, writes, _ = panel_fixture(data, findings)
    p = panel.ask('Make this configuration runnable')
    assert not p.applicable and 'No deterministic repair' in contents(panel)
    panel.apply(); assert not writes


def test_scientific_validation_blocker_prevents_partial_repair():
    data = configuration()
    panel, writes, _ = panel_fixture(data, ['Ice temperature is outside the supported range.'])
    proposal = panel.ask('Fix my configuration')
    assert not proposal.applicable
    assert 'Ice temperature' in contents(panel)
    assert 'Suggested' not in contents(panel)
    panel.apply(); assert not writes


def test_unknown_profile_has_no_invented_duration():
    data = configuration(); data['current']['profile'] = 'unregistered-resource'
    panel, writes, _ = panel_fixture(data)
    assert not panel.ask('Fix my configuration').applicable
    panel.apply(); assert not writes and data['current']['wall_time'] == ''


def test_repair_then_diagnosis_clears_previous_apply():
    data = configuration(); panel, writes, _ = panel_fixture(data)
    assert panel.ask('Fix my configuration').applicable
    panel.ask("Why can't I run this?")
    panel.apply()
    assert not writes and button(panel, 'Apply to configuration').disabled


def test_mutating_repair_cannot_add_controls():
    data = configuration(); panel, writes, _ = panel_fixture(data)
    proposal = panel.ask('Fix my configuration')
    proposal.values['cpus'] = 64
    panel.apply()
    assert not writes and data['current']['cpus'] == 4
