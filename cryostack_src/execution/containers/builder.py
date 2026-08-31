from __future__ import annotations

from .docker import build_image
from .models import ContainerImage


def build(
    image: ContainerImage,
) -> ContainerImage:
    """
    Build a container image and return its metadata.
    """

    build_image(
        image
    )

    return image