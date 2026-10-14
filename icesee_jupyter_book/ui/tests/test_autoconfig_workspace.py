"""Authenticated example context and pre-mutation proposal validation."""
import copy
import json
import os

import pytest

from cryostack_src.agents.intent import infer_request
from cryostack_src.agents.proposal_validation import proposal_findings
from cryostack_src.agents.workspace_context import workspace_examples, require_workspace_scope
from cryostack_src.agents.tests.test_configuration_intent import catalog
from cryostack_src.workspace.tests.test_user_examples import _mgr, USER_A, USER_B
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent
from icesee_jupyter_book.ui.tests.test_agent_interaction import contents, button, gateway


@pytest.fixture
def owners(tmp_path, monkeypatch):
    monkeypatch.setenv('HTTP_X_CRYOSTACK_USER_ID', USER_A.user_id)
    monkeypatch.delenv('HTTP_X_CRYOSTACK_USER_NAME', raising=False)
    a = _mgr(USER_A, tmp_path, tmp_path / 'canonical')
    b = _mgr(USER_B, tmp_path, tmp_path / 'canonical')
    one = a.create_user_example(model='issm', name='my-shelf', template={'runme.m': "md=solve(md,'Stressbalance');"})
    two = b.create_user_example(model='issm', name='private-shelf', template={'runme.m': 'PRIVATE'})
    return a, b, one, two


def context_catalog(manager):
    c = catalog()
    for item in workspace_examples(manager, 'issm'):
        c['examples'].append(dict(id=item['path'], label=item['name'], aliases=[item['name']],
                                  model=item['model'], origin='workspace', workspace_name=item['name'],
                                  modes=['remote','cloud'], parameters=[]))
    return c


def test_own_context_and_other_account_never_suggested(owners):
    a,b,one,two = owners
    c = context_catalog(a)
    p = infer_request('Run my example my-shelf with 4 CPUs', c)
    assert p.applicable and p.values['model'] == 'issm' and p.values['example'] == str(one)
    assert p.workspace_sources == {'model':'my-shelf'}
    assert 'private-shelf' not in repr(c)
    rejected = infer_request('Run private-shelf', c)
    assert not rejected.applicable and str(two) not in repr(rejected)
    assert workspace_examples(b,'issm') == []
    assert infer_request('Run SquareIceShelf', c).applicable


def test_explicit_request_and_retained_values_win(owners):
    a,_,one,_ = owners
    marker=one/'.cryostack-example.json'
    record=json.loads(marker.read_text())
    record.update(cpus=999999, parameters={'bad':float('inf')}, execution='local', gpu=True)
    marker.write_text(json.dumps(record))
    c=context_catalog(a); c['current'].update(memory='4G', cpus=2)
    p=infer_request('Run my example my-shelf with ISSM using 8 CPUs',c)
    assert p.applicable and p.values['cpus']==8 and not p.workspace_sources
    assert 'parameters' not in p.values and 'memory' not in p.values and 'mode' not in p.values
    assert not infer_request('Run my example my-shelf locally',c).applicable
    assert not infer_request('Run my example my-shelf with GPU',c).applicable
    assert not infer_request('Run my example my-shelf on Cloud with 2 nodes',c).applicable


@pytest.mark.parametrize('escape',['directory','marker','nested','hardlink','model-root','owner-root'])
def test_link_escape_is_rejected_before_read(owners,escape):
    a,b,one,two=owners
    if escape=='directory':
        (one.parent/'leak').symlink_to(two, target_is_directory=True)
    elif escape=='marker':
        (one/'.cryostack-example.json').unlink()
        (one/'.cryostack-example.json').symlink_to(two/'.cryostack-example.json')
    elif escape=='nested':
        (one/'runme.m').unlink(); (one/'runme.m').symlink_to(two/'runme.m')
    elif escape=='hardlink':
        (one/'runme.m').unlink(); os.link(two/'runme.m',one/'runme.m')
    elif escape=='model-root':
        root=one.parent; root.rename(root.with_name('moved')); root.symlink_to(two.parent,target_is_directory=True)
    else:
        root=a._owner_root; root.rename(root.with_name('moved')); root.symlink_to(b._owner_root,target_is_directory=True)
    found=workspace_examples(a,'issm')
    assert all(item['name']=='my-shelf' for item in found)
    if escape!='directory': assert not found


def test_forged_owner_model_and_account_switch(owners,monkeypatch):
    a,_,one,_=owners
    marker=one/'.cryostack-example.json'; original=json.loads(marker.read_text())
    for key,value in [('owner',USER_B.safe_id),('model','unsupported'),('name','../private')]:
        marker.write_text(json.dumps(dict(original,**{key:value})))
        assert workspace_examples(a,'issm')==[]
    monkeypatch.setenv('HTTP_X_CRYOSTACK_USER_ID',USER_B.user_id)
    with pytest.raises(ValueError): require_workspace_scope(a)
    monkeypatch.delenv('HTTP_X_CRYOSTACK_USER_ID')
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_USER',USER_A.user_id)
    assert workspace_examples(a,'issm')==[]


