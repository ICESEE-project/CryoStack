# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Registry Delivery
# File        : registry_delivery.py
#
# Description :
#     Mirrors a CryoStack tested container image into Amazon ECR and returns
#     an immutable, digest-pinned reference for the Batch job definition.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-31
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Tested-image delivery into Amazon ECR for CryoStack cloud execution.

The *tested-image registry* (:mod:`cryostack_src.models.stack.images`) stays the
only source of truth for the image reference, its verified source digest, the
models it supports and its component provenance. This module only:

1. resolves the tested image for a model from that registry,
2. derives the destination ECR repository / reference,
3. mirrors the image **once** (registry-to-registry -- never rebuilt, never
   converted, never unpacked here) through an injected ``copier``,
4. verifies what actually landed in ECR and records the destination digest
   **separately** from the verified source digest, and
5. hands back an immutable ``<repo>@sha256:<destination-digest>`` reference.

The mirror is guarded by strict idempotency: the exact tested source is bound
to its ECR result with a provenance tag (``src-<short-source-digest>``) that
lives in ECR as infrastructure state -- it is never a second scientific
provenance record.

No registry credentials are ever placed in the returned result or in any
message. ECR auth is the caller's existing AWS identity; the public tested
image needs no Docker Hub credentials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from cryostack_src.models.stack.images import (
    TestedImage,
    default_tested_image_for_model,
)

from .auth import run_aws
from .batch_config import ECR_REPOSITORY_NAMES
from .models import AWSConfig
from .registry_provision import ensure_repository

# ── deterministic ECR names ─────────────────────────────────────────────────
TESTED_TAG = "tested"                          # human-friendly alias (never used by Batch)
_SOURCE_TAG_PREFIX = "src-"                    # binds an ECR image to its tested source

# ── ECR lifecycle policy ──────────────────────────────────────────────────
LIFECYCLE_UNTAGGED_EXPIRE_DAYS = 14

_LIFECYCLE_POLICY = {
    "rules": [
        {
            "rulePriority": 1,
            "description": (
                "Expire untagged images / stale job-definition layers after "
                f"{LIFECYCLE_UNTAGGED_EXPIRE_DAYS} days. Tagged images "
                "(tested, src-*, release/version tags) are always kept, so the "
                "digest a Batch job definition pins is never removed."
            ),
            "selection": {
                "tagStatus": "untagged",
                "countType": "sinceImagePushed",
                "countUnit": "days",
                "countNumber": LIFECYCLE_UNTAGGED_EXPIRE_DAYS,
            },
            "action": {"type": "expire"},
        }
    ]
}


class RegistryDeliveryError(RuntimeError):
    """The tested image could not be delivered to / verified in ECR."""


@dataclass
class ECRImageDelivery:
    """Infrastructure state describing a tested image mirrored into ECR.

    This is **not** scientific provenance -- ``resolve_stack()`` still produces
    the run's ``container`` block from the tested-image registry. This record
    only carries the AWS-side identity Cloud execution needs.
    """

    model: str
    repository: str
    repository_uri: str
    tag: str

    source_reference: str
    source_digest: str                        # verified tested-image identity

    destination_digest: str | None = None     # what ECR actually holds
    immutable_reference: str | None = None     # <repo_uri>@<destination_digest>
    architecture: str | None = None

    mirrored: bool = False                     # a copy ran this call
    reused: bool = False                       # already present + verified
    repaired: bool = False                     # :tested alias was moved
    verified: bool = False

    messages: list[str] = field(default_factory=list)

    def digests_match(self) -> bool:
        """True only when the ECR manifest digest is byte-identical to the
        tested source digest. A registry-to-registry copy may legitimately
        produce a different destination digest, so this is reported, never
        assumed."""
        return bool(
            self.destination_digest
            and self.destination_digest == self.source_digest
        )


# ── helpers ───────────────────────────────────────────────────────────────
def tested_image_for_model(model: str) -> TestedImage:
    image = default_tested_image_for_model(model)
    if image is None:
        raise RegistryDeliveryError(
            f"No tested image is registered for model {model!r}."
        )
    return image


def ecr_repository_name(model: str) -> str:
    key = (model or "").strip().lower()
    return ECR_REPOSITORY_NAMES.get(key, f"cryostack-{key}")


def _short_source_tag(source_digest: str) -> str:
    hexpart = source_digest.split(":", 1)[-1]
    return f"{_SOURCE_TAG_PREFIX}{hexpart[:16]}"


def _run(config: AWSConfig, args: list[str], *, what: str) -> tuple[int, str, str]:
    code, stdout, stderr = run_aws(config, args)
    return code, stdout, stderr


