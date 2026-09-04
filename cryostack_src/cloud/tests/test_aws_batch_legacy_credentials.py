"""C7.5 live-incident regression -- job 1ebd6f32-0f69-407c-a931-6b1f1490fb8a.

SubmitJob correctly used the assumed-role (BYO) session; the FIRST poll
immediately executed batch:DescribeJobs as
arn:aws:iam::713938953301:user/cryostack-service, and Terminate failed the
same way. This is not a guard/assertion bug -- the credentials were resolved
correctly by CloudRunController and simply never reached the `aws` CLI
subprocess for status/logs/terminate.

ROOT CAUSE (proved below at the subprocess boundary)
------------------------------------------------------
AWSDriver.status/logs/terminate (cryostack_src/cloud/drivers/aws/driver.py)
delegate to `cryostack_src.cloud.legacy.aws_batch` (batch_status/batch_logs/
terminate_batch_job), a DIFFERENT, OLDER module than the one `submit`
uses (`cryostack_src.cloud.drivers.aws.submit` -> `.auth.run_aws`). The
legacy module's own `run_aws()` called `subprocess.run(...)` with no `env=`
override at all -- `AWSConfig.credentials` was never read anywhere in that
module, so DescribeJobs/TerminateJob/CancelJob always inherited the CURRENT
PROCESS's ambient environment (the CryoStack host's own `cryostack-service`
identity), regardless of what credentials `AWSDriver.__init__` had correctly
stored on `self.config`. `submit_batch_job` was never affected because it
uses the OTHER module (`drivers/aws/auth.py`), which already stripped
ambient credential env vars and injected `config.credentials` -- that
asymmetry is exactly why Submit worked and DescribeJobs/Terminate did not.

THE FIX
-------
`cryostack_src/cloud/legacy/aws_batch.py`'s `run_aws`/`aws_command` now
mirror `drivers/aws/auth.py`'s implementation exactly: when
`config.credentials` is set, the child `aws` process's environment is the
parent environment with every ambient AWS credential var
(AWS_PROFILE/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_SESSION_TOKEN/
AWS_SECURITY_TOKEN) stripped and replaced by ONLY the temporary triple --
never combined with `--profile`, never inheriting the host's own identity.
Developer mode (no `credentials`) is byte-for-byte unchanged (`env=None`,
ambient environment passed through exactly as before).

This is the ONLY code path that changed. `_assert_same_account` (fixed in
the previous checkpoint) is a correct, necessary, but SEPARATE invariant --
it stops a bound run from proceeding when the resolved execution is not BYO
at all. This checkpoint's bug was different: the execution WAS correctly
BYO the whole time; the temporary credentials it carried were simply
dropped one layer below the controller, inside a module the controller
never sees.

Every test below reaches the ACTUAL `subprocess.run` call (or, for the
full-chain tests, drives the real CloudBridge/CloudBackend/CloudManager/
AWSDriver/CloudRunController stack end to end) -- not a synthetic
`_bridge()` fake -- with host/ambient credentials DELIBERATELY present in
`os.environ` the whole time, and asserts they never reach the subprocess
environment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import asyncio

import cryostack_src.cloud.legacy.aws_batch as legacy_batch
from cryostack_src.cloud.bridge import CloudBridge
from cryostack_src.cloud.connect.execution import CloudExecution
from cryostack_src.cloud.legacy.aws_batch import AWSConfig as LegacyAWSConfig
from cryostack_src.frontend.cryolauncher.cloud_run_controller import (
    CANCELLED,
    FAILED,
    CloudRunController,
)

BYO = {
    "AWS_ACCESS_KEY_ID": "BYO_POLL_KEY",
    "AWS_SECRET_ACCESS_KEY": "BYO_POLL_SECRET",
    "AWS_SESSION_TOKEN": "BYO_POLL_TOKEN",
}
ACCOUNT = "774888247882"
JOB_ID = "1ebd6f32-0f69-407c-a931-6b1f1490fb8a"


def _set_ambient_host_credentials(monkeypatch):
    """The CryoStack host's own ambient identity -- deliberately present in
    the process environment throughout every test in this file, exactly as
    it is in the live deployment shell (AWS_PROFILE=cryostack-service)."""
    monkeypatch.setenv("AWS_PROFILE", "cryostack-service")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "HOST_AMBIENT_KEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "HOST_AMBIENT_SECRET")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "HOST_AMBIENT_TOKEN")


def _fake_subprocess_run(calls: list):
    """Stands in for `subprocess.run` at the exact boundary the user asked
    for -- records (cmd, env) for every invocation and answers whichever AWS
    Batch CLI verb was actually requested, entirely offline."""

    def fake_run(cmd, capture_output, text, env):
        calls.append({"cmd": list(cmd), "env": dict(env) if env is not None else None})

        class R:
            returncode = 0
            stderr = ""
            if "describe-jobs" in cmd:
                stdout = json.dumps({"jobs": [{"status": "RUNNING", "container": {}}]})
            else:
                stdout = "{}"

        return R()

    return fake_run


# -- A. the legacy module in isolation (mirrors test_cloud_connect_security's
#       coverage of the auth.py module, for the module that was actually
#       broken) -------------------------------------------------------------
def test_legacy_run_aws_uses_byo_credentials_and_drops_ambient_and_profile(monkeypatch):
    _set_ambient_host_credentials(monkeypatch)
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))

    cfg = LegacyAWSConfig(region="us-east-2", profile="cryostack-service", credentials=dict(BYO))
    legacy_batch.run_aws(cfg, ["batch", "describe-jobs", "--jobs", JOB_ID])

    assert len(calls) == 1
    assert "--profile" not in calls[0]["cmd"]
    env = calls[0]["env"]
    assert env["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
    assert env["AWS_SECRET_ACCESS_KEY"] == "BYO_POLL_SECRET"
    assert env["AWS_SESSION_TOKEN"] == "BYO_POLL_TOKEN"
    assert "AWS_PROFILE" not in env
    assert "HOST_AMBIENT_KEY" not in env.values()
    assert "HOST_AMBIENT_SECRET" not in env.values()
    assert "HOST_AMBIENT_TOKEN" not in env.values()


def test_legacy_run_aws_developer_mode_is_byte_for_byte_unchanged(monkeypatch):
    """No regression for the non-BYO path: env=None, ambient/profile as
    before -- this checkpoint's fix must not touch developer mode."""
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))
    legacy_batch.run_aws(LegacyAWSConfig(region="us-east-2", profile="dev"),
                         ["sts", "get-caller-identity"])
    assert "--profile" in calls[0]["cmd"] and "dev" in calls[0]["cmd"]
    assert calls[0]["env"] is None


