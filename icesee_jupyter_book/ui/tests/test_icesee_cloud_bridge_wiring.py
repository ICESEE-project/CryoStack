"""ICESEE Cloud tab now submits/polls/terminates through the hardened
CloudBridge adapter (icesee_jupyter_book/core/cloud_bridge_adapter.py)
instead of calling core/cloud_runner.py's functions directly -- Step 4 of
the ICESEE<->CryoLauncher cloud convergence
(overnight/AUDIT_icesee_cloud_convergence.md). No real AWS CLI is invoked:
every test patches the lowest real boundary
(cryostack_src.cloud.legacy.aws_batch's ``subprocess``), the same pattern
cryostack_src/cloud/tests/test_aws_batch_legacy_credentials.py uses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ipywidgets as W

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_GW = _REPO / "icesee_jupyter_book/ui/icesee_gateway.py"


def test_gateway_uses_the_cloud_bridge_adapter_not_the_legacy_functions_directly():
    src = _GW.read_text()
    assert "from icesee_jupyter_book.core.cloud_bridge_adapter import" in src
    assert "build_icesee_cloud_bridge(" in src
    assert "submit_icesee_cloud_run(" in src
    assert "icesee_cloud_status(" in src
    assert "icesee_cloud_terminate(" in src
    # the legacy entry points are no longer imported into the gateway --
    # they still exist and are exercised THROUGH the adapter
    assert "from icesee_jupyter_book.core.cloud_runner import" not in src
    assert "cloud_terminate_btn" in src   # a genuinely new capability


class _FakeCompleted:
    def __init__(self, stdout):
        self.returncode, self.stdout, self.stderr = 0, stdout, ""


def _build_gateway(monkeypatch, tmp_path, *, user):
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_USER", user)
    monkeypatch.setenv("USER", f"{user}-svc")
    monkeypatch.setenv("CRYOSTACK_WORKSPACE_ROOT", str(tmp_path))
    import matplotlib
    matplotlib.use("Agg")
    from icesee_jupyter_book.ui.icesee_gateway import build_icesee_ui
    return build_icesee_ui()


def _find_button(page, description, *, icon=None):
    found = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == description:
            if icon is None or getattr(w, "icon", "") == icon:
                found.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found[0] if found else None


def _freevar(fn, name):
    idx = fn.__code__.co_freevars.index(name)
    return fn.__closure__[idx].cell_contents


def _select_cloud_mode(page):
    mode_tabs = None

    def walk(w):
        nonlocal mode_tabs
        if isinstance(w, W.Tab) and mode_tabs is None:
            mode_tabs = w
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    mode_tabs.selected_index = 2   # Cloud
    return mode_tabs


def test_cloud_submit_reaches_batch_submit_job_with_the_documented_env_vars(
    monkeypatch, tmp_path, capsys,
):
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "get-caller-identity" in argv:
                return _FakeCompleted('{"Account": "1"}')
            if "submit-job" in argv:
                return _FakeCompleted(json.dumps({"jobId": "job-xyz"}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-submit-user")
    _select_cloud_mode(page)
    submit_btn = _find_button(page, "Launch cloud run")
    assert submit_btn is not None
    click_handler = submit_btn._click_handlers.callbacks[0]
    handler = _freevar(click_handler, "run_example_cloud_submit")

    aws_region = _freevar(handler, "aws_region")
    cloud_bucket = _freevar(handler, "cloud_bucket")
    batch_job_queue = _freevar(handler, "batch_job_queue")
    batch_job_def = _freevar(handler, "batch_job_def")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"

    capsys.readouterr()
    handler()
    printed = capsys.readouterr().out
    assert "[cloud][ERROR]" not in printed

    submit_call = next(c for c in calls if "submit-job" in c)
    overrides = json.loads(submit_call[submit_call.index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_S3_RUN"].startswith("s3://bucket/runs/")
    assert "ICESEE_EXAMPLE" in env and "ICESEE_RUN_SCRIPT" in env

    STATUS = _freevar(handler, "STATUS")
    assert STATUS["batch_job_id"] == "job-xyz"
    assert STATUS["s3_run"] == env["ICESEE_S3_RUN"]
    assert Path(STATUS["local_run_dir"]).is_dir()
    assert (Path(STATUS["local_run_dir"]) / ".cryostack-run.json").is_file()


def test_cloud_status_and_terminate_flow_through_the_hardened_driver(
    monkeypatch, tmp_path, capsys,
):
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "describe-jobs" in argv:
                return _FakeCompleted(json.dumps(
                    {"jobs": [{"status": "RUNNING", "statusReason": ""}]}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-status-user")
    _select_cloud_mode(page)

    status_btn = _find_button(page, "Check status", icon="search")
    status_click = status_btn._click_handlers.callbacks[0]
    status_handler = _freevar(status_click, "run_example_cloud_status")
    STATUS = _freevar(status_handler, "STATUS")
    STATUS["batch_job_id"] = "job-123"

    capsys.readouterr()
    status_handler()
    printed = capsys.readouterr().out
    assert "RUNNING" in printed
    assert any("describe-jobs" in c for c in calls)

    terminate_btn = _find_button(page, "Terminate cloud job")
    assert terminate_btn is not None
    terminate_click = terminate_btn._click_handlers.callbacks[0]
    terminate_handler = _freevar(terminate_click, "run_example_cloud_terminate")
    capsys.readouterr()
    terminate_handler()
    printed = capsys.readouterr().out
    assert "[cloud][ERROR]" not in printed
    assert any("cancel-job" in c or "terminate-job" in c for c in calls)


def test_cloud_terminate_with_no_job_id_yet_is_a_clean_noop(monkeypatch, tmp_path, capsys):
    page = _build_gateway(monkeypatch, tmp_path, user="cloud-terminate-noop-user")
    _select_cloud_mode(page)
    terminate_btn = _find_button(page, "Terminate cloud job")
    click_handler = terminate_btn._click_handlers.callbacks[0]
    handler = _freevar(click_handler, "run_example_cloud_terminate")

    capsys.readouterr()
    handler()
    printed = capsys.readouterr().out
    assert "No Batch job id yet" in printed


def test_cloud_submit_and_status_populate_aws_resources_for_the_shared_diagnostics_menu(
    monkeypatch, tmp_path,
):
    """The Runs panel (build_workspace_history_panel, reused verbatim since
    the Workspace-shell checkpoint) already renders an AWS diagnostics menu
    from run.metadata['aws_resources'] for any run, model-agnostic. ICESEE
    cloud runs must populate it too, growing it (never overwriting a known
    value with an empty one) as status polls learn more."""
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch
    from cryostack_src.workspace import read_manifest
    from icesee_jupyter_book.core.run_records import MANIFEST_NAME

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            if "get-caller-identity" in argv:
                return _FakeCompleted('{"Account": "1"}')
            if "submit-job" in argv:
                return _FakeCompleted(json.dumps({"jobId": "job-xyz"}))
            if "describe-jobs" in argv:
                return _FakeCompleted(json.dumps({"jobs": [{
                    "status": "RUNNING", "statusReason": "",
                    "container": {"logStreamName": "stream-1", "taskArn": "arn:aws:ecs:x"},
                }]}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-diagnostics-user")
    _select_cloud_mode(page)

    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    submit_handler = _freevar(submit_click, "run_example_cloud_submit")
    aws_region = _freevar(submit_handler, "aws_region")
    cloud_bucket = _freevar(submit_handler, "cloud_bucket")
    batch_job_queue = _freevar(submit_handler, "batch_job_queue")
    batch_job_def = _freevar(submit_handler, "batch_job_def")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"
    submit_handler()

    STATUS = _freevar(submit_handler, "STATUS")
    manifest_path = Path(STATUS["local_run_dir"]) / MANIFEST_NAME
    resources = read_manifest(manifest_path).metadata["aws_resources"]
    assert resources["region"] == "us-east-2"
    assert resources["batch_job_id"] == "job-xyz"
    assert resources["job_queue"] == "q"
    assert resources["job_definition"] == "jd"

    status_click = _find_button(page, "Check status", icon="search")._click_handlers.callbacks[0]
    status_handler = _freevar(status_click, "run_example_cloud_status")
    status_handler()

    resources = read_manifest(manifest_path).metadata["aws_resources"]
    assert resources["log_stream"] == "stream-1"
    assert resources["task_arn"] == "arn:aws:ecs:x"
    # earlier values survive -- the merge grows the snapshot, never clobbers it
    assert resources["batch_job_id"] == "job-xyz"
    assert resources["job_queue"] == "q"


def _patch_matlab_license(monkeypatch, *, configured, requires_tunnel):
    """Patch CloudExecution.matlab_license itself (not
    resolve_cloud_matlab_license) -- in developer mode (no BYO connection,
    the test environment here) CloudExecution.matlab_license short-circuits
    on ``self.connection is None`` before ever calling the resolver, so the
    property itself is the only seam that reaches every caller."""
    import cryostack_src.cloud.matlab_license as ml
    from cryostack_src.cloud.connect.execution import CloudExecution

    fake = ml.CloudMatlabLicense(
        configured=configured,
        mechanism="secrets-manager" if configured else "none",
        secret_arn=("arn:aws:secretsmanager:us-east-2:774888247882:secret:"
                    "cryostack/issm-matlab-Ab1" if configured else ""),
        requires_tunnel=requires_tunnel,
    )
    monkeypatch.setattr(CloudExecution, "matlab_license", property(lambda self: fake))
    return fake


def _capture_icesee_submit(monkeypatch, tmp_path, *, user):
    """Build the real ICESEE gateway, intercept the module-level
    submit_icesee_cloud_run(...) call (the ICESEE analogue of the
    icesheets gateway's `_cloud["controller"].submit(...)`), and return
    the captured kwargs -- never contacting AWS."""
    import icesee_jupyter_book.ui.icesee_gateway as gw

    page = _build_gateway(monkeypatch, tmp_path, user=user)
    _select_cloud_mode(page)
    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    handler = _freevar(submit_click, "run_example_cloud_submit")

    aws_region = _freevar(handler, "aws_region")
    cloud_bucket = _freevar(handler, "cloud_bucket")
    batch_job_queue = _freevar(handler, "batch_job_queue")
    batch_job_def = _freevar(handler, "batch_job_def")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"

    captured = {}

    class _FakeResult:
        job_id = "job-abc"
        working_directory = "s3://bucket/runs/r1"
        messages = []

    def fake_submit(*args, **kwargs):
        captured.update(kwargs)
        return _FakeResult()

    monkeypatch.setattr(gw, "submit_icesee_cloud_run", fake_submit)
    handler()
    return captured


def test_issm_requiring_icesee_workflow_passes_matlab_license_requires_tunnel_true(
    monkeypatch, tmp_path,
):
    """An ICESEE run whose forecast model is ISSM must propagate the SAME
    already-resolved CloudMatlabLicense capability a direct ISSM run does
    (resolve_workflow_capabilities is the single source of "requires
    MATLAB" -- confirmed here for context; the propagation itself is
    connection-scoped, not model-conditional, exactly like icesheets_gateway.py)."""
    from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities

    caps = resolve_workflow_capabilities(model="icesee", forecast_model="issm")
    assert caps.requires_matlab_license is True

    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=True)
    captured = _capture_icesee_submit(monkeypatch, tmp_path, user="icesee-issm-tunnel-user")

    assert captured["matlab_license_configured"] is True
    assert captured["matlab_license_requires_tunnel"] is True


def test_non_matlab_icesee_workflow_does_not_require_the_tunnel(monkeypatch, tmp_path):
    """The default ICESEE example (lorenz96, non-MATLAB) with no license
    configured on the connection -- requires_tunnel must stay False."""
    captured = _capture_icesee_submit(monkeypatch, tmp_path, user="icesee-no-tunnel-user")

    assert captured["matlab_license_configured"] is False
    assert captured["matlab_license_requires_tunnel"] is False


def test_icesee_matlab_license_configured_flag_is_unchanged_by_tunnel_propagation(
    monkeypatch, tmp_path,
):
    """matlab_license_configured reflects only whether a license secret is
    configured, independent of requires_tunnel -- the two fields come from
    one resolved object without being coupled to each other."""
    _patch_matlab_license(monkeypatch, configured=True, requires_tunnel=False)
    captured = _capture_icesee_submit(monkeypatch, tmp_path, user="icesee-configured-only-user")

    assert captured["matlab_license_configured"] is True
    assert captured["matlab_license_requires_tunnel"] is False


def test_cloud_submit_threads_mpi_ensemble_params_into_the_container_env(
    monkeypatch, tmp_path,
):
    """Same NP/Nens/model_nprocs contract Remote's SLURM template
    unconditionally threads into mpirun -- sourced from the SAME widgets
    Remote already exposes, no new UI."""
    import cryostack_src.cloud.legacy.aws_batch as legacy_batch

    calls = []

    class _FakeSubprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append(argv)
            if "get-caller-identity" in argv:
                return _FakeCompleted('{"Account": "1"}')
            if "submit-job" in argv:
                return _FakeCompleted(json.dumps({"jobId": "job-mpi"}))
            return _FakeCompleted("")

    monkeypatch.setattr(legacy_batch, "subprocess", _FakeSubprocess)

    page = _build_gateway(monkeypatch, tmp_path, user="cloud-mpi-user")
    _select_cloud_mode(page)
    submit_click = _find_button(page, "Launch cloud run")._click_handlers.callbacks[0]
    submit_handler = _freevar(submit_click, "run_example_cloud_submit")

    aws_region = _freevar(submit_handler, "aws_region")
    cloud_bucket = _freevar(submit_handler, "cloud_bucket")
    batch_job_queue = _freevar(submit_handler, "batch_job_queue")
    batch_job_def = _freevar(submit_handler, "batch_job_def")
    cluster_mpi_np = _freevar(submit_handler, "cluster_mpi_np")
    cluster_model_nprocs = _freevar(submit_handler, "cluster_model_nprocs")
    ens_sl = _freevar(submit_handler, "ens_sl")
    aws_region.value = "us-east-2"
    cloud_bucket.value = "s3://bucket/runs"
    batch_job_queue.value = "q"
    batch_job_def.value = "jd"
    cluster_mpi_np.value = 8
    cluster_model_nprocs.value = 2
    ens_sl.value = 20

    submit_handler()

    submit_call = next(c for c in calls if "submit-job" in c)
    overrides = json.loads(submit_call[submit_call.index("--container-overrides") + 1])
    env = {e["name"]: e["value"] for e in overrides["environment"]}
    assert env["ICESEE_NP"] == "8"
    assert env["ICESEE_MODEL_NPROCS"] == "2"
    assert env["ICESEE_NENS"] == "20"


# ── INSTITUTIONAL CONNECTION: Cloud reuses the SAME Connector Remote uses ──
def _find_buttons(page, description):
    found = []

    def walk(w):
        if isinstance(w, W.Button) and getattr(w, "description", "") == description:
            found.append(w)
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found


def _icesee_cloud_environment(page):
    review_btn = _find_button(page, "Review & Launch", icon="clipboard-check")
    click = review_btn._click_handlers.callbacks[0]
    build_review = _freevar(click, "_icesee_build_review")
    return _freevar(build_review, "icesee_cloud_environment")


def _icesee_update_run_plan(page):
    """The freevar chain to _update_icesee_run_plan_summary -- found via a
    widget it observes (example_dd), the same trick _find_widget_by_observer
    uses elsewhere in this repo's gateway tests."""
    found = {}

    def walk(w):
        if "fn" not in found:
            notifiers = getattr(w, "_trait_notifiers", None)
            if notifiers and "value" in notifiers:
                for handlers in notifiers["value"].values():
                    for h in handlers:
                        if getattr(h, "__name__", "") == "_update_icesee_run_plan_summary":
                            found["fn"] = h
        for c in getattr(w, "children", ()):
            walk(c)

    walk(page)
    return found.get("fn")


def _remote_open_connector_handler(page, cloud_environment):
    candidates = [
        b for b in _find_buttons(page, "Open Connector...")
        if b is not cloud_environment.institutional_connection_open_button
    ]
    assert len(candidates) == 1, "expected exactly one Remote Open Connector... button"
    btn = candidates[0]
    return btn, btn._click_handlers.callbacks[0]


def _remote_disconnect_handler(page, cloud_environment):
    candidates = [
        b for b in _find_buttons(page, "Disconnect")
        if b is not cloud_environment.institutional_connection_disconnect_button
        and b is not cloud_environment.disconnect_button
    ]
    assert len(candidates) == 1, "expected exactly one Remote Disconnect button"
    btn = candidates[0]
    return btn, btn._click_handlers.callbacks[0]


def test_institutional_connection_hidden_for_a_non_issm_icesee_workflow(monkeypatch, tmp_path):
    """Must remain hidden for Icepack-only / other workflows that do not
    require private institutional license connectivity -- ICESEE's own
    default (lorenz96) forecast model is non-MATLAB."""
    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-hidden-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)
    update_run_plan = _icesee_update_run_plan(page)
    update_run_plan()
    assert ce.institutional_connection_box.layout.display == "none"


