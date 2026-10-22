"""Manual (ASTRA) picking API: owner-scoped sessions, a compact action
protocol, atomic session/output files, downloads, and the security cases."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import write_nav, write_registry, write_tiff
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
P = pytest.importorskip("icesee_jupyter_book.applications.frozen_legacies.pickers.astra",
                        reason="the ASTRA picker is distributed separately")
from icesee_jupyter_book.applications.frozen_legacies.radar import manual
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV

API = "/frozen-legacies/api"
NAME = "F127-C0471_C0483.tiff"


def _strip(width=3000, height=420):
    """Small A-scope-like strip (ASTRA working window: 2300 x 170)."""
    img = np.full((height, width), 58000, np.uint16)
    x = np.arange(width)
    centre = (330 + 40 * np.sin(x / 50.0)).astype(int)
    for dy in range(-3, 4):
        img[np.clip(centre + dy, 0, height - 1), x] = 600
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
        f"  - key: f127\n    tiff: shared/{NAME}\n    nav: shared/127.csv\n"
    ))
    monkeypatch.setenv(SOURCES_ENV, str(registry))
    return {"tmp": tmp_path, "auth": AuthManager(), "workspace": tmp_path / "ws", "shared": shared}


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


class Client:
    """A test client bound to one app and one user's cookies."""

    def __init__(self, env, cookies):
        self.env, self.cookies = env, cookies

    def run(self, coro_fn):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(_app(self.env))) as client:
                return await coro_fn(client)

        return asyncio.run(go())

    def request(self, method, path, **kwargs):
        async def call(client):
            resp = await client.request(method, path, cookies=self.cookies,
                                        allow_redirects=False, **kwargs)
            return resp.status, resp.headers, await resp.read()
        return self.run(call)

    def json(self, method, path, **kwargs):
        status, headers, body = self.request(method, path, **kwargs)
        return status, (json.loads(body) if body else None)


def _open_shared(client) -> str:
    status, asset = client.json("POST", f"{API}/assets/shared", json={"source": "f127"})
    assert status == 201
    return asset["asset_id"]


def _asset_dir(env, user, asset_id) -> Path:
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=env["workspace"]) / "frozen_legacies" / "radar" / asset_id


class Picker:
    def __init__(self, client, asset_id):
        self.client, self.asset_id = client, asset_id
        self.url = f"{API}/assets/{asset_id}/manual"
        status, self.session = client.json("GET", self.url)
        assert status == 200

    def act(self, expect=200, **payload):
        payload.setdefault("revision", self.session["revision"])
        status, body = self.client.json("POST", self.url, json=payload)
        assert status == expect, body
        if status == 200:
            self.session = body
        return body


def _calibrated_session(picker):
    picker.act(action="setup", target="x_reference"); picker.act(action="click", x=100.6, y=10)
    picker.act(action="setup", target="y_reference"); picker.act(action="click", x=5, y=160.2)
    picker.act(action="setup", target="y_axis")
    for y in (150.0, 120.0, 90.0, 60.0):
        picker.act(action="click", x=5, y=y)
    picker.act(action="setup", target="x_axis")
    for x in (200.0, 400.0, 600.0, 800.0):
        picker.act(action="click", x=x, y=5)


# ── authentication / ownership ───────────────────────────────────────
@pytest.mark.parametrize("method, suffix", [
    ("GET", "/manual"), ("POST", "/manual"), ("GET", "/manual/window?slider=0"),
    ("GET", "/outputs/astra-csv"), ("GET", "/outputs/astra-qc"),
])
def test_manual_routes_require_authentication(env, method, suffix):
    status, _h, body = Client(env, None).request(method, f"{API}/assets/{'a' * 32}{suffix}")
    assert status == 401 and json.loads(body)["error"] == "Authentication required."


