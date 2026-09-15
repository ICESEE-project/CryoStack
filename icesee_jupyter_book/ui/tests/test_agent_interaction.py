"""Agent review/apply interaction regressions against the real gateway widgets."""
import ipywidgets as W
import pytest
from cryostack_src.agents.intent import infer_request
from cryostack_src.agents.tests.test_configuration_intent import catalog
from icesee_jupyter_book.ui.configuration_agent import build_configuration_agent


def walk(widget):
    yield widget
    for child in getattr(widget, 'children', ()):
        yield from walk(child)


def contents(panel):
    return ' '.join(w.value for w in walk(panel.container) if isinstance(w,W.HTML))


def button(panel, name):
    return next(w for w in walk(panel.container) if isinstance(w,W.Button) and w.description==name)


def test_omission_retains_but_ambiguity_does_not():
    c=catalog()
    p=infer_request('Use 4 CPUs.',c)
    assert p.applicable and p.retained==['example','model']
    assert p.values['example']=='sheet'
    p=infer_request('Icepack tutorial on Remote',c)
    assert p.applicable and p.retained==['example']
    assert not infer_request('SquareIceShelf or 01-synthetic-ice-sheet',c).applicable
    c['current']['example']='missing'
    assert not infer_request('Use 4 CPUs.',c).applicable


def test_edit_clears_proposal_and_details_remain_collapsed():
    c=catalog(); applied=[]
    panel=build_configuration_agent(catalog=lambda:c, apply_values=applied.append, snapshot=lambda:c['current'],validate=lambda:[])
    text=next(w for w in walk(panel.container) if isinstance(w,W.Textarea))
    text.value='Use 4 CPUs.'
    button(panel,'Create plan').click()
    assert '<table' in contents(panel) and 'Retained' in contents(panel)
    text.value='Use 8 CPUs.'
    assert 'Proposed configuration' not in contents(panel)
    assert button(panel,'Apply to configuration').disabled
    panel.apply(); assert not applied
    button(panel,'Create plan').click()
    button(panel,'Apply to configuration').click()
    assert applied[0]['cpus']==8
    assert 'Configuration updated' in contents(panel)
    acc=next(w for w in walk(panel.container) if isinstance(w,W.Accordion))
    assert acc.selected_index is None
    c['current']['cpus']=16
    acc.selected_index=0
    assert '>16<' in contents(panel)
    panel.apply(); assert len(applied)==1


def test_unsupported_has_no_success_heading_or_apply():
    c=catalog()
    panel=build_configuration_agent(catalog=lambda:c, apply_values=lambda _:pytest.fail('applied'),snapshot=lambda:c['current'],validate=lambda:[])
    panel.ask('Run SquareIceShelf on AWS using a GPU.')
    assert 'Unsupported request' in contents(panel)
    assert 'Ready to apply' not in contents(panel)
    assert button(panel,'Apply to configuration').layout.display=='none'
    assert 'metadata' not in contents(panel)


@pytest.fixture
def gateway(monkeypatch,tmp_path):
    monkeypatch.setenv('CRYOSTACK_AGENT_PANEL','1')
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_USER','agent-interaction-review')
    monkeypatch.setenv('CRYOSTACK_WORKSPACE_ROOT',str(tmp_path))
    monkeypatch.setenv('MPLBACKEND','Agg')
    from icesee_jupyter_book.ui import configuration_agent as module
    def build(app):
        captured={}; original=getattr(module,'build_'+app+'_configuration_agent')
        def capture(**kwargs):
            captured.update(kwargs)
            # No account/environment operations in interaction tests. Production
            # callbacks are unchanged and still run the shared preflight.
            captured['checks']=[]
            kwargs['cloud_validate']=lambda: captured['checks'].append('cloud') or []
            panel=original(**kwargs); captured['panel']=panel
            return panel
        monkeypatch.setattr(module,'build_'+app+'_configuration_agent',capture)
        if app=='icesheets':
            from icesee_jupyter_book.ui.icesheets_gateway import build_icesheets_ui
            page=build_icesheets_ui()
        else:
            from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
            page=build_icesee_ui()
        assert page is not None and 'panel' in captured
        captured['page']=page
        return captured
    return build


