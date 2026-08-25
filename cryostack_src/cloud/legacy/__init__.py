# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Cloud
# Component   : Legacy Compatibility
# File        : __init__.py
#
# Description :
#     Contains transitional cloud modules retained during the CryoStack
#     strangler migration. New cloud development should use cloud drivers.
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
Legacy CryoStack cloud compatibility modules.

These modules remain available during the strangler migration so that
existing code paths continue to function while cloud behavior moves to
the driver architecture.
"""