"""Shared CryoStack account control for Voilà applications."""

from __future__ import annotations

import ipywidgets as widgets


def cryostack_account_widget() -> widgets.HTML:
    """Return an account placeholder populated by browser JavaScript."""

    return widgets.HTML(
        value="""
<div class="cryostack-voila-account">
  <button
    type="button"
    class="cryostack-voila-account-button"
    aria-label="CryoStack account"
  >
    <span aria-hidden="true">👤</span>
    <span class="cryostack-voila-account-label">
      Account
    </span>
    <span aria-hidden="true">▾</span>
  </button>

  <div
    class="cryostack-voila-account-menu"
    hidden
  ></div>
</div>

<script>
(() => {
  const scripts = document.querySelectorAll(
    "script[data-cryostack-account-widget]"
  );

  if (scripts.length > 0) {
    return;
  }

  const script = document.createElement("script");
  script.src = "/_static/cryostack_account.js";
  script.dataset.cryostackAccountWidget = "true";
  document.head.appendChild(script);
})();
</script>
"""
    )