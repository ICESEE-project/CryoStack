import subprocess

from .models import ContainerImage


def push_to_ecr(

    image: ContainerImage,

):

    if image.uri is None:

        raise RuntimeError(

            "Image URI has not been assigned."

        )

    subprocess.run(

        [

            "docker",

            "tag",

            f"{image.name}:{image.tag}",

            image.uri,

        ],

        check=True,

    )

    subprocess.run(

        [

            "docker",

            "push",

            image.uri,

        ],

        check=True,

    )