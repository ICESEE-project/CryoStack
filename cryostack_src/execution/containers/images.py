from __future__ import annotations

from .models import ContainerImage


def issm_image(
    *,
    tag: str = "latest",
    source_uri: str | None = None,
) -> ContainerImage:

    return ContainerImage(
        name="cryostack-issm",
        tag=tag,
        source_uri=source_uri,
        runtime="docker",
        metadata={
            "model": "issm",
        },
    )


def icepack_image(
    *,
    tag: str = "latest",
    source_uri: str | None = None,
) -> ContainerImage:

    return ContainerImage(
        name="cryostack-icepack",
        tag=tag,
        source_uri=source_uri,
        runtime="docker",
        metadata={
            "model": "icepack",
        },
    )