def test_institutional_connection_shown_for_an_issm_forecast_icesee_workflow(
    monkeypatch, tmp_path,
):
    """Shown only when the resolved workflow/license capability requires
    it -- an ICESEE run whose forecast model is ISSM at a site whose
    CloudMatlabLicense.requires_tunnel is True (PACE)."""
    import icesee_jupyter_book.ui.icesee_gateway as gw
    from icesee_jupyter_book.core.run_records import DAIdentity

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-shown-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)
    update_run_plan = _icesee_update_run_plan(page)

    monkeypatch.setattr(
        gw, "da_identity_from_params",
        lambda cfg: DAIdentity(forecast_model="issm"),
    )
    update_run_plan()
    assert ce.institutional_connection_box.layout.display == ""


def test_remote_and_cloud_open_connector_share_the_exact_same_handler_icesee(
    monkeypatch, tmp_path,
):
    """No second Connector implementation, pairing, identity, or session:
    ICESEE Cloud's Open Connector... action is literally the SAME function
    object Remote's own button calls."""
    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-shared-open-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    _remote_btn, remote_handler = _remote_open_connector_handler(page, ce)
    cloud_open_click = ce.institutional_connection_open_button._click_handlers.callbacks[0]
    cloud_open_connector_fn = _freevar(cloud_open_click, "open_connector")
    assert cloud_open_connector_fn is remote_handler