# -- B. through AWSDriver.status/terminate (the real config object that
#       actually flows through the live path -- drivers.aws.models.AWSConfig,
#       not the legacy dataclass) -------------------------------------------
def test_driver_status_reaches_describe_jobs_with_the_byo_environment(monkeypatch):
    from cryostack_src.cloud.drivers.aws.driver import AWSDriver

    _set_ambient_host_credentials(monkeypatch)
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))

    driver = AWSDriver(region="us-east-2", profile=None, credentials=dict(BYO))
    status = driver.status(JOB_ID)

    assert status["status"] == "RUNNING"
    describe_calls = [c for c in calls if "describe-jobs" in c["cmd"]]
    assert len(describe_calls) == 1
    env = describe_calls[0]["env"]
    assert env["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
    assert "AWS_PROFILE" not in env
    assert "HOST_AMBIENT_KEY" not in env.values()


def test_driver_terminate_reaches_the_batch_call_with_the_byo_environment(monkeypatch):
    from cryostack_src.cloud.drivers.aws.driver import AWSDriver

    _set_ambient_host_credentials(monkeypatch)
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))

    driver = AWSDriver(region="us-east-2", profile=None, credentials=dict(BYO))
    driver.terminate(JOB_ID)

    assert len(calls) == 2                     # describe (status check) + terminate-job
    for c in calls:
        env = c["env"]
        assert env["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
        assert "AWS_PROFILE" not in env
        assert "HOST_AMBIENT_KEY" not in env.values()


# -- C. through CloudBridge (the object CloudRunController actually holds) --
def test_cloud_bridge_status_and_terminate_reach_subprocess_with_byo_env(monkeypatch):
    _set_ambient_host_credentials(monkeypatch)
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))

    bridge = CloudBridge(provider="aws", region="us-east-2", credentials=dict(BYO))
    bridge.status(job_id=JOB_ID)
    bridge.terminate(job_id=JOB_ID)

    assert len(calls) == 3                     # 1 status describe + (1 describe + 1 terminate)
    for c in calls:
        assert c["env"]["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
        assert "AWS_PROFILE" not in c["env"]


# -- D. the full live-shaped path: CloudRunController -> real CloudBridge ->
#       real CloudBackend/CloudManager/AWSDriver -> the actual subprocess
#       boundary, for poll AND terminate, with ambient host credentials
#       deliberately present the whole time. This is the exact chain named
#       in the live incident. ------------------------------------------
async def _immediate(fn):
    return fn()


async def _no_sleep(_seconds):
    return None


def _live_controller(monkeypatch, *, sync_results=None):
    _set_ambient_host_credentials(monkeypatch)
    calls: list = []
    monkeypatch.setattr(legacy_batch, "subprocess",
                         type("S", (), {"run": staticmethod(_fake_subprocess_run(calls))}))

    def execution_provider():
        return CloudExecution(mode="byo", region="us-east-2", credentials=dict(BYO),
                              profile=None, account_id=ACCOUNT)

    sink = {"states": [], "logs": []}
    ctl = CloudRunController(
        bridge_factory=lambda **kw: CloudBridge(provider="aws", **kw),
        register_run=lambda **kw: None,
        sync_results=sync_results or (lambda **kw: "/local/cloud_outputs"),
        on_state=sink["states"].append,
        on_log=sink["logs"].append,
        execution_provider=execution_provider,
        poll_interval=0.0,
        to_thread=_immediate,
        sleep=_no_sleep,
    )
    ctl._handle.job_id = JOB_ID
    ctl._handle.account_id = ACCOUNT
    return ctl, sink, calls


def test_live_path_poll_reaches_describe_jobs_with_the_byo_environment(monkeypatch):
    """CloudRunController._poll_loop -> controller._bridge(...) ->
    CloudBridge.status -> CloudBackend.status -> CloudManager.status ->
    AWSDriver.status -> legacy_batch.batch_status -> run_aws -> the actual
    subprocess -- the exact chain named in the live incident. The fake
    DescribeJobs answers RUNNING once, then FAILED, so the loop makes a
    second real (fake-subprocess) poll and exits without needing S3 result
    retrieval -- mirrors RecordingBridge.poll_sequence's established shape,
    but for the real subprocess boundary instead of a fake bridge."""
    ctl, sink, calls = _live_controller(monkeypatch)

    poll_states = iter(["RUNNING", "FAILED"])

    def fake_run(cmd, capture_output, text, env):
        calls.append({"cmd": list(cmd), "env": dict(env) if env is not None else None})

        class R:
            returncode = 0
            stderr = ""
            stdout = (
                json.dumps({"jobs": [{"status": next(poll_states), "container": {},
                                      "statusReason": "test"}]})
                if "describe-jobs" in cmd else "{}"
            )
        return R()

    monkeypatch.setattr(legacy_batch, "subprocess",
                        type("S", (), {"run": staticmethod(fake_run)}))

    asyncio.run(ctl._poll_loop(JOB_ID))

    describe_calls = [c for c in calls if "describe-jobs" in c["cmd"]]
    assert len(describe_calls) == 2
    for c in describe_calls:
        assert c["env"]["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
        assert "AWS_PROFILE" not in c["env"]
        assert "HOST_AMBIENT_KEY" not in c["env"].values()
    assert FAILED in sink["states"]
    assert any("[cloud][auth] poll account=774888247882 access=temporary-role" in m
               for m in sink["logs"])


def test_live_path_terminate_reaches_the_batch_call_with_the_byo_environment(monkeypatch):
    """CloudRunController.terminate -> _terminate_worker -> controller._bridge
    -> CloudBridge.terminate -> ... -> the actual subprocess, with ambient
    host credentials deliberately present throughout."""
    ctl, sink, calls = _live_controller(monkeypatch)

    asyncio.run(ctl._terminate_worker(JOB_ID))

    assert ctl.state == CANCELLED
    assert len(calls) == 2                     # describe + terminate-job
    for c in calls:
        assert c["env"]["AWS_ACCESS_KEY_ID"] == "BYO_POLL_KEY"
        assert "AWS_PROFILE" not in c["env"]
        assert "HOST_AMBIENT_KEY" not in c["env"].values()
    assert any("[cloud][auth] terminate account=774888247882 access=temporary-role" in m
               for m in sink["logs"])


def test_live_path_result_retrieval_was_already_credential_correct(monkeypatch):
    """Results retrieval does NOT go through the legacy aws_batch module (it
    is WorkspaceManager.sync_cloud_results' own `aws s3 sync`, which already
    strips ambient env / injects credentials) -- confirms it was never part
    of this defect, end to end through the real controller."""
    synced = []

    def fake_sync(**kw):
        synced.append(kw)
        return "/local/cloud_outputs"

    ctl, sink, calls = _live_controller(monkeypatch, sync_results=fake_sync)
    asyncio.run(ctl._retrieve_results())

    assert synced and synced[0]["credentials"] == BYO
    assert synced[0]["profile"] is None
    assert any("[cloud][auth] results account=774888247882 access=temporary-role" in m
               for m in sink["logs"])


# -- E. the diagnostic log never carries secret material --------------------
def test_auth_diagnostic_never_logs_a_secret_or_arn(monkeypatch):
    ctl, sink, calls = _live_controller(monkeypatch)
    asyncio.run(ctl._terminate_worker(JOB_ID))
    blob = "\n".join(sink["logs"])
    for secret in BYO.values():
        assert secret not in blob
    assert "arn:aws:iam" not in blob
    assert "ExternalId" not in blob