@pytest.mark.parametrize("method, suffix", [
    ("GET", "/manual"), ("GET", "/manual/window?slider=0"), ("GET", "/outputs/astra-csv"),
])
def test_other_users_cannot_reach_a_manual_session(env, method, suffix):
    _a, ca = _login(env, "a@example.org")
    _b, cb = _login(env, "b@example.org")
    a = Client(env, ca)
    asset_id = _open_shared(a)
    picker = Picker(a, asset_id)
    picker.act(action="suggest"); picker.act(action="next")
    status, _h, _b2 = Client(env, cb).request(method, f"{API}/assets/{asset_id}{suffix}")
    assert status == 404
    status, _body = Client(env, cb).json("POST", f"{API}/assets/{asset_id}/manual",
                                         json={"action": "next", "revision": 1})
    assert status == 404


@pytest.mark.parametrize("asset_id", ["..", "A" * 32, "0" * 31, "%2e%2e%2f" + "0" * 23])
def test_malformed_asset_ids(env, asset_id):
    _u, cookies = _login(env, "a@example.org")
    for suffix in ("/manual", "/manual/window?slider=0", "/outputs/astra-csv"):
        status, _h, _b = Client(env, cookies).request("GET", f"{API}/assets/{asset_id}{suffix}")
        assert status == 404