def test_remote_and_cloud_disconnect_share_the_exact_same_handler_icesee(
    monkeypatch, tmp_path,
):
    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-shared-disc-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    _remote_btn, remote_handler = _remote_disconnect_handler(page, ce)
    cloud_disc_click = ce.institutional_connection_disconnect_button._click_handlers.callbacks[0]
    cloud_disconnect_fn = _freevar(cloud_disc_click, "disconnect")
    assert cloud_disconnect_fn is remote_handler


def test_pairing_in_remote_is_immediately_reflected_in_cloud_icesee(monkeypatch, tmp_path):
    """pair in Remote -> Cloud immediately recognizes the same Connector."""
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-pair-remote-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, _handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()

    assert "connected" in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_open_button.layout.display == "none"
    assert ce.institutional_connection_disconnect_button.layout.display != "none"


def test_disconnect_in_cloud_is_immediately_reflected_in_remote_icesee(monkeypatch, tmp_path):
    """disconnecting/revoking the Connector updates both views consistently."""
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )
    cleared = {"called": False}
    monkeypatch.setattr(
        gw, "clear_connector_binding", lambda: cleared.__setitem__("called", True))

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-disc-cloud-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, remote_handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()
    assert "connected" in ce.institutional_connection_status.value.lower()

    SESSION = _freevar(remote_handler, "SESSION")
    relay_status = _freevar(remote_handler, "relay_status")
    assert SESSION.get("id") == "sess-1"

    ce.institutional_connection_disconnect_button.click()

    assert cleared["called"] is True
    assert SESSION.get("id") is None
    assert relay_status.value == ""
    assert "not connected" in ce.institutional_connection_status.value.lower()


