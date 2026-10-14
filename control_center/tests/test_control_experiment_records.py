"""Execution records end to end, with fakes for every scheduler/AWS call.

The applications' real record path is used: ``ExperimentBridge`` commands
(as the browser would send them) are replayed against the real
``/api/v1/experiments`` handlers, then the Control Center pages/APIs are read.
Covers: one record per run (ICESEE HPC, CryoLauncher remote, cloud), terminal
states applied once, the redacted failure summary, ICESEE scientific
metadata, role visibility, and "status unknown since" for stale records.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from control_center import install_control_center
from control_center.services import AccessService
from control_center.services.experiments import ExperimentService
from cryostack_src.frontend.cryolauncher import cloud_run_controller as crc
from cryostack_src.frontend.cryolauncher.cloud_experiments import (
    CloudExperimentRecorder,
    cloud_experiment_record,
)
from cryostack_src.frontend.cryolauncher.remote_runtime import build_remote_runtime_callbacks
from icesee_auth import AuthManager
from icesee_jupyter_book.core.experiment_status import experiment_update_from_job_status
from icesee_jupyter_book.ui.experiment_bridge import ExperimentBridge

#: strings that must never reach a stored record, page or API response
SECRETS = (
    "AKIAIOSFODNN7EXAMPLE",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "hunter2-correct",
    "relaytok-6f1c0e2a9b",
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU",
)

SECRET_REASON = (
    "container exited; password=hunter2-correct AKIAIOSFODNN7EXAMPLE "
    "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY "
    "relay_token=relaytok-6f1c0e2a9b "
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\n"
    "-----END OPENSSH PRIVATE KEY-----"
)

ICESEE_CONFIGURATION = {
    "execution_mode": "remote", "example": "lorenz96", "preset": "quick",
    "filter": "EnKF", "ensemble_size": 30, "output": "", "report_generation": False,
    "remote": {"access_mode": "connector", "backend": "native", "cluster": "pace",
               "host": "login.example.edu", "port": 22,
               "remote_base_dir": "/storage/home/u/icesee", "remote_tag": "t"},
    "slurm": {"job_name": "icesee", "time": "02:00:00", "nodes": 2, "tasks": 64,
              "tasks_per_node": 32, "partition": "cpu-small", "memory": "8G",
              "account": "gts-alloc"},
}


class Env:
    def __init__(self, tmp_path: Path):
        self.db = tmp_path / "auth.db"
        self.auth = AuthManager(database_path=self.db, secure_cookies=False)
        self.storage = self.auth.storage
        self.workspace_root = tmp_path / "ws"

    def app(self) -> web.Application:
        # one application per event loop (several flows run per test)
        app = web.Application()
        self.auth.install(app)
        app["access_service"] = AccessService(self.storage)
        app["control_workspace_root"] = str(self.workspace_root)
        install_control_center(app, auth=self.auth, database_path=self.db)
        return app

    def user(self, name: str, *roles: str):
        user = self.storage.create_user(email=f"{name}@example.org", display_name=name.title(),
                                        institution="Test U",
                                        password_hash="scrypt$1$1$1$00$00")
        for role in roles:
            self.storage.grant_role(user_id=user.id, role=role)
        return user

    def login(self, user) -> dict:
        session = self.storage.create_session(ttl_seconds=3600, user_id=user.id)
        return {"icesee_session": session.id}

    def run(self, script):
        async def go():
            async with TestClient(TestServer(self.app())) as client:
                return await script(client)
        return asyncio.run(go())

    def rows(self, table: str) -> list[dict]:
        with sqlite3.connect(self.db) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY created_at")]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("GITHUB", "ORCID"):
        for part in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"):
            monkeypatch.delenv(f"CRYOSTACK_{name}_{part}", raising=False)
    return Env(tmp_path)


def commands(bridge: ExperimentBridge) -> list[dict]:
    """The commands the hidden bridge element carries, as the browser reads them."""
    parts = bridge.output.value.split('data-cryostack-command="')[1:]
    return [json.loads(base64.b64decode(p.split('"', 1)[0])) for p in parts if p.split('"', 1)[0]]


async def replay(client, cookies, sent: list[dict], *, already: set | None = None):
    """Send each not-yet-sent command once, like the browser observer."""
    already = set() if already is None else already
    statuses = []
    for command in sent:
        if command["message_id"] in already:
            continue
        already.add(command["message_id"])
        client.session.cookie_jar.clear()
        response = await client.request(command["method"], command["url"],
                                        json=command["payload"], cookies=cookies)
        statuses.append(response.status)
    return statuses


class _Out:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def clear_output(self):
        pass


# ----------------------------------------------------------------------
# the three run paths
# ----------------------------------------------------------------------

def _icesee_run(env, cookies):
    """ICESEE remote submit (icesee_gateway) + three status checks."""
    bridge = ExperimentBridge()
    bridge.create(application="icesee", name="ICESEE EnKF run", backend="native",
                  status="running", job_id="4101", cluster="pace",
                  working_directory="/storage/home/u/icesee/run-1", log_path=None,
                  configuration=ICESEE_CONFIGURATION,
                  metadata={"execution_mode": "remote", "access_mode": "connector",
                            "backend": "native", "filter": "EnKF", "preset": "quick",
                            "example": "lorenz96"})
    create = commands(bridge)[-1]
    polls = [
        {"source": "squeue", "state": "RUNNING", "exit_code": None, "stdout": "4101|RUNNING|"},
        {"source": "sacct", "state": "TIMEOUT", "exit_code": "0:15",
         "stdout": "4101|TIMEOUT|0:15\n4101.batch|CANCELLED|0:15"},
        {"source": "sacct", "state": "TIMEOUT", "exit_code": "0:15"},     # user checks again
        {"source": "squeue", "state": "RUNNING", "exit_code": None},      # a late, stale reading
    ]

    async def script(client):
        sent = set()
        statuses = await replay(client, cookies, [create], already=sent)
        # a re-sent create (page re-render) must not track the job twice
        client.session.cookie_jar.clear()
        again = await client.post("/api/v1/experiments", json=create["payload"], cookies=cookies)
        statuses.append(again.status)
        for poll in polls:
            update = experiment_update_from_job_status(poll)
            bridge.update_by_job(job_id="4101", **update)
            statuses += await replay(client, cookies, commands(bridge), already=sent)
        return statuses

    return env.run(script)


def _cryolauncher_remote_run(env, cookies):
    """CryoLauncher remote Status button (remote_runtime) with a fake bridge."""
    bridge = ExperimentBridge()
    bridge.create(application="cryolauncher", name="ISSM container run", backend="container",
                  status="running", job_id="5202", cluster="pace",
                  working_directory="/remote/run", output_directory="/remote/run/outputs",
                  log_path="/remote/run/icesheets-5202.out",
                  configuration={"execution_mode": "remote", "model": "issm",
                                 "slurm": {"nodes": 1, "tasks": 8, "time": "01:00:00"}},
                  metadata={"execution_mode": "remote", "access_mode": "direct", "model": "issm"})
    readings = iter([
        SimpleNamespace(state="running", metadata={"source": "squeue", "state": "RUNNING",
                                                   "exit_code": None, "returncode": 0}),
        SimpleNamespace(state="failed", metadata={"source": "sacct", "state": "OUT_OF_MEMORY",
                                                  "exit_code": "0:125", "returncode": 0,
                                                  "stdout": "5202|OUT_OF_MEMORY|0:125"}),
        SimpleNamespace(state="failed", metadata={"source": "sacct", "state": "OUT_OF_MEMORY",
                                                  "exit_code": "0:125", "returncode": 0}),
    ])

    class FakeRemoteBridge:
        mode = "direct"

        def status(self, *, job_id):
            assert job_id == "5202"
            return next(readings)

    callbacks = build_remote_runtime_callbacks(
        runtime_status={"jobid": "5202"}, log_output=_Out(),
        status_widget=SimpleNamespace(value=""), status_html=lambda s: s,
        bridge_factory=FakeRemoteBridge, experiment_bridge=bridge,
        experiment_update_from_job_status=experiment_update_from_job_status)

    async def script(client):
        sent = set()
        statuses = await replay(client, cookies, commands(bridge), already=sent)
        for _ in range(3):
            callbacks.status()
            statuses += await replay(client, cookies, commands(bridge), already=sent)
        return statuses

    return env.run(script)


def _cloud_run(env, cookies):
    """CryoLauncher cloud run (CloudRunController states) with a fake AWS reason."""
    bridge = ExperimentBridge()
    handle = crc._RunHandle(job_id="aws-job-1", s3_run="s3://bucket/u/run-1", run_id="run-1",
                            model="issm", region="us-east-2", account_id="774888247882",
                            vcpu=4, memory_gib=16)
    recorder = CloudExperimentRecorder(bridge, job_id=lambda: "aws-job-1",
                                       reason=lambda: SECRET_REASON)
    recorder.created(cloud_experiment_record(
        handle, result_metadata={"job_queue": "q", "job_definition": "d"},
        configuration={"execution_mode": "cloud", "model": "issm"}))

    async def script(client):
        sent = set()
        statuses = await replay(client, cookies, commands(bridge), already=sent)
        for state in (crc.QUEUED, crc.RUNNING, crc.FAILED, crc.FAILED, crc.RUNNING):
            recorder.state(state)
            statuses += await replay(client, cookies, commands(bridge), already=sent)
        return statuses

    return env.run(script)


def _record(env, job_id):
    rows = [r for r in env.rows("experiments") if r["job_id"] == job_id]
    assert len(rows) == 1, rows
    return rows[0]


def _events(env, experiment_id):
    return [r["event_type"] for r in env.rows("experiment_events")
            if r["experiment_id"] == experiment_id]


def test_icesee_hpc_run_one_record_terminal_once_with_failure_summary(env):
    owner = env.user("researcher")
    statuses = _icesee_run(env, env.login(owner))
    # create 201, re-sent create 200 (same record), running 200, timeout 200,
    # repeated timeout 200 and late running 200 -- both no-ops
    assert statuses == [201, 200, 200, 200, 200, 200]
    record = _record(env, "4101")
    assert record["status"] == "failed"
    assert record["exit_code"] == 0
    assert _events(env, record["id"]) == ["created", "running", "failed"]
    metadata = json.loads(record["metadata_json"])
    assert metadata["failure"] == {
        "scheduler": "slurm", "state": "TIMEOUT", "exit_code": 0, "signal": 15,
        "reason": "The job reached its wall-clock time limit."}
    assert record["error_message"] == (
        "TIMEOUT, exit 0 (signal 15): The job reached its wall-clock time limit.")
    # the ICESEE facts in the one shape the Control Center renders
    assert metadata["ensemble_size"] == 30 and metadata["filter"] == "EnKF"
    assert metadata["requested_resources"]["mpi_ranks"] == 64
    assert len(env.rows("experiments")) == 1


def test_terminal_status_and_finish_time_are_written_once(env):
    owner = env.user("researcher")
    _icesee_run(env, env.login(owner))
    before = _record(env, "4101")
    cookies = env.login(owner)

    async def script(client):
        out = []
        for payload in ({"status": "completed"}, {"status": "running", "exit_code": 3},
                        {"status": "failed", "failure": {"state": "NODE_FAIL"}}):
            client.session.cookie_jar.clear()
            response = await client.patch("/api/v1/experiments/job/4101", json=payload,
                                          cookies=cookies)
            out.append((response.status, (await response.json())["status"]))
        client.session.cookie_jar.clear()
        response = await client.patch(f"/api/v1/experiments/{before['id']}",
                                      json={"status": "cancelled"}, cookies=cookies)
        out.append((response.status, (await response.json())["status"]))
        return out

    assert env.run(script) == [(200, "failed")] * 4
    after = _record(env, "4101")
    assert after == before
    assert _events(env, before["id"]) == ["created", "running", "failed"]


def test_cryolauncher_remote_run_out_of_memory(env):
    owner = env.user("modeler")
    assert _cryolauncher_remote_run(env, env.login(owner)) == [201, 200, 200, 200]
    record = _record(env, "5202")
    assert record["status"] == "failed" and record["exit_code"] == 0
    failure = json.loads(record["metadata_json"])["failure"]
    assert (failure["state"], failure["signal"]) == ("OUT_OF_MEMORY", 125)
    assert "memory" in failure["reason"]
    assert _events(env, record["id"]) == ["created", "running", "failed"]


def test_cloud_run_one_record_redacted_failure(env):
    owner = env.user("cloudy")
    # create; queued is the create status (not re-sent); running; failed;
    # nothing after the terminal state
    assert _cloud_run(env, env.login(owner)) == [201, 200, 200]
    record = _record(env, "aws-job-1")
    assert record["status"] == "failed" and record["backend"] == "aws"
    assert _events(env, record["id"]) == ["created", "running", "failed"]
    stored = json.dumps(record)
    for secret in SECRETS + ("774888247882",):
        assert secret not in stored
    failure = json.loads(record["metadata_json"])["failure"]
    assert failure["scheduler"] == "aws-batch" and "container exited" in failure["reason"]


def test_server_redacts_and_bounds_a_hostile_failure_payload(env):
    owner = env.user("hostile")
    experiment = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="run", backend="native",
        configuration_snapshot_json="{}", job_id="77", status="running")
    cookies = env.login(owner)

    async def script(client):
        client.session.cookie_jar.clear()
        response = await client.patch("/api/v1/experiments/job/77", cookies=cookies, json={
            "status": "failed", "exit_code": "not-an-int",
            "error_message": SECRET_REASON * 5,
            "failure": {"scheduler": "slurm", "state": "FAILED", "reason": SECRET_REASON,
                        "log_tail": [SECRET_REASON] * 100, "host": "login.example.edu"}})
        return response.status, await response.text()

    status, body = env.run(script)
    assert status == 200
    stored = _record(env, "77")
    assert stored["id"] == experiment.id and stored["exit_code"] is None
    assert len(stored["error_message"]) <= 500
    failure = json.loads(stored["metadata_json"])["failure"]
    assert len(failure["log_tail"]) == 20 and "host" not in failure
    for secret in SECRETS:
        assert secret not in json.dumps(stored) and secret not in body


def test_create_rejects_unknown_status_and_keeps_distinct_jobs_apart(env):
    owner = env.user("researcher")
    cookies = env.login(owner)
    base = {"application": "icesee", "name": "ICESEE run", "backend": "native",
            "configuration": {}, "cluster": "pace"}

    async def script(client):
        out = []
        for payload in ({**base, "status": "TIMEOUT", "job_id": "1"},
                        {**base, "job_id": "1"}, {**base, "job_id": "1"},
                        {**base, "job_id": "2"}, {**base, "job_id": "1", "cluster": "other"},
                        {**base}, {**base}):
            client.session.cookie_jar.clear()
            response = await client.post("/api/v1/experiments", json=payload, cookies=cookies)
            out.append(response.status)
        return out

    # bad status 400; job 1 once (+1 re-send); job 2; job 1 on another cluster;
    # two runs without a job id are two records
    assert env.run(script) == [400, 201, 200, 201, 201, 201, 201]
    assert len(env.rows("experiments")) == 5


# ----------------------------------------------------------------------
# Control Center display and visibility
# ----------------------------------------------------------------------

def _all_runs(env):
    owner = env.user("researcher")
    _icesee_run(env, env.login(owner))
    _cryolauncher_remote_run(env, env.login(owner))
    _cloud_run(env, env.login(env.user("cloudy")))
    return owner


def test_control_center_shows_failure_and_icesee_metadata(env):
    _all_runs(env)
    assert len(env.rows("experiments")) == 3
    developer = env.login(env.user("dev", "developer"))
    icesee = _record(env, "4101")
    cloud = _record(env, "aws-job-1")

    async def script(client):
        pages = {}
        for path in ("/control/experiments", f"/control/experiments/{icesee['id']}",
                     f"/control/experiments/{cloud['id']}", "/api/control/experiments",
                     f"/api/control/experiments/{icesee['id']}",
                     f"/api/control/experiments/{cloud['id']}", "/control/hpc",
                     "/control/cloud", "/api/control/hpc", "/api/control/cloud"):
            client.session.cookie_jar.clear()
            response = await client.get(path, cookies=developer, allow_redirects=False)
            pages[path] = (response.status, await response.text())
        return pages

    pages = env.run(script)
    assert {status for status, _ in pages.values()} == {200}
    listing = pages["/control/experiments"][1]
    for text in ("EnKF", ">30<", "64", "Filter", "Ensemble", "Nodes / ranks", "read-only"):
        assert text in listing, text
    detail = pages[f"/control/experiments/{icesee['id']}"][1]
    for text in ("Failure summary", "TIMEOUT", "wall-clock time limit", "Slurm",
                 "MPI ranks (Slurm tasks)", "02:00:00", "Requested resources",
                 "Measured resources", "Not recorded", "lorenz96", "quick"):
        assert text in detail, text
    cloud_detail = pages[f"/control/experiments/{cloud['id']}"][1]
    assert "AWS Batch" in cloud_detail and "container exited" in cloud_detail
    api = json.loads(pages[f"/api/control/experiments/{icesee['id']}"][1])["experiment"]
    assert api["failure"]["state"] == "TIMEOUT"
    assert api["overview"]["ensemble_size"] == 30
    assert api["overview"]["requested"]["mpi_ranks"] == 64
    assert api["overview"]["measured"] is None
    hpc = json.loads(pages["/api/control/hpc"][1])["executions"]
    assert hpc["summary"]["failed"] == 2
    assert {item["failure"]["state"] for item in hpc["failures"]} == {"TIMEOUT", "OUT_OF_MEMORY"}
    for path, (_, body) in pages.items():
        for secret in SECRETS + ("774888247882",):
            assert secret not in body, (path, secret)


def test_record_visibility_owner_other_user_and_control_roles(env):
    owner = _all_runs(env)
    icesee = _record(env, "4101")
    owner_cookies = env.login(owner)
    stranger = env.login(env.user("stranger"))
    roles = {role: env.login(env.user(role, role))
             for role in ("developer", "maintainer", "admin", "owner")}

    async def script(client):
        async def get(path, cookies):
            client.session.cookie_jar.clear()
            response = await client.get(path, cookies=cookies, allow_redirects=False)
            return response.status, await response.text()

        out = {
            "owner_api": await get(f"/api/v1/experiments/{icesee['id']}", owner_cookies),
            "owner_list": await get("/api/v1/experiments", owner_cookies),
            "stranger_api": await get(f"/api/v1/experiments/{icesee['id']}", stranger),
            "stranger_list": await get("/api/v1/experiments", stranger),
            "stranger_cc": await get("/control/experiments", stranger),
            "stranger_cc_api": await get(f"/api/control/experiments/{icesee['id']}", stranger),
            "anon_cc_api": await get("/api/control/experiments", {}),
        }
        for role, cookies in roles.items():
            out[role] = await get(f"/control/experiments/{icesee['id']}", cookies)
        return out

    out = env.run(script)
    status, body = out["owner_api"]
    assert status == 200 and json.loads(body)["metadata"]["failure"]["state"] == "TIMEOUT"
    assert len(json.loads(out["owner_list"][1])["experiments"]) == 2   # own two runs only
    assert out["stranger_api"][0] == 404
    assert json.loads(out["stranger_list"][1])["experiments"] == []
    assert out["stranger_cc"][0] == 403 and out["stranger_cc_api"][0] == 403
    assert out["anon_cc_api"][0] in (302, 401)
    for role in ("developer", "maintainer", "admin", "owner"):
        assert out[role][0] == 200 and "Failure summary" in out[role][1]


def test_stale_running_record_is_status_unknown_never_failed(env):
    owner = env.user("researcher")
    day = 24 * 3600
    old = time.time() - 3 * day
    stale = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="ICESEE EnKF run", backend="native",
        configuration_snapshot_json=json.dumps(ICESEE_CONFIGURATION), job_id="9001",
        cluster="pace", status="queued", now=old)
    env.storage.update_experiment(experiment_id=stale.id, user_id=owner.id,
                                  status="running", now=old)
    fresh = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="fresh run", backend="native",
        configuration_snapshot_json="{}", job_id="9002", status="running")
    developer = env.login(env.user("dev", "developer"))

    async def script(client):
        out = []
        for path in ("/control/experiments", f"/control/experiments/{stale.id}",
                     f"/api/control/experiments/{stale.id}",
                     f"/api/control/experiments/{fresh.id}", "/api/control/hpc"):
            client.session.cookie_jar.clear()
            response = await client.get(path, cookies=developer)
            out.append(await response.text())
        return out

    listing, detail, stale_api, fresh_api, hpc = env.run(script)
    assert listing.count("Status unknown since") == 1
    assert "Status unknown since" in detail and "not been marked failed" in detail
    stale_view = json.loads(stale_api)["experiment"]
    assert stale_view["status"] == "running"
    assert abs(stale_view["status_unknown_since"] - old) < 1
    assert json.loads(fresh_api)["experiment"]["status_unknown_since"] is None
    assert json.loads(hpc)["executions"]["summary"]["status_unknown"] == 1
    # never silently changed
    assert _record(env, "9001")["status"] == "running"
    assert _events(env, stale.id) == []


def test_stale_rules_wall_time_and_quiet_period(env):
    owner = env.user("researcher")
    now = 1_000_000.0
    configuration = json.dumps({"slurm": {"time": "1-00:00"}})
    queued = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="queued", backend="native",
        configuration_snapshot_json=configuration, status="queued", now=now - 10 * 3600)
    running = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="running", backend="native",
        configuration_snapshot_json=json.dumps({"slurm": {"time": "02:00:00"}}),
        status="queued", now=now - 4 * 3600)
    env.storage.update_experiment(experiment_id=running.id, user_id=owner.id,
                                  status="running", now=now - 4 * 3600)
    env.storage.update_experiment(experiment_id=running.id, user_id=owner.id,
                                  status="running", now=now - 600)
    done = env.storage.create_experiment(
        user_id=owner.id, application="icesee", name="done", backend="native",
        configuration_snapshot_json="{}", status="queued", now=now - 30 * 24 * 3600)
    env.storage.update_experiment(experiment_id=done.id, user_id=owner.id,
                                  status="completed", now=now - 30 * 24 * 3600)
    service = ExperimentService(env.storage, clock=lambda: now)
    view = {item["name"]: item["status_unknown_since"] for item in service.list_experiments()}
    # queued 10 h without an update: still inside the quiet period
    assert view["queued"] is None
    # running 4 h on a 2 h wall time (+1 h grace), last update 10 min ago
    assert view["running"] == now - 600
    # finished records are never "unknown"
    assert view["done"] is None
    assert ExperimentService(env.storage, clock=lambda: now,
                             stale_after=3600)._view(
        {"id": "x", "status": "queued", "created_at": now - 7200, "updated_at": now - 7200},
        now=now)["status_unknown_since"] == now - 7200


@pytest.mark.parametrize("value,seconds", [
    ("30", 1800), ("10:30", 630), ("02:00:00", 7200), ("1-00", 86400),
    ("1-02:30", 95400), ("2-00:00:10", 172810), ("", None), ("UNLIMITED", None),
    ("0", None),
])
def test_slurm_time_seconds(value, seconds):
    from control_center.services.compute import slurm_time_seconds
    assert slurm_time_seconds(value) == seconds