def test_cryolauncher_manual_state_remains_authoritative(gateway):
    c=gateway('icesheets'); panel=c['panel']; fields=c['fields']
    ui=next(w for w in walk(c['page']) if isinstance(w,W.ToggleButtons) and 'agent' in [v for _,v in w.options])
    ui.value='agent'
    assert panel.ask('Run SquareIceShelf with ISSM on PACE using 4 CPUs.').applicable
    panel.apply()
    assert fields['cpus'].value==4 and c['model'].value=='issm'
    fields['cpus'].value=12; fields['tasks_per_node'].value=12
    p=panel.ask('Run SquareIceShelf with ISSM on PACE.')
    assert p.applicable and 'cpus' not in p.values
    panel.apply(); assert fields['cpus'].value==12
    panel.ask('Use 8 CPUs.')
    c['mode'].value='cloud'
    panel.apply(); assert fields['cpus'].value==12
    assert 'Settings changed' in contents(panel)
    p=panel.ask('Run SquareIceShelf with ISSM on Cloud.')
    assert p.applicable
    panel.apply(); assert c['mode'].value=='cloud' and c['checks']==['cloud']
    for value in ('basic','advanced','agent'):
        ui.value=value
    assert fields['cpus'].value==12
    c['mode'].value='remote'
    p=panel.ask('Run 01-synthetic-ice-sheet on Remote using ice temperature 255.')
    assert p.applicable
    panel.apply(); assert c['icepack_panel'].overrides()=={'ice_temperature':255.0}
    p=panel.ask('Icepack tutorial on Remote')
    assert p.applicable and 'example' in p.retained
    panel.apply(); assert c['model'].value=='icepack'
    button(panel,'Review in Advanced').click(); assert ui.value=='advanced'
    assert not panel.ask('Run SquareIceShelf on AWS using a GPU.').applicable
    assert c['model'].value=='icepack' and c['mode'].value=='remote'


def test_icesee_example_filter_ensemble_and_manual_changes(gateway):
    c=gateway('icesee'); panel=c['panel']
    assert 'Lorenz96' in next(w for w in walk(panel.container) if isinstance(w,W.Textarea)).placeholder
    p=panel.ask('Prepare Lorenz96 locally with ensemble size 20 and DEnKF.')
    assert p.applicable
    panel.apply()
    assert c['ensemble'].value==20 and c['filter_widget'].value=='DEnKF'
    c['ensemble'].value=35; c['filter_widget'].value='EnKF'
    panel.ask('Prepare Lorenz96 locally.')
    panel.apply()
    assert c['ensemble'].value==35 and c['filter_widget'].value=='EnKF'
    cfg=c['params_snapshot']()
    assert any(isinstance(s,dict) and s.get('Nens')==35 and s.get('filter_type')=='EnKF' for s in cfg.values())
    panel.ask('Prepare Lorenz96 locally with 40 ensemble members.')
    c['mode_tabs'].selected_index=1
    panel.apply(); assert c['ensemble'].value==35
    p=panel.ask('Prepare ICESEE using Icepack with ensemble data assimilation on the cloud.')
    assert p.applicable
    panel.apply()
    assert 'Icepack' in c['example'].value and c['mode_tabs'].selected_index==2
    assert c['checks']==['cloud']
    panel.ask('Prepare ICESEE using ISSM on Remote with 4 CPUs.')
    panel.apply()
    assert 'ISSM' in c['example'].value and c['mode_tabs'].selected_index==1
    assert c['fields']['cpus'].value==4 and c['fields']['parallel_processes'].value==4