def test_no_duplicate_pairing_session_is_created_icesee(monkeypatch, tmp_path):
    """Exactly ONE Connector session, reused by both Remote and Cloud."""
    import icesee_jupyter_book.ui.icesee_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-1", "ws_url": "/x", "pairing_code": "AB12"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-no-dup-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, _handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()
    ce.institutional_connection_recheck_button.click()

    assert calls["n"] == 1


def test_institutional_connection_never_leaks_implementation_details_icesee(
    monkeypatch, tmp_path,
):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-abc123", "ws_url": "/connector/ws/sess-abc123",
            "pairing_code": "XZ99"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-no-leak-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, _handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()

    def _all_widgets(widget):
        out = [widget]

        def walk(w):
            for c in getattr(w, "children", ()):
                out.append(c)
                walk(c)

        walk(widget)
        return out

    blob = "\n".join([
        ce.institutional_connection_status.value,
        "\n".join(w.value for w in _all_widgets(ce.institutional_connection_box)
                   if isinstance(w, W.HTML)),
    ]).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "session id", "token", "flexnet",
        "vendor", "mlm_license_file", "secrets manager",
    ):
        assert forbidden not in blob, forbidden
    # Cloud never renders the technical diagnostics (session id / ws path)
    # at all -- those stay confined to Remote's own Advanced accordion.
    # (The pairing-page link's href necessarily carries the opaque session
    # id as a URL parameter -- the same accepted, already-tested Remote
    # behaviour -- that is a navigation target, never a readable label.)
    assert "/connector/ws" not in blob


