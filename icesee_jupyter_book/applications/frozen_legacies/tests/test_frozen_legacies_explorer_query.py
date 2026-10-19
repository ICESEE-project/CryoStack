from __future__ import annotations

from multidict import MultiDict
import pytest

from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import CatalogError
from icesee_jupyter_book.applications.frozen_legacies.radar.explorer_query import (
    decode_cursor, encode_cursor, parse_explorer_query)


def test_explorer_query_is_canonical_and_cursor_is_bound():
    query = parse_explorer_query(MultiDict([
        ("flight", "127"), ("dataset", "z"), ("dataset", "a"),
        ("cbd_max", "483"), ("cbd_min", "471"),
        ("bbox", "170,-90,-170,-70"), ("spatial", "intersects"),
    ]))
    assert query.canonical() == {
        "qv": 1, "audience": "workspace", "dataset": ["a", "z"],
        "flight": ["127"], "cbd_min": 471, "cbd_max": 483,
        "bbox": "170,-90,-170,-70", "crs": "EPSG:4326", "spatial": "intersects",
    }
    token = encode_cursor(50, query.fingerprint())
    assert decode_cursor(token, query.fingerprint()) == 50
    with pytest.raises(CatalogError):
        decode_cursor(token, "another-query")


@pytest.mark.parametrize("values", [
    [("qv", "2")], [("audience", "published")], [("crs", "EPSG:3031")],
    [("cbd_min", "5"), ("cbd_max", "4")], [("bbox", "nan,-80,2,-70")],
    [("q", "x" * 101)], [("product", "radargram")],
    [("flight", "127"), ("flight", "../private")],
    [("qv", "1"), ("qv", "2")], [("unknown", "x")],
])
def test_explorer_query_rejects_ambiguous_or_unimplemented_filters(values):
    with pytest.raises(CatalogError):
        parse_explorer_query(MultiDict(values))
