from pathlib import Path

from .models import ContainerImage


def issm_image(root: Path) -> ContainerImage:

    return ContainerImage(

        name="cryostack-issm",

        tag="latest",

        repository="cryostack-issm",

        dockerfile=root
        / "containers"
        / "issm"
        / "Dockerfile",

        context=root
        / "containers"
        / "issm",
    )