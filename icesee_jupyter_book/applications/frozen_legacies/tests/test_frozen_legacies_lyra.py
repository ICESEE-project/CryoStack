"""Automatic picking with LYRA (the default picker): availability, the
canonical reel name, calibration guidance, the phased job lifecycle,
products, frame diagnostics, cancellation and the URSA rollback switch.

LYRA itself needs pandas, matplotlib and its OCR templates on real A-scope
film; the lifecycle tests therefore run the real runner
(``pickers/lyra_runner.py``) and job code against a stand-in LYRA whose
scripts write LYRA's output layout (``output/F<flight>/phase{1,3,4}``).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import write_registry, write_tiff
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
lyra_runner = pytest.importorskip(
    "icesee_jupyter_book.applications.frozen_legacies.pickers.lyra_runner",
    reason="the LYRA runner is distributed separately")
from icesee_jupyter_book.applications.frozen_legacies.radar import automatic, products
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV

API = "/frozen-legacies/api"
CANONICAL = "47_0004800_0004824-reel_begin_end.tiff"
RENAMED = "F127-C0471_C0475.tiff"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010800000000"
                    "3a7e9b550000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")

# Shared by the stand-in scripts: where LYRA writes (relative to its root,
# its working directory) and the flight, from the TIFF argument.
_PRELUDE = '''
import os, sys, time
MODE = @MODE@
PNG = bytes.fromhex(@PNG@)
tiff = sys.argv[1]
flight = tiff.split("/")[1]
out = os.path.join("output", "F" + flight)
print("SECRET_SEEN=" + str("CRYOSTACK_TEST_SECRET" in os.environ), flush=True)
print("reading " + tiff + " exists=" + str(os.path.isfile(tiff)), flush=True)
'''
DETECT = _PRELUDE + '''
if MODE == "slow":
    time.sleep(60)
if MODE == "noframes":
    print("no frames", flush=True)
    sys.exit(1)
os.makedirs(os.path.join(out, "phase1", "ocr_diag"), exist_ok=True)
with open(os.path.join(out, "phase1", "F" + flight + "_frame_index.csv"), "w") as f:
    f.write("flight,tiff,tiff_id,frame_idx,frame_type,cbd,left_px,right_px,width_px,ocr_method,ocr_raw\\n")
    f.write(flight + ",x,4800,0,partial,,0,100,100,segment,\\n")
    f.write(flight + ",x,4800,1,complete,0471,100,400,300,segment,1270471\\n")
    f.write(flight + ",x,4800,2,complete,0472,400,700,300,segment,\\n")
    f.write(flight + ",x,4800,3,complete,0473,700,1000,300,segment,1270473\\n")
open(os.path.join(out, "phase1", "F" + flight + "_4800_contact.png"), "wb").write(PNG)
open(os.path.join(out, "phase1", "ocr_diag", "F" + flight + "_4800_ocr_diag.png"), "wb").write(PNG)
open(os.path.join(out, "phase1", "F" + flight + "_4800_contact.eps"), "wb").write(b"%!PS")
print("Done.", flush=True)
'''
CALIBRATE = _PRELUDE + '''
picks = os.path.join(out, "phase1", "F" + flight + "_cal_picks.json")
if MODE == "refuse" or not os.path.isfile(picks):
    print("No reference-line picks for this TIFF: refusing to calibrate.", flush=True)
    sys.exit(1)
os.makedirs(os.path.join(out, "phase3"), exist_ok=True)
with open(os.path.join(out, "phase3", "F" + flight + "_cal.csv"), "w") as f:
    f.write("frame_idx,cbd,mb_x,y_ref\\n1,471,120,300\\n2,472,121,300\\n3,473,119,300\\n")
for cbd in (471, 472, 473):
    open(os.path.join(out, "phase3", "F%s_4800_CBD%d_cal.png" % (flight, cbd)), "wb").write(PNG)
open(os.path.join(out, "phase3", "F" + flight + "_cal_review.json"), "w").write('{"reviewed": 0}')
'''
ECHOES = _PRELUDE + '''
if MODE == "echofail":
    sys.exit(5)
os.makedirs(os.path.join(out, "phase4"), exist_ok=True)
with open(os.path.join(out, "phase4", "F" + flight + "_echoes.csv"), "w") as f:
    f.write("frame_idx,file_id,echo_status,mb_x,surface_twt_us,bed_twt_us,h_ice_m,bed_snr_dB\\n")
    f.write("1,4800_CBD471,good,120,9.05,16.97,665.4,12.1\\n")
    f.write("2,4800_CBD472,weak_bed,121,8.92,16.86,666.7,3.0\\n")
    f.write("3,4800_CBD473,good,400,8.92,16.82,663.3,11.0\\n")
for cbd in (471, 472):
    open(os.path.join(out, "phase4", "F%s_4800_CBD%d_echoes.png" % (flight, cbd)), "wb").write(PNG)
'''
LIBRARY = "import json\n"
PICKS = {"CBD471": {"mb": 120, "ref": 300, "x_grid": [100, 200], "y_grid": [10, 20]},
         "CBD472": {"mb": 121, "ref": None},
         "CBD473": {"exclude": False}}


def install_lyra(root: Path, mode: str = "ok") -> Path:
    codes = root / "codes"
    codes.mkdir(parents=True, exist_ok=True)
    for name in ("lyra.py", "segment_ocr.py", "build_digit_templates.py"):
        (codes / name).write_text(LIBRARY)
    for name, body in (("detect_frames.py", DETECT), ("calibrate.py", CALIBRATE),
                       ("echoes.py", ECHOES)):
        (codes / name).write_text(body.replace("@MODE@", repr(mode))
                                   .replace("@PNG@", repr(PNG.hex())))
    (codes / "digit_templates.npy").write_bytes(b"\x93NUMPY")
    return root


def _strip(width=1200, height=200):
    img = np.full((height, width), 58000, np.uint16)
    img[150:153, :] = 600
    return img


@pytest.fixture
def env(tmp_path, monkeypatch):
    from icesee_auth import AuthManager

    monkeypatch.setenv("CRYOSTACK_AUTH_DATABASE", str(tmp_path / "auth.db"))
    shared = tmp_path / "shared"
    shared.mkdir()
    write_tiff(shared / CANONICAL, _strip())
    write_tiff(shared / RENAMED, _strip())
    registry = write_registry(tmp_path / "radar_sources.yaml", (
        f"  - key: reel\n    tiff: shared/{CANONICAL}\n    flight: \"127\"\n"
        f"  - key: renamed\n    tiff: shared/{RENAMED}\n"))
    monkeypatch.setenv(SOURCES_ENV, str(registry))
    root = install_lyra(tmp_path / "LYRA")
    monkeypatch.setenv(automatic.LYRA_ROOT_ENV, str(root))
    monkeypatch.delenv(automatic.PICKER_ENV, raising=False)
    monkeypatch.delenv(automatic.LYRA_RENAME_LOGS_ENV, raising=False)
    automatic._availability_cache.clear()
    return {"tmp": tmp_path, "auth": AuthManager(), "workspace": tmp_path / "ws",
            "shared": shared, "lyra": root}


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
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        async with TestClient(TestServer(_app(env))) as client:
            return await script(client)

    return asyncio.run(go())


async def _json(resp):
    return resp.status, await resp.json()


async def _shared(client, ck, source="reel"):
    resp = await client.post(f"{API}/assets/shared", json={"source": source}, cookies=ck)
    return (await resp.json())["asset_id"]


async def _state(client, ck, asset_id):
    return await _json(await client.get(f"{API}/assets/{asset_id}/automatic", cookies=ck))


async def _start(client, ck, asset_id):
    return await _json(await client.post(
        f"{API}/assets/{asset_id}/automatic", json={"action": "start"}, cookies=ck))


async def _wait(client, ck, asset_id, statuses=automatic.FINAL, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _status, body = await _state(client, ck, asset_id)
        if body["job"] and body["job"]["status"] in statuses:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("job did not finish")


async def _upload_guidance(client, ck, asset_id, doc, kind="lyra-guidance",
                           filename="F127_cal_picks.json"):
    import io

    from aiohttp import FormData

    form = FormData()
    form.add_field("kind", kind)
    form.add_field("file", io.BytesIO(json.dumps(doc).encode()), filename=filename)
    return await _json(await client.post(f"{API}/assets/{asset_id}/products", data=form,
                                         cookies=ck))


def _asset_dir(env, user, asset_id):
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=env["workspace"]) / "frozen_legacies" / "radar" / asset_id


# ── picker selection ─────────────────────────────────────────────────
@pytest.mark.parametrize("value, picker", [
    (None, "lyra"), ("lyra", "lyra"), ("ursa", "ursa"), (" URSA ", "ursa"), ("other", "lyra"),
])
def test_lyra_is_the_default_and_ursa_the_rollback(monkeypatch, value, picker):
    if value is None:
        monkeypatch.delenv(automatic.PICKER_ENV, raising=False)
    else:
        monkeypatch.setenv(automatic.PICKER_ENV, value)
    assert automatic.configured_picker() == picker
    assert ("LYRA" in automatic.scientific_note()) == (picker == "lyra")


def test_an_unrecognised_picker_setting_is_logged(monkeypatch, caplog):
    monkeypatch.setenv(automatic.PICKER_ENV, "lyraa")
    automatic._reported_pickers.discard("lyraa")
    with caplog.at_level("WARNING"):
        assert automatic.configured_picker() == "lyra"
    assert "'lyraa' is not one of lyra/ursa" in caplog.text


def test_every_job_records_its_picker_version_from_the_start(env):
    install_lyra(env["lyra"], "noframes")          # even a failed job carries it
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _start(client, ck, asset_id)
        return await _wait(client, ck, asset_id)

    job = session(env, script)["job"]
    assert job["status"] == "failed"
    version = job["picker_version"]
    assert version["picker"] == "lyra" and version["source_files"] == 7
    assert version["source_sha256"] == automatic.lyra_identity(env["lyra"])["source_sha256"]


def test_jobs_report_the_picker_they_ran_with():
    assert automatic.public_job({"picker": "ursa", "status": "completed"})["picker_label"] == "URSA"
    assert automatic.public_job({"picker": "lyra", "status": "completed"})["picker_label"] == "LYRA"


def test_live_progress_is_bounded_validated_and_public(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text(json.dumps({
        "schema": "cryostack.frozen_legacies.lyra_progress", "version": 1,
        "phase": "phase3", "status": "running", "updated_at": 123.5,
        "phases": {"phase1": {"exit": 0, "seconds": 2.1, "log_tail": ["secret"]},
                   "unknown": {"exit": 0}}, "path": "/private/work",
    }))
    progress = automatic._read_lyra_progress(path)
    assert progress == {"phase": "phase3", "status": "running", "updated_at": 123.5,
                        "phases": {"phase1": {"exit": 0, "seconds": 2.1}}}
    assert automatic.public_job({"picker": "lyra", "status": "running",
                                 "progress": progress})["progress"] == progress
    path.write_bytes(b"x" * (automatic.MAX_PROGRESS_BYTES + 1))
    assert automatic._read_lyra_progress(path) is None


def test_completed_lyra_frames_map_only_by_exact_cbd_navigation(tmp_path, monkeypatch):
    index = tmp_path / "index.csv"
    index.write_text("frame_idx,frame_type,cbd,ocr_raw\n1,complete,471,0471\n2,complete,472,\n3,partial,473,0473\n")
    echoes = tmp_path / "echoes.csv"
    echoes.write_text("frame_idx,echo_status,surface_twt_us,bed_twt_us,h_ice_m\n1,good,2,6,336\n2,weak_bed,3,7,336\n")
    monkeypatch.setattr(automatic, "read_job", lambda *_: {
        "picker": "lyra", "status": "completed", "job_id": "lyra-1"})

    def resolve(_workspace, _manifest, _sources, kind):
        path = index if kind == "lyra-frame-index" else echoes
        return {"workflow": "lyra-automatic"}, path

    monkeypatch.setattr(products, "resolve_product", resolve)
    result = automatic.lyra_map_observations(
        object(), {"asset_id": "a" * 32, "flight": "127", "dataset_id": "d"}, {},
        [{"cbd": 471, "lat": -81.5, "lon": 190.0}])
    assert result["total"] == 2 and result["positioned"] == 1
    first, second = result["records"]
    assert first["position"] == [-170.0, -81.5] and first["cbd_source"] == "lyra-ocr"
    assert first["scientific_status"] == "unvalidated" and first["h_ice_m"] == 336
    assert second["position"] is None and second["cbd_source"] == "lyra-sequence"


def test_runtime_limits_reject_invalid_and_dangerous_values(monkeypatch):
    monkeypatch.setenv(automatic.CONCURRENCY_ENV, "999")
    monkeypatch.setenv(automatic.LYRA_TIMEOUT_ENV, "nan")
    assert automatic._bounded_int_env(
        automatic.CONCURRENCY_ENV, 1, 1, automatic.MAX_CONCURRENT_JOBS) == 1
    assert automatic._bounded_float_env(
        automatic.LYRA_TIMEOUT_ENV, 3600, automatic.MIN_TIMEOUT_SECONDS,
        automatic.MAX_TIMEOUT_SECONDS) == 3600


def test_asset_job_lease_excludes_other_gateway_workers(tmp_path):
    class Workspace:
        root = tmp_path

        def asset_dir(self, asset_id):
            path = tmp_path / asset_id
            path.mkdir(exist_ok=True)
            return path

        def asset_file(self, asset_id, name):
            return self.asset_dir(asset_id) / name

    workspace, asset_id = Workspace(), "a" * 32
    first, second = automatic.AutomaticRunner(), automatic.AutomaticRunner()
    first._acquire_lease(workspace, asset_id)
    try:
        with pytest.raises(automatic.AutomaticJobBusy):
            second._acquire_lease(workspace, asset_id)
        automatic.write_job(workspace, asset_id, {
            "schema": automatic.JOB_SCHEMA, "version": automatic.JOB_VERSION,
            "asset_id": asset_id, "picker": "lyra", "status": "running"})
        assert second.current(workspace, asset_id)["status"] == "running"
    finally:
        first._release_lease(first.key(workspace, asset_id))
    assert second.current(workspace, asset_id)["status"] == "interrupted"


def test_cancelled_children_are_signalled_and_reaped():
    class Process:
        returncode = None
        pid = 123
        signal = None

        def send_signal(self, value):
            self.signal = value

        async def wait(self):
            self.returncode = -9
            return self.returncode

    runner, process = automatic.AutomaticRunner(), Process()
    asyncio.run(runner._kill_and_reap("asset", process))
    assert process.signal == automatic.signal.SIGKILL and process.returncode == -9


# ── availability ─────────────────────────────────────────────────────
def test_stand_in_lyra_passes_the_health_check(env):
    state = automatic.availability(refresh=True)
    assert state["available"] is True and state["picker"] == "LYRA"
    assert set(state["environment"]["packages"]) == set(lyra_runner.HEALTH_PACKAGES)
    assert str(env["tmp"]) not in json.dumps(state)          # no server paths


def test_health_check_never_writes_into_a_read_only_lyra(tmp_path):
    """LYRA's modules create directories next to their source on import; the
    check imports a private copy, so a read-only installation passes and is
    left untouched."""
    import os
    import stat
    import subprocess

    root = install_lyra(tmp_path / "LYRA")
    (root / "codes" / "build_digit_templates.py").write_text(
        "from pathlib import Path\n"
        "OUT_DIR = Path(__file__).resolve().parent.parent / 'output' / 'F125'\n"
        "OUT_DIR.mkdir(parents=True, exist_ok=True)\n")
    for path in (root / "codes", root):
        os.chmod(path, stat.S_IRUSR | stat.S_IXUSR)
    try:
        done = subprocess.run([sys.executable, str(automatic.LYRA_RUNNER), "--check",
                               "--lyra-root", str(root)], capture_output=True, text=True,
                              cwd=tmp_path, timeout=120)
    finally:
        for path in (root, root / "codes"):
            os.chmod(path, stat.S_IRWXU)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1])["lyra"] == "importable"
    assert sorted(p.name for p in root.iterdir()) == ["codes"]


def test_missing_lyra_installation(env, monkeypatch, tmp_path):
    monkeypatch.setenv(automatic.LYRA_ROOT_ENV, str(tmp_path / "nowhere"))
    state = automatic.availability(refresh=True)
    assert state == {"available": False, "picker": "LYRA",
                     "reason": "The LYRA automatic picker is not installed on this server."}


def test_lyra_import_failure_names_the_missing_package(env):
    (env["lyra"] / "codes" / "segment_ocr.py").write_text("import module_that_does_not_exist\n")
    state = automatic.availability(refresh=True)
    assert state["available"] is False
    assert "module_that_does_not_exist" in state["reason"]


def test_unavailable_lyra_never_starts_a_job(env, monkeypatch, tmp_path):
    monkeypatch.setenv(automatic.LYRA_ROOT_ENV, str(tmp_path / "nowhere"))
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        _s, body = await _state(client, ck, asset_id)
        assert body["picker_label"] == "LYRA" and body["availability"]["available"] is False
        status, body = await _start(client, ck, asset_id)
        assert status == 409 and body["available"] is False
        return asset_id

    asset_id = session(env, script)
    assert not (_asset_dir(env, user, asset_id) / "automatic.json").exists()


# ── the canonical reel name ──────────────────────────────────────────
def test_canonical_name_comes_from_the_file_name():
    inputs = automatic.lyra_inputs({"filename": CANONICAL, "flight": "F127"})
    assert inputs == {"ok": True, "canonical_name": CANONICAL, "flight": 127,
                      "resolved_by": "file name"}
    missing = automatic.lyra_inputs({"filename": CANONICAL, "flight": None})
    assert missing["ok"] is False and "flight number" in missing["reason"]


def _rename_log(directory: Path, name: str, pairs):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("".join(f"Old: {old}\nNew: {new}\n\n" for old, new in pairs))


def test_canonical_name_from_a_rename_log(env):
    _rename_log(env["lyra"] / "rename_logs", "F127_rename_log.txt",
                [("47_0004800_0004824-reel_begin_end.tiff", RENAMED)])
    inputs = automatic.lyra_inputs({"filename": RENAMED, "flight": "127"})
    assert inputs["ok"] is True and inputs["canonical_name"] == CANONICAL
    assert inputs["resolved_by"] == "rename log"
    assert [log["name"] for log in inputs["rename_logs"]] == ["F127_rename_log.txt"]


def test_rename_log_for_another_flight_is_not_trusted(env):
    # the asset is recorded as F127; the log names the same segment as F128
    _rename_log(env["lyra"] / "rename_logs", "F128_rename_log.txt",
                [("47_0004800_0004824-reel_begin_end.tiff", "F128-C0471_C0475.tiff")])
    inputs = automatic.lyra_inputs({"filename": "F128-C0471_C0475.tiff", "flight": "127"})
    assert inputs["ok"] is False and "different flight" in inputs["reason"]
    assert "F128_rename_log.txt: F128" in inputs["reason"]


def test_ambiguous_rename_logs_are_not_guessed(env):
    _rename_log(env["lyra"] / "rename_logs", "a_rename_log.txt",
                [("47_0004800_0004824-reel_begin_end.tiff", RENAMED)])
    _rename_log(env["lyra"] / "rename_logs", "b_rename_log.txt",
                [("48_0004900_0004924-reel_begin_end.tiff", RENAMED)])
    inputs = automatic.lyra_inputs({"filename": RENAMED, "flight": "127"})
    assert inputs["ok"] is False and "more than one original reel name" in inputs["reason"]


def test_unmapped_file_is_not_offered_to_lyra(env):
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck, "renamed")
        _s, body = await _state(client, ck, asset_id)
        assert body["lyra"]["runnable"] is False
        assert "original reel name" in body["lyra"]["reason"]
        assert any("original reel name" in w for w in body["warnings"])
        status, body = await _start(client, ck, asset_id)
        assert status == 409 and "original reel name" in body["error"]
        return asset_id

    asset_id = session(env, script)
    assert not (_asset_dir(env, user, asset_id) / "automatic.json").exists()


# ── calibration guidance (LYRA's own picks file) ─────────────────────
@pytest.mark.parametrize("doc, message", [
    ({}, "non-empty"),
    ({"frame1": {}}, "Unexpected frame key"),
    ({"CBD471": {"mb": "120"}}, "must be a number"),
    ({"CBD471": {"mb": True}}, "must be a number"),
    ({"CBD471": {"x_grid": list(range(40))}}, "short list"),
    ({"CBD471": {"path": "/etc/passwd"}}, "Unexpected field"),
])
def test_invalid_calibration_picks_are_rejected(doc, message):
    with pytest.raises(lyra_runner.GuidanceError, match=message):
        lyra_runner.validate_picks(doc)


def test_guidance_upload_is_validated_and_summarized(env):
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        bad = await _upload_guidance(client, ck, asset_id, {"CBD471": {"mb": "x"}})
        good = await _upload_guidance(client, ck, asset_id, PICKS)
        _s, state = await _state(client, ck, asset_id)
        return bad, good, state

    (bad_status, bad), (good_status, good), state = session(env, script)
    assert bad_status in (400, 422) and "must be a number" in json.dumps(bad)
    assert good_status in (200, 201)
    product = good.get("product") or next(
        p for p in good["products"] if p["kind"] == "lyra-guidance")
    assert product["producer"] == "user"
    assert product["summary"]["rows"] == 3 and product["summary"]["frames_with_reference"] == 1
    assert state["lyra"]["guidance"]["picks"]["summary"]["rows"] == 3
    assert not any("No LYRA calibration picks" in w for w in state["warnings"])


# ── lifecycle ────────────────────────────────────────────────────────
def test_without_guidance_lyra_stops_after_frame_detection(env, monkeypatch):
    # a gateway secret must never reach LYRA's processes
    monkeypatch.setenv("CRYOSTACK_TEST_SECRET", "do-not-leak")
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        _s, before = await _state(client, ck, asset_id)
        status, body = await _start(client, ck, asset_id)
        assert status == 200 and body["job"]["picker"] == "lyra"
        done = await _wait(client, ck, asset_id)
        listed = (await (await client.get(f"{API}/assets/{asset_id}/products",
                                          cookies=ck)).json())["products"]
        return asset_id, before, done, listed

    asset_id, before, done, listed = session(env, script)
    assert any("No LYRA calibration picks uploaded" in w for w in before["warnings"])
    assert any("no latitude/longitude" in w for w in before["warnings"])
    job = done["job"]
    assert job["status"] == "completed" and job["picker_label"] == "LYRA"
    assert job["message"] == automatic.LYRA_STOPPED["calibration-guidance-required"]
    assert job["summary"]["frames"] == 4 and job["summary"]["complete_frames"] == 3
    assert job["summary"]["stopped"] == "calibration-guidance-required"
    lyra = {p["kind"] for p in listed if p["workflow"] == "lyra-automatic"}
    # only what LYRA actually wrote: no calibration, no echoes
    assert lyra == {"lyra-frame-index", "lyra-diagnostic"}
    diagnostics = sorted(p["product_id"] for p in listed if p["kind"] == "lyra-diagnostic")
    assert diagnostics == ["lyra-diag-contact", "lyra-diag-ocr-diag"]
    # whole-strip figures are shown beside the frames, not per frame
    frames = done["frames"]
    assert [i["product_id"] for i in frames["strip_images"]] == diagnostics
    assert frames["picker_label"] == "LYRA" and frames["columns"][0] == "Frame"
    # LYRA ran on the TIFF under its canonical reel name; the log has no paths
    log = "\n".join(job["log_tail"])
    assert f"reading tiff/127/{CANONICAL} exists=True" in log
    assert "SECRET_SEEN=False" in log and str(env["tmp"]) not in log
    assert not (_asset_dir(env, user, asset_id) / automatic.WORK_DIRNAME).exists()
    assert done["scientific_status"] == "unvalidated" and done["publication_eligible"] is False
    assert "LYRA" in done["scientific_note"]


def test_with_guidance_lyra_calibrates_and_extracts_echoes(env):
    user, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _upload_guidance(client, ck, asset_id, PICKS)
        await _start(client, ck, asset_id)
        done = await _wait(client, ck, asset_id)
        listed = (await (await client.get(f"{API}/assets/{asset_id}/products",
                                          cookies=ck)).json())["products"]
        return asset_id, done, listed

    asset_id, done, listed = session(env, script)
    job = done["job"]
    assert job["status"] == "completed" and job["message"] == automatic.LYRA_STOPPED[None]
    assert job["summary"]["echo_rows"] == 3
    assert job["summary"]["echo_status"] == {"good": 2, "weak_bed": 1}
    kinds = {p["kind"] for p in done["products"]}
    assert kinds == {"lyra-frame-index", "lyra-calibration", "lyra-run-echoes"}
    assert all(p["scientific_status"] == "unvalidated" for p in done["products"])
    # provenance names LYRA's code, the TIFF and the guidance by digest
    provenance = job["provenance"]
    assert provenance["canonical_name"] == CANONICAL and provenance["flight"] == 127
    assert provenance["inputs"]["calibration_picks"]["sha256"]
    assert provenance["lyra"]["source_sha256"] and provenance["lyra_reviews"]["calibration"] == {
        "reviewed": 0}
    assert set(provenance["phases"]) == {"phase1", "phase3", "phase4"}
    # per-frame view: LYRA's values as written, heuristic flags, frame images
    rows = {r["frame"]: r for r in done["frames"]["rows"]}
    assert rows[1]["values"][:4] == ["1", "complete", "0471", "1270471"]
    assert rows[1]["flags"] == []
    assert rows[2]["flags"] == ["CBD inferred from the sequence: OCR read nothing",
                                "LYRA echo status: weak_bed"]
    assert rows[3]["flags"] == ["main bang position: 400 px vs strip median 121 px"]
    assert sorted(i["label"] for i in rows[1]["images"]) == [
        automatic.LYRA_FIGURE_LABELS["cal"], automatic.LYRA_FIGURE_LABELS["echoes"]]
    assert [i["label"] for i in rows[3]["images"]] == [automatic.LYRA_FIGURE_LABELS["cal"]]
    assert rows[0]["images"] == []
    # LYRA's echo CSV is kept byte for byte, never re-written
    echoes = next(p for p in listed if p["kind"] == "lyra-run-echoes")
    stored = (_asset_dir(env, user, asset_id) / "outputs" / echoes["filename"]).read_text()
    assert stored.splitlines()[2] == "2,4800_CBD472,weak_bed,121,8.92,16.86,666.7,3.0"


def test_rerun_without_echoes_removes_the_previous_echoes(env):
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _upload_guidance(client, ck, asset_id, PICKS)
        await _start(client, ck, asset_id)
        first = await _wait(client, ck, asset_id)
        install_lyra(env["lyra"], "refuse")
        automatic._availability_cache.clear()
        await asyncio.sleep(0.05)
        await _start(client, ck, asset_id)
        second = await _wait(client, ck, asset_id)
        return first, second

    first, second = session(env, script)
    assert {p["kind"] for p in first["products"]} >= {"lyra-calibration", "lyra-run-echoes"}
    assert second["job"]["message"] == automatic.LYRA_STOPPED["phase3-refused"]
    # a later run never leaves an earlier run's echoes looking current
    assert {p["kind"] for p in second["products"]} == {"lyra-frame-index"}
    assert "No reference-line picks" in "\n".join(second["job"]["log_tail"])


@pytest.mark.parametrize("mode, status, message", [
    ("noframes", "failed", "LYRA finished without detecting frames."),
    ("echofail", "completed", automatic.LYRA_STOPPED["phase4-failed"]),
])
def test_phase_failures_are_reported(env, mode, status, message):
    install_lyra(env["lyra"], mode)
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _upload_guidance(client, ck, asset_id, PICKS)
        await _start(client, ck, asset_id)
        return await _wait(client, ck, asset_id)

    done = session(env, script)
    assert done["job"]["status"] == status and done["job"]["message"] == message
    assert not any(p["kind"] == "lyra-run-echoes" for p in done["products"])


def test_cancel_stops_lyras_process_group(env):
    install_lyra(env["lyra"], "slow")
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _start(client, ck, asset_id)
        await _wait(client, ck, asset_id, statuses=("running",))
        await asyncio.sleep(0.5)                     # the phase script is sleeping
        started = time.time()
        status, body = await _json(await client.post(
            f"{API}/assets/{asset_id}/automatic", json={"action": "cancel"}, cookies=ck))
        return status, body, time.time() - started

    status, body, seconds = session(env, script)
    assert status == 200 and body["job"]["status"] == "cancelled"
    assert seconds < 15 and body["products"] == []


def test_lyra_stops_when_the_server_dies(env, tmp_path):
    """A gateway killed outright never leaves LYRA running for a job the
    restarted gateway reports as interrupted."""
    import os
    import signal
    import subprocess

    install_lyra(env["lyra"], "slow")
    tiff = env["shared"] / CANONICAL
    pidfile = tmp_path / "runner.pid"
    # stands in for the gateway: starts the runner, then is killed outright
    server_code = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, {str(automatic.LYRA_RUNNER)!r}, '--lyra-root', "
        f"{str(env['lyra'])!r}, '--tiff', {str(tiff)!r}, '--canonical-name', {CANONICAL!r}, "
        f"'--flight', '127', '--work', {str(tmp_path / 'work')!r}], start_new_session=True)\n"
        f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(120)\n")
    server = subprocess.Popen([sys.executable, "-c", server_code])
    deadline = time.time() + 30
    log = tmp_path / "work" / "logs" / "phase1.log"
    while time.time() < deadline and not (pidfile.exists() and log.exists()):
        time.sleep(0.2)
    runner = int(pidfile.read_text())
    os.kill(server.pid, signal.SIGKILL)
    server.wait()

    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        state = Path(f"/proc/{pid}/stat").read_text().split()[2] if Path(f"/proc/{pid}/stat").exists() else "X"
        return state != "Z"

    deadline = time.time() + 20
    while time.time() < deadline and alive(runner):
        time.sleep(0.2)
    assert not alive(runner)
    # LYRA's phase script (the runner's child) was stopped as well
    leftover = subprocess.run(["pgrep", "-f", str(tmp_path / "work")], capture_output=True, text=True)
    assert leftover.stdout.strip() == ""


def test_ursa_rollback_keeps_lyra_results_readable(env, monkeypatch):
    """Switching the picker never hides results: they are shown for the
    picker of the asset's job, and new runs use the configured one."""
    _u, ck = _login(env, "a@example.org")

    async def script(client):
        asset_id = await _shared(client, ck)
        await _start(client, ck, asset_id)
        await _wait(client, ck, asset_id)
        monkeypatch.setenv(automatic.PICKER_ENV, "ursa")
        _s, body = await _state(client, ck, asset_id)
        return body

    body = session(env, script)
    assert body["picker"] == "ursa" and body["picker_label"] == "URSA"
    assert body["job"]["picker_label"] == "LYRA"
    assert {p["kind"] for p in body["products"]} == {"lyra-frame-index"}
    assert body["frames"]["picker_label"] == "LYRA" and "LYRA" in body["scientific_note"]
    assert "lyra" not in body


