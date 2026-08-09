(() => {
  "use strict";

  const ACCOUNT_ENDPOINT = "/api/v1/me";
  const LOGIN_ENDPOINT = "/auth/login";

  let accountState = {
    authenticated: false,
    user: null,
  };

  /*
   * Find the right-hand side of the PyData Sphinx Theme header.
   * The fallback selectors make this resilient to minor theme changes.
   */
    function findHeaderTarget() {
    return (
      document.querySelector(
        ".cryostack-application-nav-actions"
      ) ||
      document.querySelector(".navbar-header-items__end") ||
      document.querySelector(".header-article-items__end") ||
      document.querySelector(
        ".bd-header__inner .navbar-header-items"
      ) ||
      document.querySelector(".bd-header__inner")
    );
  }

  function currentReturnPath() {
    return (
      window.location.pathname +
      window.location.search +
      window.location.hash
    );
  }

  function loginUrl(returnTo = currentReturnPath()) {
    return (
      `${LOGIN_ENDPOINT}?return_to=` +
      encodeURIComponent(returnTo)
    );
  }

  function getDisplayName(user) {
    return (
      user?.display_name ||
      user?.name ||
      user?.username ||
      user?.email ||
      "Account"
    );
  }

  function createAccountControl() {
    const existing = document.getElementById(
      "cryostack-global-account"
    );

    if (existing) {
      return existing;
    }

    const target = findHeaderTarget();

    if (!target) {
      return null;
    }

    const root = document.createElement("div");

    root.id = "cryostack-global-account";
    root.className = "cryostack-global-account loading";
    root.setAttribute("aria-live", "polite");

    root.innerHTML = `
      <button
        type="button"
        class="cryostack-global-account-button"
        aria-label="CryoStack account"
        aria-haspopup="true"
        aria-expanded="false"
      >
        <span
          class="cryostack-global-account-icon"
          aria-hidden="true"
        >
          👤
        </span>

        <span class="cryostack-global-account-label">
          Account
        </span>

        <span
          class="cryostack-global-account-chevron"
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      <div
        class="cryostack-global-account-menu"
        hidden
      ></div>
    `;

    target.appendChild(root);

    return root;
  }

    function renderGuest(root) {
    const button = root.querySelector(
      ".cryostack-global-account-button"
    );

    const label = root.querySelector(
      ".cryostack-global-account-label"
    );

    const menu = root.querySelector(
      ".cryostack-global-account-menu"
    );

    root.className = "cryostack-global-account guest";

    label.textContent = "Account";

    button.title = "Open CryoStack account options";
    button.setAttribute("aria-expanded", "false");
    button.setAttribute(
      "aria-label",
      "Open CryoStack account options"
    );

    menu.innerHTML = `
      <div class="cryostack-guest-account-header">
        <strong>Welcome to CryoStack</strong>

        <span>
          Sign in to launch applications.
        </span>
      </div>

      <div class="cryostack-guest-account-actions">
        <a
          class="cryostack-account-primary-action"
          href="/auth/login?return_to=${encodeURIComponent(
            currentReturnPath()
          )}"
        >
          Sign In
        </a>

        <a
          class="cryostack-account-secondary-action"
          href="/auth/register?return_to=${encodeURIComponent(
            currentReturnPath()
          )}"
        >
          Create Account
        </a>
      </div>

      <div class="cryostack-account-benefits">
        <span>Save application settings</span>
        <span>Resume previous jobs</span>
        <span>Manage HPC connections</span>
        <span>Sync across devices</span>
      </div>
    `;

    menu.hidden = true;

    button.onclick = (event) => {
      event.stopPropagation();

      const willOpen = menu.hidden;

      menu.hidden = !willOpen;
      button.setAttribute(
        "aria-expanded",
        String(willOpen)
      );
    };
  }

  function renderAuthenticated(root, user) {
    const displayName = getDisplayName(user);

    const button = root.querySelector(
      ".cryostack-global-account-button"
    );

    const label = root.querySelector(
      ".cryostack-global-account-label"
    );

    const menu = root.querySelector(
      ".cryostack-global-account-menu"
    );

    root.className =
      "cryostack-global-account authenticated";

    label.textContent = displayName;
    button.title = `Signed in as ${displayName}`;

    menu.innerHTML = `
      <div class="cryostack-account-menu-identity">
        <strong>${escapeHtml(displayName)}</strong>
        ${
          user?.email
            ? `<span>${escapeHtml(user.email)}</span>`
            : ""
        }
      </div>

      <a href="/account/">
        My Account
      </a>

      <a href="/configurations/">
        Saved Configurations
      </a>

      <a href="/experiments/">
        My Experiments
      </a>

      <button
        type="button"
        data-cryostack-logout
      >
        Sign Out
      </button>
    `;

    button.onclick = () => {
      menu.hidden = !menu.hidden;
    };

    menu
      .querySelector("[data-cryostack-logout]")
      ?.addEventListener("click", async () => {
        const response = await fetch("/auth/logout", {
          method: "POST",
          credentials: "same-origin",
        });

        if (response.ok) {
          window.location.reload();
        }
      });
  }

  function renderUnavailable(root) {
    const label = root.querySelector(
      ".cryostack-global-account-label"
    );

    root.className =
      "cryostack-global-account unavailable";

    label.textContent = "Account";
    root.title = "Account service unavailable";
  }

  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = String(value);
    return element.innerHTML;
  }

  async function loadAccountState() {
    const root = createAccountControl();

    if (!root) {
      window.setTimeout(loadAccountState, 150);
      return;
    }

    try {
      const response = await fetch(ACCOUNT_ENDPOINT, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(
          `Account endpoint returned HTTP ${response.status}`
        );
      }

      accountState = await response.json();

      if (
        accountState.authenticated === true &&
        accountState.user
      ) {
        renderAuthenticated(root, accountState.user);
      } else {
        renderGuest(root);
      }
    } catch (error) {
      console.error(
        "CryoStack account status could not be loaded:",
        error
      );

      renderUnavailable(root);
    }
  }

  /*
   * Application access gate.
   *
   * Any link carrying data-requires-auth="true" remains visible,
   * but anonymous users are redirected to login before entering.
   */
  function installApplicationGate() {
    document.addEventListener("click", (event) => {
      const link = event.target.closest(
        'a[data-requires-auth="true"]'
      );

      if (!link) {
        return;
      }

      if (accountState.authenticated === true) {
        return;
      }

      event.preventDefault();

      const destination = new URL(
        link.href,
        window.location.origin
      );

      const returnTo =
        destination.pathname +
        destination.search +
        destination.hash;

      window.location.href = loginUrl(returnTo);
    });
  }

  function closeMenuWhenClickingOutside() {
    document.addEventListener("click", (event) => {
      const root = document.getElementById(
        "cryostack-global-account"
      );

      if (!root || root.contains(event.target)) {
        return;
      }

      const menu = root.querySelector(
        ".cryostack-global-account-menu"
      );

      if (menu) {
        menu.hidden = true;
      }
    });
  }

  function initialize() {
    installApplicationGate();
    closeMenuWhenClickingOutside();
    loadAccountState();
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize,
      { once: true }
    );
  } else {
    initialize();
  }
})();