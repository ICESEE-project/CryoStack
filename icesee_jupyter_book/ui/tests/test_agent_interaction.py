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


def test_edit_clears_proposal_without_exposing_full_configuration():
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
    assert not any(isinstance(w, W.Accordion) for w in walk(panel.container))
    assert 'Full configuration' not in contents(panel)
    c['current']['cpus']=16
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


def test_change_preview_current_proposed_sources_and_no_scheduler_noise():
    from icesee_jupyter_book.ui.configuration_agent import _change_preview
    c = catalog()
    c['current'].update(cpus=8, tasks_per_node=8, memory='64G', account='allocation')
    proposal = infer_request('Use 4 CPUs.', c)
    rendered, changes = _change_preview(c, proposal)
    assert changes == {'cpus': 4, 'tasks_per_node': 4}
    assert all(label in rendered for label in ('Setting', 'Current', 'Proposed', 'Source', 'Retained', 'From request'))
    assert '>8<' in rendered and '>4<' in rendered
    assert '2 settings to change' in rendered
    assert '64G' not in rendered and 'allocation' not in rendered
    assert rendered.index('CPUs') < rendered.index('Retained:')
    assert rendered.count('<tr>') == 3


def test_noop_apply_avoids_writes_and_reports_zero():
    c = catalog()
    c['current'].update(cpus=4, tasks_per_node=4)
    checks = []
    panel = build_configuration_agent(catalog=lambda: c,
        apply_values=lambda _: pytest.fail('No-op must not rewrite manual controls'),
        snapshot=lambda: c['current'], validate=lambda: checks.append(True) or [])
    panel.ask('Use 4 CPUs.')
    assert 'No changes needed' in contents(panel)
    assert 'Retained:' in contents(panel)
    assert '<table' not in contents(panel)
    panel.apply()
    assert '0 settings changed' in contents(panel)
    assert 'existing controls remain authoritative' in contents(panel)
    assert 'Configuration changes' not in contents(panel)
    assert button(panel, 'Apply to configuration').layout.display == 'none'
    assert checks == [True]


def test_change_count_manual_edit_and_stale_refusal():
    c = catalog()
    c['current'].update(cpus=8, tasks_per_node=8)
    writes = []
    def apply(values):
        writes.append(values)
        c['current'].update(values)
    panel = build_configuration_agent(catalog=lambda: c, apply_values=apply,
        snapshot=lambda: c['current'], validate=lambda: [])
    panel.ask('Use 4 CPUs.')
    panel.apply()
    assert '2 settings changed' in contents(panel)
    c['current'].update(cpus=12, tasks_per_node=12)
    panel.ask('Use 6 CPUs.')
    assert '>12<' in contents(panel)
    c['current']['cpus'] = 16
    panel.apply()
    assert len(writes) == 1 and c['current']['cpus'] == 16
    assert 'Settings changed' in contents(panel)
    panel.ask('Icepack tutorial on Remote')
    panel.apply()
    assert c['current']['cpus'] == 16


def test_parameter_preview_compares_actual_override_and_escapes_values():
    from icesee_jupyter_book.ui.configuration_agent import _change_preview
    from cryostack_src.agents.intent import Proposal
    c = catalog()
    c['current']['overrides'] = {'ice_temperature': 250.0}
    p = Proposal(values={'parameters': {'ice_temperature': 255.0}, 'account': '<unsafe>'})
    rendered, changes = _change_preview(c, p)
    assert '>250.0<' in rendered and '>255.0<' in rendered
    assert changes['parameter:ice_temperature'] == 255.0
    assert '&lt;unsafe&gt;' in rendered and '<unsafe>' not in rendered
    p.values['parameters']['ice_temperature'] = 250.0
    rendered, changes = _change_preview(c, p)
    assert 'parameter:ice_temperature' not in changes and '250.0' not in rendered


def test_compact_preview_and_applied_summary_hide_internal_snapshot():
    from icesee_jupyter_book.ui.tests.test_agent_diagnosis import configuration
    c = configuration()
    c['current'].update(model='issm', example='shelf', wall_time='01:00:00')
    private = dict(execution_directory='/internal/work', run_target='runme.m')
    panel = build_configuration_agent(catalog=lambda: c,
        apply_values=lambda values: c['current'].update(values),
        snapshot=lambda: dict(c['current'], **private), validate=lambda: [])
    panel.ask('Change the CPUs to 8')
    view = contents(panel)
    assert view.count('<tr>') == 2  # header plus the one actual change
    assert 'Retained: ISSM · SquareIceShelf · Remote · PACE' in view
    assert all(value not in view for value in private.values())
    assert 'Current configuration' not in view and '<pre' not in view
    panel.apply()
    view = contents(panel)
    assert '✓ Configuration updated' in view and '1 setting changed' in view
    assert 'ISSM · SquareIceShelf · Remote · PACE · 8 CPUs' in view
    assert '<table' not in view and all(value not in view for value in private.values())
    # Hidden snapshots still guard stale proposals despite having no UI viewer.
    panel.ask('Change the CPUs to 12')
    private['run_target'] = 'different.m'
    panel.apply()
    assert c['current']['cpus'] == 8 and 'Settings changed' in contents(panel)


def test_icesee_summary_labels_filter_and_ensemble():
    from icesee_jupyter_book.ui.configuration_agent import _change_preview
    c = catalog('icesee')
    c['filters'] = ['EnKF', 'DEnKF']
    c['current'].update(mode='local', filter='DEnKF', ensemble_size=20)
    p = infer_request('Change only the filter to EnKF', c)
    view, changes = _change_preview(c, p)
    assert changes == {'filter': 'EnKF'} and view.count('<tr>') == 2
    assert '20 ensemble members' in view and 'Retained:' in view