def test_cross_origin_actions_are_refused(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    status, _h, _b = client.request("POST", f"{API}/assets/{asset_id}/manual",
                                    json={"action": "next", "revision": 0},
                                    headers={"Origin": "https://evil.example"})
    assert status == 403


# ── session lifecycle ────────────────────────────────────────────────
def test_a_new_session_is_not_written_until_the_first_action(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    assert picker.session["status"] == "new" and picker.session["title"] == "A-scope 1: CBD 471"
    assert picker.session["geometry"]["zoom_height"] == 170
    assert picker.session["geometry"]["slider_max"] == 3000 - 200
    assert len(picker.session["trace"]) == 2300
    directory = _asset_dir(env, user, asset_id)
    assert not (directory / "session.json").exists()
    picker.act(action="setup", target="x_reference")
    doc = json.loads((directory / "session.json").read_text())
    assert doc["status"] == "in_progress" and doc["revision"] == 1


def test_session_persists_across_reloads(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    _calibrated_session(picker)
    picker.act(action="step", step="jump")
    picker.act(action="select", feature="Main Bang"); picker.act(action="click", x=120.2, y=20)
    reloaded = Picker(client, asset_id)
    assert reloaded.session["state"] == picker.session["state"]
    assert reloaded.session["picks"]["mainbang"]["x_orig"] == 1120
    assert reloaded.session["revision"] == picker.session["revision"]


def test_session_file_contains_no_identity_or_paths(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    _calibrated_session(picker)
    picker.act(action="suggest"); picker.act(action="next")
    text = (_asset_dir(env, user, asset_id) / "session.json").read_text()
    for forbidden in (user.id, "a@example.org", str(env["tmp"]), str(env["shared"]), "users/"):
        assert forbidden not in text


def test_done_writes_astra_outputs_and_keeps_the_tiff(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    _calibrated_session(picker)
    picker.act(action="suggest"); picker.act(action="next")
    picker.act(action="step", step="jump"); picker.act(action="suggest")
    done = picker.act(action="done")
    assert done["status"] == "completed"
    assert set(done["outputs"]) == {"astra-csv", "astra-qc"}
    outputs = _asset_dir(env, user, asset_id) / "outputs"
    assert sorted(p.name for p in outputs.iterdir()) == [
        "F127-C0471_C0483.csv", "F127-C0471_C0483_QC.png"]
    assert (env["shared"] / NAME).is_file()                       # never moved
    rows = list(csv.reader(io.StringIO((outputs / "F127-C0471_C0483.csv").read_text())))
    assert rows[0] == done["committed"]["columns"] and rows[1:] == done["committed"]["rows"]
    assert [r[22] for r in rows[1:]] == ["471", "483"]            # ASTRA CBD by row order
    assert rows[1][23] == "-81.479401"                            # exact nav match
    # a completed session refuses further picking
    picker.act(expect=409, action="next")


def test_csv_is_rewritten_on_next_like_astra(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="next")
    path = _asset_dir(env, user, asset_id) / "outputs" / "F127-C0471_C0483.csv"
    assert len(list(csv.reader(io.StringIO(path.read_text())))) == 2
    assert not (path.parent / "F127-C0471_C0483_QC.png").exists()
    status, headers, body = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-csv")
    assert status == 200 and body == path.read_bytes()


def test_reset_requires_confirmation_and_keeps_the_radar(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="done")
    picker.act(expect=400, action="reset")
    reset = picker.act(action="reset", confirm=True)
    assert reset["status"] == "new" and reset["outputs"] == {}
    directory = _asset_dir(env, user, asset_id)
    assert sorted(p.name for p in directory.iterdir()) == ["asset.json", "outputs"]
    assert list((directory / "outputs").iterdir()) == []
    assert (env["shared"] / NAME).is_file()


# ── downloads ────────────────────────────────────────────────────────
def test_downloads_are_attachments_with_safe_names(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="done")
    status, headers, body = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-qc")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert headers["Content-Disposition"] == 'attachment; filename="F127-C0471_C0483_QC.png"'
    assert "no-store" in headers["Cache-Control"]
    assert Image.open(io.BytesIO(body)).size == (3000, 420)       # full TIFF, like ASTRA
    status, headers, _b = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-csv")
    assert headers["Content-Disposition"] == 'attachment; filename="F127-C0471_C0483.csv"'


@pytest.mark.parametrize("product", [
    "astra-csv%2F..%2F..%2Fasset.json", "../asset.json", "source.tiff", "session.json",
    "F127-C0471_C0483.csv", "astra-png", "", "astra-csv/extra",
])
def test_only_named_products_can_be_downloaded(env, product):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="done")
    status, _h, body = client.request("GET", f"{API}/assets/{asset_id}/outputs/{product}")
    assert status == 404
    assert b"58000" not in body


def test_download_before_generation_is_not_found(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    status, _h, _b = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-qc")
    assert status == 404


def test_symlinked_outputs_are_refused(env, tmp_path):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="next")
    outputs = _asset_dir(env, user, asset_id) / "outputs"
    secret = tmp_path / "secret.csv"
    secret.write_text("secret")
    (outputs / "F127-C0471_C0483.csv").unlink()
    (outputs / "F127-C0471_C0483.csv").symlink_to(secret)
    status, _h, body = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-csv")
    assert status == 404 and b"secret" not in body
    picker.act(expect=404, action="next")                  # will not write through the link
    assert secret.read_text() == "secret"

    # the whole outputs directory replaced by a link
    (outputs / "F127-C0471_C0483.csv").unlink()
    outputs.rmdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outputs.symlink_to(elsewhere)
    status, _h, _b = client.request("GET", f"{API}/assets/{asset_id}/outputs/astra-csv")
    assert status == 404
    picker.act(expect=404, action="next")
    assert list(elsewhere.iterdir()) == []


# ── action validation ────────────────────────────────────────────────
@pytest.mark.parametrize("payload, status", [
    ({"action": "explode"}, 400),
    ({"action": "setup", "target": "z_axis"}, 400),
    ({"action": "select", "feature": "Basal Ice"}, 400),
    ({"action": "sweep_rate", "rate": 3}, 400),
    ({"action": "sweep_rate", "rate": "2"}, 400),
    ({"action": "move", "slider": -1}, 400),
    ({"action": "move", "slider": 2801}, 400),
    ({"action": "move", "slider": 1.5}, 400),
    ({"action": "move", "slider": True}, 400),
    ({"action": "step", "step": "far"}, 400),
    ({"action": "click", "x": "1", "y": 2}, 400),
    ({"action": "click", "x": 2299.5, "y": 2}, 400),          # outside the window
    ({"action": "click", "x": -0.6, "y": 2}, 400),
    ({"action": "click", "x": 10, "y": 169.5}, 400),
    ({"action": "click", "x": 10, "y": None}, 400),
    ({"action": "click", "x": float("nan"), "y": 1}, 400),
    ({"action": "reset"}, 400),
])
def test_invalid_actions_are_rejected_without_changing_the_session(env, payload, status):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="setup", target="x_reference")
    before = (_asset_dir(env, user, asset_id) / "session.json").read_bytes()
    payload = {"revision": picker.session["revision"], **payload}
    body = json.dumps(payload)                     # NaN is sent as a bare NaN token
    got, _h, _b = client.request("POST", picker.url, data=body,
                                 headers={"Content-Type": "application/json"})
    assert got == status
    assert (_asset_dir(env, user, asset_id) / "session.json").read_bytes() == before


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"revision": 0}', b'{"action": 5}'])
def test_malformed_bodies(env, body):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    status, _h, _b = client.request("POST", f"{API}/assets/{asset_id}/manual", data=body,
                                    headers={"Content-Type": "application/json"})
    assert status == 400


def test_oversized_action_body(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    body = json.dumps({"action": "next", "revision": 0, "pad": "x" * 20000})
    status, _h, _b = client.request("POST", f"{API}/assets/{asset_id}/manual", data=body,
                                    headers={"Content-Type": "application/json"})
    assert status == 413


def test_window_requests_are_bounded(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    base = f"{API}/assets/{asset_id}/manual/window"
    status, headers, png = client.request("GET", f"{base}?slider=2800")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(png)).size == (1150, 85)       # 2300 x 170 / display scale 2
    for query in ("slider=2801", "slider=-1", "slider=a", ""):
        assert client.request("GET", f"{base}?{query}")[0] == 400


# ── tampering, concurrency, interruption ─────────────────────────────
@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema="other"),
    lambda d: d.update(asset_id="0" * 32),
    lambda d: d["state"].update(slider=10**9),
    lambda d: d["state"].update(sweep_rate=3),
    lambda d: d["state"].update(surface_coords=[1, 2, 3]),
    lambda d: d["state"].update(surface_coords=[5000, 1, 1, 251]),
    lambda d: d["state"].update(current_feature="Anything"),
    lambda d: d["state"].update(data=[[1] * 22]),
    lambda d: d["state"].update(y_axis_points=[1e9]),
    lambda d: d["state"].update(extra_field=1),
    lambda d: d.update(revision=-1),
    lambda d: d.update(status="hacked"),
])
def test_tampered_sessions_are_refused_and_can_be_reset(env, mutate):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="next")
    path = _asset_dir(env, user, asset_id) / "session.json"
    doc = json.loads(path.read_text())
    mutate(doc)
    path.write_text(json.dumps(doc))
    status, body = client.json("GET", picker.url)
    assert status == 409 and body["session_invalid"] is True
    status, body = client.json("POST", picker.url, json={"action": "next", "revision": 2})
    assert status == 409
    status, body = client.json("POST", picker.url, json={"action": "reset", "confirm": True})
    assert status == 200 and body["status"] == "new"


