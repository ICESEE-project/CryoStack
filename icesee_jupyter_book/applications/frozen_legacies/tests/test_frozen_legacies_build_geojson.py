from types import SimpleNamespace

from icesee_jupyter_book.applications.frozen_legacies.build_geojson import (
    split_flight_segments,
)


def _observation(cbd, frame_idx, lon, *, tiff_id):
    return SimpleNamespace(
        cbd=cbd,
        frame_idx=frame_idx,
        longitude=lon,
        latitude=-80.0,
        metadata={"tiff_id": tiff_id},
        observation_id=f"{tiff_id}-{frame_idx}",
    )


def test_flight_geometry_uses_flight_wide_cbd_not_resetting_frame_index():
    # Two TIFFs both restart frame_idx at 1. Frame-index ordering would create
    # 0 -> 2 -> 1 -> 3, the fan-shaped false connectors seen in production.
    observations = [
        _observation(100, 1, 0.0, tiff_id=10),
        _observation(102, 1, 2.0, tiff_id=20),
        _observation(101, 2, 1.0, tiff_id=10),
        _observation(103, 2, 3.0, tiff_id=20),
    ]

    segments = split_flight_segments(observations, max_segment_jump_km=1000)

    assert segments == [[[0.0, -80.0], [1.0, -80.0],
                         [2.0, -80.0], [3.0, -80.0]]]
