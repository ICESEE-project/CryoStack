"""Product model, processed-product uploads, controlled downloads, previews,
bundles, product-only assets, asset deletion and dataset downloads."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[3]
for _p in (str(_REPO), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frozen_legacies_radar_fixtures import (NAV_TEXT, requires_astra,
                                         tiff_bytes, write_nav, write_registry, write_tiff)
from cryostack_src.workspace import WorkspaceUser, owner_root
from icesee_jupyter_book.applications.frozen_legacies import server
from icesee_jupyter_book.applications.frozen_legacies.radar import products
from icesee_jupyter_book.applications.frozen_legacies.radar.sources import SOURCES_ENV

API = "/frozen-legacies/api"
NAME = "F127-C0471_C0483.tiff"


def _strip(width=3000, height=420):
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
        f"  - key: f127\n    tiff: shared/{NAME}\n    nav: shared/127.csv\n"))
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


def call(env, cookies, method, path, **kwargs):
    from aiohttp.test_utils import TestClient, TestServer

    async def go():
        async with TestClient(TestServer(_app(env))) as client:
            if callable(kwargs.get("data")):
                kwargs["data"] = kwargs["data"]()
            resp = await client.request(method, path, cookies=cookies, allow_redirects=False,
                                        **kwargs)
            return resp.status, resp.headers, await resp.read()

    return asyncio.run(go())


def jcall(env, cookies, method, path, **kwargs):
    status, headers, body = call(env, cookies, method, path, **kwargs)
    return status, json.loads(body) if body and headers.get("Content-Type", "").startswith(
        "application/json") else body


def form(kind=None, data=b"", filename="file.csv", title=None):
    from aiohttp import FormData

    def build():
        f = FormData()
        if kind is not None:
            f.add_field("kind", kind)
        if title is not None:
            f.add_field("title", title)
        f.add_field("file", io.BytesIO(data), filename=filename)
        return f
    return build


def _asset_dir(env, user, asset_id):
    ws_user = WorkspaceUser(user_id=user.id, source="cryostack-auth")
    return owner_root(ws_user, workspace_root=env["workspace"]) / "frozen_legacies" / "radar" / asset_id


def _upload_radar(env, cookies, *, nav=True):
    from aiohttp import FormData

    def build():
        f = FormData()
        f.add_field("tiff", io.BytesIO(tiff_bytes(_strip())), filename=NAME)
        if nav:
            f.add_field("nav", io.BytesIO(NAV_TEXT.encode()), filename="127.csv")
        return f
    status, body = jcall(env, cookies, "POST", f"{API}/assets/upload", data=build)
    assert status == 201, body
    return body["asset_id"]


def _shared(env, cookies):
    status, body = jcall(env, cookies, "POST", f"{API}/assets/shared", json={"source": "f127"})
    assert status == 201
    return body["asset_id"]


def _astra_csv(rows=2) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(products.ASTRA_COLUMNS)
    for i in range(rows):
        w.writerow([i + 1, 127, 500, 900, 900, 1000, 1500, 600, 150, 800, 1650, 100,
                    5.0, -6.27, 9.0, -20.0, 15.0, -40.0, 1.5, 2.9, NAME, 2,
                    471 + 6 * i, -81.48, -169.75, 420.0, 756.0, 126.0, 336.0])
    return out.getvalue().encode()


def _ursa_csv() -> bytes:
    header = products.URSA_REQUIRED + ["Transmitter_X_pixel"]
    rows = [[1, 471, -81.48, -169.75, 10.5, 20.1, 806.4, -20, -40, 1.0, -10, 120],
            [2, 472, -81.49, -169.69, "NaN", "NaN", "NaN", "NaN", "NaN", 1.1, -11, 130]]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue().encode()


def _png(width=40, height=20, mode="L") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height), 128).save(buffer, format="PNG")
    return buffer.getvalue()


# ── listing ──────────────────────────────────────────────────────────
def test_uploaded_radar_lists_raw_radar_and_navigation(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck)
    status, body = jcall(env, ck, "GET", f"{API}/assets/{asset_id}/products")
    assert status == 200
    by_id = {p["product_id"]: p for p in body["products"]}
    assert by_id["raw-radar"]["downloadable"] and by_id["raw-radar"]["producer"] == "user"
    assert by_id["navigation"]["summary"]["rows"] == 5
    assert {k["kind"] for k in body["upload_kinds"]} == set(products.UPLOAD_KINDS)
    assert str(env["tmp"]) not in json.dumps(body)


def test_shared_radar_is_listed_but_not_downloadable(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    status, body = jcall(env, ck, "GET", f"{API}/assets/{asset_id}/products")
    raw = {p["product_id"]: p for p in body["products"]}["raw-radar"]
    assert raw["workflow"] == "radar-source" and raw["downloadable"] is False
    assert raw["previewable"] and raw["preview_url"]
    status, headers, preview = call(env, ck, "GET", raw["preview_url"])
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(preview)).width <= server.PREVIEW_MAX_WIDTH
    assert call(env, ck, "GET", f"{API}/assets/{asset_id}/products/raw-radar")[0] == 403


@requires_astra
def test_astra_outputs_appear_as_generated_products(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    url = f"{API}/assets/{asset_id}/manual"
    status, s = jcall(env, ck, "GET", url)
    status, s = jcall(env, ck, "POST", url, json={"action": "suggest", "revision": 0})
    status, s = jcall(env, ck, "POST", url, json={"action": "done", "revision": 1})
    assert s["status"] == "completed"
    status, body = jcall(env, ck, "GET", f"{API}/assets/{asset_id}/products")
    by_id = {p["product_id"]: p for p in body["products"]}
    assert by_id["astra-csv"]["workflow"] == "astra-manual"
    assert by_id["astra-csv"]["producer"] == "frozen-legacies"
    assert by_id["astra-csv"]["summary"]["rows"] == 1
    assert by_id["astra-csv"]["provenance"]["a_scopes_with_suggested_picks"] == 1
    assert by_id["astra-qc"]["previewable"]
    status, headers, data = call(env, ck, "GET", by_id["astra-csv"]["download_url"])
    assert status == 200 and headers["Content-Type"] == "text/csv"
    assert headers["Content-Disposition"] == 'attachment; filename="F127-C0471_C0483.csv"'
    status, headers, png = call(env, ck, "GET", by_id["astra-qc"]["preview_url"])
    assert status == 200 and Image.open(io.BytesIO(png)).width <= server.PREVIEW_MAX_WIDTH


# ── processed-product uploads ────────────────────────────────────────
@pytest.mark.parametrize("kind, data, filename", [
    ("astra-csv", _astra_csv(), "F127-C0471_C0483.csv"),
    ("ursa-csv", _ursa_csv(), "F127-C0471_C0483_pick.csv"),
    ("echogram", _png(), "echogram.png"),
    ("radargram", _png(30, 30, "RGB"), "radargram.png"),
    ("astra-qc", _png(), "F127_QC.png"),
])
def test_valid_products_upload_and_are_labelled_user_provided(env, kind, data, filename):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    status, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                         data=form(kind, data, filename))
    assert status == 201, body
    uploaded = [p for p in body["products"] if p["product_id"].startswith("upload-")]
    assert len(uploaded) == 1
    product = uploaded[0]
    assert product["producer"] == "user" and product["kind"] == kind
    assert product["provenance"]["origin"] == "user-provided"
    assert product["filename"] == filename
    status, _h, got = call(env, ck, "GET", product["download_url"])
    assert status == 200 and got == data
    stored = list((_asset_dir(env, user, asset_id) / "outputs").iterdir())
    assert len(stored) == 1 and stored[0].name.startswith("upload-")


def test_csv_summaries(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    status, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                         data=form("ursa-csv", _ursa_csv(), "x_pick.csv"))
    summary = [p for p in body["products"] if p["kind"] == "ursa-csv"][0]["summary"]
    assert summary == {"rows": 2, "row_label": "frames", "columns": 12, "cbd_min": 471,
                       "cbd_max": 472, "positions": 2, "thickness_values": 1,
                       "thickness_min_m": 806.4, "thickness_max_m": 806.4, "qc_flags": []}


def _ursa_rows(tx_x, tx_db, path):
    header = products.URSA_REQUIRED + ["Transmitter_X_pixel"]
    with path.open("w", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(header)
        for i, (x, db) in enumerate(zip(tx_x, tx_db), start=1):
            w.writerow([i, 470 + i, -81.5, -169.7, 9.0, 16.9, 665.0, -11.0, -21.0, 0.0, db, x])
    return path


def test_ursa_frame_qc_flags_a_departing_transmitter_without_changing_picks(tmp_path):
    # the F127 pattern: the last frame's "transmitter" is really the surface echo
    path = _ursa_rows([725, 742, 728, 730, 1301], [-34.8, -35.3, -34.2, -34.7, -11.3],
                      tmp_path / "x_pick.csv")
    before = path.read_bytes()
    summary = products.summarize_csv("ursa-csv", path)
    assert summary["qc_flags"] == [{"frame": 5, "cbd": 475, "checks": [
        "transmitter position: 1301 px vs strip median 730 px",
        "transmitter power: -11.3 dB vs strip median -34.7 dB"]}]
    assert path.read_bytes() == before
    # a consistent strip, and a strip too short for a median, are not flagged
    assert products.summarize_csv("ursa-csv", _ursa_rows(
        [725, 742, 728], [-34.8, -35.3, -34.2], tmp_path / "ok_pick.csv"))["qc_flags"] == []
    assert products.summarize_csv("ursa-csv", _ursa_rows(
        [725, 1301], [-34.8, -11.3], tmp_path / "short_pick.csv"))["qc_flags"] == []


def test_ursa_frame_table_shows_ursas_values_as_written(tmp_path):
    path = tmp_path / "x_pick.csv"
    path.write_bytes(
        b"Frame,CBD,LAT,LON,Surface_Time_us,Bed_Time_us,Ice_Thickness_m,Surface_Power_dB,"
        b"Bed_Power_dB,Transmitter_Time_us,Transmitter_Power_dB,Transmitter_X_pixel\n"
        + b"".join(f"{i},{470 + i},-81.5,-169.7,9.0,16.968750,665.437500,-11.0,-21.0,"
                   f"0.000000,-34.8,{x}\n".encode() for i, x in ((1, 725), (2, 742), (3, 1301))))
    before = path.read_bytes()
    table = products.ursa_frame_table(path)
    assert table["columns"] == [c for c in products.URSA_FRAME_COLUMNS]
    assert table["rows"][0][table["columns"].index("Ice_Thickness_m")] == "665.437500"
    assert table["rows"][0][table["columns"].index("Bed_Time_us")] == "16.968750"
    assert [f["frame"] for f in table["qc_flags"]] == [3] and table["truncated"] is False
    assert path.read_bytes() == before
    # not a URSA CSV, or unreadable: no table
    (tmp_path / "other.csv").write_text("a,b\n1,2\n")
    assert products.ursa_frame_table(tmp_path / "other.csv") == {}
    assert products.ursa_frame_table(tmp_path / "missing.csv") == {}


def test_diagnostic_products_are_previewable_unvalidated_images():
    assert products.KINDS["ursa-diagnostic"]["type"] == "image"
    assert "ursa-diagnostic" in products.IMAGE_KINDS
    assert "ursa-diagnostic" not in products.UPLOAD_KINDS     # never user-declared
    assert products.DIAGNOSTIC_LABEL == "URSA diagnostic (unvalidated)"


def _no_upload_files(env, user, asset_id):
    outputs = _asset_dir(env, user, asset_id) / "outputs"
    return not any(p.name.startswith("upload-") for p in outputs.iterdir())


@pytest.mark.parametrize("kind, data, filename, status", [
    ("astra-csv", b"a,b\n1,2\n", "x.csv", 400),                         # wrong schema
    ("astra-csv", _astra_csv().replace(b"420.0", b"abc"), "x.csv", 400),   # non-numeric
    ("astra-csv", _astra_csv() + b"1,2,3\n", "x.csv", 400),             # ragged
    ("ursa-csv", b"Frame,CBD\n1,2\n", "x.csv", 400),
    ("lyra-echoes-csv", b"flight,cbd\n1,2\n", "x.csv", 400),
    ("astra-csv", b"\xff\xfe\x00\x01binary", "x.csv", 400),
    ("astra-csv", _astra_csv(), "x.png", 400),                          # extension for kind
    ("echogram", b"not an image at all", "e.png", 400),
    ("echogram", _png(), "e.jpg", 400),                                 # PNG named .jpg
    ("echogram", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "e.png", 400),   # signature only
    ("astra-qc", _png(), "qc.jpg", 400),
    ("raw-radar", tiff_bytes(_strip(10, 10)), "x.tiff", 400),           # not an upload kind
    ("../etc", _astra_csv(), "x.csv", 400),
    (None, _astra_csv(), "x.csv", 400),                                 # no kind
    ("astra-csv", b"", "x.csv", 400),
    ("astra-csv", _astra_csv(), ".hidden.csv", 400),
])
def test_invalid_product_uploads_are_rejected_and_cleaned_up(env, kind, data, filename, status):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    got, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                      data=form(kind, data, filename))
    assert got == status, body
    assert _no_upload_files(env, user, asset_id)
    assert not (_asset_dir(env, user, asset_id) / "products.json").exists()


def test_image_dimension_limits(env, monkeypatch):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    monkeypatch.setattr(products, "MAX_IMAGE_PIXELS", 100)
    got, _b = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                    data=form("echogram", _png(40, 20), "e.png"))
    assert got == 400 and _no_upload_files(env, user, asset_id)


def test_oversized_product_upload(env, monkeypatch):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    monkeypatch.setattr(products, "MAX_IMAGE_BYTES", 100)
    got, _b = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                    data=form("echogram", _png(200, 200) + b"\x00" * 200, "e.png"))
    assert got == 413 and _no_upload_files(env, user, asset_id)


def test_navigation_can_be_added_once_to_an_uploaded_radar(env):
    user, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck, nav=False)
    got, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                      data=form("navigation", NAV_TEXT.encode(), "127.csv"))
    assert got == 201
    assert (_asset_dir(env, user, asset_id) / "nav.csv").read_text() == NAV_TEXT
    status, detail = jcall(env, ck, "GET", f"{API}/assets/{asset_id}")
    assert detail["nav"]["present"] and [r["cbd"] for r in detail["nav_rows"]] == [471, 472, 473, 483]
    got, _b = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                    data=form("navigation", NAV_TEXT.encode(), "127.csv"))
    assert got == 400                                              # never replaced


def test_navigation_cannot_replace_shared_navigation(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    got, _b = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                    data=form("navigation", NAV_TEXT.encode(), "127.csv"))
    assert got == 400


# ── product-only assets ──────────────────────────────────────────────
def test_product_only_asset_has_no_invented_radar_metadata(env):
    user, ck = _login(env, "a@example.org")
    status, asset = jcall(env, ck, "POST", f"{API}/assets/products",
                          data=form("astra-csv", _astra_csv(3), "F127-C0471_C0483.csv"))
    assert status == 201, asset
    assert asset["origin"] == "products"
    assert asset["image"] is None and asset["flight"] is None and asset["cbd_start"] is None
    assert asset["title"] == "F127-C0471_C0483"
    asset_id = asset["asset_id"]
    status, body = jcall(env, ck, "GET", f"{API}/assets/{asset_id}/products")
    assert [p["kind"] for p in body["products"]] == ["astra-csv"]
    for path in (f"/assets/{asset_id}/manual", f"/assets/{asset_id}/view?x=0&width=1&scale=1"):
        got, err = jcall(env, ck, "GET", f"{API}{path}")
        assert got in (400, 409), err
    got, err = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/automatic", json={"action": "start"})
    assert got == 409


def test_failed_product_only_upload_leaves_no_asset(env):
    user, ck = _login(env, "a@example.org")
    got, _b = jcall(env, ck, "POST", f"{API}/assets/products",
                    data=form("astra-csv", b"bad,csv\n", "x.csv"))
    assert got == 400
    root = _asset_dir(env, user, "x").parent
    assert not root.exists() or list(root.iterdir()) == []


# ── downloads and security ───────────────────────────────────────────
def test_other_users_cannot_list_download_preview_or_delete(env):
    _a, cka = _login(env, "a@example.org")
    _b, ckb = _login(env, "b@example.org")
    asset_id = _upload_radar(env, cka)
    status, body = jcall(env, cka, "POST", f"{API}/assets/{asset_id}/products",
                         data=form("echogram", _png(), "e.png"))
    pid = [p for p in body["products"] if p["kind"] == "echogram"][0]["product_id"]
    for method, suffix in (("GET", "/products"), ("GET", "/products/raw-radar"),
                           ("GET", f"/products/{pid}"), ("GET", f"/products/{pid}/preview"),
                           ("GET", "/products.zip"), ("DELETE", f"/products/{pid}"),
                           ("DELETE", ""), ("GET", "/automatic")):
        assert call(env, ckb, method, f"{API}/assets/{asset_id}{suffix}")[0] == 404, suffix


@pytest.mark.parametrize("product_id", [
    "..", "asset.json", "session.json", "source.tiff", "../asset.json", "UPPER",
    "products.json", "%2e%2e%2fasset.json", "x" * 65, "missing-product",
])
def test_unknown_or_unsafe_product_ids(env, product_id):
    _u, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck)
    status, _h, body = call(env, ck, "GET", f"{API}/assets/{asset_id}/products/{product_id}")
    assert status == 404
    assert b'"schema"' not in body


def test_symlinked_product_files_are_refused(env, tmp_path):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    status, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                         data=form("echogram", _png(), "e.png"))
    product = [p for p in body["products"] if p["kind"] == "echogram"][0]
    stored = next((_asset_dir(env, user, asset_id) / "outputs").glob("upload-*"))
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")
    stored.unlink()
    stored.symlink_to(secret)
    assert call(env, ck, "GET", product["download_url"])[0] == 404
    assert call(env, ck, "GET", f"{API}/assets/{asset_id}/products.zip")[2].find(b"secret") == -1


def test_tampered_products_manifest_cannot_reach_other_files(env):
    user, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck)
    path = _asset_dir(env, user, asset_id) / "products.json"
    path.write_text(json.dumps({"schema": products.PRODUCTS_SCHEMA, "version": 1,
                                "asset_id": asset_id, "products": [
        {"product_id": "evil", "kind": "echogram", "file": "../asset.json", "producer": "user"},
        {"product_id": "evil2", "kind": "echogram", "file": "../../../../etc/passwd",
         "producer": "user"},
    ]}))
    for pid in ("evil", "evil2"):
        assert call(env, ck, "GET", f"{API}/assets/{asset_id}/products/{pid}")[0] == 404


@requires_astra
def test_bundle_contains_products_and_safe_index_only(env):
    _u, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck)
    jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
          data=form("ursa-csv", _ursa_csv(), "x_pick.csv"))
    url = f"{API}/assets/{asset_id}/manual"
    jcall(env, ck, "POST", url, json={"action": "suggest", "revision": 0})
    jcall(env, ck, "POST", url, json={"action": "done", "revision": 1})
    status, headers, data = call(env, ck, "GET", f"{API}/assets/{asset_id}/products.zip")
    assert status == 200 and headers["Content-Type"] == "application/zip"
    assert headers["Content-Disposition"] == 'attachment; filename="F127-C0471_C0483_products.zip"'
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    assert names == {"nav.csv", "x_pick.csv", "F127-C0471_C0483.csv", "F127-C0471_C0483_QC.png",
                     "PRODUCTS.json"}
    index = json.loads(archive.read("PRODUCTS.json"))
    text = json.dumps(index)
    assert str(env["tmp"]) not in text and "session.json" not in text and "revision" not in text
    assert {p["workflow"] for p in index["products"]} == {"upload", "astra-manual"}


def test_user_products_can_be_deleted_but_generated_ones_cannot(env):
    user, ck = _login(env, "a@example.org")
    asset_id = _upload_radar(env, ck)
    status, body = jcall(env, ck, "POST", f"{API}/assets/{asset_id}/products",
                         data=form("echogram", _png(), "e.png"))
    pid = [p for p in body["products"] if p["kind"] == "echogram"][0]["product_id"]
    assert call(env, ck, "DELETE", f"{API}/assets/{asset_id}/products/raw-radar")[0] == 403
    assert call(env, ck, "DELETE", f"{API}/assets/{asset_id}/products/navigation")[0] == 403
    status, body = jcall(env, ck, "DELETE", f"{API}/assets/{asset_id}/products/{pid}")
    assert status == 200 and pid not in [p["product_id"] for p in body["products"]]
    assert _no_upload_files(env, user, asset_id)
    assert call(env, ck, "DELETE", f"{API}/assets/{asset_id}/products/{pid}",
                headers={"Origin": "https://evil.example"})[0] == 403


def test_deleting_an_asset_never_touches_shared_radar(env):
    user, ck = _login(env, "a@example.org")
    asset_id = _shared(env, ck)
    assert call(env, ck, "DELETE", f"{API}/assets/{asset_id}",
                headers={"Origin": "https://evil.example"})[0] == 403
    status, body = jcall(env, ck, "DELETE", f"{API}/assets/{asset_id}")
    assert status == 200 and body == {"deleted": asset_id}
    assert not _asset_dir(env, user, asset_id).exists()
    assert (env["shared"] / NAME).is_file()
    assert call(env, ck, "GET", f"{API}/assets/{asset_id}")[0] == 404


def test_anonymous_product_routes(env):
    for method, path in (("GET", f"{API}/assets/{'a' * 32}/products"),
                         ("POST", f"{API}/assets/products"),
                         ("GET", f"{API}/assets/{'a' * 32}/products.zip"),
                         ("DELETE", f"{API}/assets/{'a' * 32}"),
                         ("GET", f"{API}/datasets/frozen-legacies-lyra/downloads/flights_geojson")):
        assert call(env, None, method, path)[0] == 401


# ── shared dataset downloads (capabilities) ──────────────────────────
def test_dataset_downloads_follow_manifest_capabilities(env):
    _u, ck = _login(env, "a@example.org")
    for kind in ("observations_geojson", "flights_geojson"):
        status, headers, data = call(env, ck, "GET",
                                     f"{API}/datasets/frozen-legacies-lyra/downloads/{kind}")
        assert status == 200
        collection = json.loads(data)
        assert collection["features"]
        assert {f["properties"]["dataset_id"] for f in collection["features"]} == {
            "frozen-legacies-lyra"}
    assert call(env, ck, "GET", f"{API}/datasets/no-such-dataset/downloads/flights_geojson")[0] == 404
    assert call(env, ck, "GET", f"{API}/datasets/frozen-legacies-lyra/downloads/catalog")[0] == 404


def test_dataset_without_download_capability(env, tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "catalog.json").write_text(json.dumps({"datasets": [
        {"id": "d1", "capabilities": {"downloads": False},
         "build": {"downloads": {"flights_geojson": True}}}]}))
    (data_root / "flights.geojson").write_text('{"features": []}')
    _u, ck = _login(env, "a@example.org")

    async def go():
        app = _app(env)
        app[server.DATASETS_ROOT_KEY] = str(data_root)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(f"{API}/datasets/d1/downloads/flights_geojson", cookies=ck)
            return resp.status

    assert asyncio.run(go()) == 404


# ── preview derivative and declared-origin labels ────────────────────
def test_qc_preview_is_bounded_and_keeps_thin_dark_marks(tmp_path):
    """A preview of a large 16-bit QC image is a small derivative in which
    ASTRA's 3-pixel pick circles remain visible; the stored file is unchanged."""
    import io as _io

    import numpy as _np
    from PIL import Image as _Image, ImageDraw as _Draw

    from icesee_jupyter_book.applications.frozen_legacies.server import (
        PREVIEW_MAX_HEIGHT, PREVIEW_MAX_WIDTH, _render_preview)

    big = _Image.new("I;16", (9600, 1200), 50000)
    draw = _Draw.Draw(big)
    draw.ellipse((4790, 590, 4810, 610), outline="green", width=3)   # as ASTRA draws
    path = tmp_path / "qc.png"
    big.save(path, format="PNG")
    before = path.read_bytes()
    preview = _Image.open(_io.BytesIO(_render_preview(path)))
    assert preview.width <= PREVIEW_MAX_WIDTH and preview.height <= PREVIEW_MAX_HEIGHT
    pixels = _np.asarray(preview)
    assert pixels.min() < 64 and _np.median(pixels) > 128          # the mark survives
    assert path.read_bytes() == before


