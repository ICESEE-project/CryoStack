"""Local runs as background jobs, and the launcher's prepare/start/finalize
path, on a small fake example that writes ICESEE-shaped outputs."""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml

from icesee_jupyter_book.core import local_jobs, provenance, results_service, run_launcher, run_lifecycle, run_records
from icesee_jupyter_book.core.local_jobs import JobStatus, LocalJob, clean_log, parse_progress

FAKE_MODEL = textwrap.dedent('''
    import os, sys, time
    import numpy as np, h5py, yaml
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    p = yaml.safe_load(open(sys.argv[sys.argv.index("-F") + 1]))
    mode = p["modeling-parameters"].get("mode", "ok")
    n = 20
    for k in range(1, n + 1):
        print(f"[ICESEE] Assimilation progress (1 ranks): {100*k//n:3d}%|##| {k}/{n} [00:00<00:00]", end="\\r", flush=True)
        time.sleep(float(p["modeling-parameters"].get("sleep", 0.01)))
    if mode == "crash":
        raise SystemExit(3)
    if mode == "hang_after_error":
        print("[ICESEE] Error in partial run mode:\\nTraceback (most recent call last):\\nValueError: could not convert string to float: 'N'", flush=True)
        time.sleep(600)
    if mode == "swallowed":
        print("[ICESEE] Error in serial run mode:\\nTraceback (most recent call last):\\nValueError: x")
        sys.exit(0)
    d = "_modelrun_datasets"; os.makedirs(d, exist_ok=True)
    t = np.linspace(0, 1, 21); truth = np.random.default_rng(0).normal(size=(3, 21))
    with h5py.File(f"{d}/true-wrong-fake.h5", "w") as f:
        f["t"] = t; f["obs_index"] = np.array([2, 6, 10]); f["obs_max_time"] = np.array([0.5]); f["run_mode"] = np.array([0])
    with h5py.File(f"{d}/true_nurged_states.h5", "w") as f:
        f["true_state"] = truth; f["nurged_state"] = truth + 1
    with h5py.File(f"{d}/synthetic_obs.h5", "w") as f:
        f["hu_obs"] = truth[:, [2, 6, 10]]
    ens = truth[:, None, :] + 0.1
    with h5py.File(f"{d}/icesee_ensemble_data.h5", "w") as f:
        f["ensemble"] = np.repeat(ens, 3, axis=1); f["ensemble_mean"] = truth + 0.1
    if mode == "shutdown_trace":
        print("Traceback (most recent call last):\\nmpi4py.MPI.Exception: MPI_ERR_COMM: invalid communicator")
    print("[ICESEE] Writing data to", d)
''')

PARAMS = {"physical-parameters": {"a": 1.0},
          "modeling-parameters": {"num_years": 1, "mode": "ok", "sleep": 0.01},
          "enkf-parameters": {"Nens": 3, "filter_type": "EnKF", "model_name": "fake",
                              "vec_inputs": ["x", "y", "z"], "observed_vars": ["x"]}}
CONTRACT = {"schema": "icesee-results/1", "model_name": "fake", "views": ["lorenz.state_estimation"]}


@pytest.fixture
def fake_example(tmp_path):
    ex = tmp_path / "apps" / "fake_ex"
    ex.mkdir(parents=True)
    (ex / "run_da_fake.py").write_text(FAKE_MODEL)
    (ex / "params.yaml").write_text(yaml.safe_dump(PARAMS, sort_keys=False))
    (ex / "inputs.csv").write_text("a,b\n1,2\n")
    (ex / "results.yaml").write_text(json.dumps(CONTRACT))
    return {"base": ex, "run_script": "run_da_fake.py", "params": "params.yaml", "model_name": "fake",
            "report_nb": None}


def _launch(tmp_path, cfg, **mode):
    params = {**PARAMS, "modeling-parameters": {**PARAMS["modeling-parameters"], **mode}}
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=cfg, config=params, environment="native",
                                     run_root=tmp_path / "runs", user_id="tester")
    assert not [i for i in run_launcher.validate_launch(req) if i.level == "error"]
    prepared = run_launcher.prepare_local_run(req)
    job = run_launcher.start_local_run(prepared)
    return prepared, job


