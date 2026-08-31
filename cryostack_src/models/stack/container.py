"""Container identity for the reproducibility contract.

The selected software versions are not enough to reproduce a run: the container
they run inside is part of the contract. Whenever a Docker/OCI source is used we
anchor on the *resolved image digest*; a mutable tag such as ``latest`` is never
the only thing recorded. For git/local source modes an OCI digest does not
exist, so we preserve whatever immutable image/build provenance we actually know
(the ICESEE-Containers definition + its pinned base image + base digest) rather
than fabricating a digest.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .images import TestedImage

ICESEE_CONTAINERS_REPO = "https://github.com/ICESEE-project/ICESEE-Containers.git"
ICESEE_CONTAINERS_DEF = "spack-managed/combined-container/combined-env-inbuilt-matlab.def"

# The immutable OCI base that the proven combined-env.sif (and the not-yet-
# published icesee-combined image) derive from — verified against Docker Hub.
BASE_IMAGE_REF = "docker.io/bkyanjo/combined-lean:v1.0"
BASE_IMAGE_DIGEST = "sha256:e2dc1c0dec138c632f4db95de89775a62175c3542170012c093845bd4e0e63f3"


class ContainerIdentityError(RuntimeError):
    """A container source/reference combination that must not reach submission."""


@dataclass(frozen=True)
class ContainerIdentity:
    source: str                       # "docker" | "local" | "git"
    reference: str | None             # image ref / SIF path / None
    digest: str | None                # "sha256:..." when known (OCI), else None
    build_provenance: dict = field(default_factory=dict)

    def as_provenance(self) -> dict:
        out: dict = {
            "source": self.source,
            "reference": self.reference,
            "digest": self.digest,
        }
        if self.build_provenance:
            out["build_provenance"] = dict(self.build_provenance)
        return out


def resolve_container(
    *,
    container_source: str | None,
    image_uri: str | None,
    tested_image: TestedImage | None = None,
    digest_resolver=None,
) -> ContainerIdentity:
    """Resolve the container the run will execute in.

    ``tested_image`` is a curated :class:`~cryostack_src.models.stack.TestedImage`
    the user selected from the tested-image dropdown; when present (Docker/OCI
    source only) the run anchors on its registry reference and *verified* digest
    and no user-typed URI is needed.

    ``digest_resolver`` is an optional callable ``(oci_ref) -> "sha256:..."|None``
    (e.g. ``skopeo inspect``); when absent, a *custom* Docker/OCI reference is
    recorded without a digest and the caller is responsible for surfacing that
    gap. A mutable tag is never recorded as if it were immutable.
    """
    src = (container_source or "git").strip().lower()
    uri = (image_uri or "").strip()

    if src in {"docker", "oci"}:
        if tested_image is not None:
            return ContainerIdentity(
                source="docker",
                reference=tested_image.docker_reference,
                digest=tested_image.digest,
                build_provenance={
                    "tested_image": tested_image.key,
                    "tested_image_label": tested_image.label,
                    "digest_source": "cryostack-tested-registry",
                },
            )
        if not uri:
            raise ContainerIdentityError(
                "Docker/OCI source selected but no image reference was provided."
            )
        ref = uri if "://" in uri else f"docker://{uri}"
        digest = None
        if digest_resolver is not None:
            digest = digest_resolver(ref) or None
        prov: dict = {}
        if digest is None:
            prov["digest_status"] = "unresolved"
        if uri and "@sha256:" not in uri and ":" in uri.rsplit("/", 1)[-1]:
            prov["requested_tag"] = uri.rsplit(":", 1)[-1]
        return ContainerIdentity(source="docker", reference=ref, digest=digest,
                                 build_provenance=prov)

    if src == "local":
        return ContainerIdentity(
            source="local",
            reference=uri or None,
            digest=None,
            build_provenance={"sif_path": uri or None, "digest_status": "not-applicable"},
        )

    # git build mode: combined-env-inbuilt-matlab.def -> combined-env.sif on the
    # cluster. No OCI digest exists; record the immutable build inputs we know.
    return ContainerIdentity(
        source="git",
        reference=None,
        digest=None,
        build_provenance={
            "digest_status": "not-applicable",
            "icesee_containers_repo": ICESEE_CONTAINERS_REPO,
            "definition": ICESEE_CONTAINERS_DEF,
            "base_image": BASE_IMAGE_REF,
            "base_image_digest": BASE_IMAGE_DIGEST,
        },
    )