def test_uploaded_qc_png_is_labelled_as_declared_not_verified():
    """A PNG cannot prove it is ASTRA output: a user upload of kind astra-qc
    is titled as declared, while schema-validated CSV kinds keep their titles."""
    def record(kind):
        return products.upload_record(
            kind, product_id="upload-0123456789ab", stored_name="upload-0123456789ab.bin",
            display_name="file", sha256="0" * 64, validated={"summary": {}, "mime": "x"})
    qc = record("astra-qc")
    assert qc["title"] == "QC image (declared ASTRA, not verified)"
    assert qc["producer"] == "user" and qc["workflow"] == "upload"
    assert record("astra-csv")["title"] == products.KINDS["astra-csv"]["title"]


def test_preview_derivative_records_parent_checksum_and_preserves_source(env):
    user, cookies = _login(env, "preview@example.org")
    asset_id = _upload_radar(env, cookies)
    source = _asset_dir(env, user, asset_id) / "source.tiff"
    original = source.read_bytes()

    status, headers, png = call(
        env, cookies, "GET", f"{API}/assets/{asset_id}/products/raw-radar/preview")
    assert status == 200 and headers["X-Scientific-Status"] == "preview-only"
    assert len(headers["X-Preview-SHA256"]) == 64
    assert len(headers["X-Preview-Source-SHA256"]) == 64
    assert source.read_bytes() == original

    cache = _asset_dir(env, user, asset_id) / ".preview-cache"
    sidecar = json.loads(next(cache.glob("*.png.json")).read_text(encoding="utf-8"))
    assert sidecar["source"]["asset_id"] == asset_id
    assert sidecar["source"]["product_id"] == "raw-radar"
    assert sidecar["source"]["sha256"] == headers["X-Preview-Source-SHA256"]
    assert sidecar["derivative"]["sha256"] == headers["X-Preview-SHA256"]
    assert sidecar["scientific_status"] == "preview-only"
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_preview_pdf_is_labelled_private_and_owner_isolated(env):
    _owner, owner_cookies = _login(env, "owner@example.org")
    _other, other_cookies = _login(env, "other@example.org")
    asset_id = _upload_radar(env, owner_cookies)
    url = f"{API}/assets/{asset_id}/products/raw-radar/preview.pdf"

    assert call(env, other_cookies, "GET", url)[0] == 404
    status, headers, data = call(env, owner_cookies, "GET", url)
    assert status == 200 and headers["Content-Type"] == "application/pdf"
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["X-Scientific-Status"] == "preview-only"
    assert data.startswith(b"%PDF")