def test_corrupt_or_oversized_session_files(env, monkeypatch):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    path = _asset_dir(env, user, asset_id) / "session.json"
    path.write_text('{"truncated": ')
    assert client.json("GET", f"{API}/assets/{asset_id}/manual")[0] == 409
    path.write_text(" " * 64)
    monkeypatch.setattr(manual, "MAX_SESSION_BYTES", 10)
    assert client.json("GET", f"{API}/assets/{asset_id}/manual")[0] == 409


def test_stale_revisions_conflict_instead_of_overwriting(env):
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    tab_a = Picker(client, asset_id)
    tab_b = Picker(client, asset_id)
    tab_a.act(action="suggest")
    body = tab_b.act(expect=409, action="next")                  # tab B is behind
    assert "another window" in body["error"]


def test_concurrent_actions_are_serialized(env):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    url = f"{API}/assets/{asset_id}/manual"

    async def both(c):
        async def post(payload):
            resp = await c.post(url, json=payload, cookies=cookies)
            return resp.status
        return await asyncio.gather(*(post({"action": "suggest", "revision": 0}) for _ in range(6)))

    statuses = client.run(both)
    assert sorted(statuses) == [200] + [409] * 5
    doc = json.loads((_asset_dir(env, user, asset_id) / "session.json").read_text())
    assert doc["revision"] == 1
    assert not [p for p in _asset_dir(env, user, asset_id).rglob("*.tmp")]


