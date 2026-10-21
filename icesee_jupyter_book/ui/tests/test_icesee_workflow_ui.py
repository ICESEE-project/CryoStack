"""The ICESEE workflow UI, driven through its real widgets: Mode first and
its dependent state, experiment loading, the Editor bound to the run
configuration, and a Local launch from Review & launch through the run
lifecycle to Results -- on a small fake example so no real model runs."""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import ipywidgets as W
import pytest
import yaml

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

FAKE_MODEL = textwrap.dedent('''
    import os, sys, time
    import numpy as np, h5py, yaml
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    p = yaml.safe_load(open(sys.argv[sys.argv.index("-F") + 1]))
    for k in range(1, 11):
        print(f"[ICESEE] Assimilation progress (1 ranks): {10*k:3d}%|#| {k}/10 [00:00<00:00]", end="\\r", flush=True)
        time.sleep(0.05)
    d = "_modelrun_datasets"; os.makedirs(d, exist_ok=True)
    t = np.linspace(0, 1, 21); truth = np.random.default_rng(0).normal(size=(3, 21))
    with h5py.File(f"{d}/true-wrong-fake.h5", "w") as f:
        f["t"] = t; f["obs_index"] = np.array([2, 6, 10]); f["obs_max_time"] = np.array([0.5]); f["run_mode"] = np.array([0])
    with h5py.File(f"{d}/true_nurged_states.h5", "w") as f:
        f["true_state"] = truth; f["nurged_state"] = truth + 1
    with h5py.File(f"{d}/synthetic_obs.h5", "w") as f:
        f["hu_obs"] = truth[:, [2, 6, 10]]
    with h5py.File(f"{d}/icesee_ensemble_data.h5", "w") as f:
        f["ensemble"] = np.repeat(truth[:, None, :], 3, axis=1); f["ensemble_mean"] = truth
''')
PARAMS = {"physical-parameters": {"a": 1.0},
          "modeling-parameters": {"num_years": 1, "example_name": "fake"},
          "enkf-parameters": {"Nens": 3, "filter_type": "EnKF", "model_name": "fake", "seed": 1,
                              "vec_inputs": ["x", "y", "z"], "observed_vars": ["x"]}}
FAKE_KEY = "Fake DA example (tests)"


def _walk(w):
    yield w
    for c in getattr(w, "children", ()) or ():
        yield from _walk(c)


def _cls(page, name):
    return [w for w in _walk(page) if name in getattr(w, "_dom_classes", ())]


def _button(page, label):
    """A workspace button (the optional configuration agent has look-alikes)."""
    ws = _cls(page, "cryostack-output-workspace")[0]
    return next(w for w in _walk(ws) if isinstance(w, W.Button) and w.description == label)


def _mode(page):
    return next(w for w in _walk(page) if isinstance(w, W.ToggleButtons) and "Cloud" in w._options_labels)


def _html(page, needle):
    return [w for w in _walk(page) if isinstance(w, W.HTML) and needle in (w.value or "")]


def _launch_card(page):
    return _cls(page, "icw-anchor-launch")[0]