def test_ambiguous_workspace_name_is_not_selected(owners):
    a,_,_,_=owners
    c=context_catalog(a)
    c['examples'].append(dict(c['examples'][-1],id='another'))
    p=infer_request('Run my example my-shelf',c)
    assert not p.applicable and p.unresolved
    # A model-only request must not recommend a private example implicitly.
    c['current']['example']='missing'
    p=infer_request('Run ISSM',c)
    assert p.values['example']=='shelf'


def test_preview_provenance_stale_context_and_manual_authority(owners):
    a,_,one,_=owners
    c=context_catalog(a); mutations=[]
    def apply(values):
        mutations.append(copy.deepcopy(values)); c['current'].update(values)
    panel=build_configuration_agent(catalog=lambda:c,apply_values=apply,snapshot=lambda:c['current'],validate=lambda:[])
    panel.ask('Run my example my-shelf')
    rendered=contents(panel)
    assert 'User workspace' in rendered and 'your workspace' in rendered and str(one) not in rendered
    panel.apply(); assert len(mutations)==1 and 'Configuration updated' in contents(panel)
    c['current']['cpus']=7
    panel.ask('Run my example my-shelf')
    c['current']['cpus']=8
    panel.apply(); assert len(mutations)==1 and c['current']['cpus']==8
    panel.ask('Run my example my-shelf')
    c['examples'].pop()
    panel.apply(); assert len(mutations)==1


@pytest.mark.parametrize('prompt', ['Run SquareIceShelf with 999 CPUs','Run SquareIceShelf with 0 CPUs'])
def test_preapply_bounds_no_mutation(prompt):
    c=catalog(); c['control_bounds']={'cpus':(1,64)}; mutations=[]
    panel=build_configuration_agent(catalog=lambda:c,apply_values=mutations.append,snapshot=lambda:c['current'],validate=lambda:pytest.fail('post validation'))
    assert not panel.ask(prompt).applicable
    panel.apply(); assert not mutations


@pytest.mark.parametrize('value',[float('nan'),float('inf'),300,True])
def test_invalid_parameter_cannot_reach_controls(value):
    c=catalog(); p=infer_request('01-synthetic-ice-sheet ice temperature 255',c)
    p.values['parameters']['ice_temperature']=value
    assert proposal_findings(p,c)


def test_shared_solver_validation_precedes_apply():
    c=catalog(); c['validate_scientific']=True
    c['current']['overrides']={'unsupported_field':42}
    p=infer_request('Run SquareIceShelf',c)
    assert not p.applicable


def test_real_cryolauncher_workspace_callback(gateway,monkeypatch):
    monkeypatch.setenv('HTTP_X_CRYOSTACK_USER_ID','workspace-widget-user')
    c=gateway('icesheets'); manager=c['manager']; panel=c['panel']
    path=manager.create_user_example(model='issm',name='owned-shelf',template={'runme.m':"md=solve(md,'Stressbalance');"})
    # The workspace UI normally refreshes this existing picker after creation.
    c['example'].options=(*c['example'].options,('owned-shelf',str(path)))
    p=panel.ask('Run my example owned-shelf')
    assert p.applicable and p.workspace_sources=={'model':'owned-shelf'}
    assert 'User workspace' in contents(panel)
    panel.apply()
    assert c['example'].value==str(path)
    assert not c['checks']  # No Cloud/submit path invoked.


def test_real_icesee_bounds_and_unchanged_authority(gateway):
    c=gateway('icesee'); panel=c['panel']; ensemble=c['ensemble']
    before=ensemble.value
    p=panel.ask(f'Use {ensemble.max+1} ensemble members')
    assert not p.applicable
    panel.apply(); assert ensemble.value==before and not c['checks']


def test_metadata_changes_and_provenance_tampering_refuse_apply(owners):
    a,_,_,_=owners
    c=context_catalog(a); mutations=[]
    panel=build_configuration_agent(catalog=lambda:c,apply_values=mutations.append,snapshot=lambda:c['current'],validate=lambda:[])
    proposal=panel.ask('Run my example my-shelf')
    proposal.workspace_sources['model']='forged source'
    panel.apply(); assert not mutations
    panel.ask('Run my example my-shelf')
    c['examples'][-1]['modes']=['cloud']
    panel.apply(); assert not mutations
    assert not panel.ask('Run my example my-shelf on Remote').applicable


def test_shared_resource_conflict_prevents_any_mutation():
    c=catalog(); c['validate_resources']=True
    c['current'].update(profile='pace',nodes=2,cpus=8,tasks_per_node=4,
                        wall_time='01:00:00',memory='4G',account='example')
    mutations=[]
    panel=build_configuration_agent(catalog=lambda:c,apply_values=mutations.append,snapshot=lambda:c['current'],validate=lambda:[])
    assert not panel.ask('Run SquareIceShelf with 8 CPUs and 9 tasks per node').applicable
    panel.apply(); assert not mutations