def test_interrupted_output_generation_leaves_the_session_unfinished(env, monkeypatch):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest"); picker.act(action="next")
    directory = _asset_dir(env, user, asset_id)
    csv_before = (directory / "outputs" / "F127-C0471_C0483.csv").read_bytes()
    session_before = (directory / "session.json").read_bytes()

    def failing_qc(tiff_path, data, out_path):
        Path(out_path).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(manual, "save_qc_image", failing_qc)
    status, _h, _b = client.request("POST", picker.url, json={
        "action": "done", "revision": picker.session["revision"]})
    assert status == 500 and b"could not write" in _b
    assert (directory / "session.json").read_bytes() == session_before
    assert (directory / "outputs" / "F127-C0471_C0483.csv").read_bytes() == csv_before
    assert not (directory / "outputs" / "F127-C0471_C0483_QC.png").exists()
    assert not [p for p in directory.rglob("*.tmp")]
    status, body = client.json("GET", picker.url)
    assert body["status"] == "in_progress"


def test_session_write_is_atomic(env, monkeypatch):
    user, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    picker.act(action="suggest")
    path = _asset_dir(env, user, asset_id) / "session.json"
    before = path.read_bytes()

    def failing_replace(src, dst):
        raise OSError("interrupted")

    monkeypatch.setattr(manual.os, "replace", failing_replace)
    status, _h, _b = client.request("POST", picker.url, json={
        "action": "next", "revision": picker.session["revision"]})
    assert status == 500
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert not [p for p in path.parent.rglob("*.tmp")]


def test_session_parity_through_the_api_matches_the_port(env):
    """The HTTP protocol applies exactly the port's state machine."""
    _u, cookies = _login(env, "a@example.org")
    client = Client(env, cookies)
    asset_id = _open_shared(client)
    picker = Picker(client, asset_id)
    _calibrated_session(picker)
    picker.act(action="select", feature="Noise Floor"); picker.act(action="click", x=1500.4, y=3)
    picker.act(action="select", feature="Main Bang"); picker.act(action="click", x=150.2, y=3)
    picker.act(action="next")

    pixels = _strip()
    g = P.AstraGeometry.for_image(3000, 420)
    s = P.AstraSession(g, NAME)
    trace = lambda: P.astra_trace(P.astra_window(pixels, g, s.slider))[1]
    s.setup_x_reference_line(); s.on_click(100.6, 10, trace())
    s.setup_reference_line(); s.on_click(5, 160.2, trace())
    s.setup_y_axis()
    for y in (150.0, 120.0, 90.0, 60.0):
        s.on_click(5, y, trace())
    s.setup_x_axis()
    for x in (200.0, 400.0, 600.0, 800.0):
        s.on_click(x, 5, trace())
    s.select_feature("Noise Floor"); s.on_click(1500.4, 3, trace())
    s.select_feature("Main Bang"); s.on_click(150.2, 3, trace())
    s.next_ascope()
    assert picker.session["state"] == s.to_state()
    assert picker.session["trace"] == [int(v) for v in trace()]