def test_existing_remote_controls_are_preserved_icesee(monkeypatch, tmp_path):
    """Restore the Remote Connector UI: the established compact controls
    remain present and reachable in the ICESEE gateway too."""
    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-preserve-user")

    def _all_widgets(widget):
        out = [widget]

        def walk(w):
            for c in getattr(w, "children", ()):
                out.append(c)
                walk(c)

        walk(widget)
        return out

    html = "\n".join(w.value for w in _all_widgets(page) if isinstance(w, W.HTML))
    assert "Compute resource" in html
    assert "Your HPC identity" in html
    assert "Access" in html
    assert "Status" in html

    buttons = [w for w in _all_widgets(page) if isinstance(w, W.Button)]
    assert any(b.description == "Check SSH Access" for b in buttons)
    assert any(b.description == "Open Connector..." for b in buttons)


def test_preflight_blocks_review_launch_when_connector_required_but_not_paired_icesee(
    monkeypatch, tmp_path,
):
    """If institutional connectivity is required and no Connector is
    currently paired, ICESEE Cloud launch must remain blocked before AWS
    submission -- the existing fail-closed build_icesee_cloud_review gate."""
    import icesee_jupyter_book.ui.icesee_gateway as gw
    from icesee_jupyter_book.core.run_records import DAIdentity

    monkeypatch.setattr(
        gw, "da_identity_from_params", lambda cfg: DAIdentity(forecast_model="issm"))

    class _FakeMatlabLicense:
        configured = True
        requires_tunnel = True

    class _FakeExecution:
        is_byo = False
        account_id = ""
        region = "us-east-2"
        profile = None
        credentials = None
        defaults = None
        matlab_license = _FakeMatlabLicense()

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-preflight-user")
    _select_cloud_mode(page)
    review_btn = _find_button(page, "Review & Launch", icon="clipboard-check")
    click = review_btn._click_handlers.callbacks[0]
    build_review_fn = _freevar(click, "_icesee_build_review")

    monkeypatch.setattr(
        gw, "build_icesee_cloud_bridge",
        lambda cfg: type("B", (), {"check_environment": lambda self: None})())

    # _resolve_icesee_cloud_execution is itself a closure -- patch what it
    # calls (resolve_cloud_execution) so the fake, requires_tunnel=True
    # license flows through the real build_icesee_cloud_review call.
    import cryostack_src.cloud.connect as connect_mod
    monkeypatch.setattr(connect_mod, "resolve_cloud_execution", lambda **kw: _FakeExecution())

    review = build_review_fn()
    assert review.can_launch is False
    assert any("CryoStack Connector" in r for r in review.blocked_reasons)


