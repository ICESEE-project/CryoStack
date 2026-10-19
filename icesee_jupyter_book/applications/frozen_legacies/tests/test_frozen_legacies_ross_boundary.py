import json
from pathlib import Path

from icesee_jupyter_book.applications.frozen_legacies.build_ross_boundary import build


APP = Path(__file__).resolve().parents[1]


def test_ross_boundary_is_reproducible_and_scientifically_labeled(tmp_path):
    generated = build(output=tmp_path / "ross.geojson")
    tracked = json.loads(
        (APP / "data/antarctica/ross_ice_shelf.geojson").read_text(encoding="utf-8")
    )
    assert generated == tracked
    feature = tracked["features"][0]
    assert feature["id"] == "ross-ice-shelf"
    assert feature["properties"]["name"] == "Ross Ice Shelf"
    assert feature["properties"]["display_only"] is True
    assert 470_000 <= feature["properties"]["area_km2_approx"] <= 490_000


def test_frontend_loads_boundary_before_data_and_preserves_full_features():
    index = (APP / "index.html").read_text(encoding="utf-8")
    data = (APP / "assets/data.js").read_text(encoding="utf-8")
    assert index.index("ross_focus.js") < index.index("data.js")
    assert "ross_ice_shelf.geojson" in data
    assert "FrozenLegaciesRossFocus.focus" in data
    assert "fullFlightFeatures" in data
    assert "fullObservationFeatures" in data