def _wait(predicate, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


@pytest.fixture
def page(monkeypatch, tmp_path):
    ex = tmp_path / "apps" / "fake_ex"
    ex.mkdir(parents=True)
    (ex / "run_da_fake.py").write_text(FAKE_MODEL)
    (ex / "params.yaml").write_text(yaml.safe_dump(PARAMS, sort_keys=False))
    (ex / "obs.csv").write_text("a,b\n1,2\n")
    (ex / "results.yaml").write_text(json.dumps({"schema": "icesee-results/1", "model_name": "fake",
                                                 "views": ["lorenz.state_estimation"]}))
    from icesee_jupyter_book.core import example_registry

    fake = dict(enabled=True, base=ex, run_script="run_da_fake.py", params="params.yaml", report_nb=None,
                assets=[], model_name="fake", figures_dir="figures", remote_rel="x", remote_sbatch=None)
    registry = example_registry.ExampleRegistry({FAKE_KEY: fake, **example_registry.EXAMPLES})
    monkeypatch.setattr(example_registry, "EXAMPLES", registry)
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(gw, "EXAMPLES", registry)
    monkeypatch.setattr(gw, "enabled_names", lambda: list(registry))
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", "workflow-ui-user")
    monkeypatch.setenv("USER", "workflow-ui-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path / "ws"))
    import matplotlib

    matplotlib.use("Agg")
    return gw.build_icesee_ui()


# ── mode first, and what depends on it ────────────────────────────────────
def test_mode_card_is_the_first_section(page):
    left = _cls(page, "icw-col")[0]
    first = next(c for c in left.children if "icw-card" in c._dom_classes)
    assert "icw-anchor-mode" in first._dom_classes


def test_mode_switch_updates_environment_launch_action_and_validation(page):
    stack = next(w for w in _walk(page) if isinstance(w, W.Stack) and len(w.children) == 3)
    hero = next(w for w in _walk(_launch_card(page)) if isinstance(w, W.Button) and "icw-btn-hero" in w._dom_classes)
    assert stack.selected_index == 0 and hero.description == "Launch run" and not hero.disabled
    _mode(page).value = "cluster"
    assert stack.selected_index == 1 and hero.description == "Submit to cluster"
    issues = " ".join(h.value for h in _html(_launch_card(page), "icw-issues"))
    assert "HPC username" in issues and hero.disabled          # nothing to submit with yet
    _mode(page).value = "cloud"
    assert stack.selected_index == 2 and hero.description == "Review cloud launch"
    _mode(page).value = "local"
    assert stack.selected_index == 0 and hero.description == "Launch run" and not hero.disabled
    assert not _html(_launch_card(page), "HPC username")      # no stale Remote errors


def test_programmatic_mode_change_keeps_the_selector_in_sync(page):
    stack = next(w for w in _walk(page) if isinstance(w, W.Stack) and len(w.children) == 3)
    stack.selected_index = 2          # e.g. the configuration agent
    assert _mode(page).value == "cloud"


def test_unrunnable_local_example_is_flagged_and_blocks_launch(page, monkeypatch):
    from icesee_jupyter_book.core import local_jobs

    monkeypatch.setenv(local_jobs.CONTAINER_ENV, "0")
    local_jobs._docker_cache.clear()
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = "Icepack (under development)"
    card = _cls(page, "icw-anchor-experiment")[0]
    assert any("Not runnable on this server" in h.value for h in _walk(card) if isinstance(h, W.HTML))
    hero = next(w for w in _walk(_launch_card(page)) if isinstance(w, W.Button) and "icw-btn-hero" in w._dom_classes)
    assert hero.disabled
    local_jobs._docker_cache.clear()


# ── experiment loading and the editor ─────────────────────────────────────
def test_selecting_an_example_loads_its_configuration_into_the_editor(page):
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    tabs = _cls(page, "icw-tabs")[0].children[0]
    tabs.value = "Editor"
    editor = next(w for w in _walk(_cls(page, "icw-editor")[0]) if isinstance(w, W.Textarea))
    cfg = yaml.safe_load(editor.value)
    assert cfg["enkf-parameters"]["model_name"] == "fake"
    files = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and "params.yaml" in w._options_values)
    labels = list(files._options_labels)
    assert any("run_da_fake.py" in label and "read-only" in label for label in labels)
    assert any("obs.csv" in label and "input" in label for label in labels)


def test_editor_rejects_invalid_and_applies_valid_configuration(page):
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    _cls(page, "icw-tabs")[0].children[0].value = "Editor"
    editor = next(w for w in _walk(_cls(page, "icw-editor")[0]) if isinstance(w, W.Textarea))
    apply_btn = _button(page, "Apply to configuration")
    original = editor.value
    editor.value = original.replace("Nens: 3", "Nens: 0")
    apply_btn.click()
    issues = _cls(page, "icw-ed-issues")[0].value
    assert "Nens" in issues and "line" in issues
    ens = next(w for w in _walk(page) if isinstance(w, W.IntSlider))
    assert ens.value == 3                                       # the form did not take the bad value
    editor.value = original.replace("Nens: 3", "Nens: 7").replace("filter_type: EnKF", "filter_type: DEnKF")
    apply_btn.click()
    assert "Applied" in _cls(page, "icw-ed-issues")[0].value
    assert ens.value == 7
    filt = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and "DEnKF" in w._options_values)
    assert filt.value == "DEnKF"
    summary = _html(_launch_card(page), "icw-kv")[0].value
    assert "DEnKF" in summary


