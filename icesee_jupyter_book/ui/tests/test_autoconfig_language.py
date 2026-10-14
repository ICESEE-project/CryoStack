"""Compositional deterministic configuration language, with no execution authority."""
import copy

import pytest

from cryostack_src.agents.intent import infer_request
from cryostack_src.agents.diagnosis import diagnose_request
from cryostack_src.agents.tests.test_configuration_intent import catalog
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent
from icesee_jupyter_book.ui.tests.test_agent_interaction import contents, button, gateway


def data(app='icesheets'):
    c=catalog(app)
    c['current'].update(model='icepack',cpus=4,nodes=1,tasks_per_node=4,
        wall_time='01:00:00',memory='4G',account='science',profile='pace',
        backend='spack',user='scientist',directory='/scratch/science',
        ensemble_size=20,filter='DEnKF',overrides={'ice_temperature':250})
    c['defaults']={'wall_time':'02:00:00'}
    c['filters']=['EnKF','DEnKF','ETKF']
    c['control_bounds']={'cpus':(1,64),'ensemble_size':(1,1000)}
    c['parameters']['icepack'].append(dict(key='num_timesteps',label='Number of timesteps',kind='int',min=1,max=100000))
    if app=='icesee':
        c['parameters']={}
        c['examples'].append(dict(id='lorenz',label='Lorenz-96',model='lorenz96',aliases=['Lorenz96','Lorenz-96']))
        c['current'].update(example='lorenz',model='lorenz96')
    return c


def panel_for(c):
    writes=[]
    def apply(v):
        writes.append(copy.deepcopy(v));c['current'].update(v)
    panel=build_configuration_agent(catalog=lambda:copy.deepcopy(c),snapshot=lambda:copy.deepcopy(c['current']),
                                    apply_values=apply,validate=lambda:[],diagnosis_validate=lambda:[])
    return panel,writes


@pytest.mark.parametrize('prompt,expected',[
    ('Run SquareIceShelf with ISSM remotely with 8 CPUs and 32 GB of memory',{'model':'issm','example':'shelf','cpus':8,'memory':'32G','mode':'remote'}),
    ('Run SquareIceShelf on PACE with 8 cores and 32000 MB memory for 90 minutes on one node',{'cpus':8,'memory':'32000M','wall_time':'01:30:00','nodes':1}),
    ('Run SquareIceShelf with 8 CPUs on two nodes for 2 hours',{'cpus':8,'nodes':2,'tasks_per_node':4,'wall_time':'02:00:00'}),
    ('Use Icepack with the canonical example 01-synthetic-ice-sheet and 4 CPUs',{'model':'icepack','example':'sheet','cpus':4}),
    ('Keep my current model but increase CPUs from 4 to 8',{'cpus':8,'model':'icepack','example':'sheet'}),
    ('Double the number of CPUs',{'cpus':8}),
    ('Increase CPUs to 8',{'cpus':8}),
    ('Use the same configuration but run remotely',{'mode':'remote','model':'icepack'}),
    ('Keep everything else and change the filter to EnKF',{'filter':'EnKF'}),
    ('Reset walltime to the default',{'wall_time':'02:00:00'}),
    ('Run SquareIceShelf with walltime 1.5 hours',{'wall_time':'01:30:00'}),
])
def test_composable_slots(prompt,expected):
    c=data(); before=copy.deepcopy(c)
    p=infer_request(prompt,c)
    assert p.applicable,(p.errors,p.unresolved)
    assert all(p.values[k]==v for k,v in expected.items())
    assert c==before


def test_icesee_multislot_and_refinement():
    c=data('icesee')
    p=infer_request('Configure ICESEE with Lorenz-96 on Remote, ensemble size 40, EnKF, and 8 CPUs',c)
    assert p.applicable,(p.errors,p.unresolved)
    assert {k:p.values[k] for k in ('model','ensemble_size','filter','cpus')}==dict(model='lorenz96',ensemble_size=40,filter='EnKF',cpus=8)
    p=infer_request('Change the ensemble size to 60 but keep the rest of my configuration',c)
    assert p.applicable and p.values['ensemble_size']==60
    assert 'filter' not in p.values and 'cpus' not in p.values


