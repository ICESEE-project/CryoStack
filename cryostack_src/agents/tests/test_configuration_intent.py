import copy
import pytest
from cryostack_src.agents.intent import infer_request


def catalog(app="icesheets"):
    return dict(application=app, examples=[
        dict(id="shelf", label="SquareIceShelf", model="issm", aliases=["SquareIceShelf"]),
        dict(id="sheet", label="01-synthetic-ice-sheet", model="icepack", aliases=["01-synthetic-ice-sheet"]),
        dict(id="stream", label="04-synthetic-ice-stream", model="icepack", aliases=["04-synthetic-ice-stream"]),
    ], modes=["remote", "cloud"] if app == "icesheets" else ["local", "remote", "cloud"],
       profiles=["pace", "ub-ccr"], backends=["spack", "container"],
       current=dict(mode="remote", nodes=1, example="sheet"),
       parameters={"icepack": [dict(key="ice_temperature", label="Ice temperature", kind="float", min=200, max=273.15)]})


def test_realistic_request():
    p = infer_request("Run SquareIceShelf with ISSM on PACE using 4 CPUs", catalog())
    assert p.applicable
    assert p.values == dict(model="issm", example="shelf", mode="remote", profile="pace", cpus=4, tasks_per_node=4)


def test_model_from_example_metadata():
    assert infer_request("Run 01-synthetic-ice-sheet on ub-ccr", catalog()).values["model"] == "icepack"


@pytest.mark.parametrize("text", ["Run 01-synthetic-ice-sheet or 04-synthetic-ice-stream", "Run SquareIceShelf locally or on AWS", "Run SquareIceShelf with Icepack", "Run SquareIceShelf on AWS with a GPU", "Run SquareIceShelf with -4 CPUs", "Run SquareIceShelf using new_parameter=3", "Run SquareIceShelf on cloud with 2 nodes"])
def test_unresolved_or_invalid_never_applicable(text):
    assert not infer_request(text, catalog()).applicable


def test_defaults_are_current_selection_only():
    p = infer_request("Icepack tutorial using defaults", catalog())
    assert p.applicable and p.values["example"] == "sheet"
    assert "cpus" not in p.values


def test_standalone_local_is_not_implemented():
    p = infer_request("Run 01-synthetic-ice-sheet locally", catalog())
    assert p.errors and not p.applicable


def test_icesee_local_and_ensemble():
    p = infer_request("Run 01-synthetic-ice-sheet locally with 20 ensemble members", catalog("icesee"))
    assert p.applicable and p.values["ensemble_size"] == 20 and p.values["mode"] == "local"


def test_model_example_conflict():
    assert infer_request("SquareIceShelf with Icepack", catalog()).errors


def test_parameters_use_metadata_bounds():
    c = catalog()
    assert infer_request("01-synthetic-ice-sheet ice temperature 255", c).values["parameters"] == {"ice_temperature": 255.0}
    assert infer_request("01-synthetic-ice-sheet ice temperature 300", c).errors
    c["parameters"]["icepack"][0]["max"] = 400
    assert infer_request("01-synthetic-ice-sheet ice temperature 300", c).applicable


def test_no_mutation_or_cross_request_state():
    c = catalog(); original = copy.deepcopy(c)
    infer_request("SquareIceShelf with 4 CPUs", c)
    p = infer_request("01-synthetic-ice-sheet", c)
    assert "cpus" not in p.values and c == original


def test_resource_consistency():
    p = infer_request("SquareIceShelf on PACE with 2 nodes and 8 CPUs", catalog())
    assert p.values["tasks_per_node"] == 4
    assert not infer_request("SquareIceShelf on PACE with 3 nodes and 8 CPUs", catalog()).applicable


def test_capability_resolver_controls_gpu(monkeypatch):
    from cryostack_src.models import workflow_capabilities
    seen = []
    real = workflow_capabilities.resolve_workflow_capabilities
    def resolve(**kw):
        seen.append(kw)
        return real(**kw)
    monkeypatch.setattr(workflow_capabilities, "resolve_workflow_capabilities", resolve)
    assert infer_request("SquareIceShelf cloud GPU", catalog("icesee")).errors
    assert seen == [dict(model="icesee", forecast_model="issm")]


@pytest.mark.parametrize("text", ["SquareIceShelf with a custom sliding law", "SquareIceShelf with mesh resolution 50", "SquareIceShelf using model unknownsolver"])
def test_unhandled_scientific_intent_is_not_silently_dropped(text):
    assert not infer_request(text, catalog()).applicable


def test_request_to_run_is_only_an_inert_proposal():
    p = infer_request("Run SquareIceShelf on PACE", catalog())
    assert p.applicable and not hasattr(p, "submit") and not hasattr(p, "approve")


def test_resource_profile_is_metadata_driven():
    c = catalog(); c["profiles"].append("new-lab-cluster")
    p = infer_request("SquareIceShelf on new-lab-cluster with 4 CPUs", c)
    assert p.applicable and p.values["profile"] == "new-lab-cluster"


def _locked(mode):
    c = catalog()
    c.update(mode_locked=True)
    c["current"]["mode"] = mode
    return c


@pytest.mark.parametrize("mode", ["remote", "cloud"])
def test_locked_mode_plans_for_the_selected_mode_without_switching(mode):
    p = infer_request("Run SquareIceShelf with ISSM", _locked(mode))
    assert p.applicable and "mode" not in p.values and p.values["example"] == "shelf"


def test_locked_remote_keeps_scheduler_settings():
    p = infer_request("Run SquareIceShelf on PACE using 4 CPUs", _locked("remote"))
    assert p.applicable and "mode" not in p.values
    assert p.values["profile"] == "pace" and p.values["cpus"] == 4 and p.values["tasks_per_node"] == 4


def test_locked_cloud_never_takes_hpc_resources():
    p = infer_request("Run SquareIceShelf with ISSM using 4 CPUs", _locked("cloud"))
    assert not p.applicable and "cpus" not in p.values and p.unresolved


@pytest.mark.parametrize("mode,text,named", [
    ("remote", "Run SquareIceShelf on AWS", "Cloud"),
    ("cloud", "Run SquareIceShelf on the cluster", "Remote HPC"),
    ("cloud", "Run SquareIceShelf on PACE", "Remote HPC"),
])
def test_locked_mode_reports_a_request_for_another_mode(mode, text, named):
    p = infer_request(text, _locked(mode))
    assert not p.applicable and "mode" not in p.values
    assert any(named in e and "is selected" in e for e in p.errors)


def test_a_matching_mode_word_is_accepted():
    assert infer_request("Run SquareIceShelf on Remote using 4 CPUs", _locked("remote")).applicable
    assert infer_request("Run SquareIceShelf in the cloud", _locked("cloud")).applicable


def test_unlocked_catalog_still_infers_the_mode():
    assert infer_request("Run SquareIceShelf on AWS", catalog()).values["mode"] == "cloud"


def test_locked_remote_repair_does_not_switch_from_cloud():
    from cryostack_src.agents.diagnosis import diagnose_request
    d = diagnose_request("repair_remote", _locked("cloud"), lambda: [])
    assert not d.proposal.applicable and "mode" not in d.proposal.values
    assert "Remote HPC is not the selected execution mode" in d.issues[0]