def test_saved_input_draft_is_reported_in_review(page):
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    _cls(page, "icw-tabs")[0].children[0].value = "Editor"
    files = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and "obs.csv" in w._options_values)
    files.value = "obs.csv"
    editor = next(w for w in _walk(_cls(page, "icw-editor")[0]) if isinstance(w, W.Textarea))
    editor.value = "a,b\n9,9\n"
    save = _button(page, "Save draft")
    save.click()
    assert "Draft saved" in _cls(page, "icw-ed-issues")[0].value
    summary = _html(_launch_card(page), "icw-kv")[0].value
    assert "Edited inputs" in summary and "obs.csv" in summary
    _mode(page).value = "cluster"
    warnings = " ".join(h.value for h in _html(_launch_card(page), "icw-issues"))
    assert "Local runs only" in warnings


# ── launch, lifecycle, results ────────────────────────────────────────────
def test_launch_runs_through_the_lifecycle_and_results_become_ready(page):
    example = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    example.value = FAKE_KEY
    hero = next(w for w in _walk(_launch_card(page)) if isinstance(w, W.Button) and "icw-btn-hero" in w._dom_classes)
    hero.click()
    hero.click()                                               # a double click starts one run
    runs = _cls(page, "icw-runlist")[0]
    assert _wait(lambda: any("Completed" in label for label, _v in runs.options), 60), runs.options
    assert len([v for _l, v in runs.options if v]) == 1
    from icesee_jupyter_book.core import run_records
    from cryostack_src.workspace import user_run_root

    run = run_records.discover_runs(user_run_root(app="icesee"))[0]
    assert [e["state"] for e in run.metadata["lifecycle"]] == ["preparing", "running", "completed"]
    assert (Path(run.workspace_directory) / "provenance.json").is_file()
    _cls(page, "icw-tabs")[0].children[0].value = "Results"
    assert _wait(lambda: any("State estimation" in (h.value or "") and "<img" in (h.value or "")
                             for h in _walk(page) if isinstance(h, W.HTML)), 60)
    assert any("Results ready" in (h.value or "") for h in _walk(page) if isinstance(h, W.HTML))


@pytest.mark.parametrize("example", ["Lorenz-96 (fully runnable locally)", "Icepack (under development)",
                                     "ISSM (fully runable in Remote)", "Flowline (under development)"])
def test_each_example_configuration_survives_the_form_unchanged(page, example):
    """What is launched is the example's params.yaml: every key, value and
    type survives the form (null stays null, numbers stay numbers)."""
    from icesee_jupyter_book.core.config_io import load_yaml
    from icesee_jupyter_book.core.example_discovery import find_params_template
    from icesee_jupyter_book.core.example_registry import EXAMPLES

    dropdown = next(w for w in _walk(page) if isinstance(w, W.Dropdown) and FAKE_KEY in w.options)
    dropdown.value = example
    template = load_yaml(find_params_template(EXAMPLES[example]))
    _cls(page, "icw-tabs")[0].children[0].value = "Editor"
    editor = next(w for w in _walk(_cls(page, "icw-editor")[0]) if isinstance(w, W.Textarea))
    config = yaml.safe_load(editor.value)
    assert config == template
    for section, values in template.items():
        if isinstance(values, dict):
            for key, value in values.items():
                assert type(config[section][key]) is type(value), (section, key)
