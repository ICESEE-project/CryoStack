"""Scheduler state -> experiment record: the state mapping table, the
bounded/redacted failure summary, and the scientific/resource overview."""
import base64
import json

import pytest

from icesee_jupyter_book.core import experiment_status as es


# ----------------------------------------------------------------------
# state mapping
# ----------------------------------------------------------------------

STATE_TABLE = [
    # queued
    ("PENDING", "queued"), ("PD", "queued"), ("REQUEUED", "queued"),
    ("REQUEUE_FED", "queued"), ("REQUEUE_HOLD", "queued"), ("RESV_DEL_HOLD", "queued"),
    # preparing
    ("CONFIGURING", "preparing"), ("CF", "preparing"),
    # running (the job still holds its allocation)
    ("RUNNING", "running"), ("R", "running"), ("SUSPENDED", "running"),
    ("STOPPED", "running"), ("SIGNALING", "running"), ("RESIZING", "running"),
    ("COMPLETING", "running"), ("CG", "running"), ("STAGE_OUT", "running"),
    # terminal
    ("COMPLETED", "completed"), ("CD", "completed"),
    ("CANCELLED", "cancelled"), ("CA", "cancelled"),
    ("CANCELLED+", "cancelled"), ("CANCELLED by 12345", "cancelled"),
    ("FAILED", "failed"), ("F", "failed"),
    ("TIMEOUT", "failed"), ("TO", "failed"),
    ("OUT_OF_MEMORY", "failed"), ("OOM", "failed"),
    ("NODE_FAIL", "failed"), ("NF", "failed"),
    ("PREEMPTED", "failed"), ("PR", "failed"),
    ("BOOT_FAIL", "failed"), ("DEADLINE", "failed"), ("REVOKED", "failed"),
    ("SPECIAL_EXIT", "failed"), ("LAUNCH_FAILED", "failed"),
    # lower case and whitespace from a hand-parsed squeue line
    (" running ", "running"), ("timeout", "failed"),
    # unknown / empty: no update is sent
    ("", None), (None, None), ("SOMETHING_NEW", None),
]


@pytest.mark.parametrize("state,expected", STATE_TABLE)
def test_slurm_state_mapping_table(state, expected):
    assert es.slurm_state_to_experiment_status(state) == expected


def test_every_mapped_status_is_a_known_experiment_status():
    assert set(es.SLURM_STATUS.values()) <= es.EXPERIMENT_STATUSES
    # every unsuccessful terminal state has a plain-language reason
    for state, status in es.SLURM_STATUS.items():
        if status in {"failed", "cancelled"}:
            assert es.SLURM_REASONS[state]


@pytest.mark.parametrize("state,reason_word", [
    ("TIMEOUT", "time limit"),
    ("OUT_OF_MEMORY", "memory"),
    ("NODE_FAIL", "node"),
    ("PREEMPTED", "preempted"),
    ("CANCELLED by 4242", "cancelled"),
])
def test_unsuccessful_terminal_updates_carry_a_failure_summary(state, reason_word):
    update = es.experiment_update_from_job_status(
        {"state": state, "exit_code": "0:9", "source": "sacct",
         "stdout": "123|TIMEOUT|0:9\n", "stderr": ""})
    failure = update["failure"]
    assert failure["scheduler"] == "slurm"
    assert failure["state"] == es.normalize_slurm_state(state)
    assert (failure["exit_code"], failure["signal"]) == (0, 9)
    assert reason_word in failure["reason"].lower()
    assert update["exit_code"] == 0
    assert update["error_message"].startswith(failure["state"])
    # scheduler stdout is not log text and never enters the record
    assert "log_tail" not in failure
    assert "123|" not in json.dumps(update)


def test_running_and_completed_updates_have_no_failure():
    assert es.experiment_update_from_job_status(
        {"state": "RUNNING", "exit_code": None}) == {"status": "running"}
    assert es.experiment_update_from_job_status(
        {"state": "COMPLETED", "exit_code": "0:0"}) == {"status": "completed", "exit_code": 0}
    # a non-integer exit code (RemoteBackend already parsed) is accepted too
    assert es.experiment_update_from_job_status(
        {"state": "FAILED", "exit_code": 2})["exit_code"] == 2
    assert es.experiment_update_from_job_status({"state": "WHATEVER"}) is None


