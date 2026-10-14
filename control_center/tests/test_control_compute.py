"""Control Center compute pages (HPC, Cloud): redaction, roles, rendering."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from control_center.services.compute import (
    ComputeService,
    MAX_LOG_LINES,
    execution_target,
    mask_account_id,
    redact_text,
    registered_resources,
    registry_log_sources,
)
from cryostack_src.resources.profiles import ComputeProfile, SchedulerDefaults


# Secret-like fixture values that must never appear in any response.
SECRETS = (
    "hunter2-pass",
    "AKIAZZZZYYYYXXXXWWWW",
    "synthetic-aws-secret-for-redaction-tests",
    "eyJhbGciOiJIUzI1NiJ9.payload.sig",
    "27000@license.example.edu",
    "1711@matlablic.ecs.gatech.edu",
    "210987654321",
    "123456789012",
    "jdoe-hpc-user",
    "gt-secret-allocation",
    "/storage/home/hcoda1/jdoe",
    "relay-control-token-value",
    "a1b2c3d4" * 8,
    "ExternalIdValue-123",
    "X-Amz-Signature",
)

PROFILE = ComputeProfile(
    name="testhpc",
    login_host="login.testhpc.example.edu",
    requires_vpn=True,
    supported_access_modes=("connector", "direct"),
    scheduler_defaults=SchedulerDefaults(partition="cpu-small", wall_time="02:00:00"),
    account_required=True,
    matlab_license_value="27000@license.example.edu",
    matlab_license_cloud_requires_tunnel=True,
    matlab_license_vendor_port=27001,
)

ENVIRON = {
    "CRYOSTACK_AWS_PRINCIPAL_ARN": "arn:aws:iam::210987654321:role/CryoStackPrincipal",
    "CRYOSTACK_CF_TEMPLATE_URL": (
        "https://templates.example.org/role.json?X-Amz-Signature=deadbeef"
    ),
    "AWS_REGION": "us-east-2",
    "AWS_SECRET_ACCESS_KEY": "synthetic-aws-secret-for-redaction-tests",
    "CRYOSTACK_RELAY_CONTROL_TOKEN": "relay-control-token-value",
}

LOG_LINES = [
    "[remote] sbatch submitted job 4242 on testhpc",
    "[remote][ERROR] ssh failed: password=hunter2-pass",
    "[cloud][ERROR] AssumeRole failed for arn:aws:iam::123456789012:role/X "
    "AWS_SECRET_ACCESS_KEY=synthetic-aws-secret-for-redaction-tests",
    "[cloud] batch job submitted with key AKIAZZZZYYYYXXXXWWWW",
    "GET /control/ Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
    "session cookie icesee_session=" + "a1b2c3d4" * 8,
    "MLM_LICENSE_FILE 1711@matlablic.ecs.gatech.edu reachable",
    "unrelated voila line",
]


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def env(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    database = tmp_path / "auth.db"
    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(database))
    auth = AuthManager(database_path=database)
    storage = auth.storage

    def user(name, *roles):
        record = storage.create_user(
            email=f"{name}@example.org", display_name=name.title(),
            institution=None, password_hash="x",
        )
        for role in roles:
            storage.grant_role(user_id=record.id, role=role)
        session = storage.create_session(ttl_seconds=3600, user_id=record.id)
        return record, {"icesee_session": session.id}

    users = {
        "plain": user("plain"),
        "developer": user("dev", "developer"),
        "maintainer": user("maint", "maintainer"),
        "admin": user("admin", "admin"),
        "owner": user("owner", "owner"),
    }

    researcher = users["plain"][0]

    hpc_config = {
        "execution_mode": "remote",
        "remote": {"host": "login.testhpc.example.edu", "user": "jdoe-hpc-user",
                   "remote_base_dir": "/storage/home/hcoda1/jdoe"},
        "slurm": {"nodes": 2, "tasks": 8, "tasks_per_node": 4, "partition": "cpu-small",
                  "time": "01:00:00", "memory": "4G", "account": "gt-secret-allocation"},
    }

    failed = storage.create_experiment(
        user_id=researcher.id, application="cryolauncher", name="ISSM ssh run",
        backend="ssh", status="running", configuration_snapshot_json=json.dumps(hpc_config),
        job_id="4242", cluster="testhpc",
        working_directory="/storage/home/hcoda1/jdoe/run1",
        log_path="/storage/home/hcoda1/jdoe/run1/out.log",
        metadata_json=json.dumps({"execution_mode": "remote"}), now=1000.0,
    )
    storage.update_experiment(
        experiment_id=failed.id, user_id=researcher.id, status="failed", exit_code=1,
        error_message=("sbatch: error: password=hunter2-pass rejected; "
                       "license 27000@license.example.edu unavailable"),
        now=1600.0,
    )

    storage.create_experiment(
        user_id=researcher.id, application="icesee", name="ICESEE EnKF run",
        backend="ssh", status="running", configuration_snapshot_json=json.dumps(hpc_config),
        job_id="4243", cluster="testhpc", metadata_json="{}", now=2000.0,
    )

    cloud = storage.create_experiment(
        user_id=researcher.id, application="cryolauncher", name="ISSM cloud run",
        backend="aws_batch", status="running",
        configuration_snapshot_json=json.dumps({
            "execution_mode": "cloud",
            "cloud": {"region": "us-east-2", "job_queue": "cryostack-queue",
                      "job_definition": "cryostack-issm",
                      "external_id": "ExternalIdValue-123"},
        }),
        job_id="b7f0c3a2-1111-2222-3333-444455556666",
        metadata_json=json.dumps({"execution_mode": "cloud",
                                  "aws_resources": {"account_id": "123456789012"}}),
        now=3000.0,
    )
    storage.update_experiment(
        experiment_id=cloud.id, user_id=researcher.id, status="failed",
        error_message=("AccessDenied for arn:aws:iam::123456789012:role/CryoStackExecutionRole "
                       "SessionToken=" + "Q" * 60 + " key AKIAZZZZYYYYXXXXWWWW"),
        now=3300.0,
    )

    log = tmp_path / "icesee.log"
    log.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")

    probes = []

    def probe(url):
        probes.append(url)
        return {"status": "healthy", "detail": "Relay status endpoint responding.",
                "latency_ms": 12}

    return {
        "tmp": tmp_path, "auth": auth, "database": database, "users": users,
        "failed_id": failed.id, "cloud_id": cloud.id, "log": log, "probes": probes,
        "probe": probe,
    }


def _service(env, **overrides):
    from control_center.services.access import AccessService
    from control_center.storage import ControlStorage

    options = {
        "access": AccessService(env["auth"].storage),
        "profiles": {"testhpc": PROFILE, "testhpc-alias": PROFILE},
        "environ": ENVIRON,
        "log_sources": {
            "gui": {"label": "Gateway and Voilà services", "path": env["log"]},
            "connector": {"label": "Connector relay", "path": env["tmp"] / "relay.log"},
        },
        "relay_url": "https://relay.example.org",
        "relay_probe": env["probe"],
    }
    options.update(overrides)
    return ComputeService(ControlStorage(env["database"]), **options)


def _run(env, script):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from control_center import install_control_center
    from control_center.services.access import AccessService

    app = web.Application()
    env["auth"].install(app)
    app["access_service"] = AccessService(env["auth"].storage)
    install_control_center(app, auth=env["auth"], database_path=env["database"])
    app["control_compute_service"] = _service(env)

    async def go():
        async with TestClient(TestServer(app)) as client:
            return await script(client)

    return asyncio.run(go())


def _assert_no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, secret


# ============================================================
# Redaction
# ============================================================

@pytest.mark.parametrize(
    "raw, secret",
    [
        ("password=hunter2-pass", "hunter2-pass"),
        ('{"SessionToken": "FQoGZXIvYXdzEabc"}', "FQoGZXIvYXdzEabc"),
        ("key AKIAZZZZYYYYXXXXWWWW used", "AKIAZZZZYYYYXXXXWWWW"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "eyJhbGciOiJIUzI1NiJ9"),
        ("MLM_LICENSE_FILE=1711@matlablic.ecs.gatech.edu", "matlablic"),
        ("license 27000@license.example.edu down", "license.example.edu"),
        ("https://user:pw-secret@host.example.org/x", "pw-secret"),
        ("arn:aws:iam::123456789012:role/R", "123456789012"),
        ("session " + "a1b2c3d4" * 8, "a1b2c3d4" * 8),
        ("external_id=ExternalIdValue-123", "ExternalIdValue-123"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3Nza\n-----END OPENSSH PRIVATE KEY-----",
         "AAAAB3Nza"),
        ("pairing_code: 482913", "482913"),
    ],
)
def test_redact_text_removes_secret_material(raw, secret):
    assert secret not in redact_text(raw)


def test_redact_text_keeps_operational_detail_and_bounds_length():
    text = "sbatch: job 4242 FAILED on cpu-small exit 1"
    assert redact_text(text) == text
    assert redact_text("arn:aws:iam::123456789012:role/R") == "arn:aws:iam::********9012:role/R"
    assert redact_text("\x1b[31mred\x1b[0m") == "red"
    assert len(redact_text("word " * 1000, limit=100)) == 100
    assert redact_text(None) == ""


def test_mask_account_id():
    assert mask_account_id("123456789012") == "********9012"
    assert mask_account_id("12345") == ""
    assert mask_account_id(None) == ""


def test_execution_target_classification():
    assert execution_target(backend="ssh", configuration={}, metadata={}) == "hpc"
    assert execution_target(backend="https", configuration={}, metadata={}) == "hpc"
    assert execution_target(backend="aws_batch", configuration={}, metadata={}) == "cloud"
    assert execution_target(backend="x", configuration={"execution_mode": "cloud"},
                            metadata={}) == "cloud"
    assert execution_target(backend="local", configuration={}, metadata={}) == "local"


# ============================================================
# Services
# ============================================================

def test_registered_resources_group_aliases_and_withhold_license():
    resources = registered_resources({"testhpc": PROFILE, "testhpc-alias": PROFILE})
    assert len(resources) == 1
    resource = resources[0]
    assert resource["aliases"] == ["testhpc", "testhpc-alias"]
    assert resource["scheduler"] == {"type": "Slurm", "default_partition": "cpu-small",
                                     "default_wall_time": "02:00:00"}
    assert resource["matlab_license"]["configured"] is True
    assert resource["matlab_license"]["cloud_requires_tunnel"] is True
    _assert_no_secrets(json.dumps(resources))
    assert "27001" not in json.dumps(resources)


def test_installation_profiles_never_expose_the_site_license():
    resources = registered_resources()
    assert {r["name"] for r in resources} == {"pace"}
    assert "matlablic" not in json.dumps(resources)


def test_hpc_overview_reports_requires_session_and_executions(env):
    overview = _service(env).hpc_overview()
    assert [c["status"] for c in overview["scheduler_checks"]] == ["requires_session"]
    executions = overview["executions"]
    assert executions["summary"]["total"] == 2
    assert executions["summary"]["failed"] == 1
    assert executions["summary"]["failure_rate"] == 1.0
    failure = executions["failures"][0]
    assert failure["id"] == env["failed_id"]
    assert failure["exit_code"] == 1
    assert "password=<redacted>" in failure["error"]
    assert failure["resources"] == {"nodes": "2", "tasks": "8", "tasks_per_node": "4",
                                    "partition": "cpu-small", "time": "01:00:00",
                                    "memory": "4G"}
    assert [item["name"] for item in executions["active"]] == ["ICESEE EnKF run"]
    _assert_no_secrets(json.dumps(overview))
    assert env["probes"] == []                      # nothing live on a read


def test_cloud_overview_masks_principal_and_hides_byo_details(env):
    overview = _service(env).cloud_overview()
    platform = overview["platform"]
    assert platform["principal"]["display"] == "arn:aws:iam::********4321:role/CryoStackPrincipal"
    assert platform["template_url"] == {"variable": "CRYOSTACK_CF_TEMPLATE_URL",
                                        "configured": True, "host": "templates.example.org"}
    assert platform["server_region"] == "us-east-2"
    assert {m["model"] for m in platform["models"]} == {"issm", "icepack"}
    assert platform["fargate_default"]["valid"] is True
    assert platform["execution_role_template"]["in_sync_with_code"] is True
    assert overview["researcher_accounts"]["listed"] is False
    assert overview["configuration_changes"]["supported"] is False
    cloud = overview["executions"]
    assert [item["id"] for item in cloud["failures"]] == [env["cloud_id"]]
    assert cloud["failures"][0]["resources"]["job_queue"] == "cryostack-queue"
    assert "external_id" not in cloud["failures"][0]["resources"]
    _assert_no_secrets(json.dumps(overview))


def test_log_excerpt_filters_bounds_and_redacts(env):
    service = _service(env)
    hpc = service.log_excerpt(source="gui", topic="hpc")
    assert hpc["available"] is True
    assert any("sbatch submitted" in line for line in hpc["lines"])
    assert not any("unrelated voila" in line for line in hpc["lines"])
    errors = service.log_excerpt(source="gui", topic="cloud", level="errors")
    assert len(errors["lines"]) == 1 and "AssumeRole failed" in errors["lines"][0]
    everything = service.log_excerpt(source="gui", topic="all", lines=10_000)
    assert len(everything["lines"]) == len(LOG_LINES)
    _assert_no_secrets(json.dumps([hpc, errors, everything]))
    assert service.log_excerpt(source="connector")["available"] is False
    with pytest.raises(KeyError):
        service.log_excerpt(source="../../etc/passwd")
    with pytest.raises(ValueError):
        service.log_excerpt(source="gui", topic="shell")


def test_log_excerpt_is_capped(env):
    env["log"].write_text("\n".join(f"[remote] line {i}" for i in range(1000)))
    excerpt = _service(env).log_excerpt(source="gui", lines=10_000)
    assert len(excerpt["lines"]) == MAX_LOG_LINES
    assert excerpt["truncated"] is True
    assert excerpt["lines"][-1] == "[remote] line 999"


def test_registry_log_sources_are_confined_to_the_root(tmp_path):
    registry = tmp_path / "applications.yaml"
    registry.write_text(
        "platform:\n  runtime:\n"
        "    gui: {log: icesee.log}\n"
        "    escape: {log: ../outside.log}\n"
        "    absolute: {log: /etc/passwd}\n"
        "    none: {command: [x]}\n"
    )
    sources = registry_log_sources(registry_path=registry, root=tmp_path)
    assert list(sources) == ["gui"]
    assert sources["gui"]["path"] == (tmp_path / "icesee.log").resolve()


def test_installation_registry_declares_gateway_and_relay_logs():
    assert set(registry_log_sources()) == {"gui", "connector"}


def test_relay_check_requires_operator_and_is_audited(env):
    service = _service(env)
    developer = env["users"]["developer"][0]
    maintainer = env["users"]["maintainer"][0]
    with pytest.raises(PermissionError):
        service.run_relay_check(actor_user_id=developer.id)
    assert env["probes"] == []
    result = service.run_relay_check(actor_user_id=maintainer.id)
    assert result["status"] == "healthy"
    assert env["probes"] == ["https://relay.example.org"]
    assert service.relay_status()["last_check"]["status"] == "healthy"
    with service.storage._connect() as connection:
        rows = connection.execute(
            "SELECT actor_user_id, action, metadata_json FROM control_audit_log"
        ).fetchall()
    assert [(r["actor_user_id"], r["action"]) for r in rows] == [
        (maintainer.id, "compute_relay_checked")]
    assert json.loads(rows[0]["metadata_json"]) == {"status": "healthy"}


def test_relay_check_sanitises_probe_output(env):
    service = _service(env, relay_probe=lambda url: {
        "status": "weird", "detail": "token=relay-control-token-value"})
    result = service.run_relay_check(actor_user_id=env["users"]["owner"][0].id)
    assert result["status"] == "failed"
    _assert_no_secrets(json.dumps(result))


def test_default_relay_probe_reads_public_status(monkeypatch):
    from control_center.services import compute

    seen = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, size):
            return b'{"session_id": "control-center-probe", "online": false, "state": "unknown"}'

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        return Response()

    monkeypatch.setattr(compute.urllib.request, "urlopen", urlopen)
    result = compute.probe_relay("https://relay.example.org/")
    assert result["status"] == "healthy"
    assert seen["url"] == "https://relay.example.org/connector/status/control-center-probe"
    assert "Authorization" not in seen["headers"]


# ============================================================
# HTTP: pages, API, roles
# ============================================================

def test_pages_render_for_every_control_role_without_secrets(env):
    async def script(client):
        out = {}
        for role in ("developer", "maintainer", "admin", "owner"):
            cookies = env["users"][role][1]
            for page in ("/control/hpc", "/control/cloud"):
                response = await client.get(page, cookies=cookies)
                out[(role, page)] = (response.status, await response.text())
        response = await client.get(
            "/control/hpc?log=gui&topic=all&level=all", cookies=env["users"]["developer"][1])
        out["log"] = (response.status, await response.text())
        response = await client.get(
            "/control/cloud?log=../../etc/passwd", cookies=env["users"]["developer"][1])
        out["bad_log"] = (response.status, await response.text())
        return out

    out = _run(env, script)
    for key, (status, text) in out.items():
        assert status == 200, key
        _assert_no_secrets(text)

    hpc_dev = out[("developer", "/control/hpc")][1]
    assert "TESTHPC" in hpc_dev
    assert "Requires a connected session" in hpc_dev
    assert "cpu-small" in hpc_dev and "Apptainer" in hpc_dev and "Slurm" in hpc_dev
    assert "ISSM ssh run" in hpc_dev and "ICESEE EnKF run" in hpc_dev
    assert "ISSM cloud run" not in hpc_dev
    assert 'id="cc-relay-check"' not in hpc_dev
    assert "Live checks require a maintainer" in hpc_dev
    assert 'id="cc-relay-check"' in out[("maintainer", "/control/hpc")][1]

    cloud = out[("developer", "/control/cloud")][1]
    assert "ISSM cloud run" in cloud and "ISSM ssh run" not in cloud
    assert "********4321" in cloud
    assert "cryostack-fargate" in cloud and "cryostack-ec2-queue" in cloud
    assert "not listed here" in cloud

    assert "sbatch submitted job 4242" in out["log"][1]
    assert "&lt;redacted&gt;" in out["log"][1]
    assert "Select a log" in out["bad_log"][1]


def test_pages_refuse_ordinary_users_and_anonymous(env):
    async def script(client):
        plain = env["users"]["plain"][1]
        return {
            "plain_hpc": (await client.get("/control/hpc", cookies=plain)).status,
            "plain_cloud": (await client.get("/control/cloud", cookies=plain)).status,
            "plain_api": (await client.get("/api/control/hpc", cookies=plain)).status,
            "plain_post": (await client.post("/api/control/hpc/relay-check", cookies=plain,
                                             json={})).status,
            "anon": await client.get("/control/hpc", allow_redirects=False),
        }

    out = _run(env, script)
    assert out["plain_hpc"] == 403
    assert out["plain_cloud"] == 403
    assert out["plain_api"] == 403
    assert out["plain_post"] == 403
    assert out["anon"].status == 302
    assert out["anon"].headers["Location"].startswith("/auth/login")
    assert env["probes"] == []


def test_json_api_is_redacted(env):
    async def script(client):
        dev = env["users"]["developer"][1]
        out = {}
        for path in ("/api/control/hpc", "/api/control/cloud", "/api/control/compute/logs",
                     "/api/control/compute/logs?source=gui&topic=all",
                     "/api/control/compute/logs?source=gui&level=errors&lines=5"):
            response = await client.get(path, cookies=dev)
            out[path] = (response.status, await response.text())
        out["unknown"] = (await client.get("/api/control/compute/logs?source=/etc/passwd",
                                           cookies=dev)).status
        out["bad_topic"] = (await client.get("/api/control/compute/logs?source=gui&topic=x",
                                             cookies=dev)).status
        out["bad_lines"] = (await client.get("/api/control/compute/logs?source=gui&lines=a",
                                             cookies=dev)).status
        out["no_cloud_mutation"] = (await client.post("/api/control/cloud", cookies=dev,
                                                      json={})).status
        return out

    out = _run(env, script)
    for path in ("/api/control/hpc", "/api/control/cloud", "/api/control/compute/logs",
                 "/api/control/compute/logs?source=gui&topic=all",
                 "/api/control/compute/logs?source=gui&level=errors&lines=5"):
        status, text = out[path]
        assert status == 200, path
        _assert_no_secrets(text)
    assert json.loads(out["/api/control/compute/logs"][1])["sources"][0]["key"] == "gui"
    assert out["unknown"] == 404
    assert out["bad_topic"] == 400
    assert out["bad_lines"] == 400
    assert out["no_cloud_mutation"] == 405


def test_relay_check_endpoint_roles_and_csrf(env):
    async def script(client):
        url = "/api/control/hpc/relay-check"
        dev = env["users"]["developer"][1]
        maint = env["users"]["maintainer"][1]
        out = {
            "developer": (await client.post(url, cookies=dev, json={})).status,
            "form": (await client.post(url, cookies=maint, data={"x": "1"})).status,
            "cross_origin": (await client.post(
                url, cookies=maint, json={},
                headers={"Origin": "https://evil.example.com"})).status,
        }
        response = await client.post(url, cookies=maint, json={})
        out["maintainer"] = (response.status, await response.json())
        for role in ("admin", "owner"):
            out[role] = (await client.post(url, cookies=env["users"][role][1], json={})).status
        page = await client.get("/control/hpc", cookies=dev)
        out["page"] = await page.text()
        return out

    out = _run(env, script)
    assert out["developer"] == 403
    assert out["form"] == 415
    assert out["cross_origin"] == 403
    assert out["maintainer"][0] == 200
    assert out["maintainer"][1]["status"] == "healthy"
    assert out["admin"] == 200 and out["owner"] == 200
    assert len(env["probes"]) == 3
    assert "Relay status endpoint responding" in out["page"]
