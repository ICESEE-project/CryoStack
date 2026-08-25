import subprocess

from .models import ContainerImage


def build_image(

    image: ContainerImage,

):

    subprocess.run(

        [

            "docker",

            "build",

            "-t",

            f"{image.name}:{image.tag}",

            "-f",

            str(image.dockerfile),

            str(image.context),

        ],

        check=True,

    )