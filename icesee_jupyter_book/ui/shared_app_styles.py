"""Shared visual styles for CryoStack Voilà applications."""

from __future__ import annotations

import ipywidgets as W


_SHARED_APPLICATION_CSS = """
<style>

/* =========================================================
   CryoStack application page
   ========================================================= */

.cryostack-application-page,
.icesee-page {
    width: 100%;

    font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Arial,
        sans-serif;
}


/* =========================================================
   Page title and introduction
   ========================================================= */

.cryostack-application-title,
.icesee-title {
    margin: 4px 0 6px;

    color: #1f2937;

    font-size: 20px;
    font-weight: 700;
    line-height: 1.25;
}

.cryostack-application-subtitle,
.icesee-subtitle {
    max-width: 900px;
    margin-bottom: 10px;

    color: rgba(15, 23, 42, 0.68);

    font-size: 14px;
    line-height: 1.5;
}


/* =========================================================
   Section headings
   ========================================================= */

.cryostack-section-heading,
.icesee-h {
    margin: 2px 0 14px;

    color: #1f2937;

    font-size: 18px;
    font-weight: 750;
    line-height: 1.3;
}


/* =========================================================
   Cards
   ========================================================= */

.cryostack-application-card,
.icesee-card {
    padding: 18px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 16px;

    background: #ffffff;

    box-shadow:
        0 8px 24px rgba(15, 23, 42, 0.04);
}


/* =========================================================
   Form labels and supporting text
   ========================================================= */

.cryostack-form-label,
.icesee-lbl {
    padding-top: 8px;

    color: rgba(15, 23, 42, 0.78);

    font-weight: 600;
}

.cryostack-subtle,
.icesee-subtle {
    margin-bottom: 6px;

    color: rgba(15, 23, 42, 0.56);

    font-size: 12px;
    line-height: 1.45;
}


/* =========================================================
   Status chips
   ========================================================= */

.cryostack-status,
.icesee-status {
    display: inline-block;

    padding: 8px 14px;

    border: 1px solid rgba(15, 23, 42, 0.10);
    border-radius: 999px;

    font-weight: 700;
    line-height: 1;
}

.cryostack-status-idle,
.icesee-idle {
    background: rgba(15, 23, 42, 0.04);
    color: #475569;
}

.cryostack-status-running,
.icesee-running {
    background: rgba(37, 99, 235, 0.12);
    color: #1d4ed8;
}

.cryostack-status-done,
.icesee-done {
    background: rgba(22, 163, 74, 0.14);
    color: #15803d;
}

.cryostack-status-failed,
.icesee-fail {
    background: rgba(220, 38, 38, 0.14);
    color: #b91c1c;
}


/* =========================================================
   Configuration summaries
   ========================================================= */

.cryostack-summary,
.icesee-summary {
    padding: 14px 16px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 14px;

    background:
        linear-gradient(
            to bottom,
            rgba(15, 23, 42, 0.015),
            rgba(15, 23, 42, 0.03)
        );

    color: rgba(15, 23, 42, 0.78);

    line-height: 1.75;
}

.cryostack-summary-key,
.icesee-summary-k {
    color: rgba(15, 23, 42, 0.90);

    font-weight: 700;
}


/* =========================================================
   Main two-column application layout
   ========================================================= */

.cryostack-application-grid,
.icesee-grid {
    display: flex;
    width: 100%;
    align-items: stretch;
    gap: 24px;
}

.cryostack-application-left,
.icesee-left {
    flex: 0 0 46%;
    min-width: 0;
}

.cryostack-application-right,
.icesee-right {
    flex: 0 0 54%;
    min-width: 0;
}


/* =========================================================
   Action rows
   ========================================================= */

.cryostack-actions,
.icesee-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}


/* =========================================================
   Code and command previews
   ========================================================= */

.cryostack-application-page pre,
.icesee-page pre,
pre.cryostack-code-block {
    overflow-x: auto;

    padding: 12px;

    border: 1px solid rgba(15, 23, 42, 0.08);
    border-radius: 10px;

    background: #f6f8fa;

    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
}


/* =========================================================
   Shared account placement inside application menus
   ========================================================= */

.cryostack-application-nav-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: flex-end;

    margin-left: auto;
}

.cryostack-application-nav-actions
.cryostack-global-account {
    width: auto !important;
    margin: 0 !important;
}

.cryostack-application-nav-actions
.cryostack-global-account-menu {
    z-index: 5000 !important;
}


/* =========================================================
   Standard widget spacing
   ========================================================= */

.cryostack-application-card
.widget-box,
.icesee-card
.widget-box {
    max-width: 100%;
}


/* =========================================================
   Responsive layout
   ========================================================= */

@media (max-width: 1050px) {
    .cryostack-application-grid,
    .icesee-grid {
        flex-direction: column;
    }

    .cryostack-application-left,
    .cryostack-application-right,
    .icesee-left,
    .icesee-right {
        flex: 1 1 auto;
        width: 100%;
    }
}

@media (max-width: 700px) {
    .cryostack-application-card,
    .icesee-card {
        padding: 14px;
        border-radius: 13px;
    }

    .cryostack-application-title,
    .icesee-title {
        font-size: 18px;
    }

    .cryostack-section-heading,
    .icesee-h {
        font-size: 16px;
    }
}


/* =========================================================
   Dark theme
   ========================================================= */

html[data-theme="dark"]
.cryostack-application-page,
html[data-theme="dark"]
.icesee-page {
    color: #e2e8f0;
}

html[data-theme="dark"]
.cryostack-application-title,
html[data-theme="dark"]
.icesee-title,
html[data-theme="dark"]
.cryostack-section-heading,
html[data-theme="dark"]
.icesee-h {
    color: #f8fafc;
}

html[data-theme="dark"]
.cryostack-application-subtitle,
html[data-theme="dark"]
.icesee-subtitle,
html[data-theme="dark"]
.cryostack-subtle,
html[data-theme="dark"]
.icesee-subtle {
    color: #94a3b8;
}

html[data-theme="dark"]
.cryostack-application-card,
html[data-theme="dark"]
.icesee-card {
    border-color: rgba(226, 232, 240, 0.12);
    background: #111827;

    box-shadow:
        0 8px 24px rgba(0, 0, 0, 0.22);
}

html[data-theme="dark"]
.cryostack-summary,
html[data-theme="dark"]
.icesee-summary {
    border-color: rgba(226, 232, 240, 0.12);
    background: rgba(30, 41, 59, 0.72);
    color: #cbd5e1;
}

html[data-theme="dark"]
.cryostack-summary-key,
html[data-theme="dark"]
.icesee-summary-k {
    color: #f1f5f9;
}

html[data-theme="dark"]
.cryostack-application-page pre,
html[data-theme="dark"]
.icesee-page pre,
html[data-theme="dark"]
pre.cryostack-code-block {
    border-color: rgba(226, 232, 240, 0.12);
    background: #0f172a;
    color: #e2e8f0;
}

</style>
"""


def shared_application_styles() -> W.HTML:
    """Return the shared CSS used by CryoStack Voilà applications."""

    widget = W.HTML(value=_SHARED_APPLICATION_CSS)
    widget.layout = W.Layout(width="100%")

    return widget