# ── Cloud completes the ENTIRE compact pairing flow itself (ICESEE) ──────
def test_pairing_initiated_entirely_from_cloud_icesee(monkeypatch, tmp_path):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-cloud-1", "ws_url": "/x", "pairing_code": "QR77"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-pair-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()

    assert calls["n"] == 1
    open_click = ce.institutional_connection_open_button._click_handlers.callbacks[0]
    open_connector_fn = _freevar(open_click, "open_connector")
    SESSION = _freevar(open_connector_fn, "SESSION")
    assert SESSION.get("id") == "sess-cloud-1"


def test_cloud_displays_pairing_code_and_action_while_waiting_icesee(monkeypatch, tmp_path):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-wait-1", "ws_url": "/x", "pairing_code": "QR77"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-waiting-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()

    assert "waiting" in ce.institutional_connection_status.value.lower()
    assert "QR77" in ce.institutional_connection_pairing_info.value
    assert "session=sess-wait-1" in ce.institutional_connection_pairing_link.value
    assert "app=icesee" in ce.institutional_connection_pairing_link.value
    assert ce.institutional_connection_open_button.layout.display == "none"
    assert ce.institutional_connection_disconnect_button.layout.display != "none"


def test_successful_cloud_pairing_updates_cloud_to_connected_icesee(monkeypatch, tmp_path):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    online = {"value": False}
    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-succeed-1", "ws_url": "/x", "pairing_code": "QR77"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {
            "online": online["value"],
            "state": "connected" if online["value"] else "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-success-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()
    online["value"] = True
    ce.institutional_connection_recheck_button.click()

    assert "connected" in ce.institutional_connection_status.value.lower()
    assert ce.institutional_connection_pairing_info.value == ""
    assert ce.institutional_connection_pairing_link.value == ""


