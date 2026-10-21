"""Every example ICESEE couples to an application is offered, discovered
from the ICESEE repository; the keys used before discovery still resolve."""
from __future__ import annotations

import ipywidgets as W

from icesee_jupyter_book.core import example_registry as reg


def _app(root, folder, name, *, driver=None, params=True):
    d = root / folder / "examples" / name
    d.mkdir(parents=True)
    if driver:
        (d / driver).write_text("")
    if params:
        (d / "params.yaml").write_text("enkf-parameters: {}\n")
    return d


def test_discovers_coupled_examples_only_default_first(tmp_path):
    _app(tmp_path, "issm_model", "ISMIP", driver="run_da_issm.py")
    _app(tmp_path, "issm_model", "ISMIP_Choi", driver="run_da_issm.py").joinpath("run_job_spack.sbatch").write_text("")
    _app(tmp_path, "issm_model", "notebooks_only")                 # no driver: not coupled
    _app(tmp_path, "icepack_model", "shallowIce", params=False, driver="run_da_icepack.py")
    _app(tmp_path, "icepack_model", "new_case", driver="run_da_icepack.py")
    found = reg.discover(tmp_path)
    assert list(found) == ["ISSM · ISMIP_Choi", "ISSM · ISMIP", "Icepack · new_case"]
    choi = found["ISSM · ISMIP_Choi"]
    assert choi["application"] == "ISSM" and choi["model_name"] == "issm" and choi["default"]
    assert choi["remote_sbatch"] == "run_job_spack.sbatch" and found["ISSM · ISMIP"]["remote_sbatch"] is None
    assert choi["remote_rel"] == "ICESEE/applications/issm_model/examples/ISMIP_Choi"
    assert choi["report_nb"] == "read_results.m"


def test_the_shipped_icesee_examples_are_all_offered():
    apps = reg.applications()
    assert apps == ["Lorenz-96", "ISSM", "Icepack", "Flowline"]
    for app in apps:
        examples = reg.examples_of(app)
        assert examples and reg.EXAMPLES[examples[0]]["default"]
        for key in examples:
            cfg = reg.EXAMPLES[key]
            assert (cfg["base"] / cfg["run_script"]).is_file() and (cfg["base"] / "params.yaml").is_file()
    assert len(reg.examples_of("ISSM")) >= 2 and len(reg.examples_of("Icepack")) >= 2


def test_legacy_keys_resolve():
    for old, (folder, name) in reg.LEGACY_KEYS.items():
        assert old in reg.EXAMPLES
        assert reg.EXAMPLES[old]["example"] == name
        assert reg.canonical(old) == reg.example_key(reg.APPLICATIONS[folder][0], name)
    assert reg.EXAMPLES.get("ISSM (fully runable in Remote)")["example"] == "ISMIP_Choi"


def test_picker_follows_and_drives_the_example_selector():
    from icesee_jupyter_book.ui.icesee_workflow.examples import ExamplePicker

    source = W.Dropdown(options=reg.selector_options(), value=reg.enabled_names()[0])
    picker = ExamplePicker(source)
    assert picker.application.value == "Lorenz-96"
    picker.application.value = "ISSM"                         # an application: its default example
    assert source.value == "ISSM · ISMIP_Choi"
    other = [v for _l, v in picker.example.options if v != "ISSM · ISMIP_Choi"][0]
    picker.example.value = other                              # another example of it
    assert source.value == other
    source.value = "Icepack · synthetic_ice_stream"           # set elsewhere (Auto-config)
    assert picker.application.value == "Icepack" and picker.example.value == source.value
    source.value = "Lorenz-96 (fully runnable locally)"       # an old run record's key
    assert source.value == "Lorenz-96 · lorenz96" and picker.application.value == "Lorenz-96"
    assert "coupled to ICESEE" in picker.note.value
