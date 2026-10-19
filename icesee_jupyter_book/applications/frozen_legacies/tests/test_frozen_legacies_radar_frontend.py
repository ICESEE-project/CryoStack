"""Radar workspace frontend: Node unit tests for the pure viewing geometry,
plus structural checks that the explorer, navigation and account control
are preserved and the modes are wired to one workspace."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_APP = _HERE.parent
_INDEX = (_APP / "index.html").read_text(encoding="utf-8")
_RADAR_JS = (_APP / "assets" / "radar.js").read_text(encoding="utf-8")
_UI_JS = (_APP / "assets" / "ui.js").read_text(encoding="utf-8")
_DATA_JS = (_APP / "assets" / "data.js").read_text(encoding="utf-8")
_QUERY_JS = (_APP / "assets" / "explorer_query.js").read_text(encoding="utf-8")
_CATALOG_JS = (_APP / "assets" / "catalog.js").read_text(encoding="utf-8")
_CSS = (_APP / "assets" / "frozen_legacies.css").read_text(encoding="utf-8")
_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_radar_geometry_js_unit_tests():
    result = subprocess.run(
        [_NODE, "--test", str(_HERE / "frozen_legacies_radar_geometry.test.mjs")],
        capture_output=True, text=True, cwd=str(_HERE),
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_explorer_query_js_unit_tests():
    result = subprocess.run(
        [_NODE, str(_HERE / "frozen_legacies_explorer_query.test.cjs")],
        capture_output=True, text=True, cwd=str(_HERE),
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("name", ["data.js", "radar.js", "radar_geometry.js", "astra_picker.js", "products.js",
                                  "automatic.js", "ui.js", "frozen_legacies.js", "styles.js",
                                  "layers.js", "map.js", "explorer_query.js"])
def test_scripts_parse(name):
    result = subprocess.run([_NODE, "--check", str(_APP / "assets" / name)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_three_modes_share_one_workspace_with_map_default():
    modes = re.findall(r'class="fl-mode-button[^"]*" data-mode="(\w+)"', _INDEX)
    assert modes == ["map", "manual", "automatic"]
    assert re.search(r'class="fl-mode-button active" data-mode="map"', _INDEX)
    assert _INDEX.count('id="fl-radar-workspace"') == 1
    # the radar workspace overlays the (still mounted) map and starts hidden
    workspace = _INDEX.index('id="fl-radar-workspace"')
    assert _INDEX.index('id="frozen-legacies-map"') < workspace
    assert "hidden" in _INDEX[workspace:_INDEX.index(">", workspace)]


def test_flight_selector_synchronizes_explorer_and_names_ascope_preview():
    assert 'closeObservationPopup(document.getElementById("fl-observation-popup"));' in _UI_JS
    assert 'renderEmptyObservation(data.datasetIndex?.get(state.datasetId) || null);' in _UI_JS
    select_flight = _UI_JS[_UI_JS.index("function selectFlight({"):_UI_JS.index("function selectDataset({")]
    assert select_flight.index("fitToFeature") < select_flight.index("writeExplorerContextUrl")
    assert _UI_JS.count('A-scope film scan') >= 2


def test_existing_navigation_and_account_control_are_preserved():
    for href in ("/frozen-legacies/",
                 "/applications/frozen_legacies/getting_started.html",
                 "/applications/frozen_legacies/user_manual.html",
                 "/applications/frozen_legacies/developer.html"):
        assert f'href="{href}"' in _INDEX
    assert _INDEX.count('id="cryostack-account-slot"') == 1
    assert _INDEX.count("cryostack_account.js") == 1
    for element in ('id="dataset-select"', 'id="flight-select"', 'id="selected-record"'):
        assert element in _INDEX


def test_shareable_scientific_filter_controls_use_one_explorer_query_store():
    assert _INDEX.index("explorer_query.js") < _INDEX.index("ui.js")
    for element in ("fl-scientific-filters", "fl-filter-cbd-min", "fl-filter-cbd-max",
                    "fl-filter-review", "fl-filter-query", "fl-active-filters",
                    "fl-filter-status", "fl-filter-copy", "fl-filter-clear"):
        assert f'id="{element}"' in _INDEX
    assert 'aria-live="polite"' in _INDEX
    assert "FrozenLegaciesExplorerStore" in _UI_JS
    assert "applyExplorerQuery" in (_APP / "assets" / "catalog.js").read_text(encoding="utf-8")
    assert 'layers.layers.observations.setStyle' in _UI_JS
    assert 'layers.layers.flights.setStyle' in _UI_JS
    for key in ("qv", "audience", "dataset", "flight", "source", "product", "review",
                "cbd_min", "cbd_max", "q", "sort"):
        assert f'"{key}"' in _QUERY_JS
    assert "history[push ? \"pushState\" : \"replaceState\"]" in _UI_JS
    assert "navigator.clipboard.writeText(window.location.href)" in _UI_JS
    assert 'const query = window.FrozenLegaciesExplorerStore?.get?.()' in _RADAR_JS
    assert 'params.get("dataset") || params.get("ds")' in _RADAR_JS


def test_explorer_snapshot_drives_catalog_and_radar_coverage_together():
    assert 'const EXPLORER_API = "/frozen-legacies/api/radar/explorer"' in _CATALOG_JS
    assert "state.explorerSnapshot = body.snapshot" in _CATALOG_JS
    assert "applyExplorerFeatures(body)" in _CATALOG_JS
    assert "items: body.items || []" in _CATALOG_JS
    assert "features: body.features" not in _CATALOG_JS  # consumed, never rebuilt from rows
    assert '${API}/segments' not in _CATALOG_JS
    assert "state.cursorHistory.push(state.nextCursor)" in _CATALOG_JS


def test_map_observation_quicklook_is_accessible_and_progressive():
    assert 'id="fl-observation-popup"' in _INDEX
    assert 'role="dialog"' in _INDEX
    assert "new ol.Overlay" in _UI_JS
    assert "SCIENTIFIC QUICKLOOK" in _UI_JS
    assert "Quicklook only" in _UI_JS
    assert 'data-fl-popup-action="manual"' in _UI_JS
    assert "@media (max-width: 680px)" in _CSS


def test_quicklook_has_deterministic_flight_navigation_and_shareable_state():
    assert 'data-fl-popup-action="previous-flight"' in _UI_JS
    assert 'data-fl-popup-action="next-flight"' in _UI_JS
    assert 'data-fl-popup-action="previous-observation"' in _UI_JS
    assert 'data-fl-popup-action="next-observation"' in _UI_JS
    assert 'aria-label="Flights in this dataset"' in _UI_JS
    assert 'aria-label="Observations in this flight"' in _UI_JS
    assert "orderedFlightObservations" in _UI_JS
    assert "orderedDatasetFlights" in _UI_JS
    assert "navigateFlight" in _UI_JS
    assert "aCbd - bCbd" in _UI_JS
    for key in ("dataset", "flight", "observation"):
        assert f'url.searchParams.set("{key}"' in _UI_JS
    assert "restoreObservationSelection" in _UI_JS
    assert "A flight choice is a map-navigation action" in _UI_JS
    assert 'closeObservationPopup(document.getElementById("fl-observation-popup"));' in _UI_JS
    assert "selectObservation({map, data, layers, state, feature: target, zoomFlight: true})" in _UI_JS
    entry = (_APP / "assets" / "frozen_legacies.js").read_text(encoding="utf-8")
    assert "if (!ui.restoreObservationSelection())" in entry


def test_quicklook_keyboard_close_navigation_and_motion_preferences():
    map_start = _INDEX.index('id="frozen-legacies-map"')
    map_tag = _INDEX[map_start:_INDEX.index(">", map_start)]
    assert 'tabindex="0"' in map_tag
    assert 'aria-label="Frozen Legacies observation map"' in map_tag
    assert 'event.key === "Escape"' in _UI_JS
    assert 'event.key === "ArrowLeft"' in _UI_JS
    assert 'event.key === "ArrowRight"' in _UI_JS
    assert "closeObservationPopup(element)" in _UI_JS
    assert "active !== document.body && active !== document.documentElement" in _UI_JS
    assert 'element._flMapTarget?.focus?.({preventScroll: true})' in _UI_JS
    assert 'matchMedia?.("(prefers-reduced-motion: reduce)")' in _UI_JS
    assert "behavior: quicklookScrollBehavior()" in _UI_JS


def test_quicklook_has_independent_media_and_accessible_repositioning():
    assert "function observationMediaUrls(properties)" in _UI_JS
    assert "A-scope film scan" in _UI_JS
    assert "Z-scope radar image" in _UI_JS
    assert "A-scope film scan not indexed yet." in _UI_JS
    assert "Z-scope radar image not indexed yet." in _UI_JS
    assert "data-fl-popup-drag" in _UI_JS
    assert "setPointerCapture" in _UI_JS
    assert "element._flOverlay.setOffset" in _UI_JS
    assert "function popupInteractiveTarget(target)" in _UI_JS
    assert "button, a, input, select, textarea" in _UI_JS
    assert ".fl-popup-media-grid" in _CSS
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in _CSS


def test_maintainer_quicklook_previews_resolve_only_indexed_temporary_sources():
    routes = (_APP / "catalog_routes.py").read_text(encoding="utf-8")
    assert "api_catalog_observation_preview" in routes
    assert '"ascope": "ascope-temporary"' in routes
    assert '"zscope": "zscope-temporary"' in routes
    assert 'record.get("source_id") != source_id' in routes
    assert '"X-Scientific-Status"] = "temporary-scratch-preview"' in routes
    assert "observation-preview?v=2&scope=" in _UI_JS


def test_map_reuses_livist_scientific_geography_and_labels():
    layers = (_APP / "assets" / "layers.js").read_text(encoding="utf-8")
    styles = (_APP / "assets" / "styles.js").read_text(encoding="utf-8")
    for dataset in ("quantartica-simple-basemap.json", "basins.json", "place-names.json"):
        assert f'/livist/{dataset}' in layers
    assert "scientificBasemap" in layers and "drainageBasin" in layers
    assert "antarcticPlaceName" in layers
    assert 'rawName.replaceAll("#", "\\n")' in styles
    assert "Ross Ice Shelf" in (_APP.parents[2] /
                                 "external" / "living-ice-sheet-temperature" / "frontend" /
                                 "public" / "place-names.json").read_text(encoding="utf-8").replace("#", " ")


def test_script_order_loads_radar_before_the_entry_point():
    order = [m for m in re.findall(
        r'src="/frozen-legacies/assets/([\w.]+)(?:\?[^\"]+)?"', _INDEX
    )]
    assert (order.index("radar_geometry.js") < order.index("astra_picker.js")
            < order.index("products.js") < order.index("automatic.js")
            < order.index("radar.js") < order.index("frozen_legacies.js"))
    assert order.index("ui.js") < order.index("radar.js")


def test_explorer_announces_selection_without_radar_coupling():
    assert _UI_JS.count("announceObservationSelection(") == 3   # definition + 2 calls
    assert "FrozenLegaciesRadar" not in _UI_JS


def test_navigation_only_flights_are_optional_and_never_presented_as_imagery():
    assert '"/frozen-legacies/api/navigation/flights"' in _DATA_JS
    assert "loadNavigationFlights()" in _DATA_JS
    assert "optional navigation collection unavailable" in _DATA_JS
    assert 'dataset?.availability === "navigation-only"' in _RADAR_JS
    assert "Navigation available." in _RADAR_JS
    assert "has not been installed yet" in _RADAR_JS
    for slot in ("Source radar TIFF", "Radargram / echogram", "Digitized radar data",
                 "Automatic-picker output"):
        assert slot in _RADAR_JS
    assert "interface placeholders, not scientific observations" in _RADAR_JS
    assert "checksum validation and catalog indexing" in _RADAR_JS


def test_riggs_is_optional_verified_context_and_not_a_pick_layer():
    layers = (_APP / "assets" / "layers.js").read_text(encoding="utf-8")
    styles = (_APP / "assets" / "styles.js").read_text(encoding="utf-8")
    entry = (_APP / "assets" / "frozen_legacies.js").read_text(encoding="utf-8")
    assert '"/frozen-legacies/api/context/riggs"' in _DATA_JS
    assert "optional RIGGS context unavailable" in _DATA_JS
    assert 'visible: false' in layers and 'id: "riggs-reference-stations"' in layers
    assert "riggsStation" in styles and "measurement_method" in styles
    assert 'id="fl-riggs-toggle"' in _INDEX
    assert "independent stations" in entry
    assert "renderRiggsStation" in _UI_JS
    assert "Independent scientific context" in _UI_JS
    assert "not a Frozen Legacies manual or automatic pick" in _UI_JS


def test_radar_frontend_uses_only_server_ids_and_no_paths():
    assert 'const API = "/frozen-legacies/api";' in _RADAR_JS
    assert 'path.startsWith("/frozen-legacies/") ? path : `${API}${path}`' in _RADAR_JS
    assert "/frozen-legacies/api/assets/" in (_APP / "assets" / "radar_geometry.js").read_text()
    for forbidden in ("source.tiff", "nav.csv", "users/", "owner_root"):
        assert forbidden not in _RADAR_JS


_AUTOMATIC_JS = (_APP / "assets" / "automatic.js").read_text(encoding="utf-8")
_PRODUCTS_JS = (_APP / "assets" / "products.js").read_text(encoding="utf-8")


def test_automatic_mode_runs_only_when_the_server_reports_the_picker_available():
    # the Run button is enabled only for a radar asset with the configured
    # picker available (and, for LYRA, a file it can read under its reel name)
    assert ("const canRun = info.has_radar && availability.available && info.lyra?.runnable !== false\n"
            "      && !running && !state.busy;") in _AUTOMATIC_JS
    # every picker label is the server's, never assumed by the browser
    assert 'info.picker_label || "URSA"' in _AUTOMATIC_JS and "job?.picker_label" in _AUTOMATIC_JS
    assert "is not available on this server" in _AUTOMATIC_JS
    assert "No automatic results have been produced" in _AUTOMATIC_JS
    # results shown are the server's products, never computed in the browser
    assert "info.products" in _AUTOMATIC_JS
    for forbidden in ("Surface_Time_us", "Ice_Thickness_m", "h_ice_m", "bed_twt_us",
                      "Math.random"):
        assert forbidden not in _AUTOMATIC_JS


def test_raw_radar_and_processed_product_uploads_are_separate():
    assert ">\n              Upload raw radar\n" in _INDEX
    assert ">\n              Upload processed product\n" in _INDEX
    assert _INDEX.count('id="fl-radar-upload"') == 1 and _INDEX.count('id="fl-product-upload"') == 1
    assert 'name="kind"' in _INDEX


def test_product_upload_kinds_match_the_server():
    import sys
    sys.path.insert(0, str(_APP.parents[2]))
    from icesee_jupyter_book.applications.frozen_legacies.radar import products

    kinds = re.findall(r'\{ kind: "([a-z-]+)", title: "([^"]+)", extensions: \[([^\]]*)\] \}', _PRODUCTS_JS)
    assert {k for k, _t, _e in kinds} == set(products.UPLOAD_KINDS)
    for kind, title, extensions in kinds:
        assert title == products.KINDS[kind]["title"]
        assert re.findall(r'"([^"]+)"', extensions) == list(products.KINDS[kind]["upload"])


def test_products_frontend_uses_product_ids_not_paths():
    for forbidden in ("outputs/", "source.tiff", "products.json", "session.json", "users/"):
        assert forbidden not in _PRODUCTS_JS
    assert "download_url" in _PRODUCTS_JS and "preview_url" in _PRODUCTS_JS
    assert "data-product-preview" in _PRODUCTS_JS
    assert "Preview here" in _PRODUCTS_JS and "Open full preview" in _PRODUCTS_JS


def test_product_preview_disclosure_and_provenance_are_accessible():
    assert 'aria-expanded="false"' in _PRODUCTS_JS
    assert 'aria-controls="${escapeHtml(previewId)}"' in _PRODUCTS_JS
    assert 'button.setAttribute("aria-expanded", String(opening))' in _PRODUCTS_JS
    assert 'role="region"' in _PRODUCTS_JS
    assert '<summary>Provenance</summary>' in _PRODUCTS_JS
    for field in ("picker", "written_by", "source_filename", "original_filename",
                  "shared_source", "sha256"):
        assert f"provenance.{field}" in _PRODUCTS_JS
    assert "overflow-wrap: anywhere" in (_APP / "assets" / "frozen_legacies.css").read_text(
        encoding="utf-8")


def test_right_panel_has_bounded_feature_detected_scientific_preview_slots():
    css = (_APP / "assets" / "frozen_legacies.css").read_text(encoding="utf-8")
    for key, label in (("source", "Source radar image"),
                       ("radargram", "Radargram / echogram"),
                       ("qc", "QC image"),
                       ("diagnostic", "Picker diagnostics")):
        assert f'key: "{key}", title: "{label}"' in _PRODUCTS_JS
    assert "product.available && product.preview_url" in _PRODUCTS_JS
    assert "Placeholder only · no scientific data shown" in _PRODUCTS_JS
    assert "Source material · not a scientific interpretation" in _PRODUCTS_JS
    assert "Scientifically unvalidated" in _PRODUCTS_JS
    assert "Loading preview…" in _PRODUCTS_JS and "Preview could not be loaded" in _PRODUCTS_JS
    assert 'aria-labelledby="fl-preview-shelf-title"' in _PRODUCTS_JS
    assert "max-height: 180px" in css and "object-fit: contain" in css
    assert "@media (max-width: 1100px)" in css


_PICKER_JS = (_APP / "assets" / "astra_picker.js").read_text(encoding="utf-8")


def test_manual_mode_offers_astras_controls_in_astras_order():
    """Button names and order follow the ASTRA control panel (ASTRA_MAC.py)."""
    labels = re.findall(
        r'<button type="button"[^>]*data-astra-(?:setup|feature)="[^"]+"[^>]*>([^<]+)</button>'
        r'|<button type="button" id="fl-astra-(?:suggest|next|done)"[^>]*>([^<]+)</button>',
        _INDEX,
    )
    names = [a or b for a, b in labels]
    assert names == [
        "Set Up X Axis Reference Line", "Set Up Y Axis Reference Line", "Set Up Y Axis",
        "Set Up X Axis", "Surface", "No Surface", "Bed", "No Bed", "Suggest Picks",
        "Noise Floor", "Main Bang", "Next A-scope", "Done",
    ]
    sweep = re.findall(r'data-astra-sweep="(\d)"', _INDEX)
    assert sweep == ["1", "2", "5"]
    steps = re.findall(r'data-astra-step="(\w+)"', _INDEX)
    assert steps == ["left", "right", "jump"] and "Move 1000 px" in _INDEX


def test_the_picker_sends_actions_not_scientific_results():
    # the browser never computes picks, calibration, CBDs or CSV content itself
    for forbidden in ("pixel_to_us", "pixel_to_db", "gaussian", "percentile", "168"):
        assert forbidden not in _PICKER_JS
    for action in ('action: "setup"', 'action: "select"', 'action: "click"', 'action: "move"',
                   'action: "step"', 'action: "suggest"', 'action: "next"', 'action: "done"',
                   'action: "reset"', 'action: "sweep_rate"'):
        assert action in _PICKER_JS
    assert "astraDataCoordinates" in _PICKER_JS


def test_manual_mode_no_longer_shows_the_placeholder_note():
    assert "Manual picking tools will be added" not in _RADAR_JS


_PRODUCTS_JS = (_APP / "assets" / "products.js").read_text(encoding="utf-8")
_AUTOMATIC_JS = (_APP / "assets" / "automatic.js").read_text(encoding="utf-8")


def test_manual_controls_are_three_numbered_workflow_steps():
    steps = re.findall(r'<span class="fl-astra-step-number">(\d)</span>\s*(\w[\w-]*)', _INDEX)
    assert steps == [("1", "Calibration"), ("2", "Picks"), ("3", "A-scope")]
    calibration = _INDEX.index("fl-astra-step-calibration")
    picks = _INDEX.index("fl-astra-step-picks")
    ascope = _INDEX.index("fl-astra-step-ascope")
    assert calibration < _INDEX.index('data-astra-setup="x_axis"') < picks
    assert picks < _INDEX.index('data-astra-feature="Main Bang"') < ascope
    assert ascope < _INDEX.index('id="fl-astra-reset"')


def test_trace_toggle_is_display_only():
    assert 'id="fl-astra-trace-toggle" checked' in _INDEX
    # the toggle only skips drawing; the trace sent to the server is untouched
    assert "if (traceVisible())" in _PICKER_JS
    assert "trace" not in re.findall(r'act\(\{[^}]*\}\)', _PICKER_JS)


def test_one_right_panel_ordered_by_mode():
    assert _INDEX.count('class="fl-panel"') == 1
    explorer = _INDEX.index('id="fl-explorer-section"')
    assert explorer < _INDEX.index('id="selected-record"') < _INDEX.index('id="fl-radar-panel"')
    assert "explorer.before(radar)" in _RADAR_JS and "explorer.after(radar)" in _RADAR_JS


def test_product_origins_are_distinguished():
    for label in ("Shared installation radar", "ASTRA manual result", "LYRA automatic result",
                  "URSA automatic result",
                  "User-provided product", "My upload"):
        assert label in _PRODUCTS_JS


def test_unavailable_automatic_picking_is_explicit():
    assert "Run automatic picking (unavailable)" in _AUTOMATIC_JS
    # operational availability never reads as scientific validation
    assert _AUTOMATIC_JS.count("Scientifically unvalidated") >= 2
    assert "cannot be submitted for review or publication" in _AUTOMATIC_JS


def test_automatic_frame_diagnostics_show_server_values_flags_and_picker_images():
    # the per-frame table renders the server's frames (the picker's values as
    # text), the heuristic flags and the picker's own images by product id
    # (LYRA's whole-strip figures too); nothing is recomputed or corrected in
    # the browser
    assert "framesHtml(info.frames, shown)" in _AUTOMATIC_JS
    assert "frames.strip_images" in _AUTOMATIC_JS
    assert "QC flags (heuristic)" in _AUTOMATIC_JS and "frames.note" in _AUTOMATIC_JS
    assert "data-diagnostic" in _AUTOMATIC_JS and "selected.preview_url" in _AUTOMATIC_JS
    assert "SHA-256" in _AUTOMATIC_JS and "frames.label" in _AUTOMATIC_JS
    for forbidden in ("outputs/", "ref_line_qa", "parseFloat", "toFixed(row"):
        assert forbidden not in _AUTOMATIC_JS
    # the Products panel lists them as one line, labelled unvalidated
    assert '[["ursa-diagnostic", "URSA"], ["lyra-diagnostic", "LYRA"]]' in _PRODUCTS_JS
    assert "${picker} diagnostic (unvalidated)" in _PRODUCTS_JS
    assert ".fl-automatic-frames-scroll" in (_APP / "assets" / "frozen_legacies.css").read_text(encoding="utf-8")


def test_automatic_guidance_upload_is_an_integrated_workflow_step():
    assert 'data-upload-guidance' in _AUTOMATIC_JS
    assert 'openUpload?.("lyra-guidance")' in _AUTOMATIC_JS
    assert 'How to create them' in _AUTOMATIC_JS
    assert 'openUpload,' in _PRODUCTS_JS
    # Product validation can change whether phases 3–4 are runnable, so the
    # Automatic state is refreshed after the Products module reloads.
    assert 'FrozenLegaciesAutomatic?.refresh?.()' in _RADAR_JS


def test_automatic_diagnostics_can_focus_on_flagged_frames():
    assert 'data-frame-filter="all"' in _AUTOMATIC_JS
    assert 'data-frame-filter="flagged"' in _AUTOMATIC_JS
    assert 'frames.rows.filter(row => row.flags?.length > 0)' in _AUTOMATIC_JS
    assert 'Needs review ${frames.flagged}' in _AUTOMATIC_JS


def test_automatic_phase_rail_uses_server_live_progress():
    assert "info.job?.progress?.phase" in _AUTOMATIC_JS
    for phase in ("phase1", "phase3", "phase4"):
        assert phase in _AUTOMATIC_JS


def test_private_map_layer_includes_distinct_automatic_results():
    assert 'feature.get("workflow") === "lyra-automatic"' in _USER_LAYER_JS
    assert 'Scientifically unvalidated' in _USER_LAYER_JS
    assert 'data-open-automatic' in _USER_LAYER_JS
    assert 'Show my manual and automatic results on the map' in _USER_LAYER_JS
    assert 'FrozenLegaciesUserLayer?.reload()' in _RADAR_JS
    assert "radius: 4.5" in _USER_LAYER_JS
    assert "radius: selected" not in _USER_LAYER_JS


_USER_LAYER_JS = (_APP / "assets" / "user_layer.js").read_text(encoding="utf-8")
_CATALOG_JS = (_APP / "assets" / "catalog.js").read_text(encoding="utf-8")


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("name", ["user_layer.js", "catalog.js"])
def test_new_scripts_parse(name):
    result = subprocess.run([_NODE, "--check", str(_APP / "assets" / name)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_my_picks_is_a_separate_owner_scoped_layer():
    assert '"/frozen-legacies/api/observations"' in _USER_LAYER_JS
    assert 'id: "frozen-my-picks"' in _USER_LAYER_JS
    # never reads or writes the shared observation data
    assert "observations.geojson" not in _USER_LAYER_JS
    assert "layer === state.layer" in _USER_LAYER_JS          # its own click handling


def test_catalog_browser_is_server_paginated_and_optional():
    assert '<button type="button" id="fl-catalog-toggle" class="fl-radar-button" hidden>' in _INDEX
    assert 'id="fl-catalog-browser" class="fl-catalog-browser" hidden' in _INDEX
    assert 'const API = "/frozen-legacies/api/radar/catalog";' in _CATALOG_JS
    assert "page_size" in _CATALOG_JS and "${API}/summary" in _CATALOG_JS
    assert "if (!state.summary || !state.summary.total)" in _CATALOG_JS
    # catalog entries are opened by reference, never listed into the asset selector
    assert "fl-radar-asset" not in _CATALOG_JS


# ── scientific workflow presentation ─────────────────────────────────
def test_control_pages_share_the_control_center_style_and_never_alert():
    from icesee_jupyter_book.applications.frozen_legacies import catalog_routes, review_routes
    from icesee_jupyter_book.applications.frozen_legacies.control_style import STYLE

    assert "[hidden] { display: none !important; }" in STYLE      # hidden fields stay hidden
    for script in (catalog_routes._CONTROL_SCRIPT, review_routes._REVIEW_SCRIPT):
        assert "alert(" not in script                              # inline notices instead
        assert "status-pill" in script
    page = (_APP / "catalog_routes.py").read_text(encoding="utf-8")
    assert 'data-provider="local"' in page and 'data-provider="s3"' in page
    assert "Never enter access keys" in page


def test_source_cards_keep_messages_and_open_problems_across_refreshes():
    from icesee_jupyter_book.applications.frozen_legacies import catalog_routes

    script = catalog_routes._CONTROL_SCRIPT
    # the periodic rebuild re-renders the last message and the open problem list
    assert "data-notice>${notices[s.source_id] ? noticeHtml(...notices[s.source_id])" in script
    assert 'data-problems${openProblems.has(s.source_id) ? " open" : ""}' in script
    assert 'sourceNotice(id, box, r.ok ? "ok" : "bad", esc(r.message))' in script


def test_review_page_separates_astra_film_and_published_cbd():
    from icesee_jupyter_book.applications.frozen_legacies import review_routes

    script = review_routes._REVIEW_SCRIPT
    for heading in ("ASTRA-assigned CBD", "Film CBD", "Published CBD"):
        assert heading in script
    # only "verified" maps to a verified position; everything else is labelled
    assert 'if (status === "verified") return {cbd: o.verified_cbd, pos: o.verified_position' in script
    assert '"Unverified · ASTRA-assigned"' in script


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("name", ["georef.js", "review.js", "published_layer.js", "user_layer.js"])
def test_workflow_scripts_parse(name):
    result = subprocess.run([_NODE, "--check", str(_APP / "assets" / name)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_manual_result_names_the_three_cbds_and_surfaces_confirmation():
    georef = (_APP / "assets" / "georef.js").read_text(encoding="utf-8")
    for heading in ("ASTRA-assigned CBD", "Film CBD (printed on the frame)", "Georeferenced CBD"):
        assert heading in georef
    assert "Confirm film CBDs" in georef and "fl-georef-callout" in georef
    assert "ASTRA's position, unverified" in georef


def test_workspace_layout_is_a_display_preference_that_keeps_the_click_mapping():
    picker = (_APP / "assets" / "astra_picker.js").read_text(encoding="utf-8")
    css = (_APP / "assets" / "frozen_legacies.css").read_text(encoding="utf-8")
    assert 'id="fl-layout-panel"' in _INDEX and 'id="fl-layout-focus"' in _INDEX
    # per-browser preference, guarded (private windows, blocked storage)
    load = _RADAR_JS[_RADAR_JS.index("function loadLayout"):_RADAR_JS.index("function applyLayout")]
    assert load.count("try {") == 2 and "localStorage" in load
    # the window box is sized at the exact aspect ratio and clicks are still
    # mapped against the box with the unchanged geometry function
    assert "FrozenLegaciesRadarGeometry.fitBox(" in picker
    assert 'astraDataCoordinates(\n      clientX, clientY, rect, geometry.zoom_width, geometry.zoom_height' in picker
    assert '$("fl-astra-box").getBoundingClientRect(), session.geometry' in picker
    # the box has no border: the image covers the whole mapped rectangle
    box = css[css.index(".fl-astra-box {"):]
    box = box[:box.index("}")]
    assert not re.search(r"^\s*border:", box, re.M) and "box-shadow" in box and "flex: none" in box


def test_url_state_carries_only_mode_asset_selection_and_map_view():
    block = _RADAR_JS[_RADAR_JS.index("const ASSET_ID"):_RADAR_JS.index("function bindUrlState")]
    assert "ASSET_ID = /^[0-9a-f]{32}$/" in block
    # the selected dataset/flight survive reload and back/forward; values are
    # validated tokens, and an unknown one is dropped rather than guessed
    assert "SELECTION_VALUE = /^[A-Za-z0-9._-]{1,64}$/" in block
    assert 'params.append("dataset", dataset)' in block and 'params.append("flight", flight)' in block
    assert "knownDataset" in block and "knownFlight" in block
    assert "syncUrl({ push: true })" in _RADAR_JS
    assert 'params.set("mode", state.mode)' in block and 'params.set("asset", state.asset.asset_id)' in block
    assert 'params.set("view", `${zoom.toFixed(2)}' in block
    # an asset in the URL opens only if it is one of the viewer's own assets
    assert "state.assets.some(a => a.asset_id === target.asset && a.available)" in block
    assert 'addEventListener("popstate"' in _RADAR_JS and '"moveend"' in _RADAR_JS
    # the review page's ?open=<catalog ID> deep link keeps working
    assert "/^cat-[0-9a-f]{24}$/.test(deepLink)" in _RADAR_JS


def test_url_camera_is_applied_after_the_selection_it_would_be_fitted_away_by():
    # selecting a dataset fits the map to its flights; the camera from the URL
    # must be applied after that, or a reload loses the user's map view
    block = _RADAR_JS[_RADAR_JS.index("async function applyUrlState"):_RADAR_JS.index("function restoreDatasetAndFlight")]
    assert block.index("restoreDatasetAndFlight(target)") < block.index("view.setCenter(")


def test_coverage_layer_and_selected_segment_survive_reload_and_back():
    block = _RADAR_JS[_RADAR_JS.index("const ASSET_ID"):_RADAR_JS.index("function bindUrlState")]
    # only a validated catalog ID, and only together with the coverage toggle
    assert "SEGMENT_ID = /^cat-[0-9a-f]{24}$/" in block
    assert 'params.get("cov") === "1"' in block
    assert "coverage && SEGMENT_ID.test(" in block
    assert 'params.set("cov", "1")' in block and 'params.set("seg", coverage.segment)' in block
    apply = block[block.index("async function applyUrlState"):block.index("function restoreDatasetAndFlight")]
    # restored after the camera, so it never moves the user's map view
    assert apply.index("view.setCenter(") < apply.index("FrozenLegaciesCatalog?.restore?.(")
    assert "onSelection: () => syncUrl({ push: true })" in _RADAR_JS
    assert "|| initial.coverage" in _RADAR_JS
    catalog_js = (_APP / "assets" / "catalog.js").read_text(encoding="utf-8")
    restore = catalog_js[catalog_js.index("async function restore("):catalog_js.index("function panelHtml")]
    # a segment is selected only if the loaded coverage contains it
    assert "getFeatureById(segment)" in restore and "await loadCoverage()" in restore
    assert "selection, restore" in catalog_js


def test_segments_without_navigation_are_labelled_unplaced():
    catalog_js = (_APP / "assets" / "catalog.js").read_text(encoding="utf-8")
    assert "Segments without navigation are not placed on the map." in catalog_js
    assert "none · unplaced" in catalog_js
