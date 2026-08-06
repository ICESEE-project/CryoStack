"""Small HTML templates used by the CryoStack authentication pages."""

from __future__ import annotations

from html import escape


def auth_page(
    *,
    title: str,
    subtitle: str,
    form_action: str,
    return_to: str,
    fields: str,
    submit_label: str,
    alternate_text: str,
    alternate_href: str,
    alternate_label: str,
    error: str | None = None,
) -> str:
    safe_error = escape(error) if error else ""

    error_block = (
        f'<div class="auth-error" role="alert">{safe_error}</div>'
        if error
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >
  <title>{escape(title)} | CryoStack</title>

  <style>
    :root {{
      color-scheme: light;
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system,
        BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: 2rem;
      background:
        radial-gradient(
          circle at 12% 8%,
          rgba(125, 211, 252, 0.22),
          transparent 32%
        ),
        linear-gradient(135deg, #eff6ff, #f8fafc);
      color: #0f172a;
    }}

    .auth-shell {{
      width: min(100%, 430px);
    }}

    .auth-brand {{
      margin-bottom: 1.2rem;
      text-align: center;
    }}

    .auth-brand a {{
      color: #0f172a;
      font-size: 1.7rem;
      font-weight: 800;
      text-decoration: none;
    }}

    .auth-brand span {{
      color: #2563eb;
    }}

    .auth-card {{
      padding: 2rem;
      border: 1px solid rgba(148, 163, 184, 0.24);
      border-radius: 20px;
      background: rgba(255, 255, 255, 0.96);
      box-shadow: 0 22px 55px rgba(15, 23, 42, 0.11);
    }}

    h1 {{
      margin: 0 0 0.55rem;
      font-size: 1.65rem;
      letter-spacing: -0.035em;
    }}

    .subtitle {{
      margin: 0 0 1.5rem;
      color: #64748b;
      font-size: 0.92rem;
      line-height: 1.55;
    }}

    label {{
      display: grid;
      gap: 0.4rem;
      margin-bottom: 1rem;
      color: #334155;
      font-size: 0.83rem;
      font-weight: 700;
    }}

    input {{
      width: 100%;
      min-height: 43px;
      padding: 0.7rem 0.8rem;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      background: #ffffff;
      color: #0f172a;
      font: inherit;
      font-size: 0.9rem;
    }}

    input:focus {{
      outline: 3px solid rgba(37, 99, 235, 0.13);
      border-color: #2563eb;
    }}

    .submit {{
      width: 100%;
      min-height: 44px;
      margin-top: 0.3rem;
      border: 0;
      border-radius: 10px;
      background: #2563eb;
      color: #ffffff;
      font: inherit;
      font-size: 0.9rem;
      font-weight: 750;
      cursor: pointer;
    }}

    .submit:hover {{
      background: #1d4ed8;
    }}

    .auth-error {{
      margin-bottom: 1rem;
      padding: 0.75rem 0.85rem;
      border: 1px solid rgba(220, 38, 38, 0.2);
      border-radius: 9px;
      background: #fef2f2;
      color: #b91c1c;
      font-size: 0.82rem;
      line-height: 1.45;
    }}

    .alternate {{
      margin: 1.25rem 0 0;
      color: #64748b;
      font-size: 0.84rem;
      text-align: center;
    }}

    .alternate a {{
      color: #2563eb;
      font-weight: 700;
      text-decoration: none;
    }}

    .back {{
      display: block;
      margin-top: 1rem;
      color: #64748b;
      font-size: 0.8rem;
      text-align: center;
      text-decoration: none;
    }}
  </style>
</head>

<body>
  <main class="auth-shell">
    <div class="auth-brand">
      <a href="/index.html">Cryo<span>Stack</span></a>
    </div>

    <section class="auth-card">
      <h1>{escape(title)}</h1>
      <p class="subtitle">{escape(subtitle)}</p>

      {error_block}

      <form method="post" action="{escape(form_action)}">
        <input
          type="hidden"
          name="return_to"
          value="{escape(return_to)}"
        >

        {fields}

        <button class="submit" type="submit">
          {escape(submit_label)}
        </button>
      </form>

      <p class="alternate">
        {escape(alternate_text)}
        <a href="{escape(alternate_href)}">
          {escape(alternate_label)}
        </a>
      </p>
    </section>

    <a class="back" href="/index.html">
      ← Return to CryoStack
    </a>
  </main>
</body>
</html>
"""


def login_fields(email: str = "") -> str:
    return f"""
<label>
  Email
  <input
    type="email"
    name="email"
    value="{escape(email)}"
    autocomplete="email"
    required
  >
</label>

<label>
  Password
  <input
    type="password"
    name="password"
    autocomplete="current-password"
    required
  >
</label>
"""


def register_fields(
    *,
    display_name: str = "",
    email: str = "",
    institution: str = "",
) -> str:
    return f"""
<label>
  Name
  <input
    type="text"
    name="display_name"
    value="{escape(display_name)}"
    autocomplete="name"
    maxlength="120"
    required
  >
</label>

<label>
  Email
  <input
    type="email"
    name="email"
    value="{escape(email)}"
    autocomplete="email"
    maxlength="254"
    required
  >
</label>

<label>
  Institution
  <input
    type="text"
    name="institution"
    value="{escape(institution)}"
    autocomplete="organization"
    maxlength="160"
  >
</label>

<label>
  Password
  <input
    type="password"
    name="password"
    autocomplete="new-password"
    minlength="8"
    required
  >
</label>

<label>
  Confirm password
  <input
    type="password"
    name="confirm_password"
    autocomplete="new-password"
    minlength="8"
    required
  >
</label>
"""

def account_settings_page(
    *,
    user,
    message: str | None = None,
    error: str | None = None,
) -> str:
    safe_message = escape(message) if message else ""
    safe_error = escape(error) if error else ""

    message_block = (
        f"""
        <div class="account-message" role="status">
          {safe_message}
        </div>
        """
        if message
        else ""
    )

    error_block = (
        f"""
        <div class="account-error" role="alert">
          {safe_error}
        </div>
        """
        if error
        else ""
    )

    def selected(value: str | None, expected: str) -> str:
        return "selected" if value == expected else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">

  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >

  <title>Account Settings | CryoStack</title>

  <style>
    :root {{
      font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      min-height: 100vh;
      margin: 0;
      background: #f8fafc;
      color: #0f172a;
    }}

    .account-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.9rem 1.5rem;
      border-bottom: 1px solid #e2e8f0;
      background: #ffffff;
    }}

    .account-brand {{
      color: #0f172a;
      font-size: 1.2rem;
      font-weight: 800;
      text-decoration: none;
    }}

    .account-brand span {{
      color: #2563eb;
    }}

    .account-back {{
      color: #475569;
      font-size: 0.84rem;
      font-weight: 650;
      text-decoration: none;
    }}

    .account-shell {{
      width: min(100% - 2rem, 980px);
      margin: 2rem auto;
    }}

    .account-intro {{
      margin-bottom: 1.4rem;
    }}

    .account-intro h1 {{
      margin: 0 0 0.4rem;
      font-size: 1.75rem;
      letter-spacing: -0.035em;
    }}

    .account-intro p {{
      margin: 0;
      color: #64748b;
      line-height: 1.55;
    }}

    .account-layout {{
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 1.5rem;
    }}

    .account-sidebar,
    .account-card {{
      border: 1px solid #e2e8f0;
      border-radius: 16px;
      background: #ffffff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
    }}

    .account-sidebar {{
      align-self: start;
      padding: 0.65rem;
    }}

    .account-sidebar a {{
      display: block;
      padding: 0.7rem 0.8rem;
      border-radius: 9px;
      color: #475569;
      font-size: 0.85rem;
      font-weight: 650;
      text-decoration: none;
    }}

    .account-sidebar a.active {{
      background: #eff6ff;
      color: #1d4ed8;
    }}

    .account-card {{
      padding: 1.5rem;
    }}

    .account-section {{
      margin-bottom: 1.8rem;
    }}

    .account-section:last-child {{
      margin-bottom: 0;
    }}

    .account-section h2 {{
      margin: 0 0 0.35rem;
      font-size: 1.05rem;
    }}

    .account-section-intro {{
      margin: 0 0 1rem;
      color: #64748b;
      font-size: 0.84rem;
      line-height: 1.5;
    }}

    .account-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }}

    label {{
      display: grid;
      gap: 0.4rem;
      color: #334155;
      font-size: 0.8rem;
      font-weight: 700;
    }}

    label.full {{
      grid-column: 1 / -1;
    }}

    input,
    select {{
      width: 100%;
      min-height: 42px;
      padding: 0.65rem 0.75rem;
      border: 1px solid #cbd5e1;
      border-radius: 9px;
      background: #ffffff;
      color: #0f172a;
      font: inherit;
      font-size: 0.88rem;
    }}

    input[readonly] {{
      background: #f8fafc;
      color: #64748b;
    }}

    input:focus,
    select:focus {{
      outline: 3px solid rgba(37, 99, 235, 0.12);
      border-color: #2563eb;
    }}

    .account-actions {{
      display: flex;
      justify-content: flex-end;
      margin-top: 1.3rem;
    }}

    .account-save {{
      min-height: 40px;
      padding: 0 1rem;
      border: 0;
      border-radius: 9px;
      background: #2563eb;
      color: #ffffff;
      font: inherit;
      font-size: 0.84rem;
      font-weight: 750;
      cursor: pointer;
    }}

    .account-save:hover {{
      background: #1d4ed8;
    }}

    .account-message,
    .account-error {{
      margin-bottom: 1rem;
      padding: 0.75rem 0.85rem;
      border-radius: 9px;
      font-size: 0.82rem;
    }}

    .account-message {{
      border: 1px solid rgba(22, 163, 74, 0.2);
      background: #f0fdf4;
      color: #15803d;
    }}

    .account-error {{
      border: 1px solid rgba(220, 38, 38, 0.2);
      background: #fef2f2;
      color: #b91c1c;
    }}

    @media (max-width: 760px) {{
      .account-layout {{
        grid-template-columns: 1fr;
      }}

      .account-grid {{
        grid-template-columns: 1fr;
      }}

      label.full {{
        grid-column: auto;
      }}
    }}
  </style>
</head>

<body>
  <header class="account-header">
    <a class="account-brand" href="/index.html">
      Cryo<span>Stack</span>
    </a>

    <a class="account-back" href="/index.html">
      Return to CryoStack
    </a>
  </header>

  <main class="account-shell">
    <div class="account-intro">
      <h1>Account Settings</h1>

      <p>
        Manage your CryoStack profile and application preferences.
      </p>
    </div>

    <div class="account-layout">
      <nav class="account-sidebar">
        <a class="active" href="/account/">
          Profile and Preferences
        </a>

        <a href="/configurations/">
          Saved Configurations
        </a>

        <a href="/experiments/">
          My Experiments
        </a>
      </nav>

      <section class="account-card">
        {message_block}
        {error_block}

        <form method="post" action="/account/">
          <div class="account-section">
            <h2>Profile</h2>

            <p class="account-section-intro">
              Information associated with your CryoStack workspace.
            </p>

            <div class="account-grid">
              <label>
                Display name

                <input
                  type="text"
                  name="display_name"
                  maxlength="120"
                  value="{escape(user.display_name)}"
                  required
                >
              </label>

              <label>
                Email

                <input
                  type="email"
                  value="{escape(user.email)}"
                  readonly
                >
              </label>

              <label>
                Institution

                <input
                  type="text"
                  name="institution"
                  maxlength="160"
                  value="{escape(user.institution or '')}"
                >
              </label>

              <label>
                Research role

                <select name="research_role">
                  <option value="">Select a role</option>

                  <option
                    value="student"
                    {selected(user.research_role, "student")}
                  >
                    Student
                  </option>

                  <option
                    value="researcher"
                    {selected(user.research_role, "researcher")}
                  >
                    Researcher
                  </option>

                  <option
                    value="faculty"
                    {selected(user.research_role, "faculty")}
                  >
                    Faculty
                  </option>

                  <option
                    value="engineer"
                    {selected(user.research_role, "engineer")}
                  >
                    Research Engineer
                  </option>

                  <option
                    value="educator"
                    {selected(user.research_role, "educator")}
                  >
                    Educator
                  </option>

                  <option
                    value="other"
                    {selected(user.research_role, "other")}
                  >
                    Other
                  </option>
                </select>
              </label>

              <label class="full">
                Country

                <input
                  type="text"
                  name="country"
                  maxlength="100"
                  value="{escape(user.country or '')}"
                >
              </label>
            </div>
          </div>

          <div class="account-section">
            <h2>Application Preferences</h2>

            <p class="account-section-intro">
              Select defaults used when opening CryoStack applications.
            </p>

            <div class="account-grid">
              <label>
                Default application

                <select name="default_application">
                  <option value="">No default</option>

                  <option
                    value="cryolauncher"
                    {selected(
                        user.default_application,
                        "cryolauncher"
                    )}
                  >
                    CryoLauncher
                  </option>

                  <option
                    value="icesee"
                    {selected(
                        user.default_application,
                        "icesee"
                    )}
                  >
                    ICESEE
                  </option>

                  <option
                    value="livist"
                    {selected(
                        user.default_application,
                        "livist"
                    )}
                  >
                    LIVIST
                  </option>
                </select>
              </label>

              <label>
                Default execution mode

                <select name="default_execution_mode">
                  <option value="">Application default</option>

                  <option
                    value="local"
                    {selected(
                        user.default_execution_mode,
                        "local"
                    )}
                  >
                    Local
                  </option>

                  <option
                    value="remote"
                    {selected(
                        user.default_execution_mode,
                        "remote"
                    )}
                  >
                    Remote or HPC
                  </option>

                  <option
                    value="cloud"
                    {selected(
                        user.default_execution_mode,
                        "cloud"
                    )}
                  >
                    Cloud
                  </option>
                </select>
              </label>
            </div>
          </div>

          <div class="account-actions">
            <button class="account-save" type="submit">
              Save Changes
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</body>
</html>
"""