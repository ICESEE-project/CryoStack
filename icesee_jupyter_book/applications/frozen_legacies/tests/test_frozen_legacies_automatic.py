"""Automatic picking with URSA (the rollback picker) jobs: truthful availability, the subprocess job
lifecycle, products, failures, cancellation, recovery and ownership.

URSA itself needs OpenCV, which the CryoStack test environment does not
provide; the lifecycle tests therefore run the real runner and job code
against a small stand-in package with URSA's entry points
(``ascope_processor.AScope``, ``main.load_navigation_file``).
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import (NAV_TEXT, requires_picker_runners,
                                         tiff_bytes, write_nav, write_registry, write_tiff)
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
from icesee_jupyter_book.applications.frozen_legacies.radar import automatic
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV

API = "/frozen-legacies/api"
NAME = "F127-C0471_C0483.tiff"

FAKE_PROCESSOR = '''
import os, sys, time
class AScope:
    def __init__(self, config_path=None):
        self.nav_dict = {}
        self.output_dir = "output"
        os.makedirs("output", exist_ok=True)       # URSA's cwd side effect
    def set_output_directory(self, output_dir):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    def set_interactive_mode(self, enabled=True, defer_frame_plots=True):
        assert enabled is False
    def process_image(self, file_path, output_dir=None):
        # behaviour is set by the test through a file beside the stand-in
        # (the job runs URSA with a minimal environment)
        mode_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode.txt")
        mode = open(mode_file).read().strip() if os.path.exists(mode_file) else "ok"
        print("SECRET_SEEN=" + str("CRYOSTACK_TEST_SECRET" in os.environ), flush=True)
        print("Loading image:", file_path, flush=True)
        stem = os.path.splitext(os.path.basename(file_path))[0]
        if mode == "slow":
            time.sleep(60)
        if mode == "nothing":
            return
        if mode == "crash":
            sys.exit(7)
        lat, lon = self.nav_dict.get(471, ("NaN", "NaN"))
        here = os.path.dirname(os.path.abspath(__file__))
        if mode in ("frames", "diagnostics", "hostile"):
            # URSA's CSV of a 4-frame strip whose last frame took another echo
            # for the transmitter (written byte for byte as given)
            open(os.path.join(self.output_dir, stem + "_pick.csv"), "wb").write(
                open(os.path.join(here, "frames.csv"), "rb").read())
        else:
            with open(os.path.join(self.output_dir, stem + "_pick.csv"), "w") as f:
                f.write("Frame,CBD,LAT,LON,Surface_Time_us,Bed_Time_us,Ice_Thickness_m,"
                        "Surface_Power_dB,Bed_Power_dB,Transmitter_Time_us,Transmitter_Power_dB\\n")
                f.write(f"1,471,{lat},{lon},10.0,20.0,840.0,-20.0,-40.0,1.0,-10.0\\n")
                f.write("2,472,NaN,NaN,NaN,NaN,NaN,NaN,NaN,1.0,-10.0\\n")
        open(os.path.join(self.output_dir, stem + "_pick.npz"), "wb").write(b"npz")
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010800000000"
                            "3a7e9b550000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")
        # real URSA saves this plot under "output/" in its working directory
        verification_dir = "output" if mode == "cwd_verification" else self.output_dir
        os.makedirs(verification_dir, exist_ok=True)
        open(os.path.join(verification_dir, stem + "_frame_verification.png"), "wb").write(png)
        for i in (1, 2):
            open(os.path.join(self.output_dir, f"{stem}_frame{i:02d}_picked.png"), "wb").write(png)
        if mode in ("diagnostics", "hostile"):
            # URSA's reference-line QA images (functions/grid_detection.py)
            qa = os.path.join(self.output_dir, "ref_line_qa")
            os.makedirs(qa, exist_ok=True)
            for i in (1, 2, 3, 4):
                for what in ("01_search_region", "02_blackhat"):
                    open(os.path.join(qa, f"{stem}_frame{i:02d}_{what}.png"), "wb").write(png + bytes([i]))
        if mode == "hostile":
            qa = os.path.join(self.output_dir, "ref_line_qa")
            outside = os.path.join(here, "outside")
            # a link to a file outside the work area, under a diagnostic name
            os.symlink(os.path.join(outside, "secret.png"), os.path.join(qa, f"{stem}_frame03_05_projection.png"))
            # a non-PNG under a diagnostic name
            open(os.path.join(qa, f"{stem}_frame04_03_threshold_raw.png"), "wb").write(b"not a png")
            # a linked diagnostics directory
            os.symlink(outside, os.path.join("output", "ref_line_qa"))
            # names that do not follow URSA's pattern
            open(os.path.join(qa, "other_frame01_01_search_region.png"), "wb").write(png)
            open(os.path.join(qa, f"{stem}_frame00_01_search_region.png"), "wb").write(png)
'''
FAKE_MAIN = '''
import csv, os
def load_navigation_file(nav_path):
    if not nav_path or not os.path.exists(nav_path):
        return {}
    out = {}
    for row in csv.DictReader(open(nav_path)):
        out[int(row["CBD"])] = (float(row["LAT"]), float(row["LON"]))
    return out
'''


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010800000000"
                    "3a7e9b550000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")
#: URSA's columns, values as URSA formats them (CRLF line ends kept as-is)
FRAMES_CSV = (
    b"Frame,CBD,LAT,LON,Surface_Time_us,Bed_Time_us,Ice_Thickness_m,Surface_Power_dB,"
    b"Bed_Power_dB,Transmitter_Time_us,Transmitter_Power_dB,Transmitter_X_pixel,"
    b"Noise_Floor_Time_us,Noise_Floor_Power_dB\r\n"
    b"1,471,-81.479401,-169.753098,9.046875,16.968750,665.437500,-12.018349,-28.715596,"
    b"0.000000,-34.816514,725,5.687500,-55.917431\r\n"
    b"2,472,-81.494598,-169.686996,8.921875,16.859375,666.750000,-14.128440,-24.541284,"
    b"0.000000,-35.275229,742,6.281250,-55.779817\r\n"
    b"3,473,-81.509796,-169.617996,8.922280,16.818653,663.295337,-12.064220,-20.458716,"
    b"0.000000,-34.220183,728,5.626943,-55.091743\r\n"
    b"4,474,-81.657104,-168.972702,7.937500,21.515625,1140.562500,-24.128440,-26.055046,"
    b"0.000000,-11.284404,1301,6.281250,-52.935780\r\n"
)


@pytest.fixture(autouse=True)
def _ursa_picker(monkeypatch):
    """These tests cover URSA, selected as the rollback picker (LYRA is the
    default: test_frozen_legacies_lyra.py)."""
    monkeypatch.setenv(automatic.PICKER_ENV, "ursa")


def _strip(width=3000, height=420):
    img = np.full((height, width), 58000, np.uint16)
    img[300:305, :] = 600
    return img


@pytest.fixture
def env(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    shared = tmp_path / "shared"
    shared.mkdir()
    write_tiff(shared / NAME, _strip())
    write_nav(shared / "127.csv")
    registry = write_registry(tmp_path / "radar_sources.yaml", (
        f"  - key: f127\n    tiff: shared/{NAME}\n    nav: shared/127.csv\n"))
    monkeypatch.setenv(SOURCES_ENV, str(registry))
    root = tmp_path / "ursa"
    (root / "config").mkdir(parents=True)
    (root / "functions").mkdir()
    (root / "ascope_processor.py").write_text(FAKE_PROCESSOR)
    (root / "frames.csv").write_bytes(FRAMES_CSV)
    (root / "outside").mkdir()
    (root / "outside" / "secret.png").write_bytes(PNG + b"outside-secret")
    (root / "outside" / f"{Path(NAME).stem}_frame02_03_threshold_raw.png").write_bytes(PNG)
    (root / "main.py").write_text(FAKE_MAIN)
    (root / "config" / "default_config.json").write_text("{}")
    monkeypatch.setenv(automatic.ROOT_ENV, str(root))
    monkeypatch.setattr(automatic, "URSA_DEPENDENCIES", ("json",))
    automatic._availability_cache.clear()
    return {"tmp": tmp_path, "auth": AuthManager(), "workspace": tmp_path / "ws",
            "shared": shared, "ursa": root}


def _login(env, email):
    user = env["auth"].storage.create_user(
        email=email, display_name=email, institution=None, password_hash="x")
    session = env["auth"].storage.create_session(ttl_seconds=3600, user_id=user.id)
    return user, {"icesee_session": session.id}


def _app(env):
    from aiohttp import web

    app = web.Application()
    env["auth"].install(app)
    app[server.WORKSPACE_ROOT_KEY] = str(env["workspace"])
    server.install_frozen_legacies(app, auth=env["auth"])
    return app


def session(env, script):
    """Run ``script(client)`` against one live app (jobs outlive requests)."""
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        async with TestClient(TestServer(_app(env))) as client:
            return await script(client)

    return asyncio.run(go())


async def _json(resp):
    return resp.status, await resp.json()


async def _shared(client, ck):
    resp = await client.post(f"{API}/assets/shared", json={"source": "f127"}, cookies=ck)
    return (await resp.json())["asset_id"]


async def _wait(client, ck, asset_id, statuses=automatic.FINAL, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))
        if body["job"] and body["job"]["status"] in statuses:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("job did not finish")


def _asset_dir(env, user, asset_id):
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=env["workspace"]) / "frozen_legacies" / "radar" / asset_id


# ── availability ─────────────────────────────────────────────────────
@pytest.mark.skipif(importlib.util.find_spec("cv2") is not None, reason="OpenCV is installed here")
def test_real_ursa_is_reported_unavailable_without_opencv(monkeypatch):
    monkeypatch.delenv(automatic.ROOT_ENV, raising=False)
    automatic._availability_cache.clear()
    if not automatic.DEFAULT_URSA_ROOT.is_dir():
        pytest.skip("URSA sources (external/FrozenLegacies) not present")
    state = automatic.availability(refresh=True)
    assert state["available"] is False
    assert "cv2" in state["reason"]


def test_missing_ursa_installation(monkeypatch, tmp_path):
    monkeypatch.setenv(automatic.ROOT_ENV, str(tmp_path / "nowhere"))
    automatic._availability_cache.clear()
    state = automatic.availability(refresh=True)
    assert state == {"available": False, "picker": "URSA",
                     "reason": "The URSA automatic picker is not installed on this server."}


@requires_picker_runners
def test_unavailable_ursa_never_starts_a_job(env, monkeypatch):
    monkeypatch.setattr(automatic, "URSA_DEPENDENCIES", ("module_that_does_not_exist",))
    automatic._availability_cache.clear()
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        status, body = await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))
        assert body["availability"]["available"] is False and body["job"] is None
        assert "module_that_does_not_exist" in body["availability"]["reason"]
        status, body = await _json(await client.post(
            f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck))
        assert status == 409 and body["available"] is False
        return asset_id

    asset_id = session(env, script)
    assert not (_asset_dir(env, user, asset_id) / "automatic.json").exists()


# ── lifecycle ────────────────────────────────────────────────────────
@requires_picker_runners
def test_job_runs_ursa_and_registers_automatic_products(env, monkeypatch):
    # a gateway secret must never reach the URSA subprocess
    monkeypatch.setenv("CRYOSTACK_TEST_SECRET", "do-not-leak")
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        status, body = await _json(await client.post(
            f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck))
        assert status == 200 and body["job"]["status"] in ("queued", "running")
        done = await _wait(client, ck, asset_id)
        resp = await client.get(f"{API}/assets/{asset_id}/products", cookies=ck)
        listed = (await resp.json())["products"]
        frames = await client.get(f"{API}/assets/{asset_id}/products/ursa-frames", cookies=ck)
        return asset_id, done, listed, await frames.read()

    asset_id, done, listed, frames = session(env, script)
    job = done["job"]
    assert job["status"] == "completed" and job["message"] == "URSA finished."
    assert job["summary"]["rows"] == 2 and job["summary"]["thickness_values"] == 1
    kinds = {p["kind"]: p for p in listed if p["workflow"] == "ursa-automatic"
             and p["kind"] != "ursa-diagnostic"}
    assert set(kinds) == {"ursa-csv", "ursa-npz", "ursa-verification", "ursa-frames"}
    # URSA's per-frame picks plots are kept as diagnostic images as well
    assert sorted(p["product_id"] for p in listed if p["kind"] == "ursa-diagnostic") == [
        "ursa-diag-f01-picked", "ursa-diag-f02-picked"]
    assert all(p["producer"] == "frozen-legacies" for p in kinds.values())
    assert kinds["ursa-csv"]["filename"] == "F127-C0471_C0483_pick.csv"
    assert sorted(zipfile.ZipFile(io.BytesIO(frames)).namelist()) == [
        "F127-C0471_C0483_frame01_picked.png", "F127-C0471_C0483_frame02_picked.png"]
    # URSA saw the TIFF under its original name and read the navigation
    csv_text = (_asset_dir(env, user, asset_id) / "outputs" / "F127-C0471_C0483_pick.csv").read_text()
    assert "1,471,-81.479401,-169.753098" in csv_text
    # log tail is kept without server paths; the work area is removed
    log = "\n".join(job["log_tail"])
    assert "Loading image:" in log and str(env["tmp"]) not in log
    assert "SECRET_SEEN=False" in log
    assert not (_asset_dir(env, user, asset_id) / automatic.WORK_DIRNAME).exists()
    assert not (env["shared"] / "output").exists()          # URSA's cwd side effect contained


@requires_picker_runners
def test_rerun_replaces_the_previous_automatic_products(env):
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        for _ in range(2):
            await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"},
                              cookies=ck)
            await _wait(client, ck, asset_id)
            await asyncio.sleep(0.05)
        resp = await client.get(f"{API}/assets/{asset_id}/products", cookies=ck)
        return asset_id, (await resp.json())["products"]

    asset_id, listed = session(env, script)
    assert sum(1 for p in listed if p["kind"] == "ursa-csv") == 1
    outputs = sorted(p.name for p in (_asset_dir(env, user, asset_id) / "outputs").iterdir())
    assert outputs == ["F127-C0471_C0483_frame_verification.png", "F127-C0471_C0483_pick.csv",
                       "F127-C0471_C0483_pick.npz", "F127-C0471_C0483_ursa_diag_frame01_picked.png",
                       "F127-C0471_C0483_ursa_diag_frame02_picked.png",
                       "F127-C0471_C0483_ursa_frames.zip"]
    assert sum(1 for p in listed if p["product_id"] == "ursa-diag-f01-picked") == 1


@pytest.mark.parametrize("mode, message", [
    ("nothing", "URSA finished without producing picks."),
    ("crash", "URSA stopped with exit status 7."),
])
@requires_picker_runners
def test_failures_are_reported_without_results(env, monkeypatch, mode, message):
    (env["ursa"] / "mode.txt").write_text(mode)
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        return await _wait(client, ck, asset_id)

    body = session(env, script)
    assert body["job"]["status"] == "failed" and body["job"]["message"] == message
    assert body["products"] == []


@requires_picker_runners
def test_ursa_import_failure(env):
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        # the installation breaks after the (cached) health check passed:
        # the job itself must still fail cleanly
        status, body = await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))
        assert body["availability"]["available"] is True
        (env["ursa"] / "ascope_processor.py").write_text("import module_that_does_not_exist\n")
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        return await _wait(client, ck, asset_id)

    body = session(env, script)
    assert body["job"]["status"] == "failed"
    assert body["job"]["message"] == "URSA could not be started in this environment."


@requires_picker_runners
def test_cancel_a_running_job(env, monkeypatch):
    (env["ursa"] / "mode.txt").write_text("slow")
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        await _wait(client, ck, asset_id, statuses=("running",))
        status, _b = await _json(await client.post(
            f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck))
        assert status == 409                                    # already running
        resp = await client.delete(f"{API}/assets/{asset_id}", cookies=ck)
        assert resp.status == 409                               # not while running
        started = time.time()
        status, body = await _json(await client.post(
            f"{API}/assets/{asset_id}/automatic", json={"action": "cancel"}, cookies=ck))
        assert time.time() - started < 10
        return asset_id, status, body

    asset_id, status, body = session(env, script)
    assert status == 200 and body["job"]["status"] == "cancelled"
    assert not (_asset_dir(env, user, asset_id) / automatic.WORK_DIRNAME).exists()


def test_orphaned_jobs_are_reported_as_interrupted(env):
    user, ck = _login(env, "a@example.org")

    async def create(client):
        return await _shared(client, ck)

    asset_id = session(env, create)
    path = _asset_dir(env, user, asset_id) / "automatic.json"
    path.write_text(json.dumps({
        "schema": automatic.JOB_SCHEMA, "version": 1, "asset_id": asset_id, "job_id": "ursa-1",
        "picker": "ursa", "status": "running", "created_at": 1, "started_at": 1,
        "finished_at": None, "message": "", "log_tail": [], "summary": {}, "warnings": []}))

    async def read(client):
        return await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))

    status, body = session(env, read)
    assert body["job"]["status"] == "interrupted" and "restarted" in body["job"]["message"]
    assert json.loads(path.read_text())["status"] == "interrupted"


def test_warnings_for_names_and_navigation():
    assert automatic.warnings_for("F103-C0467_C0479.tiff", True) == []
    w = automatic.warnings_for("scan.tiff", False)
    assert len(w) == 2 and "CBD" in w[0] and "navigation" in w[1].lower()


# ── ownership and validation ─────────────────────────────────────────
@requires_picker_runners
def test_jobs_belong_to_their_owner(env):
    _a, cka = _login(env, "a@example.org")
    _b, ckb = _login(env, "b@example.org")

    async def script(client):
        asset_id = await _shared(client, cka)
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=cka)
        other_get = await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ckb)
        other_post = await client.post(f"{API}/assets/{asset_id}/automatic",
                                       json={"action": "cancel"}, cookies=ckb)
        anon = await client.get(f"{API}/assets/{asset_id}/automatic")
        await _wait(client, cka, asset_id)
        return other_get.status, other_post.status, anon.status

    assert session(env, script) == (404, 404, 401)


@pytest.mark.parametrize("payload, status", [
    ({"action": "explode"}, 400), ({}, 400), ([], 400), ({"action": "cancel"}, 409),
])
def test_invalid_automatic_actions(env, payload, status):
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        resp = await client.post(f"{API}/assets/{asset_id}/automatic", json=payload, cookies=ck)
        cross = await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"},
                                  cookies=ck, headers={"Origin": "https://evil.example"})
        return resp.status, cross.status

    assert session(env, script) == (status, 403)


@requires_picker_runners
def test_uploaded_radar_without_nav_warns_but_runs(env):
    _u, ck = _login(env, "a@example.org")
    from aiohttp import FormData

    async def script(client):
        f = FormData()
        f.add_field("tiff", io.BytesIO(tiff_bytes(_strip())), filename="scan.tiff")
        resp = await client.post(f"{API}/assets/upload", data=f, cookies=ck)
        asset_id = (await resp.json())["asset_id"]
        status, body = await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        done = await _wait(client, ck, asset_id)
        return body, done

    before, done = session(env, script)
    assert len(before["warnings"]) == 2
    assert done["job"]["status"] == "completed" and len(done["job"]["warnings"]) == 2


# ── health check, scientific status, publication ─────────────────────
@requires_picker_runners
def test_health_check_imports_ursa_in_the_job_environment(env, monkeypatch):
    monkeypatch.setenv("CRYOSTACK_TEST_SECRET", "do-not-leak")
    state = automatic.availability(refresh=True)
    assert state["available"] is True and state["reason"] is None
    environment = state["environment"]
    assert environment["python"].count(".") == 2
    assert set(environment["packages"]) == {"numpy", "scipy", "pandas", "matplotlib", "cv2", "skimage"}
    assert str(env["tmp"]) not in json.dumps(state)          # versions only, no paths
    # the check ran without the service user's site-packages
    assert automatic.ursa_environment()["PYTHONNOUSERSITE"] == "1"
    assert "CRYOSTACK_TEST_SECRET" not in automatic.ursa_environment()


@requires_picker_runners
def test_health_check_fails_when_ursa_cannot_be_imported(env):
    (env["ursa"] / "main.py").write_text("raise ImportError('broken install')\n")
    state = automatic.availability(refresh=True)
    assert state["available"] is False
    assert state["reason"] == ("URSA could not be imported in the automatic-picking environment "
                               "on this server.")


def test_scikit_image_is_a_checked_dependency():
    # URSA's grid detection imports skimage.transform.rotate
    assert "skimage" in automatic.URSA_DEPENDENCIES and "cv2" in automatic.URSA_DEPENDENCIES


@requires_picker_runners
def test_runner_check_and_run_arguments():
    import subprocess as sp
    runner = str(automatic.RUNNER)
    missing = sp.run([sys.executable, runner, "--ursa-root", "/nonexistent"],
                     capture_output=True, text=True)
    assert missing.returncode == 2 and "--tiff and --output are required" in missing.stderr


@requires_picker_runners
def test_automatic_results_are_unvalidated_and_never_publishable(env):
    """URSA output: labelled unvalidated everywhere, never a review snapshot."""
    from icesee_jupyter_book.applications.frozen_legacies.radar import review

    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        done = await _wait(client, ck, asset_id)
        listed = (await (await client.get(f"{API}/assets/{asset_id}/products", cookies=ck)).json())["products"]
        state = await (await client.get(f"{API}/assets/{asset_id}/review", cookies=ck)).json()
        submit = await client.post(f"{API}/assets/{asset_id}/review", json={"action": "submit"},
                                   cookies=ck, headers={"Origin": str(client.make_url("/")).rstrip("/")})
        return done, listed, state, submit.status, await submit.json()

    done, listed, state, status, body = session(env, script)
    assert done["job"]["status"] == "completed"
    assert done["job"]["scientific_status"] == "unvalidated"
    assert done["scientific_status"] == "unvalidated" and done["publication_eligible"] is False
    assert "cannot be submitted" in done["scientific_note"]
    ursa = [p for p in listed if p["workflow"] == "ursa-automatic"]
    assert ursa and all(p["scientific_status"] == "unvalidated" for p in ursa)
    assert all(p["provenance"]["scientific_status"] == "unvalidated" for p in ursa)
    assert all("scientific_status" not in p for p in listed if p["workflow"] != "ursa-automatic"
               and not p["kind"].startswith("ursa-"))
    # a completed URSA job does not make the asset submittable, and review
    # snapshots only ever hold ASTRA's products
    assert state["can_submit"] is False
    assert status >= 400 and "error" in body
    assert review.SNAPSHOT_PRODUCTS == ("astra-csv", "astra-qc") and review.WORKFLOW == "astra-manual"


@requires_picker_runners
def test_verification_plot_saved_in_ursas_working_directory_is_collected(env):
    (env["ursa"] / "mode.txt").write_text("cwd_verification")
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
        return await _wait(client, ck, asset_id)

    body = session(env, script)
    assert body["job"]["status"] == "completed"
    assert "ursa-verification" in {p["kind"] for p in body["products"]}


# ── URSA diagnostic images, frame diagnostics, provenance ────────────
STEM = Path(NAME).stem


async def _run_job(client, ck, asset_id=None):
    asset_id = asset_id or await _shared(client, ck)
    await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck)
    return asset_id, await _wait(client, ck, asset_id)


async def _products(client, ck, asset_id):
    return (await (await client.get(f"{API}/assets/{asset_id}/products", cookies=ck)).json())["products"]


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


@requires_picker_runners
def test_ursa_diagnostic_images_are_registered_per_frame(env):
    (env["ursa"] / "mode.txt").write_text("diagnostics")
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id, done = await _run_job(client, ck)
        listed = await _products(client, ck, asset_id)
        preview = await client.get(f"{API}/assets/{asset_id}/products/ursa-diag-f04-01-search-region/preview",
                                   cookies=ck)
        download = await client.get(f"{API}/assets/{asset_id}/products/ursa-diag-f04-01-search-region",
                                    cookies=ck)
        return asset_id, done, listed, preview.status, preview.content_type, await download.read()

    asset_id, done, listed, preview_status, preview_type, downloaded = session(env, script)
    outputs = _asset_dir(env, user, asset_id) / "outputs"
    diagnostics = {p["product_id"]: p for p in listed if p["kind"] == "ursa-diagnostic"}
    expected = {"ursa-diag-f01-picked", "ursa-diag-f02-picked"} | {
        f"ursa-diag-f{i:02d}-{what}" for i in (1, 2, 3, 4)
        for what in ("01-search-region", "02-blackhat")}
    assert set(diagnostics) == expected
    for product in diagnostics.values():
        stored = outputs / product["filename"]
        assert stored.is_file() and not stored.is_symlink()
        assert product["provenance"]["sha256"] == _sha(stored.read_bytes())
        assert product["bytes"] == stored.stat().st_size
        assert product["title"].startswith("URSA diagnostic (unvalidated) · frame ")
        assert product["diagnostic"] == "URSA diagnostic (unvalidated)"
        assert product["scientific_status"] == "unvalidated"
        assert product["provenance"]["scientific_status"] == "unvalidated"
        assert product["producer"] == "frozen-legacies" and product["workflow"] == "ursa-automatic"
        assert product["preview_url"] and product["download_url"]
    f4 = diagnostics["ursa-diag-f04-01-search-region"]
    assert f4["summary"] == {"frame": 4, "label": "reference line: search region", "bytes": len(PNG) + 1}
    assert f4["provenance"]["source_name"] == f"ref_line_qa/{STEM}_frame04_01_search_region.png"
    assert downloaded == PNG + bytes([4])
    assert preview_status == 200 and preview_type == "image/png"
    # URSA's CSV is stored byte for byte; the work area is gone
    assert (outputs / f"{STEM}_pick.csv").read_bytes() == FRAMES_CSV
    assert not (_asset_dir(env, user, asset_id) / automatic.WORK_DIRNAME).exists()
    # the Automatic view's product list stays the results; diagnostics are per frame
    assert all(p["kind"] != "ursa-diagnostic" for p in done["products"])

    frames = done["frames"]
    assert frames["scientific_status"] == "unvalidated"
    assert frames["label"] == "URSA diagnostic (unvalidated)"
    assert "heuristic" in frames["note"] and "correct nothing" in frames["note"]
    assert frames["columns"][:2] == ["Frame", "CBD"] and "Transmitter_X_pixel" in frames["columns"]
    assert [r["frame"] for r in frames["rows"]] == [1, 2, 3, 4]
    row4 = dict(zip(frames["columns"], frames["rows"][3]["values"]))
    # URSA's values as written, not reparsed or rounded
    assert row4["Ice_Thickness_m"] == "1140.562500" and row4["Transmitter_X_pixel"] == "1301"
    assert frames["flagged"] == 1
    assert [r["flags"] for r in frames["rows"][:3]] == [[], [], []]
    assert frames["rows"][3]["flags"] == ["transmitter position: 1301 px vs strip median 735 px",
                                          "transmitter power: -11.3 dB vs strip median -34.5 dB"]
    assert [len(r["images"]) for r in frames["rows"]] == [3, 3, 2, 2]
    image = next(i for i in frames["rows"][3]["images"] if i["product_id"] == f4["product_id"])
    assert image["sha256"] == f4["provenance"]["sha256"] and image["bytes"] == len(PNG) + 1
    assert all(i["preview_url"].endswith("/preview") for r in frames["rows"] for i in r["images"])


@requires_picker_runners
def test_automatic_provenance_records_ursa_inputs_parameters_and_diagnostics(env):
    (env["ursa"] / "mode.txt").write_text("diagnostics")
    (env["ursa"] / "config" / "default_config.json").write_text(
        '{"processing_params": {"tx_search_frac": 0.2}}')
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id, done = await _run_job(client, ck)
        return asset_id, done, await _products(client, ck, asset_id)

    asset_id, done, listed = session(env, script)
    provenance = done["job"]["provenance"]
    assert provenance["scientific_status"] == "unvalidated"
    assert provenance["ursa"]["commit"] is None                 # not a git checkout of URSA
    assert len(provenance["ursa"]["source_sha256"]) == 64
    assert provenance["ursa"]["config_sha256"] == _sha(
        (env["ursa"] / "config" / "default_config.json").read_bytes())
    assert provenance["parameters"] == {"processing_params": {"tx_search_frac": 0.2}}
    assert provenance["runner"] == {"interactive": False, "defer_frame_plots": False, "navigation": True}
    assert provenance["inputs"]["tiff"] == {
        "name": NAME, "bytes": (env["shared"] / NAME).stat().st_size,
        "sha256": _sha((env["shared"] / NAME).read_bytes())}
    assert provenance["inputs"]["navigation"]["sha256"] == _sha((env["shared"] / "127.csv").read_bytes())
    assert provenance["outputs"]["ursa-csv"]["sha256"] == _sha(FRAMES_CSV)
    images = {i["product_id"]: i for i in provenance["diagnostics"]["images"]}
    diagnostics = {p["product_id"]: p for p in listed if p["kind"] == "ursa-diagnostic"}
    assert set(images) == set(diagnostics) and provenance["diagnostics"]["count"] == 10
    assert all(images[k]["sha256"] == diagnostics[k]["provenance"]["sha256"] for k in images)
    assert provenance["diagnostics"]["skipped"] == 0
    # every product of the run carries the run's identity (additive fields)
    for product in (p for p in listed if p["workflow"] == "ursa-automatic"):
        assert product["provenance"]["job_id"] == done["job"]["job_id"]
        assert product["provenance"]["ursa_source_sha256"] == provenance["ursa"]["source_sha256"]
        assert product["provenance"]["input_sha256"] == provenance["inputs"]["tiff"]["sha256"]
    # names and hashes only: no server paths
    text = json.dumps(done)
    assert str(env["tmp"]) not in text and str(env["workspace"]) not in text


def test_ursa_commit_is_recorded_only_for_ursas_own_checkout(monkeypatch, tmp_path):
    import subprocess as sp

    root = tmp_path / "FrozenLegacies" / "URSA"
    root.mkdir(parents=True)
    commit = "0123456789abcdef0123456789abcdef01234567"

    def fake_run(toplevel):
        return lambda *a, **k: sp.CompletedProcess(a[0], 0, f"{toplevel}\n{commit}\n", "")

    monkeypatch.setattr(automatic.subprocess, "run", fake_run(tmp_path / "FrozenLegacies"))
    assert automatic._git_commit(root) == commit
    # a copied URSA tree inside the CryoStack repository has no URSA commit
    monkeypatch.setattr(automatic.subprocess, "run", fake_run(automatic._REPO))
    assert automatic._git_commit(root) is None
    monkeypatch.setattr(automatic.subprocess, "run", fake_run(tmp_path / "elsewhere"))
    assert automatic._git_commit(root) is None


@requires_picker_runners
def test_diagnostics_never_follow_links_or_take_non_png_files(env):
    (env["ursa"] / "mode.txt").write_text("hostile")
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id, done = await _run_job(client, ck)
        return asset_id, done, await _products(client, ck, asset_id)

    asset_id, done, listed = session(env, script)
    assert done["job"]["status"] == "completed"
    ids = {p["product_id"] for p in listed if p["kind"] == "ursa-diagnostic"}
    # the linked file, the linked directory, the non-PNG, frame 0 and foreign
    # names are not kept
    assert ids == {"ursa-diag-f01-picked", "ursa-diag-f02-picked"} | {
        f"ursa-diag-f{i:02d}-{what}" for i in (1, 2, 3, 4)
        for what in ("01-search-region", "02-blackhat")}
    assert done["job"]["provenance"]["diagnostics"]["skipped"] == 1     # the non-PNG
    outputs = _asset_dir(env, user, asset_id) / "outputs"
    for path in outputs.iterdir():
        assert path.is_file() and not path.is_symlink()
        assert b"outside-secret" not in path.read_bytes()


@pytest.mark.parametrize("limit, value, kept", [
    ("MAX_DIAGNOSTIC_TOTAL_BYTES", 2 * len(PNG) + 2 * (len(PNG) + 1),
     {"ursa-diag-f01-picked", "ursa-diag-f02-picked", "ursa-diag-f01-01-search-region",
      "ursa-diag-f01-02-blackhat"}),
    ("MAX_DIAGNOSTIC_FILES", 2, {"ursa-diag-f01-picked", "ursa-diag-f02-picked"}),
    ("MAX_DIAGNOSTIC_FILE_BYTES", len(PNG), {"ursa-diag-f01-picked", "ursa-diag-f02-picked"}),
])
@requires_picker_runners
def test_diagnostics_are_bounded_keeping_every_frames_picks_plot_first(env, monkeypatch, limit, value, kept):
    (env["ursa"] / "mode.txt").write_text("diagnostics")
    monkeypatch.setattr(automatic, limit, value)
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id, done = await _run_job(client, ck)
        return done, await _products(client, ck, asset_id)

    done, listed = session(env, script)
    assert done["job"]["status"] == "completed"
    assert {p["product_id"] for p in listed if p["kind"] == "ursa-diagnostic"} == kept
    diagnostics = done["job"]["provenance"]["diagnostics"]
    assert diagnostics["count"] == len(kept) and diagnostics["skipped"] == 10 - len(kept)
    assert diagnostics["bytes"] <= automatic.MAX_DIAGNOSTIC_TOTAL_BYTES


@requires_picker_runners
def test_diagnostics_are_owner_scoped_and_contained(env):
    user, cka = _login(env, "a@example.org")
    _b, ckb = _login(env, "b@example.org")
    (env["ursa"] / "mode.txt").write_text("diagnostics")
    base = "{api}/assets/{asset}/products/ursa-diag-f01-picked"

    async def script(client):
        asset_id, _done = await _run_job(client, cka)
        url = base.format(api=API, asset=asset_id)
        statuses = {
            "owner": (await client.get(url, cookies=cka)).status,
            "other": (await client.get(url, cookies=ckb)).status,
            "other_preview": (await client.get(url + "/preview", cookies=ckb)).status,
            "other_automatic": (await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ckb)).status,
            "anonymous": (await client.get(url)).status,
            "traversal": (await client.get(f"{API}/assets/{asset_id}/products/..%2Fautomatic.json",
                                           cookies=cka)).status,
            "delete": (await client.delete(url, cookies=cka, headers={
                "Origin": str(client.make_url("/")).rstrip("/")})).status,
        }
        outputs = _asset_dir(env, user, asset_id) / "outputs"
        # a stored diagnostic replaced by a link is refused, never followed
        stored = outputs / f"{STEM}_ursa_diag_frame02_picked.png"
        stored.unlink()
        stored.symlink_to(env["ursa"] / "outside" / "secret.png")
        statuses["linked"] = (await client.get(
            base.format(api=API, asset=asset_id).replace("f01", "f02"), cookies=cka)).status
        # a record naming a file outside outputs/ is dropped
        doc_path = _asset_dir(env, user, asset_id) / "products.json"
        doc = json.loads(doc_path.read_text())
        for record in doc["products"]:
            if record["product_id"] == "ursa-diag-f03-02-blackhat":
                record["file"] = "../automatic.json"
        doc_path.write_text(json.dumps(doc))
        statuses["outside"] = (await client.get(
            f"{API}/assets/{asset_id}/products/ursa-diag-f03-02-blackhat", cookies=cka)).status
        return statuses

    statuses = session(env, script)
    assert statuses == {"owner": 200, "other": 404, "other_preview": 404, "other_automatic": 404,
                        "anonymous": 401, "traversal": 404, "delete": 403, "linked": 404,
                        "outside": 404}


@requires_picker_runners
def test_rerun_replaces_the_previous_runs_diagnostics(env):
    user, ck = _login(env, "a@example.org")

    async def script(client):
        (env["ursa"] / "mode.txt").write_text("diagnostics")
        asset_id, first = await _run_job(client, ck)
        (env["ursa"] / "mode.txt").write_text("ok")
        await asyncio.sleep(0.05)
        _id, second = await _run_job(client, ck, asset_id)
        return asset_id, first, second, await _products(client, ck, asset_id)

    asset_id, first, second, listed = session(env, script)
    assert first["frames"]["diagnostic_images"] == 10
    assert sorted(p["product_id"] for p in listed if p["kind"] == "ursa-diagnostic") == [
        "ursa-diag-f01-picked", "ursa-diag-f02-picked"]
    outputs = sorted(p.name for p in (_asset_dir(env, user, asset_id) / "outputs").iterdir())
    assert not [n for n in outputs if "search_region" in n or "blackhat" in n]
    # the second run's CSV has no transmitter columns to compare: no flags
    assert second["frames"]["flagged"] == 0 and len(second["frames"]["rows"]) == 2


@requires_picker_runners
def test_diagnostics_never_make_automatic_results_reviewable(env):
    from icesee_jupyter_book.applications.frozen_legacies.radar import review

    (env["ursa"] / "mode.txt").write_text("diagnostics")
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id, done = await _run_job(client, ck)
        state = await (await client.get(f"{API}/assets/{asset_id}/review", cookies=ck)).json()
        submit = await client.post(f"{API}/assets/{asset_id}/review", json={"action": "submit"},
                                   cookies=ck, headers={"Origin": str(client.make_url("/")).rstrip("/")})
        return done, state, submit.status

    done, state, status = session(env, script)
    assert done["frames"]["diagnostic_images"] == 10 and done["publication_eligible"] is False
    assert state["can_submit"] is False and status >= 400
    assert "ursa-diagnostic" not in review.SNAPSHOT_PRODUCTS


def test_frames_view_is_absent_without_an_automatic_result(env):
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        return await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))

    _status, body = session(env, script)
    assert body["frames"] is None


_REAL_URSA_PYTHON = Path.home() / ".cryostack-envs" / "ursa" / "bin" / "python"


@pytest.mark.skipif(not _REAL_URSA_PYTHON.is_file(), reason="no separate URSA environment here")
def test_the_separate_ursa_environment_passes_the_health_check(monkeypatch):
    """The real URSA sources in the environment built by env/build_ursa_env.sh."""
    if not automatic.DEFAULT_URSA_ROOT.is_dir():
        pytest.skip("URSA sources (external/FrozenLegacies) not present")
    monkeypatch.delenv(automatic.ROOT_ENV, raising=False)
    monkeypatch.setenv(automatic.PYTHON_ENV, str(_REAL_URSA_PYTHON))
    automatic._availability_cache.clear()
    state = automatic.availability(refresh=True)
    automatic._availability_cache.clear()
    assert state["available"] is True, state
    lock = (_HERE.parent / "env" / "ursa-requirements.lock").read_text()
    for name, dist in (("numpy", "numpy"), ("scipy", "scipy"), ("pandas", "pandas"),
                       ("matplotlib", "matplotlib"), ("skimage", "scikit-image")):
        assert f"{dist}=={state['environment']['packages'][name]}" in lock
