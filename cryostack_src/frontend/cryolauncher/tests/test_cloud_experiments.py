"""Cloud runs enter the shared experiment record (Control Center execution
records), with non-secret identity and requested -- not measured -- resources."""
import json

from cryostack_src.frontend.cryolauncher import cloud_run_controller as crc
from cryostack_src.frontend.cryolauncher.cloud_experiments import (
    CloudExperimentRecorder,
    cloud_experiment_record,
    experiment_status,
    masked_account,
)


class _Bridge:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(("create", kw))

    def update_by_job(self, **kw):
        self.calls.append(("update", kw))


def _handle(**over):
    h = crc._RunHandle(job_id="job-123", s3_run="s3://bucket/u/run-1", run_id="run-1",
                       model="issm", region="us-east-2", account_id="774888247882",
                       example="square", run_target="runme.m", vcpu=4, memory_gib=16,
                       expected_runtime_minutes=30, image_label="issm 4.24",
                       image_digest="sha256:abc")
    for k, v in over.items():
        setattr(h, k, v)
    return h


def test_record_carries_identity_and_requested_resources_only():
    record = cloud_experiment_record(_handle(), result_metadata={
        "job_queue": "cryostack-fargate", "job_definition": "cryostack-issm"},
        configuration={"model": "issm"})
    assert record["backend"] == "aws" and record["job_id"] == "job-123"
    assert record["status"] == "queued" and record["cluster"] == "aws-batch"
    assert record["output_directory"] == "s3://bucket/u/run-1/outputs"
    meta = record["metadata"]
    assert meta["aws_account"] == "****7882"
    assert meta["cloud"] == {"region": "us-east-2", "job_queue": "cryostack-fargate",
                             "job_definition": "cryostack-issm", "vcpu": 4, "memory_mib": 16384}
    assert meta["measured_resources"] is None
    # the Control Center shows it as a cloud execution with requested resources
    from control_center.services.compute import _execution_view
    view = _execution_view({"id": "e1", "backend": "aws", "status": "queued",
                            "configuration_snapshot_json": json.dumps(record["configuration"]),
                            "metadata_json": json.dumps(meta), "created_at": 0},
                           now=10, last_failure=None)
    assert view["target"] == "cloud"
    assert view["resources"]["vcpu"] == "4" and view["resources"]["memory_mib"] == "16384"
    assert view["resources"]["job_queue"] == "cryostack-fargate"
    text = json.dumps(record)
    assert "774888247882" not in text
    for word in ("secret", "token", "credential", "externalid", "password"):
        assert word not in text.lower()


def test_controller_states_map_to_experiment_statuses():
    assert experiment_status(crc.STAGING) is None and experiment_status(crc.SUBMITTING) is None
    assert [experiment_status(s) for s in (crc.QUEUED, crc.RUNNING, crc.COMPLETED,
                                           crc.FAILED, crc.CANCELLED)] == [
        "queued", "running", "completed", "failed", "cancelled"]
    assert masked_account("") == "" and masked_account("12") == ""


def test_recorder_sends_each_status_once_and_only_for_recorded_jobs():
    bridge, job = _Bridge(), {"id": ""}
    recorder = CloudExperimentRecorder(bridge, job_id=lambda: job["id"])
    recorder.state(crc.RUNNING)                      # nothing submitted yet
    job["id"] = "job-123"
    recorder.state(crc.RUNNING)                      # not created: ignored
    recorder.created(cloud_experiment_record(_handle()))
    for state in (crc.QUEUED, crc.RUNNING, crc.RUNNING, crc.COMPLETED, crc.COMPLETED):
        recorder.state(state)
    assert [c[0] for c in bridge.calls] == ["create", "update", "update"]
    assert [c[1]["status"] for c in bridge.calls[1:]] == ["running", "completed"]
    assert all(c[1]["job_id"] == "job-123" for c in bridge.calls[1:])


def test_recorder_reports_failure_once_with_a_redacted_summary():
    from cryostack_src.frontend.cryolauncher.cloud_experiments import cloud_status_update

    bridge = _Bridge()
    reason = {"text": "Essential container exited; token=abc123def AKIAIOSFODNN7EXAMPLE"}
    recorder = CloudExperimentRecorder(bridge, job_id=lambda: "job-123",
                                       reason=lambda: reason["text"])
    recorder.created(cloud_experiment_record(_handle()))
    for state in (crc.RUNNING, crc.FAILED, crc.FAILED, crc.RUNNING, crc.COMPLETED):
        recorder.state(state)
    updates = [c[1] for c in bridge.calls if c[0] == "update"]
    assert [u["status"] for u in updates] == ["running", "failed"]   # nothing after terminal
    failure = updates[1]["failure"]
    assert failure["scheduler"] == "aws-batch" and failure["state"] == "FAILED"
    assert "Essential container exited" in failure["reason"]
    text = json.dumps(updates)
    assert "abc123def" not in text and "AKIAIOSFODNN7EXAMPLE" not in text
    assert updates[1]["error_message"].startswith("FAILED: Essential container exited")
    # raw AWS Batch statuses map the same way; pre-job states send nothing
    assert cloud_status_update("SUCCEEDED") == {"status": "completed"}
    assert cloud_status_update("RUNNABLE") == {"status": "queued"}
    assert cloud_status_update(crc.STAGING) is None
    assert cloud_status_update(crc.CANCELLED)["failure"]["state"] == "CANCELLED"


def test_reattached_run_is_not_recreated_and_only_new_states_are_sent():
    bridge = _Bridge()
    recorder = CloudExperimentRecorder(bridge, job_id=lambda: "job-9")
    recorder.state(crc.RUNNING)          # attach() replays the manifest state
    recorder.state(crc.RUNNING)
    recorder.state(crc.COMPLETED)        # the next poll observes the end
    recorder.state(crc.COMPLETED)
    assert bridge.calls == [("update", {"job_id": "job-9", "status": "completed"})]
    # an attach of an already-terminal run sends nothing at all
    done = _Bridge()
    recorder = CloudExperimentRecorder(done, job_id=lambda: "job-10")
    recorder.state(crc.FAILED)
    assert done.calls == []
