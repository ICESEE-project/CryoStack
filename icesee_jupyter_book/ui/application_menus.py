"""Shared application navigation menus for CryoStack Voilà applications."""

from __future__ import annotations

import ipywidgets as W
from IPython.display import Javascript, display

from icesee_jupyter_book.ui.shared_application_header import cryostack_mark_img


_SHARED_MENU_CSS = """
<style>
.cryostack-app-header {
    display: flex;
    width: 100%;
    align-items: center;
    justify-content: space-between;
    gap: 20px;

    padding: 8px 0 12px;
    margin: 0 0 20px;

    border-bottom: 1px solid rgba(15, 23, 42, 0.10);

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Helvetica,
        Arial,
        sans-serif;
}

.cryostack-app-header-left {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 10px;
}

/* Canonical CryoStack mark + application name -- kept together on one line. */
.cryostack-app-identity {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    gap: 10px;
}

.cryostack-app-mark {
    flex: 0 0 auto;
    width: 30px;
    height: 30px;
    object-fit: contain;
    border-radius: 7px;
}

.cryostack-app-mark--fallback {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    line-height: 1;
    color: #1565c0;
}

.cryostack-app-home {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;

    min-height: 36px;
    padding: 8px 15px;

    border-radius: 9px;
    background: #1565c0;
    color: #ffffff !important;

    font-size: 14px;
    font-weight: 750;
    line-height: 1;
    text-decoration: none !important;

    transition:
        background-color 160ms ease,
        transform 160ms ease;
}

.cryostack-app-home:hover {
    background: #0f56aa;
    transform: translateY(-1px);
}

.cryostack-app-nav {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
}

.cryostack-app-nav a {
    display: inline-flex;
    align-items: center;

    min-height: 36px;
    padding: 8px 11px;

    border: 1px solid transparent;
    border-radius: 9px;

    color: #475569;
    font-size: 14px;
    font-weight: 650;
    line-height: 1;
    text-decoration: none !important;

    transition:
        background-color 160ms ease,
        color 160ms ease;
}

.cryostack-app-nav a:hover {
    background: #f1f5f9;
    color: #1565c0;
}

.cryostack-app-nav a.active {
    background: #eef5ff;
    color: #1565c0;
}

/*
 * cryostack_account.js injects the shared account component
 * into this container.
 */
.cryostack-application-nav-actions {
    display: flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: flex-end;

    min-width: 110px;
    margin-left: auto;
    padding-left: 18px;
}

.cryostack-application-nav-actions
.cryostack-global-account {
    width: auto !important;
    margin: 0 !important;
}

/*
 * Ensure the account dropdown opens above notebook widgets.
 */
.cryostack-application-nav-actions
.cryostack-global-account-menu {
    z-index: 5000 !important;
}

/* Dark-theme support */
html[data-theme="dark"] .cryostack-app-header {
    border-bottom-color: rgba(226, 232, 240, 0.15);
}

html[data-theme="dark"] .cryostack-app-nav a {
    color: #cbd5e1;
}

html[data-theme="dark"] .cryostack-app-nav a:hover {
    background: rgba(51, 65, 85, 0.8);
    color: #93c5fd;
}

/* Responsive application header */
@media (max-width: 820px) {
    .cryostack-app-header {
        flex-wrap: wrap;
        align-items: flex-start;
        gap: 10px;
    }

    .cryostack-app-header-left {
        align-items: flex-start;
        flex-direction: column;
    }

    .cryostack-app-nav {
        gap: 2px;
    }

    .cryostack-application-nav-actions {
        min-width: auto;
        padding-left: 6px;
        margin-left: 0;
    }
}

@media (max-width: 430px) {
    .cryostack-app-header {
        padding: 6px 0 10px;
        margin-bottom: 14px;
    }

    .cryostack-app-home {
        padding: 7px 12px;
        font-size: 13px;
    }

    .cryostack-app-nav a {
        min-height: 34px;
        padding: 6px 9px;
        font-size: 13px;
    }
}
</style>
"""


def _build_application_menu(
    *,
    application_name: str,
    application_href: str,
    documentation_root: str,
) -> W.HTML:
    """Build a shared CryoStack application navigation header."""

    documentation_root = documentation_root.rstrip("/")

    cryostack_mark = cryostack_mark_img()

    widget = W.HTML(
        value=f"""
{_SHARED_MENU_CSS}

<div class="cryostack-app-header">

    <div class="cryostack-app-header-left">

        <div class="cryostack-app-identity">
            {cryostack_mark}
            <a
                class="cryostack-app-home"
                href="{application_href}"
            >
                {application_name}
            </a>
        </div>

        <nav
            class="cryostack-app-nav"
            aria-label="{application_name} documentation"
        >
            <a href="{documentation_root}/getting_started.html">
                Getting Started
            </a>

            <a href="{documentation_root}/user_manual.html">
                User Manual
            </a>

            <a href="{documentation_root}/resources.html">
                Resources
            </a>
        </nav>

    </div>

    <div
        class="cryostack-application-nav-actions"
        aria-label="CryoStack account"
    ></div>

</div>
"""
    )

    widget.layout = W.Layout(width="100%")
    return widget


def build_icesheets_app_menu() -> W.HTML:
    """Return the CryoLauncher application navigation menu."""

    return _build_application_menu(
        application_name="CryoLauncher",
        application_href="/icesheets/",
        documentation_root="/applications/icesheets",
    )


def build_icesee_app_menu() -> W.HTML:
    """Return the ICESEE application navigation menu."""

    return _build_application_menu(
        application_name="ICESEE",
        application_href="/icesee-gui/",
        documentation_root="/applications/icesee",
    )


def load_cryostack_account_assets() -> None:
    """Load the shared account CSS and JavaScript into a Voilà page.

    The operation is idempotent. Calling it more than once does not add
    duplicate assets.
    """

    display(
        Javascript(
            """
(() => {
    "use strict";

    const cssId = "cryostack-shared-account-css";
    const scriptId = "cryostack-shared-account-script";

    if (!document.getElementById(cssId)) {
        const css = document.createElement("link");

        css.id = cssId;
        css.rel = "stylesheet";
        css.href = "/_static/icesee.css";

        document.head.appendChild(css);
    }

    /*
     * Avoid loading the account script more than once.
     */
    if (document.getElementById(scriptId)) {
        return;
    }

    /*
     * The script retries until it finds
     * .cryostack-application-nav-actions, so it is safe to load
     * before or immediately after the application menu renders.
     */
    const script = document.createElement("script");

    script.id = scriptId;
    script.src = "/_static/cryostack_account.js";
    script.async = true;

    script.onerror = () => {
        console.error(
            "CryoStack account assets could not be loaded."
        );
    };

    document.head.appendChild(script);
})();
"""
        )
    )