@pytest.mark.parametrize("raw,expected", [
    ("1:0", (1, None)), ("0:15", (0, 15)), (3, (3, None)), ("", (None, None)),
    (None, (None, None)), ("x:y", (None, None)), (True, (None, None)),
])
def test_parse_exit_code(raw, expected):
    assert es.parse_exit_code(raw) == expected


# ----------------------------------------------------------------------
# redaction + bounds
# ----------------------------------------------------------------------

PRIVATE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "-----END OPENSSH PRIVATE KEY-----"
)

SECRETS = {
    "private key": PRIVATE_KEY,
    "aws key id": "credentials AKIAIOSFODNN7EXAMPLE were rejected",
    "aws temp key id": "ASIAY34FZKBOKMUTVV7A expired",
    "aws secret": "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "bare aws secret": "got wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY back",
    "password": "login failed password=hunter2-correct",
    "token": "relay token: 6f1c0e2a9b",
    "bearer": "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig",
    "url creds": "fetch https://alice:s3cretpw@example.org/x failed",
    "license": "MLM_LICENSE_FILE 27000@license.example.edu unreachable",
    "session": "session_secret=abcdef123456",
    "long token": "id " + "Q" * 20 + "a1" * 15,
}

SECRET_VALUES = (
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU", "AKIAIOSFODNN7EXAMPLE", "ASIAY34FZKBOKMUTVV7A",
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "hunter2-correct", "6f1c0e2a9b",
    "eyJhbGciOiJIUzI1NiJ9", "s3cretpw", "27000@license.example.edu", "abcdef123456",
    "Q" * 20 + "a1" * 15,
)


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_redact_secrets_removes_each_secret_form(name):
    text = es.redact_secrets(SECRETS[name])
    for value in SECRET_VALUES:
        assert value not in text, (name, text)


def test_redaction_keeps_ordinary_paths_and_bounds_length():
    path = "/storage/home/hcoda1/1/researcher/scratch/icesee-runs/run-20261011"
    assert es.redact_secrets(f"wrote {path}") == f"wrote {path}"
    assert len(es.redact_secrets("word " * 1000, limit=100)) == 100
    assert es.redact_secrets("\x1b[31mred\x1b[0m\x07") == "red"


def test_sanitize_failure_allowlists_redacts_and_bounds():
    raw = {
        "scheduler": "slurm",
        "state": "out_of_memory; rm -rf",
        "exit_code": 137,
        "signal": 9,
        "reason": "oom " + SECRETS["aws secret"] + " " + "r" * 1000,
        "log_tail": [f"line {i} password=pw{i}" for i in range(50)] + [PRIVATE_KEY],
        "stdout": "whole scheduler output",
        "host": "login.example.edu",
        "nested": {"token": "abc"},
    }
    failure = es.sanitize_failure(raw)
    assert set(failure) == {"scheduler", "state", "exit_code", "signal", "reason", "log_tail"}
    assert failure["state"] == "OUT_OF_MEMORYRMRF"[:32]
    assert len(failure["reason"]) <= es.FAILURE_REASON_LIMIT
    assert len(failure["log_tail"]) == es.FAILURE_LOG_LINES
    assert all(len(line) <= es.FAILURE_LOG_LINE_LIMIT for line in failure["log_tail"])
    text = json.dumps(failure)
    for value in SECRET_VALUES + ("pw49", "whole scheduler output", "login.example.edu"):
        assert value not in text
    assert es.sanitize_failure("TIMEOUT") is None
    assert es.sanitize_failure({"scheduler": "slurm"}) is None
    assert es.sanitize_failure({"scheduler": "pbs", "state": "X", "exit_code": True}) == {"state": "X"}


def test_failure_message_is_one_line():
    assert es.failure_message(None) is None
    assert es.failure_message({"state": "TIMEOUT", "exit_code": 0, "signal": 15,
                               "reason": "limit"}) == "TIMEOUT, exit 0 (signal 15): limit"
    assert es.failure_message({"reason": "only"}) == "only"


# ----------------------------------------------------------------------
# scientific / resource overview
# ----------------------------------------------------------------------

