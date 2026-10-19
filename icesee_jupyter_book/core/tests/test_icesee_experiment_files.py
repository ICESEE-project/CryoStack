"""Editor backend: experiment file roles, drafts, validation, containment."""
from __future__ import annotations

import pytest
import yaml

from icesee_jupyter_book.core.experiment_files import (
    MAX_EDIT_BYTES, ExperimentFileError, ExperimentFiles, validate, validate_params,
)

TEMPLATE = {
    "physical-parameters": {"sigma_96": 10.0, "beta_96": "8.0/3.0"},
    "modeling-parameters": {"dt": 0.01, "num_years": 10, "example_name": "lorenz96"},
    "enkf-parameters": {"Nens": 30, "filter_type": "EnKF", "freq_obs": 0.2, "obs_start_time": 0.1,
                        "obs_max_time": 2, "vec_inputs": ["x", "y", "z"], "observed_vars": ["x", "y", "z"],
                        "num_state_vars": 3, "num_param_vars": 0, "joint_estimation": False,
                        "parallel_flag": "serial"},
}


@pytest.fixture
def example(tmp_path):
    ex = tmp_path / "examples" / "lorenz96"
    (ex / "_modelrun_datasets").mkdir(parents=True)
    (ex / "params.yaml").write_text(yaml.safe_dump(TEMPLATE, sort_keys=False))
    (ex / "run_da_lorenz96.py").write_text("print('model')\n")
    (ex / "obs_sites.csv").write_text("x,y\n1,2\n")
    (ex / "README.md").write_text("# readme\n")
    (ex / "read_results.ipynb").write_text('{"cells": [{"cell_type": "code", "source": ["print(1)"]}]}')
    (ex / "_modelrun_datasets" / "true-wrong-lorenz.h5").write_bytes(b"\x89HDF")
    (ex / "blob.yaml").write_bytes(b"a: 1\n\x00\x00")
    return ExperimentFiles(ex, tmp_path / "drafts", example_key="Lorenz-96 (fully runnable locally)")


def test_roles_and_listing(example):
    files = {f.path: f for f in example.files()}
    assert files["params.yaml"].role == "config" and files["params.yaml"].editable
    assert files["obs_sites.csv"].role == "input" and files["obs_sites.csv"].editable
    assert files["run_da_lorenz96.py"].role == "source" and not files["run_da_lorenz96.py"].editable
    assert "read-only" in files["run_da_lorenz96.py"].reason
    assert files["README.md"].role == "reference" and not files["README.md"].editable
    assert not any(p.startswith("_modelrun_datasets") for p in files)       # outputs are not experiment files
    assert list(files)[0] == "params.yaml"


def test_save_writes_a_draft_never_the_example(example):
    original = (example.example_dir / "obs_sites.csv").read_text()
    issues = example.save("obs_sites.csv", "x,y\n3,4\n")
    assert issues == []
    assert (example.example_dir / "obs_sites.csv").read_text() == original
    opened = example.open("obs_sites.csv")
    assert opened.origin == "draft" and opened.text == "x,y\n3,4\n"
    assert example.drafts_in_use() == {"obs_sites.csv": example.draft_path("obs_sites.csv")}
    assert example.reset("obs_sites.csv") and example.open("obs_sites.csv").origin == "example"
    assert not example.reset("obs_sites.csv")


def test_invalid_config_is_not_saved(example):
    bad = yaml.safe_dump({**TEMPLATE, "enkf-parameters": {**TEMPLATE["enkf-parameters"], "Nens": 0}})
    issues = example.save("params.yaml", bad, template=TEMPLATE)
    assert any(i.level == "error" and "Nens" in i.message for i in issues)
    assert example.config_draft() is None
    good = yaml.safe_dump({**TEMPLATE, "enkf-parameters": {**TEMPLATE["enkf-parameters"], "Nens": 12}})
    assert not [i for i in example.save("params.yaml", good, template=TEMPLATE) if i.level == "error"]
    assert example.config_draft()["enkf-parameters"]["Nens"] == 12


def test_source_and_reference_cannot_be_saved(example):
    for rel in ("run_da_lorenz96.py", "README.md"):
        with pytest.raises(ExperimentFileError):
            example.save(rel, "import os\n")


@pytest.mark.parametrize("rel", ["../outside.yaml", "/etc/passwd", "~/x.yaml", "a/../../b.yaml", ""])
def test_paths_outside_the_experiment_are_refused(example, rel):
    with pytest.raises(ExperimentFileError):
        example.open(rel)
    with pytest.raises(ExperimentFileError):
        example.save(rel, "a: 1")


def test_symlink_escape_is_not_listed_or_opened(example, tmp_path):
    secret = tmp_path / "secret.yaml"
    secret.write_text("token: abc\n")
    (example.example_dir / "link.yaml").symlink_to(secret)
    assert "link.yaml" not in {f.path for f in example.files()}
    with pytest.raises(ExperimentFileError):
        example.open("link.yaml")


def test_size_and_binary_limits(example):
    with pytest.raises(ExperimentFileError, match="larger than"):
        example.save("obs_sites.csv", "x" * (MAX_EDIT_BYTES + 1))
    opened = example.open("blob.yaml")
    assert not opened.file.editable and "Binary" in opened.file.reason


def test_notebook_shown_as_cells(example):
    assert "# %%  (cell 0)\nprint(1)" in example.open("read_results.ipynb").text


def test_yaml_syntax_error_reports_the_line():
    issues = validate("params.yaml", "a: 1\nb: [1, 2\nc: 3\n")
    assert issues[0].level == "error" and issues[0].line is not None


@pytest.mark.parametrize("change, fragment", [
    ({"enkf-parameters": {"filter_type": "KF"}}, "filter_type"),
    ({"enkf-parameters": {"Nens": "many"}}, "Nens"),
    ({"enkf-parameters": {"obs_start_time": 5}}, "obs_start_time is after"),
    ({"enkf-parameters": {"observed_vars": ["q"]}}, "observed_vars"),
    ({"enkf-parameters": {"freq_obs": 0}}, "freq_obs"),
    ({"modeling-parameters": {"num_years": -1}}, "num_years"),
    ({"enkf-parameters": {"joint_estimation": "maybe"}}, "true/false"),
    ({"physical-parameters": {"sigma_96": "ten"}}, "must be a number"),
])
def test_params_rules(change, fragment):
    data = {k: {**v, **change.get(k, {})} for k, v in TEMPLATE.items()}
    text = yaml.safe_dump(data, sort_keys=False)
    issues = validate_params(data, text=text, template=TEMPLATE)
    hit = [i for i in issues if fragment in i.message and i.level == "error"]
    assert hit, issues
    assert hit[0].line is not None


def test_missing_section_and_unknown_key():
    data = {k: dict(v) for k, v in TEMPLATE.items() if k != "physical-parameters"}
    data["enkf-parameters"]["new_knob"] = 1
    issues = validate_params(data, template=TEMPLATE)
    assert any(i.level == "error" and "physical-parameters" in i.message for i in issues)
    assert any(i.level == "info" and "new_knob" in i.message for i in issues)
    assert not [i for i in validate_params(TEMPLATE, template=TEMPLATE) if i.level != "info"]
