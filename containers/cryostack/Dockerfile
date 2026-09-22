# syntax=docker/dockerfile:1
#
# CryoStack platform/gateway image (ghcr.io/icesee-project/cryostack).
#
# This is NOT the ISSM/Firedrake/Icepack/MATLAB scientific-compute image
# (that build lives at tools/cloud/Dockerfile, is published separately to a
# personal Docker Hub namespace, and is not touched by this file). This
# image is the web platform only: the aiohttp gateway (bin/icesee_app.py),
# its two Voila-backed applications, the static Jupyter Book site (Frozen
# Legacies + application docs included), the LIVIST frontend, and the
# connector relay server. Scientific execution (ISSM/HPC/AWS Batch) is
# driven BY this gateway but happens on remote resources it talks to, not
# inside this image.
#
# Built entirely from public dependencies: conda-forge + PyPI via
# tools/icesee1_environment.yml (the same environment file
# .github/workflows/tests.yml already installs and tests on public
# GitHub-hosted runners), plus a public npm/yarn registry for the LIVIST
# frontend build stage below. No private index, no institutional channel.

# ============================================================================
# Stage: livist-builder -- builds the LIVIST (external/living-ice-sheet-
# temperature) frontend from its own, unmodified upstream source. Multi-stage
# so the Node/yarn toolchain and node_modules (hundreds of MB) never reach
# the final runtime image -- only the built static dist/ output does.
#
# LIVIST is a separate MIT-licensed upstream project (see
# external/living-ice-sheet-temperature/LICENSE, preserved and copied into
# the final image below for attribution); this stage runs its own documented
# build (`yarn install --immutable && yarn build`, per
# deployment/applications.yaml's "livist" target and the submodule's own
# README) verbatim, with no source modification. Its vite.config.ts already
# pins `base: "/livist/"`, matching exactly where bin/icesee_app.py's
# livist_root() serves it -- no path rewriting needed.
# ============================================================================
FROM node:22-slim AS livist-builder

WORKDIR /build

COPY external/living-ice-sheet-temperature/frontend/package.json \
     external/living-ice-sheet-temperature/frontend/yarn.lock \
     external/living-ice-sheet-temperature/frontend/.yarnrc.yml \
     ./
COPY external/living-ice-sheet-temperature/frontend/.yarn ./.yarn

RUN corepack enable \
    && corepack prepare yarn@4.13.0 --activate \
    && yarn install --immutable

COPY external/living-ice-sheet-temperature/frontend/ ./
RUN yarn build

# ============================================================================
# Stage: cryostack -- the platform/gateway runtime image.
# ============================================================================
FROM condaforge/miniforge3:26.7.2-0@sha256:eeb947cc87d61d46820b123bd7c26e1cbdc4b182ff7d0331e501a32a936b82e3

LABEL org.opencontainers.image.title="CryoStack" \
      org.opencontainers.image.description="CryoStack: open-source cyberinfrastructure stack for assembling reproducible cryosphere workflows from scientific applications, user workspaces, data catalogs, simulation configurations, and heterogeneous execution resources." \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/ICESEE-project/CryoStack" \
      org.opencontainers.image.url="https://cryostack.eas.gatech.edu/" \
      org.opencontainers.image.vendor="ICESEE Project"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ICESEE_ENV_NAME=cryostack \
    CRYOSTACK_HOST=0.0.0.0

WORKDIR /opt/cryostack

# ---- dependency layer -----------------------------------------------------
# Copied alone first so the (large, slow) conda solve/download only reruns
# when the environment spec itself changes, not on every source edit.
COPY tools/icesee1_environment.yml /opt/cryostack/tools/icesee1_environment.yml

RUN conda env create -n cryostack -f /opt/cryostack/tools/icesee1_environment.yml \
    && conda clean -afy

# ---- application source ----------------------------------------------------
# Respects .dockerignore at the repo root: excludes users/, var/, *.log,
# credentials-shaped files, the desktop Connector source, institutional
# deployment config (GT nginx / AWS CloudFormation), paper/proposal/
# presentation/advertising material, and everything in the LIVIST submodule
# except its frontend build source and LICENSE (the frontend's *build
# output* comes from the livist-builder stage below, not from here).
COPY . /opt/cryostack

# ---- build the static site at image-construction time (never at first
# container start), via CryoStack's own dependency-aware builder
# (deployment/cryostack_build.py + deployment/applications.yaml as the
# single source of truth for build order). -----------------------------
#
# This previously failed for "frozen-legacies": importing that package's
# __init__.py unconditionally imported its (unmounted, unused-by-the-
# running-app) Flask Blueprint in app.py, and `flask` is not a dependency
# in tools/icesee1_environment.yml. Fixed upstream in
# icesee_jupyter_book/applications/frozen_legacies/__init__.py (now
# degrades to frozen_legacies_bp = None when Flask is absent, instead of
# failing the whole package import) rather than adding an unneeded Flask
# dependency here or bypassing the real builder -- tested both standalone
# (python -S, i.e. no site-packages) and via this build. Flask remains
# absent from tools/icesee1_environment.yml; it was never required by the
# active application architecture.
RUN . /opt/conda/etc/profile.d/conda.sh \
    && conda activate cryostack \
    && python deployment/cryostack_build.py build frozen-legacies \
    && python deployment/cryostack_build.py build cryostack-book \
    && python deployment/cryostack_build.py build application-docs

# ---- LIVIST: place the build output from the livist-builder stage exactly
# where bin/icesee_app.py's livist_root() (external/living-ice-sheet-
# temperature/frontend/dist) expects it. Source only, from the builder
# stage's build output -- no LIVIST source is duplicated into CryoStack's
# own tree, and its LICENSE (already present via the COPY above) stays
# alongside it for attribution. -----------------------------------------
COPY --from=livist-builder /build/dist /opt/cryostack/external/living-ice-sheet-temperature/frontend/dist

# Runtime state (auth DB, workspace history) is never baked in -- created
# fresh here as an empty, writable mount point; production deployments
# should bind-mount or volume this path so state survives container
# recreation.
RUN mkdir -p /opt/cryostack/var

RUN chmod +x /opt/cryostack/containers/cryostack/entrypoint.sh

EXPOSE 8080

# bin/icesee_app.py binds CRYOSTACK_HOST if set, else 127.0.0.1 (bare-metal
# production default, where nginx reverse-proxies to it on the same host --
# unchanged). This image sets CRYOSTACK_HOST=0.0.0.0 above so ordinary
# Docker port publishing (`docker run -p 8080:8080 ...`, no --network host
# required) reaches it, matching how a container's published port actually
# routes (arrives on the container's eth0, not its loopback).
ENTRYPOINT ["/opt/cryostack/containers/cryostack/entrypoint.sh"]