def _describe_ecr_image(
    config: AWSConfig, *, repository: str, image_id: str
) -> dict | None:
    """Return the ECR image detail for ``imageTag=...`` / ``imageDigest=...``
    or ``None`` when it does not exist."""
    code, stdout, stderr = _run(
        config,
        ["ecr", "describe-images", "--repository-name", repository,
         "--image-ids", image_id],
        what="ecr describe-images",
    )
    text = stderr or stdout or ""
    if code != 0:
        if "ImageNotFoundException" in text or "RepositoryNotFoundException" in text:
            return None
        raise RegistryDeliveryError(text.strip() or "ecr describe-images failed.")
    details = json.loads(stdout or "{}").get("imageDetails", [])
    return details[0] if details else None


def _image_architecture(detail: dict) -> str | None:
    # describe-images may surface it directly, or inside the manifest media type.
    return (
        detail.get("imageArchitecture")
        or (detail.get("imageManifestPlatform") or {}).get("architecture")
        or None
    )


def _add_tag_to_digest(
    config: AWSConfig, *, repository: str, source_digest: str, new_tag: str
) -> None:
    """Give an existing ECR manifest an additional tag (used for the
    ``src-<digest>`` provenance tag and to repair the ``:tested`` alias)."""
    code, stdout, stderr = _run(
        config,
        ["ecr", "batch-get-image", "--repository-name", repository,
         "--image-ids", f"imageDigest={source_digest}"],
        what="ecr batch-get-image",
    )
    if code != 0:
        raise RegistryDeliveryError(
            (stderr or stdout).strip() or "ecr batch-get-image failed."
        )
    images = json.loads(stdout or "{}").get("images", [])
    if not images:
        raise RegistryDeliveryError(
            f"ECR manifest {source_digest} not found in {repository}."
        )
    manifest = images[0]["imageManifest"]
    media_type = images[0].get("imageManifestMediaType")

    args = [
        "ecr", "put-image", "--repository-name", repository,
        "--image-manifest", manifest, "--image-tag", new_tag,
    ]
    if media_type:
        args += ["--image-manifest-media-type", media_type]
    code, stdout, stderr = _run(config, args, what="ecr put-image")
    text = stderr or stdout or ""
    if code != 0 and "ImageAlreadyExistsException" not in text:
        raise RegistryDeliveryError(text.strip() or "ecr put-image failed.")


# ── ECR lifecycle policy ─────────────────────────────────────────────────
def ensure_ecr_lifecycle_policy(config: AWSConfig, *, repository: str) -> bool:
    """Install CryoStack's ECR lifecycle policy on ``repository`` if missing or
    drifted. Returns ``True`` when it was written. Never removes tagged images,
    so the digest a Batch job definition pins is safe."""
    desired = json.dumps(_LIFECYCLE_POLICY, sort_keys=True)

    code, stdout, stderr = _run(
        config,
        ["ecr", "get-lifecycle-policy", "--repository-name", repository],
        what="ecr get-lifecycle-policy",
    )
    if code == 0:
        current_text = json.loads(stdout or "{}").get("lifecyclePolicyText", "")
        try:
            current = json.dumps(json.loads(current_text), sort_keys=True)
        except (ValueError, TypeError):
            current = ""
        if current == desired:
            return False
    elif "LifecyclePolicyNotFoundException" not in (stderr or stdout or ""):
        raise RegistryDeliveryError(
            (stderr or stdout).strip() or "ecr get-lifecycle-policy failed."
        )

    code, stdout, stderr = _run(
        config,
        ["ecr", "put-lifecycle-policy", "--repository-name", repository,
         "--lifecycle-policy-text", json.dumps(_LIFECYCLE_POLICY)],
        what="ecr put-lifecycle-policy",
    )
    if code != 0:
        raise RegistryDeliveryError(
            (stderr or stdout).strip() or "ecr put-lifecycle-policy failed."
        )
    return True