def _wait(job, model="fake", timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = job.poll(model_name=model)
        if st.state != "running":
            return st
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_successful_run_lifecycle_provenance_and_results(tmp_path, fake_example):
    prepared, job = _launch(tmp_path, fake_example)
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    assert info.status == "running" and info.jobid.startswith("local:")
    st = _wait(job)
    assert st.state == "completed" and st.step == (20, 20)
    run_launcher.finalize_local_run(prepared.run_dir, st)
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    assert [e["state"] for e in info.metadata["lifecycle"]] == ["preparing", "running", "completed"]
    prov = provenance.load(prepared.run_dir)
    assert prov["experiment"]["example"] == "Fake" and prov["params"]["sha256"]
    assert prov["code"]["icesee"]["upstream_commit"]
    assert {f["path"] for f in prov["inputs"]} >= {"run_da_fake.py", "params.yaml", "inputs.csv"}
    assert info.metadata["provenance"]["params_sha256"] == prov["params"]["sha256"]
    res = results_service.discover(info, lifecycle_state="completed")
    assert res.status == "ready", res.message
    out = results_service.render(res, "lorenz.state_estimation")
    assert out.ok and out.png.is_file()
    again = results_service.render(res, "lorenz.state_estimation")
    assert again.cached and again.png == out.png


def test_edited_inputs_are_staged_and_recorded(tmp_path, fake_example):
    draft = tmp_path / "draft.csv"
    draft.write_text("a,b\n9,9\n")
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=fake_example, config=PARAMS,
                                     run_root=tmp_path / "runs", drafts={"inputs.csv": draft})
    prepared = run_launcher.prepare_local_run(req)
    assert (prepared.run_dir / "example" / "fake_ex" / "inputs.csv").read_text() == "a,b\n9,9\n"
    assert (fake_example["base"] / "inputs.csv").read_text() == "a,b\n1,2\n"
    prov = provenance.load(prepared.run_dir)
    assert prov["edited_inputs"] == ["inputs.csv"]
    assert next(f for f in prov["inputs"] if f["path"] == "inputs.csv")["edited"]


def test_staging_refuses_new_or_escaping_files(tmp_path, fake_example):
    from icesee_jupyter_book.core.local_runner import stage_example

    other = tmp_path / "x.csv"
    other.write_text("1")
    for rel in ("new.csv", "../escape.csv"):
        with pytest.raises(ValueError):
            stage_example(fake_example, tmp_path / f"run-{rel.count('.')}", overlays={rel: other})


@pytest.mark.parametrize("mode, detail", [("crash", "status 3"), ("swallowed", "reported an error")])
def test_failures_are_failures(tmp_path, fake_example, mode, detail):
    prepared, job = _launch(tmp_path, fake_example, mode=mode)
    st = _wait(job)
    assert st.state == "failed" and detail in st.detail
    run_launcher.finalize_local_run(prepared.run_dir, st)
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    assert info.status == "failed" and detail in info.metadata["final_detail"]
    res = results_service.discover(info, lifecycle_state="failed")
    assert res.status == "no_outputs" and "failed" in res.message


def test_shutdown_traceback_with_outputs_completes_with_warning(tmp_path, fake_example):
    _prepared, job = _launch(tmp_path, fake_example, mode="shutdown_trace")
    st = _wait(job)
    assert st.state == "completed" and st.warnings


def test_cancel_and_reconcile_after_reload(tmp_path, fake_example):
    prepared, job = _launch(tmp_path, fake_example, sleep=0.5)
    time.sleep(0.5)
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    state, live = run_launcher.reconcile_local_run(info)          # "page reload": re-attach
    assert state == "running" and live is not None
    assert LocalJob(prepared.run_dir).cancel()
    st = _wait(LocalJob(prepared.run_dir))
    assert st.state == "cancelled"
    info = run_records.load_run(tmp_path / "runs", prepared.run_id)
    state, live = run_launcher.reconcile_local_run(info)          # settles without a watcher
    assert state == "cancelled" and live is None
    assert run_records.load_run(tmp_path / "runs", prepared.run_id).status == "cancelled"


def test_lost_process_is_failed_not_running(tmp_path):
    rd = tmp_path / "r"
    rd.mkdir()
    (rd / local_jobs.JOB_FILE).write_text(json.dumps({"pid": 999_999_9, "proc_start": "1", "started": time.time()}))
    st = LocalJob(rd).poll()
    assert st.state == "failed" and "exit status" in st.detail


def test_validation_blocks_bad_launches(tmp_path, fake_example):
    bad = {**PARAMS, "enkf-parameters": {**PARAMS["enkf-parameters"], "filter_type": "nope"}}
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=fake_example, config=bad, run_root=tmp_path)
    assert any(i.level == "error" and "filter_type" in i.message for i in run_launcher.validate_launch(req))
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=fake_example, config=PARAMS,
                                     environment="teleport", run_root=tmp_path)
    assert any("unknown local environment" in i.message for i in run_launcher.validate_launch(req))
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=fake_example, config=PARAMS,
                                     drafts={"inputs.csv": tmp_path}, run_root=tmp_path)
    assert any("Local runs only" in i.message for i in run_launcher.validate_launch(req, mode="remote"))