def test_cloud_created_pairing_is_immediately_recognized_by_remote_icesee(
    monkeypatch, tmp_path,
):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-cloud-2", "ws_url": "/x", "pairing_code": "MK55"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-to-remote-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()

    _remote_btn, remote_handler = _remote_open_connector_handler(page, ce)
    SESSION = _freevar(remote_handler, "SESSION")
    relay_status = _freevar(remote_handler, "relay_status")
    assert SESSION.get("id") == "sess-cloud-2"
    assert "connected" in relay_status.value.lower()


def test_remote_created_waiting_pairing_is_immediately_recognized_by_cloud_icesee(
    monkeypatch, tmp_path,
):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-remote-1", "ws_url": "/x", "pairing_code": "TT21"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-remote-to-cloud-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, _handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()

    assert "waiting" in ce.institutional_connection_status.value.lower()
    assert "TT21" in ce.institutional_connection_pairing_info.value


def test_disconnect_from_remote_updates_cloud_state_icesee(monkeypatch, tmp_path):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-rd-1", "ws_url": "/x", "pairing_code": "PP44"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": True, "state": "connected"},
    )
    monkeypatch.setattr(gw, "clear_connector_binding", lambda: None)

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-remote-disc-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    remote_btn, remote_handler = _remote_open_connector_handler(page, ce)
    remote_btn.click()
    assert "connected" in ce.institutional_connection_status.value.lower()

    remote_disconnect_btn, _h = _remote_disconnect_handler(page, ce)
    remote_disconnect_btn.click()

    SESSION = _freevar(remote_handler, "SESSION")
    assert SESSION.get("id") is None
    assert "not connected" in ce.institutional_connection_status.value.lower()


def test_repeated_open_connector_from_cloud_does_not_create_duplicate_sessions_icesee(
    monkeypatch, tmp_path,
):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    calls = {"n": 0}

    def fake_create_session(*, owner_user_id):
        calls["n"] += 1
        return {"session_id": "sess-nodup-1", "ws_url": "/x", "pairing_code": "ZZ00"}

    monkeypatch.setattr(gw, "create_session", fake_create_session)
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-nodup-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()
    ce.institutional_connection_recheck_button.click()
    ce.institutional_connection_recheck_button.click()

    assert calls["n"] == 1


def test_cloud_institutional_connection_box_stays_compact_icesee(monkeypatch, tmp_path):
    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-compact-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    children = list(ce.institutional_connection_box.children)
    assert len(children) == 6
    for expected in (
        ce.institutional_connection_status,
        ce.institutional_connection_pairing_info,
        ce.institutional_connection_pairing_link,
    ):
        assert expected in children


def test_cloud_waiting_state_terminology_hygiene_icesee(monkeypatch, tmp_path):
    import icesee_jupyter_book.ui.icesee_gateway as gw

    monkeypatch.setattr(
        gw, "create_session",
        lambda *, owner_user_id: {
            "session_id": "sess-hygiene-1", "ws_url": "/connector/ws/sess-hygiene-1",
            "pairing_code": "HY99"},
    )
    monkeypatch.setattr(
        gw, "relay_check_status",
        lambda session_id, force=False: {"online": False, "state": "waiting"},
    )

    page = _build_gateway(monkeypatch, tmp_path, user="icesee-inst-conn-cloud-hygiene-user")
    _select_cloud_mode(page)
    ce = _icesee_cloud_environment(page)

    ce.institutional_connection_open_button.click()

    def _all_widgets(widget):
        out = [widget]

        def walk(w):
            for c in getattr(w, "children", ()):
                out.append(c)
                walk(c)

        walk(widget)
        return out

    blob = "\n".join(w.value for w in _all_widgets(ce.institutional_connection_box)
                      if isinstance(w, W.HTML)).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "session id", "token", "flexnet",
        "vendor", "mlm_license_file", "secrets manager",
    ):
        assert forbidden not in blob, forbidden
    assert "/connector/ws" not in blob
