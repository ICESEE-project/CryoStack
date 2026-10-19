"""Persistence across gateway restarts, through the real gateway assembly
(``bin/icesee_app.make_app``) in a subprocess with ``CRYOSTACK_DATA_ROOT``:
an uploaded radar asset and processed product, a registered and indexed
external data source, a Control Center setting with its audit record, and
the users' sessions all survive a crash (SIGKILL) and a clean restart, and
every byte of state is written under the data root -- none in the source
tree."""
from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
FL_TESTS = REPO / "icesee_jupyter_book" / "applications" / "frozen_legacies" / "tests"
for _p in (str(REPO), str(FL_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cryostack_src import storage_layout as layout  # noqa: E402

API = "/frozen-legacies/api"
def _png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("L", (64, 32), 128).save(out, format="PNG")
    return out.getvalue()


PNG = _png()
RUNNER = """
import sys
from pathlib import Path
repo = Path(sys.argv[1]); sys.path[:0] = [str(repo), str(repo / "bin")]
import icesee_app
from aiohttp import web
app = icesee_app.make_app()
app.on_startup.clear()             # no Voila services; Frozen Legacies cleanup is kept
keep = [h for h in app.on_cleanup if "frozen_legacies" in getattr(h, "__module__", "")]
app.on_cleanup.clear(); app.on_cleanup.extend(keep)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[2]), print=None)
"""


def _strip(width=1200, height=200):
    img = np.full((height, width), 58000, np.uint16)
    img[150:153, :] = 600
    return img


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def installation(tmp_path):
    from frozen_legacies_radar_fixtures import tiff_bytes, write_tiff
    from icesee_auth.storage import AuthStorage

    data, archive = tmp_path / "data", tmp_path / "archive"
    archive.mkdir()
    write_tiff(archive / "F127-C0471_C0472.tiff", _strip())
    env = {k: v for k, v in os.environ.items()
           if k not in {s.env for s in layout.STORES} | {layout.REQUIRE_ENV}}
    env.update({layout.DATA_ROOT_ENV: str(data),
                "CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS": str(archive),
                "MPLBACKEND": "Agg"})
    auth = AuthStorage(data / "db" / "cryostack_auth.db")
    users = {}
    for name, role in (("alice", None), ("maint", "maintainer")):
        user = auth.create_user(email=f"{name}@example.org", display_name=name, institution=None,
                                password_hash="x")
        if role:
            auth.grant_role(user_id=user.id, role=role)
        users[name] = auth.create_session(ttl_seconds=3600, user_id=user.id).id
    return {"data": data, "archive": archive, "env": env, "cookies": users,
            "tiff": tiff_bytes(_strip()), "port": _free_port()}


class Gateway:
    def __init__(self, inst):
        self.inst = inst
        self.process = None

    def start(self):
        self.process = subprocess.Popen([sys.executable, "-c", RUNNER, str(REPO),
                                         str(self.inst["port"])], env=self.inst["env"],
                                        cwd=self.inst["data"].parent, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("gateway exited: " + self.process.stderr.read()[-2000:])
            try:
                socket.create_connection(("127.0.0.1", self.inst["port"]), timeout=1).close()
                return
            except OSError:
                time.sleep(0.2)
        raise AssertionError("gateway did not start")

    def stop(self, sig):
        self.process.send_signal(sig)
        self.process.wait(timeout=30)


def run(inst, script):
    import aiohttp

    async def go():
        base = f"http://127.0.0.1:{inst['port']}"
        async with aiohttp.ClientSession(base) as http:
            return await script(http, base)

    return asyncio.run(go())


def _ck(inst, who):
    return {"icesee_session": inst["cookies"][who]}


def _origin(base):
    return {"Origin": base}


async def _phase_one(http, base, inst):
    import aiohttp

    form = aiohttp.FormData()
    form.add_field("tiff", io.BytesIO(inst["tiff"]), filename="F127-C0471_C0483.tiff")
    resp = await http.post(f"{API}/assets/upload", data=form, cookies=_ck(inst, "alice"),
                           headers=_origin(base))
    assert resp.status == 201, await resp.text()
    asset = await resp.json()
    form = aiohttp.FormData()
    form.add_field("kind", "echogram")
    form.add_field("file", io.BytesIO(PNG), filename="echogram.png")
    resp = await http.post(f"{API}/assets/{asset['asset_id']}/products", data=form,
                           cookies=_ck(inst, "alice"), headers=_origin(base))
    assert resp.status in (200, 201), await resp.text()
    resp = await http.post(f"{API}/admin/sources", json={
        "source_id": "archive", "name": "Test archive", "provider": "local",
        "dataset_id": "test-archive", "root": str(inst["archive"])},
        cookies=_ck(inst, "maint"), headers=_origin(base))
    assert resp.status in (200, 201), await resp.text()
    resp = await http.post(f"{API}/admin/sources/archive/index", json={},
                           cookies=_ck(inst, "maint"), headers=_origin(base))
    assert resp.status in (200, 201, 202), await resp.text()
    deadline = time.time() + 60
    while time.time() < deadline:
        found = await (await http.get(f"{API}/radar/catalog?q=F127-C0471_C0472",
                                      cookies=_ck(inst, "maint"))).json()
        if found.get("total") or found.get("results") or found.get("items"):
            break
        await asyncio.sleep(0.5)
    resp = await http.post("/control/settings", data={
        "op": "save", "key": "frozen_legacies.working_cache_mb", "value": "4096",
        "reason": "persistence test"}, cookies=_ck(inst, "maint"), headers=_origin(base),
        allow_redirects=False)
    assert resp.status in (302, 303), await resp.text()
    return asset


async def _observe(http, base, inst):
    assets = (await (await http.get(f"{API}/assets", cookies=_ck(inst, "alice"))).json())["assets"]
    asset = next(a for a in assets if a["filename"] == "F127-C0471_C0483.tiff")
    listed = (await (await http.get(f"{API}/assets/{asset['asset_id']}/products",
                                    cookies=_ck(inst, "alice"))).json())["products"]
    echogram = next(p for p in listed if p["kind"] == "echogram")
    body = await (await http.get(echogram["download_url"], cookies=_ck(inst, "alice"))).read()
    sources = (await (await http.get(f"{API}/admin/sources", cookies=_ck(inst, "maint"))).json())
    catalog = await (await http.get(f"{API}/radar/catalog?q=F127-C0471_C0472",
                                    cookies=_ck(inst, "maint"))).json()
    page = await (await http.get("/control/settings", cookies=_ck(inst, "maint"))).text()
    return {"asset": asset, "echogram": body,
            "sources": [s.get("source_id") for s in sources["sources"]],
            "catalog": json.dumps(catalog), "settings_page": page}


def _tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")} if root.exists() else set()


def test_state_survives_crash_and_clean_restart_and_lives_on_the_data_root(installation):
    inst = installation
    repo_before = {d: _tree(REPO / d) for d in ("var", "users")}
    gateway = Gateway(inst)
    gateway.start()
    try:
        asset = run(inst, lambda http, base: _phase_one(http, base, inst))
        first = run(inst, lambda http, base: _observe(http, base, inst))
    finally:
        gateway.stop(signal.SIGKILL)                      # a crash, not a clean stop
    for stop in (signal.SIGTERM, None):
        gateway.start()
        try:
            seen = run(inst, lambda http, base: _observe(http, base, inst))
        finally:
            gateway.stop(stop or signal.SIGTERM)
        assert seen["asset"]["asset_id"] == asset["asset_id"]
        assert seen["asset"] == first["asset"]                    # sessions and manifest intact
        assert seen["echogram"] == PNG
        assert "archive" in seen["sources"]
        assert "F127-C0471_C0472.tiff" in seen["catalog"]
        assert "4096" in seen["settings_page"]

    data = inst["data"]
    from control_center.ops_store import OpsStore
    ops = OpsStore(data / "db" / "control_center_ops.db")
    assert ops.stored_settings()["frozen_legacies.working_cache_mb"]["value"] == 4096
    assert [a["key"] for a in ops.audit()] == ["frozen_legacies.working_cache_mb"]
    # every store is under the data root; nothing was written into the source tree
    for name in ("cryostack_auth.db", "control_center_ops.db", "frozen_legacies_catalog.db"):
        assert (data / "db" / name).is_file()
    radar = list((data / "workspace" / "users").glob(f"*/frozen_legacies/radar/{asset['asset_id']}"))
    assert len(radar) == 1 and (radar[0] / "source.tiff").read_bytes() == inst["tiff"]
    assert not list(radar[0].glob("*.part")) and not list(radar[0].rglob(".*.tmp"))
    assert {d: _tree(REPO / d) for d in ("var", "users")} == repo_before