ICESEE_CONFIGURATION = {
    "execution_mode": "remote", "example": "lorenz96", "preset": "quick",
    "filter": "EnKF", "ensemble_size": 30, "output": "", "report_generation": False,
    "remote": {"access_mode": "connector", "backend": "native", "cluster": "pace",
               "host": "login.example.edu", "port": 22,
               "remote_base_dir": "/storage/home/u/icesee", "remote_tag": "t"},
    "slurm": {"job_name": "icesee", "time": "02:00:00", "nodes": 2, "tasks": 64,
              "tasks_per_node": 32, "partition": "cpu-small", "memory": "8G",
              "account": "gts-secret-alloc"},
}


def test_overview_reads_icesee_configuration_without_inventing_usage():
    overview = es.experiment_overview(
        ICESEE_CONFIGURATION, {"execution_mode": "remote", "filter": "EnKF"})
    assert overview["filter"] == "EnKF" and overview["ensemble_size"] == 30
    assert overview["preset"] == "quick" and overview["example"] == "lorenz96"
    assert overview["execution_mode"] == "remote"
    assert overview["requested"] == {
        "nodes": 2, "tasks": 64, "tasks_per_node": 32, "mpi_ranks": 64,
        "partition": "cpu-small", "time": "02:00:00", "memory": "8G"}
    assert overview["measured"] is None
    # no allocation, host or remote directory in the overview
    text = json.dumps(overview)
    for value in ("gts-secret-alloc", "login.example.edu", "/storage/home/u"):
        assert value not in text


def test_overview_mpi_ranks_fallback_and_measured_only_when_recorded():
    overview = es.experiment_overview(
        {"slurm": {"nodes": "3", "tasks_per_node": "4"}},
        {"measured_resources": {"elapsed_seconds": 120, "max_rss_mib": 900.5,
                                "cpu_seconds": "lots", "note": "x"}})
    assert overview["requested"]["mpi_ranks"] == 12
    assert overview["measured"] == {"elapsed_seconds": 120, "max_rss_mib": 900.5}
    cloud = es.experiment_overview({}, {"cloud": {"vcpu": 4, "memory_mib": 16384},
                                        "measured_resources": None})
    assert cloud["requested"] == {"vcpu": 4, "memory_mib": 16384}
    assert cloud["measured"] is None
    assert es.experiment_overview(None, None)["requested"] == {}


def test_record_metadata_fills_missing_facts_and_never_overwrites():
    metadata = es.record_metadata(ICESEE_CONFIGURATION, {
        "execution_mode": "remote", "filter": "DEnKF", "access_mode": "connector"})
    assert metadata["filter"] == "DEnKF"              # the application's value wins
    assert metadata["ensemble_size"] == 30            # filled from the snapshot
    assert metadata["preset"] == "quick" and metadata["example"] == "lorenz96"
    assert metadata["requested_resources"]["mpi_ranks"] == 64
    assert metadata["access_mode"] == "connector"
    assert es.record_metadata({}, None) == {}


# ----------------------------------------------------------------------
# the browser bridge
# ----------------------------------------------------------------------

def _commands(bridge):
    html = bridge.output.value
    encoded = [part.split('"', 1)[0]
               for part in html.split('data-cryostack-command="')[1:]]
    return [json.loads(base64.b64decode(item)) for item in encoded if item]


def test_bridge_keeps_recent_commands_so_quick_updates_are_not_lost():
    from icesee_jupyter_book.ui.experiment_bridge import PENDING_COMMANDS, ExperimentBridge

    bridge = ExperimentBridge()
    bridge.create(application="icesee", name="ICESEE EnKF run", backend="native",
                  configuration=ICESEE_CONFIGURATION, status="running", job_id="101",
                  metadata={"execution_mode": "remote", "filter": "EnKF"})
    bridge.update_by_job(job_id="101", status="failed")
    commands = _commands(bridge)
    assert [c["action"] for c in commands] == ["create", "update-by-job"]
    assert len({c["message_id"] for c in commands}) == 2
    created = commands[0]["payload"]
    assert created["metadata"]["ensemble_size"] == 30
    assert created["metadata"]["requested_resources"]["nodes"] == 2
    for i in range(PENDING_COMMANDS + 3):
        bridge.update_by_job(job_id="101", status="running")
    assert len(_commands(bridge)) == PENDING_COMMANDS