@pytest.mark.parametrize('prompt',[
    'Use 4 CPUs and use 16 CPUs', 'Run ISSM with Icepack',
    'Run SquareIceShelf locally and remotely', 'Use EnKF or ETKF',
    'Use EnKF and ETKF', 'Use 4G memory and 8G memory',
    'Use walltime 01:00:00 and walltime 02:00:00',
    'Use 2 hours and 90 minutes',
    'Set ice temperature to 250 and set ice_temperature to 260',
    'Increase CPUs from 2 to 8',
    'Set ice temperature to 300', 'Set ice temperature to 199',
    'Set ice temperature to true', 'Set Number of timesteps to 2.5',
    'Set unknown_parameter to 4', 'Run SquareIceShelf with ice temperature 255',
    'Run SquareIceShelf with 0 GB memory', 'Run SquareIceShelf with -4 GB memory',
    'Run SquareIceShelf with -2 hours', 'Run SquareIceShelf with 0 minutes',
    'Run SquareIceShelf with 2.5 nodes', 'Run SquareIceShelf with 4 GPUs',
    'Run SquareIceShelf on Cloud with two nodes',
    'Reset CPUs to the default', 'Run shelf',
    'Keep my current model and run SquareIceShelf with ISSM',
    'Keep my scientific parameters and set ice temperature to 260',
    'Run SquareIceShelf without thermal physics',
    'Run SquareIceShelf; submit it',
])
def test_unsupported_conflicting_or_ambiguous_requests_never_apply(prompt):
    c=data(); panel,writes=panel_for(c);p=panel.ask(prompt)
    assert p is not None and not p.applicable,p
    panel.apply();assert not writes


@pytest.mark.parametrize('prompt',[
    'Set ice temperature to 255', 'Increase ice temperature to 255',
    'Change ice temperature from 250 to 255',
    'Set ice temperature to 255 and set Number of timesteps to 60',
])
def test_registered_scientific_assignments(prompt):
    p=infer_request(prompt,data())
    assert p.applicable,(p.errors,p.unresolved)
    assert p.values['parameters']['ice_temperature']==255


def test_parameter_from_requires_known_current_value_and_alias_ambiguity():
    c=data();del c['current']['overrides']['ice_temperature']
    assert not infer_request('Change ice temperature from 250 to 255',c).applicable
    for spec in c['parameters']['icepack']: spec['aliases']=['setting']
    p=infer_request('Set setting to 255',c)
    assert not p.applicable and any('Ambiguous parameter' in m for m in p.unresolved)


def test_no_guessing_relative_invalid_or_absent_default():
    c=data();c['current']['cpus']=None
    assert not infer_request('Double CPUs',c).applicable
    c['current']['cpus']=40
    assert not infer_request('Double CPUs',c).applicable
    p=infer_request('Reset walltime to default',c)
    assert p.applicable and 'wall_time' in p.suggested


def test_relative_refinement_manual_edit_stale_and_provenance():
    c=data();panel,writes=panel_for(c)
    panel.ask('Double CPUs'); panel.apply();assert c['current']['cpus']==8
    c['current']['cpus']=6
    p=panel.ask('Double CPUs'); assert p.values['cpus']==12
    panel.ask('Why did Auto-config suggest 12 CPUs?')
    assert 'From request' in contents(panel) and 'twice the current value (6)' in contents(panel)
    assert len(writes)==1
    panel.ask('Double CPUs');c['current']['cpus']=7
    panel.apply();assert len(writes)==1


def test_mode_replacement_keeps_science_and_checks_original_mode():
    c=data('icesee');c['current']['mode']='local'
    prompt='Switch from local to remote execution without changing my scientific parameters'
    p=infer_request(prompt,c)
    assert p.applicable,(p.errors,p.unresolved)
    assert p.values['mode']=='remote' and 'parameters' not in p.values
    c['current']['mode']='cloud'
    assert not infer_request(prompt,c).applicable


@pytest.mark.parametrize('prompt',[
    "Why can't this configuration run?", 'What is wrong with my current configuration?',
    'Why is GPU unavailable?', "Why can't I use this solver?",
    'Is this configuration compatible with remote execution?',
])
def test_readonly_diagnosis_and_capability_questions(prompt):
    c=data();panel,writes=panel_for(c);before=copy.deepcopy(c)
    panel.ask(prompt);panel.apply()
    assert not writes and c==before and 'Unable to' not in contents(panel)
    assert button(panel,'Apply to configuration').disabled


def test_remote_repair_and_resource_repair_are_conservative():
    c=data('icesee');c['current'].update(mode='local',wall_time='')
    panel,writes=panel_for(c)
    p=panel.ask('Make this configuration valid for remote execution')
    assert p.applicable and p.values['mode']=='remote' and p.values['wall_time']
    assert 'wall_time' in p.suggested and 'mode' not in p.suggested
    assert 'parameters' not in p.values
    panel.apply();assert writes and c['current']['mode']=='remote'
    c['current']['wall_time']=''
    p=panel.ask('Fix the resource settings but keep my scientific parameters')
    assert p.applicable and set(p.values)=={'model','example','wall_time'}
    c['current']['tasks_per_node']=100
    assert not panel.ask('Fix this configuration').applicable


def test_structured_findings_use_shared_validation():
    c=data();c['current'].update(tasks_per_node=8,wall_time='')
    d=diagnose_request('diagnose',c,lambda:[])
    assert any(f['category']=='Resource conflict' for f in d.findings)
    assert any(f['category']=='Missing requirement' for f in d.findings)


