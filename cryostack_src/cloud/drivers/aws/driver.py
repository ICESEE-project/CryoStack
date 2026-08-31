# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : AWS Driver
# File        : driver.py
#
# Description :
#     Provides the high-level AWS cloud driver used by CryoStack to
#     discover and prepare AWS resources.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-24
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
AWS cloud driver for CryoStack.

The driver combines AWS authentication, storage, networking, IAM,
registry, Batch, and capability discovery behind one interface.

Resource provisioning is introduced incrementally. Storage and IAM
can currently be prepared automatically, while registry and AWS Batch
resources remain discovery-only until their provisioning layers are
completed.
"""

from __future__ import annotations

from ..base import CloudDriver

from .auth import (
    AWSCredentialsError,
    discover_account,
)

from .batch import (
    discover_batch_resources,
)

from .batch_config import (
    DEFAULT_MAX_VCPUS,
)

from .batch_provision import (
    AWSBatchProvisionResult,
    ensure_batch_resources,
)

from .registry_delivery import (
    RegistryDeliveryError,
    buildx_imagetools_copier,
    mirror_tested_image,
)

from .capabilities import (
    discover_capabilities,
)

from .iam import (
    discover_iam_resources,
)

from .iam_provision import (
    ensure_iam_resources,
)

from .models import (
    AWSConfig,
)

from .network import (
    discover_network_resources,
)

from .registry import (
    discover_registry_resources,
)

from .storage import (
    prepare_storage,
)

from .registry_provision import (
    ensure_registry_resources,
)

from cryostack_src.cloud.legacy.aws_batch import (
    batch_logs,
    batch_status,
    terminate_batch_job,
)

class AWSDriver(
    CloudDriver
):
    """
    CryoStack AWS cloud driver.
    """

    name = "aws"

    def __init__(
        self,
        *,
        region: str = "us-east-2",
        profile: str | None = None,
        submitter=None,
    ) -> None:

        self.config = AWSConfig(
            region=region,
            profile=profile,
        )

        #
        # Transitional submission hook.
        #
        # ISSM cloud submission will move fully into the AWS
        # driver after Batch provisioning is completed.
        #
        self._submitter = submitter

    def account(
        self,
    ):

        return discover_account(
            self.config
        )

    def capabilities(
        self,
    ):

        return discover_capabilities(
            self.config
        )

    def prepare_storage(
        self,
        *,
        bucket: str | None = None,
    ):

        return prepare_storage(
            self.config,
            bucket=bucket,
        )

    def network(
        self,
    ):

        return discover_network_resources(
            self.config
        )

    def iam(
        self,
    ):

        return discover_iam_resources(
            self.config
        )

    def registry(
        self,
    ):

        return discover_registry_resources(
            self.config
        )

    def batch(
        self,
    ):

        return discover_batch_resources(
            self.config
        )

    def prepare_batch(
        self,
        *,
        network=None,
        iam=None,
        registry=None,          # accepted for call-site compatibility; unused
        max_vcpus: int = DEFAULT_MAX_VCPUS,
        include_icepack: bool = False,
        image_copier=None,
    ) -> AWSBatchProvisionResult:
        """
        Idempotently provision AWS Batch on Fargate: a scale-to-zero compute
        environment, a job queue, and the ISSM job definition (+ log group).

        The ISSM job definition is pinned to the tested image **by digest**:
        the tested image is mirrored into ECR (once) and the resulting
        ``<repo>@sha256:...`` reference feeds the job definition. A failed or
        unconfigured mirror leaves the job definition untouched -- CryoStack
        never points Batch at an unverified image.

        Discovery results for network / IAM may be passed in to avoid
        re-describing. ``image_copier`` overrides the transfer mechanism; by
        default it is ``buildx_imagetools_copier`` -- a one-time, idempotent
        registry-to-registry copy (``docker buildx imagetools create``): no
        image rebuild, no Apptainer conversion, and Batch never depends on a
        mutable tag. The copy runs only when the exact tested image is not
        already in ECR.
        """

        network = network or self.network()
        iam = iam or self.iam()

        copier = (image_copier if image_copier is not None
                  else buildx_imagetools_copier(self.config))

        delivery = None
        issm_image = None
        delivery_messages: list[str] = []
        try:
            delivery = mirror_tested_image(
                self.config, model="issm", copier=copier,
            )
            if delivery.verified and delivery.immutable_reference:
                issm_image = delivery.immutable_reference
                delivery_messages.extend(delivery.messages)
        except RegistryDeliveryError as err:
            delivery_messages.append(
                f"Tested-image delivery not ready: {err} "
                "-- ISSM job definition left unchanged."
            )

        result = ensure_batch_resources(
            self.config,
            subnets=network.subnet_ids,
            security_groups=network.security_group_ids,
            job_role_arn=iam.job_role,
            execution_role_arn=iam.ecs_execution_role,
            issm_image=issm_image,
            max_vcpus=max_vcpus,
            include_icepack=include_icepack,
        )
        result.image_delivery = delivery
        result.messages.extend(delivery_messages)
        return result

    def bootstrap(
        self,
        *,
        bucket: str | None = None,
    ) -> dict:
        """
        Prepare the AWS environment currently supported by CryoStack.

        The bootstrap sequence currently:

        1. verifies the AWS connection,
        2. prepares S3 run storage,
        3. discovers usable networking,
        4. prepares required IAM roles,
        5. discovers ECR repositories,
        6. discovers AWS Batch resources,
        7. recalculates the final capability state.

        Registry and Batch provisioning will be added separately.
        """

        messages: list[str] = []

        #
        # ---------------------------------------------------------
        # Account
        # ---------------------------------------------------------
        #
        account = self.account()

        if not account.authenticated:

            return {
                "success": False,
                "provider": self.name,
                "region": self.config.region,
                "account": account,
                "storage": None,
                "network": None,
                "iam": None,
                "registry": None,
                "batch": None,
                "capabilities": self.capabilities(),
                "messages": [
                    "AWS account is not connected.",
                ],
            }

        messages.append(
            "AWS account connected."
        )

        #
        # ---------------------------------------------------------
        # Storage
        # ---------------------------------------------------------
        #
        try:

            storage = self.prepare_storage(
                bucket=bucket,
            )

        except AWSCredentialsError:

            return {
                "success": False,
                "provider": self.name,
                "region": self.config.region,
                "account": account,
                "storage": None,
                "network": None,
                "iam": None,
                "registry": None,
                "batch": None,
                "capabilities": None,
                "messages": [
                    "AWS credentials are not available.",
                ],
            }

        if storage.created:

            messages.append(
                "CryoStack S3 storage created."
            )

        else:

            messages.append(
                "CryoStack S3 storage already exists."
            )

        #
        # ---------------------------------------------------------
        # Network
        # ---------------------------------------------------------
        #
        network = self.network()

        if (
            network.vpc_id
            and network.subnet_ids
            and network.security_group_ids
        ):

            messages.append(
                "AWS networking discovered."
            )

        else:

            messages.append(
                "AWS networking is incomplete."
            )

        #
        # ---------------------------------------------------------
        # IAM
        # ---------------------------------------------------------
        #
        iam_result = ensure_iam_resources(
            self.config,
            bucket=storage.bucket,
        )

        iam = iam_result.resources

        if iam_result.created:

            messages.append(
                "Created IAM resources: "
                + ", ".join(
                    iam_result.created
                )
            )

        if iam_result.reused:

            messages.append(
                "Reused IAM resources: "
                + ", ".join(
                    iam_result.reused
                )
            )

        #
        # ---------------------------------------------------------
        # Registry
        # ---------------------------------------------------------
        #
        registry_result = self.prepare_registry(
            include_icepack=False,
        )

        registry = registry_result.resources

        if registry_result.created:

            messages.append(
                "Created ECR repositories: "
                + ", ".join(
                    registry_result.created
                )
            )

        if registry_result.reused:

            messages.append(
                "Reused ECR repositories: "
                + ", ".join(
                    registry_result.reused
                )
            )

        #
        # ---------------------------------------------------------
        # Batch (Fargate) provisioning
        # ---------------------------------------------------------
        #
        batch_result = self.prepare_batch(
            network=network,
            iam=iam,
            registry=registry,
        )

        batch = batch_result.resources

        for label, items in (
            ("Created", batch_result.created),
            ("Updated", batch_result.updated),
            ("Reused", batch_result.reused),
        ):
            if items:
                messages.append(
                    f"{label} AWS Batch resources: "
                    + ", ".join(items)
                )

        for skipped in batch_result.skipped:
            messages.append(
                f"AWS Batch: skipped {skipped}"
            )

        for message in batch_result.messages:
            messages.append(message)

        if (
            batch.compute_environment
            and batch.job_queue
            and batch.issm_job_definition
        ):

            messages.append(
                "AWS Batch environment is ready."
            )

        else:

            messages.append(
                "AWS Batch environment is incomplete."
            )

        #
        # Recalculate after provisioning.
        #
        capabilities = self.capabilities()

        success = bool(
            capabilities.authenticated
            and capabilities.storage_ready
            and capabilities.network_ready
            and capabilities.iam_ready
            and capabilities.batch_ready
        )

        return {
            "success": success,
            "provider": self.name,
            "region": self.config.region,
            "account": account,
            "storage": storage,
            "network": network,
            "iam": iam,
            "registry": registry,
            "batch": batch,
            "capabilities": capabilities,
            "messages": messages,
        }

    def prepare_registry(
        self,
        *,
        include_icepack: bool = False,
    ):

        return ensure_registry_resources(
            self.config,
            include_icepack=include_icepack,
        )

    def submit(
        self,
        **kwargs,
    ):
        """
        Submit a cloud workload.

        During the strangler migration, existing cloud submission
        implementations may be injected through ``submitter``.
        """

        if self._submitter is None:
            raise RuntimeError(
                "AWS cloud submission is not configured yet."
            )

        return self._submitter(
            **kwargs
        )

    def status(
        self,
        job_id: str,
    ):

        return batch_status(
            self.config,
            job_id,
        )

    def logs(
        self,
        job_id: str,
    ):

        return batch_logs(
            self.config,
            job_id,
        )

    def terminate(
        self,
        job_id: str,
    ):

        return terminate_batch_job(
            self.config,
            job_id,
        )