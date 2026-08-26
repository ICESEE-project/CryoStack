# =============================================================================
#
# CryoStack
# Unified Platform for Scientific Computing
#
# Module      : Frontend
# Component   : Shared Theme
# File        : theme.py
#
# Description :
#     Defines shared CryoStack frontend styling used across scientific
#     applications and execution interfaces.
#
# Author(s)   :
#     Brian Kyanjo
#
# Created     : 2026-08-25
#
# Copyright (c) 2026 ICESEE Project
# SPDX-License-Identifier: BSD-3-Clause
#
# =============================================================================

"""
Shared CryoStack frontend styling.

This module contains presentation only. Backend and execution behavior
must not be introduced here.
"""


CRYOSTACK_FRONTEND_CSS = r"""
<style>

:root {
  --cryostack-blue: #1264d8;
  --cryostack-blue-soft: #edf5ff;

  --cryostack-text: #172033;
  --cryostack-muted: #66758d;

  --cryostack-border: #dfe6ef;
  --cryostack-border-soft: #edf1f6;

  --cryostack-panel: #ffffff;
  --cryostack-background: #f7f9fc;

  --cryostack-success: #20a45b;
  --cryostack-warning: #d99516;
  --cryostack-danger: #d64242;

  --cryostack-radius: 10px;
}


/* ---------------------------------------------------------
   Global application area
   --------------------------------------------------------- */

.cryostack-ui {
  color: var(--cryostack-text);
  width: 100%;
}

.cryostack-ui * {
  box-sizing: border-box;
}


/* ---------------------------------------------------------
   Section heading
   --------------------------------------------------------- */

.cryostack-section-heading {
  margin-bottom: 12px;
}

.cryostack-section-heading h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--cryostack-text);
}

.cryostack-section-heading p {
  margin: 4px 0 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--cryostack-muted);
}


/* ---------------------------------------------------------
   Cards
   --------------------------------------------------------- */

.cryostack-card {
  background: var(--cryostack-panel);
  border: 1px solid var(--cryostack-border);
  border-radius: var(--cryostack-radius);
  overflow: hidden;
}

.cryostack-card-header {
  padding: 12px 14px;
  border-bottom: 1px solid var(--cryostack-border-soft);
  font-size: 13px;
  font-weight: 700;
  color: var(--cryostack-text);
}

.cryostack-card-body {
  padding: 14px;
}


/* ---------------------------------------------------------
   Detail rows
   --------------------------------------------------------- */

.cryostack-detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;

  padding: 9px 0;
  border-bottom: 1px solid var(--cryostack-border-soft);
}

.cryostack-detail-row:last-child {
  border-bottom: 0;
}

.cryostack-detail-label {
  color: var(--cryostack-muted);
  font-size: 12px;
}

.cryostack-detail-value {
  color: var(--cryostack-text);
  font-size: 12px;
  font-weight: 600;
  text-align: right;
}


/* ---------------------------------------------------------
   Status indicators
   --------------------------------------------------------- */

.cryostack-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;

  padding: 4px 9px;

  border-radius: 999px;

  font-size: 11px;
  font-weight: 700;
}

.cryostack-status::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.cryostack-status-idle {
  background: #f1f4f8;
  color: #64748b;
}

.cryostack-status-idle::before {
  background: #a8b4c4;
}

.cryostack-status-running {
  background: #edf5ff;
  color: #1264d8;
}

.cryostack-status-running::before {
  background: #1264d8;
}

.cryostack-status-ready,
.cryostack-status-success {
  background: #edf9f1;
  color: #16834a;
}

.cryostack-status-ready::before,
.cryostack-status-success::before {
  background: #20a45b;
}

.cryostack-status-warning {
  background: #fff7e7;
  color: #a66800;
}

.cryostack-status-warning::before {
  background: #d99516;
}

.cryostack-status-error,
.cryostack-status-failed {
  background: #fff0f0;
  color: #bf3030;
}

.cryostack-status-error::before,
.cryostack-status-failed::before {
  background: #d64242;
}


/* ---------------------------------------------------------
   Environment state
   --------------------------------------------------------- */

.cryostack-environment-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.cryostack-environment-item {
  padding: 10px 12px;

  border: 1px solid var(--cryostack-border-soft);
  border-radius: 8px;

  background: #fafbfd;
}

.cryostack-environment-item-label {
  color: var(--cryostack-muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.cryostack-environment-item-value {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 700;
}


/* ---------------------------------------------------------
   Runtime toolbar
   --------------------------------------------------------- */

.cryostack-runtime-toolbar {
  padding-top: 10px;
  border-top: 1px solid var(--cryostack-border-soft);
}


/* ---------------------------------------------------------
   Advanced details
   --------------------------------------------------------- */

.cryostack-advanced-note {
  margin-top: 8px;
  padding: 8px 10px;

  background: #fafbfd;
  border: 1px solid var(--cryostack-border-soft);
  border-radius: 7px;

  color: var(--cryostack-muted);
  font-size: 11px;
}


/* ---------------------------------------------------------
   Responsive
   --------------------------------------------------------- */

@media (max-width: 900px) {

  .cryostack-environment-grid {
    grid-template-columns: 1fr;
  }

}

</style>
"""