def test_full_parallel_mode_is_refused_in_the_container(tmp_path, fake_example):
    full = {**PARAMS, "enkf-parameters": {**PARAMS["enkf-parameters"], "execution_mode": 2}}
    blocked = lambda env: [i for i in run_launcher.validate_launch(run_launcher.LaunchRequest(  # noqa: E731
        example="Fake", example_cfg=fake_example, config=full, environment=env, run_root=tmp_path))
        if "parallel HDF5" in i.message]
    assert blocked("container") and blocked("container")[0].level == "error"
    assert not blocked("native")


def test_serial_mode_on_several_container_processes_is_refused(tmp_path, fake_example):
    serial = {**PARAMS, "enkf-parameters": {**PARAMS["enkf-parameters"], "execution_mode": 0}}
    issues = lambda np: [i for i in run_launcher.validate_launch(run_launcher.LaunchRequest(  # noqa: E731
        example="Fake", example_cfg=fake_example, config=serial, environment="container", np=np,
        run_root=tmp_path)) if "serial" in i.message]
    assert issues(2) and not issues(1)


def test_progress_parsing_and_log_cleaning():
    text = ("[ICESEE] Generating true state ...\n[ICESEE] Assimilation progress (12 ranks):  10%|#| 24/240 [00:01]"
            "\r[ICESEE] Assimilation progress (12 ranks):  50%|##| 120/240 [00:02]")
    p = parse_progress(text)
    assert p["step"] == (120, 240) and p["progress"] == 0.5 and p["stage"] == "Assimilating observations"
    assert clean_log("a\rb\rc\n\x1b[31mred\x1b[0m") == "c\nred"


def test_container_command_is_confined(tmp_path):
    rd = tmp_path / "run"
    (rd / "example" / "synthetic_ice_stream").mkdir(parents=True)
    argv, env, name = local_jobs.container_command(
        run_dir=rd, staged_example=rd / "example" / "synthetic_ice_stream",
        run_script=Path("run_da_icepack.py"), model="icepack", run_id="20261015_1-ab", np=2, nens=8,
        image="img:1", post_mesh=True)
    assert argv[:3] == ["docker", "run", "--rm"] and "--network" in argv and argv[argv.index("--network") + 1] == "none"
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert any(m.endswith(":/opt/ICESEE:ro") for m in mounts) and f"{rd}:/icesee-run" in mounts
    assert "mpirun --allow-run-as-root -np 2 python run_da_icepack.py" in argv[-1]
    assert "--Nens=8" in argv[-1] and "venv-icepack" in argv[-1] and "icepack_mesh" in argv[-1]
    assert not any(k.startswith("AWS_") for k in env) and name == "icesee-20261015_1-ab"


def test_native_command_keeps_the_existing_shape(tmp_path):
    argv, env = local_jobs.native_command(tmp_path / "run_da_x.py", tmp_path / "params.yaml")
    assert argv == [sys.executable, str(tmp_path / "run_da_x.py"), "-F", str(tmp_path / "params.yaml")]
    assert "external" in env["PYTHONPATH"] and not any(k.startswith("AWS_") for k in env)


def test_unsupported_environment_is_reported(monkeypatch):
    monkeypatch.setenv(local_jobs.CONTAINER_ENV, "0")
    local_jobs._docker_cache.clear()
    envs = {e.kind: e for e in local_jobs.environments("lorenz")}
    assert envs["native"].available and not envs["container"].available
    assert "disabled" in envs["container"].reason
    local_jobs._docker_cache.clear()


def test_a_run_that_hangs_after_an_error_is_stopped_and_failed(tmp_path, fake_example, monkeypatch):
    """ICESEE's parallel modes can leave a rank waiting forever after another
    one failed: the job must not stay "running" indefinitely."""
    monkeypatch.setattr(local_jobs, "STALL_AFTER_ERROR_S", 1)
    prepared, job = _launch(tmp_path, fake_example, mode="hang_after_error")
    st = _wait(job, timeout=60)
    assert st.state == "failed" and "stopped making progress" in st.detail and "convert string to float" in st.detail
    deadline = time.time() + 15
    while time.time() < deadline and job._alive():
        time.sleep(0.2)
    assert not job._alive()
    assert LocalJob(prepared.run_dir).poll().state == "failed"          # stable after the process ends


def test_concurrent_local_runs_per_user_are_capped(tmp_path, fake_example, monkeypatch):
    monkeypatch.setenv(run_launcher.MAX_ACTIVE_LOCAL_ENV, "1")
    prepared, job = _launch(tmp_path, fake_example, sleep=0.5)
    req = run_launcher.LaunchRequest(example="Fake", example_cfg=fake_example, config=PARAMS,
                                     run_root=tmp_path / "runs")
    issues = run_launcher.validate_launch(req)
    assert any(i.level == "error" and "in progress" in i.message and prepared.run_id in i.message for i in issues)
    job.cancel()
    _wait(job)
    assert not [i for i in run_launcher.validate_launch(req) if "in progress" in i.message]