# ── the delivery primitive ───────────────────────────────────────────────
def mirror_tested_image(
    config: AWSConfig,
    *,
    model: str,
    copier=None,
) -> ECRImageDelivery:
    """Ensure the model's tested image is present in ECR and return an
    immutable, digest-pinned reference.

    ``copier`` is ``callable(source_reference: str, destination_reference: str)``
    performing a **registry-to-registry** copy (no local rebuild / unpack). When
    ``None`` and a mirror would be required, a :class:`RegistryDeliveryError` is
    raised -- the transfer mechanism must be chosen explicitly.
    """
    image = tested_image_for_model(model)
    repository = ecr_repository_name(model)

    repo_detail, _ = ensure_repository(config, repository_name=repository)
    repository_uri = repo_detail.get("repositoryUri") or ""
    if not repository_uri:
        raise RegistryDeliveryError(
            f"Could not resolve the ECR repository URI for {repository}."
        )

    ensure_ecr_lifecycle_policy(config, repository=repository)

    result = ECRImageDelivery(
        model=(model or "").strip().lower(),
        repository=repository,
        repository_uri=repository_uri,
        tag=TESTED_TAG,
        source_reference=image.reference,
        source_digest=image.digest,
    )

    src_tag = _short_source_tag(image.digest)
    tested_detail = _describe_ecr_image(
        config, repository=repository, image_id=f"imageTag={TESTED_TAG}")
    source_bound = _describe_ecr_image(
        config, repository=repository, image_id=f"imageTag={src_tag}")

    # ---------------------------------------------------------------
    # Already delivered: an image carries our src-<digest> provenance tag.
    # ---------------------------------------------------------------
    if source_bound is not None:
        dest_digest = source_bound.get("imageDigest")
        result.destination_digest = dest_digest
        result.architecture = _image_architecture(source_bound)

        if tested_detail is None or tested_detail.get("imageDigest") != dest_digest:
            # :tested is missing or points at the wrong image -> repair the alias
            _add_tag_to_digest(
                config, repository=repository,
                source_digest=dest_digest, new_tag=TESTED_TAG)
            result.repaired = True
            result.messages.append(
                f"Repaired :{TESTED_TAG} alias -> {dest_digest}.")
        else:
            result.reused = True
            result.messages.append(
                f"Tested image already in ECR ({dest_digest}); no transfer.")

        result.verified = True
        result.immutable_reference = f"{repository_uri}@{dest_digest}"
        return result

    # ---------------------------------------------------------------
    # Not delivered yet -> mirror once.
    # ---------------------------------------------------------------
    if copier is None:
        raise RegistryDeliveryError(
            "The tested image is not in ECR and no registry copier is "
            "configured. Choose an image-transfer mechanism (see the Cloud "
            "Commit 2 report) before running Prepare."
        )

    destination = f"{repository_uri}:{TESTED_TAG}"
    try:
        copier(image.reference, destination)
    except Exception as err:  # noqa: BLE001 - surfaced as a delivery failure
        raise RegistryDeliveryError(
            f"Registry-to-registry copy failed: {err}"
        ) from err
    result.mirrored = True

    pushed = _describe_ecr_image(
        config, repository=repository, image_id=f"imageTag={TESTED_TAG}")
    if pushed is None or not pushed.get("imageDigest"):
        raise RegistryDeliveryError(
            "Mirror reported success but no image is present in ECR under "
            f":{TESTED_TAG}. Aborting before any Batch change."
        )

    dest_digest = pushed["imageDigest"]
    result.destination_digest = dest_digest
    result.architecture = _image_architecture(pushed)

    # Bind this ECR image to the exact tested source for future idempotency.
    _add_tag_to_digest(
        config, repository=repository, source_digest=dest_digest, new_tag=src_tag)

    result.verified = True
    result.immutable_reference = f"{repository_uri}@{dest_digest}"
    result.messages.append(
        f"Mirrored {image.reference} -> {repository}@{dest_digest} "
        f"(source digest {image.digest}"
        + ("" if result.digests_match() else "; destination digest differs -- "
           "recorded separately")
        + ")."
    )
    return result


# ── default registry-to-registry copier (opt-in) ─────────────────────────
def buildx_imagetools_copier(config: AWSConfig):
    """A ``copier`` backed by ``docker buildx imagetools create`` -- a
    registry-to-registry manifest+blob copy that never builds, converts or
    unpacks the image into local storage.

    NOTE: image blobs still stream through this host. It is opt-in: pass the
    returned callable into :func:`mirror_tested_image` only when that is an
    acceptable one-time transfer. Docker Hub is public, so no upstream
    credentials are used; ECR auth is the ambient AWS identity.
    """
    import subprocess

    def _copy(source_reference: str, destination_reference: str) -> None:
        registry = destination_reference.split("/", 1)[0]
        code, password, stderr = run_aws(config, ["ecr", "get-login-password"])
        if code != 0:
            raise RegistryDeliveryError("Could not obtain an ECR login token.")
        login = subprocess.run(
            ["docker", "login", "--username", "AWS", "--password-stdin", registry],
            input=password, capture_output=True, text=True,
        )
        if login.returncode != 0:
            raise RegistryDeliveryError("docker login to ECR failed.")
        copy = subprocess.run(
            ["docker", "buildx", "imagetools", "create",
             "--tag", destination_reference, source_reference],
            capture_output=True, text=True,
        )
        if copy.returncode != 0:
            # never echo the login token; only the copy's own stderr
            raise RegistryDeliveryError(
                (copy.stderr or copy.stdout).strip() or "imagetools copy failed."
            )

    return _copy