def test_explanation_sources_and_mismatched_question():
    c=data();c['examples'].append(dict(id='owned',label='my-shelf',model='issm',aliases=['my-shelf'],origin='workspace',workspace_name='my-shelf'))
    panel,writes=panel_for(c)
    panel.ask('Run my example my-shelf')
    panel.ask('Where did this model selection come from?')
    assert 'User workspace' in contents(panel) and 'my-shelf' in contents(panel)
    panel.ask('Run SquareIceShelf with 8 CPUs')
    panel.ask('Why did Auto-config suggest 16 CPUs?')
    assert 'does not specify' in contents(panel)
    panel.ask('Reset walltime to default');panel.ask('Why is this Suggested?')
    assert 'Suggested' in contents(panel)
    panel.ask('Use 8 CPUs');panel.ask('Why was this setting retained?')
    assert 'Retained' in contents(panel)
    panel.ask('Run SquareIceShelf with GPU');panel.ask('Why is this option unsupported?')
    assert 'GPU' in contents(panel) and not writes


@pytest.mark.parametrize('app',['icesheets','icesee'])
def test_real_rendered_multislot_callbacks(gateway,app):
    host=gateway(app);fields=host['fields'];panel=host['panel']
    for key,value in dict(cpus=4,nodes=1,tasks_per_node=4,wall_time='01:00:00',memory='4G',account='science',user='scientist',directory='/scratch/science').items():
        fields[key].value=value
    if app=='icesheets':
        host['mode'].value='remote'
        text='Run SquareIceShelf with ISSM remotely with 8 CPUs and 32 GB of memory for 90 minutes'
    else:
        host['mode_tabs'].selected_index=1
        text='Configure ICESEE with Lorenz96 remotely, ensemble size 40, EnKF, and 8 CPUs for 90 minutes'
    p=panel.ask(text);assert p.applicable,(p.errors,p.unresolved)
    assert all(label in contents(panel) for label in ('Current','Proposed','Source'))
    panel.apply()
    assert fields['cpus'].value==8 and fields['wall_time'].value=='01:30:00'
    if app=='icesheets': assert fields['memory'].value=='32G'
    else: assert host['ensemble'].value==40 and host['filter_widget'].value=='EnKF'
    before={k:w.value for k,w in fields.items()}
    panel.ask('Is this configuration compatible with remote execution?')
    assert before=={k:w.value for k,w in fields.items()} and not host['checks']


@pytest.mark.parametrize('prompt',[
    'Increase CPUs from 4 to 2',
    'Increase CPUs to 2',
    'Decrease CPUs to 8',
    'Decrease CPUs from 4 to 8',
    'Increase ice temperature from 250 to 240',
    'Decrease ice temperature to 260',
])
def test_directional_conflicts_are_not_silently_assigned(prompt):
    assert not infer_request(prompt,data()).applicable


def test_fractional_current_cpu_is_not_valid_relative_context():
    c=data();c['current']['cpus']=2.5
    assert not infer_request('Double CPUs',c).applicable


def test_same_value_duplicate_is_accepted_and_unexposed_controls_explained():
    assert infer_request('Use 8 CPUs and 8 cores',data()).applicable
    p=infer_request('Configure a solver',data())
    assert not p.applicable and any('solver-selection' in m for m in p.unresolved)
    p=infer_request('Set observations to 4',data('icesee'))
    assert not p.applicable and any('Observation configuration' in m for m in p.unresolved)


def test_explicit_model_conflict_cannot_override_workspace_identity():
    c=data();c['examples'].append(dict(id='owned',label='my-shelf',model='issm',aliases=['my-shelf'],origin='workspace',workspace_name='my-shelf'))
    p=infer_request('Use my example my-shelf with Icepack and 8 CPUs',c)
    assert not p.applicable


def test_mode_diagnosis_and_repair_do_not_call_current_cloud_validation():
    c=data('icesee');c['current']['mode']='cloud'
    def forbidden(): pytest.fail('Cloud validation called by read-only diagnosis')
    d=diagnose_request('diagnose_remote',c,forbidden)
    assert not d.issues and c['current']['mode']=='cloud'
    d=diagnose_request('repair_remote',c,forbidden)
    assert d.proposal.applicable and d.proposal.values['mode']=='remote'


def test_remote_repair_no_changes_and_stale_state():
    c=data('icesee');panel,writes=panel_for(c)
    panel.ask('Make this configuration valid for remote execution')
    assert 'No changes needed' in contents(panel)
    assert button(panel,'Apply to configuration').disabled
    c['current'].update(mode='local',wall_time='')
    panel.ask('Make this configuration valid for remote execution')
    c['current']['ensemble_size']=35
    panel.apply(); assert not writes


def test_canonical_qualifier_precedes_the_example_name():
    p=infer_request('Use Icepack with the canonical 01-synthetic-ice-sheet example and 4 CPUs',data())
    assert p.applicable and p.values['example']=='sheet'


@pytest.mark.parametrize('nodes',[0,None,-1])
def test_invalid_current_nodes_require_clarification_without_parser_failure(nodes):
    c=data();c['current']['nodes']=nodes
    p=infer_request('Use 8 CPUs',c)
    assert not p.applicable and any('node count' in message for message in p.unresolved)