def test_lyra_jobs_belong_to_their_owner(env):
    _a, ck_a = _login(env, "a@example.org")
    _b, ck_b = _login(env, "b@example.org")

    async def script(client):
        asset_id = await _shared(client, ck_a)
        resp = await client.post(f"{API}/assets/{asset_id}/automatic", json={"action": "start"},
                                 cookies=ck_b)
        return resp.status

    assert session(env, script) == 404


# ── frame table (display only) ───────────────────────────────────────
def test_frame_keys_follow_lyras_figure_names():
    index = [{"frame_idx": "0", "frame_type": "partial", "cbd": ""},
             {"frame_idx": "1", "frame_type": "complete", "cbd": "0810"},
             {"frame_idx": "2", "frame_type": "complete", "cbd": "0810"},
             {"frame_idx": "3", "frame_type": "complete", "cbd": "0811"}]
    duplicates = {810}
    assert [automatic._lyra_frame_key(r, duplicates) for r in index] == [
        "fr00", "CBD810_f1", "CBD810_f2", "CBD811"]
    for name, key in (("F127_4800_CBD810_f1_cal.png", "CBD810_f1"),
                      ("F127_4800_CBD811_echoes.png", "CBD811"),
                      ("F127_4800_fr00_cal.png", "fr00")):
        assert automatic._LYRA_FRAME_FIGURE.fullmatch(name).group(1) == key


def test_frame_table_never_changes_lyras_values():
    table = automatic.lyra_frame_table(
        [{"frame_idx": "1", "frame_type": "complete", "cbd": "0471", "ocr_raw": "1270471"}],
        [{"frame_idx": "1", "echo_status": "good", "mb_x": "120.50", "h_ice_m": "665.40"}])
    assert table["rows"][0]["values"][5] == "120.50" and table["rows"][0]["values"][8] == "665.40"
    assert table["rows"][0]["flags"] == []


def test_lyra_products_are_never_publishable():
    assert "lyra-automatic" in products.AUTOMATIC_WORKFLOWS
    assert products.DIAGNOSTIC_KINDS["lyra-diagnostic"] == "LYRA diagnostic (unvalidated)"