def test_preview_cache_follows_current_source_bytes_not_declared_hash(tmp_path):
    from icesee_jupyter_book.applications.frozen_legacies.radar import preview_derivatives

    asset_dir = tmp_path / "asset"
    asset_dir.mkdir()
    source = asset_dir / "source.bin"
    source.write_bytes(b"first")
    record = {
        "asset_id": "asset-1", "kind": "raw-radar",
        "provenance": {"sha256": "0" * 64},
    }

    first, first_doc = preview_derivatives.get_or_create(
        asset_dir=asset_dir, product_id="raw-radar", source=source,
        source_record=record, extension="bin", media_type="application/octet-stream",
        generator="test", render=lambda path: b"preview:" + path.read_bytes())
    source.write_bytes(b"second")
    second, second_doc = preview_derivatives.get_or_create(
        asset_dir=asset_dir, product_id="raw-radar", source=source,
        source_record=record, extension="bin", media_type="application/octet-stream",
        generator="test", render=lambda path: b"preview:" + path.read_bytes())

    assert first == b"preview:first" and second == b"preview:second"
    assert first_doc["source"]["sha256"] != second_doc["source"]["sha256"]
    assert second_doc["source"]["sha256"] != record["provenance"]["sha256"]


def test_preview_rejects_image_over_pixel_bound(tmp_path):
    from icesee_jupyter_book.applications.frozen_legacies.server import _render_preview

    path = tmp_path / "oversize.png"
    Image.new("L", (10, 10)).save(path)
    original_limit = products.MAX_IMAGE_PIXELS
    try:
        products.MAX_IMAGE_PIXELS = 50
        with pytest.raises(products.ProductValidationError, match="dimensions"):
            _render_preview(path)
    finally:
        products.MAX_IMAGE_PIXELS = original_limit
