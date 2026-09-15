"""Shared "Remote Connection" panel -- reusable by IceSheets, ICESEE and future
Icepack UIs.

Reorganised around the user's workflow instead of the transport internals:

    Compute resource      Resource / Host / Port
    Your HPC identity     HPC username / Remote working directory
    Access                Connection method / Authentication method
    Status                * Not checked / Verified / Mismatch / Failed
    [ Check SSH Access ] [ Open Connector... ] [ Disconnect ]
    (pairing code / connected line -- shown only while relevant, one line,
     the SAME Remote visual language as everything above it, never a
     second boxed "CRYOSTACK CONNECTOR" card)
    > Advanced             remote job tag + connector diagnostics (session
                            id / ws path / relay state), only when present

This is a presentation helper. It takes the gateway's existing widget
instances and arranges them; it never changes transport behaviour, the B3
AccessState machine, identity verification, or the Run gate. The single
Connector pairing/session this panel drives is also the ONE binding Cloud
workflows read (``connector_relay_client.current_binding()``) -- see
``cryostack_src.frontend.cryolauncher.cloud_environment.
wire_institutional_connection_widgets``. There is exactly one Connector
implementation/pairing/session; Cloud never creates its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W

from icesee_jupyter_book.ui.shared_auth_ux import (
    auth_method_options,
    manual_registration_steps,
    portal_link,
    requires_manual_registration,
    supports_password_bootstrap,
)

# status chip: (css-modifier, dot, label)
_STATUS = {
    "unchecked": ("is-unchecked", "●", "Not checked"),
    "checking": ("is-checking", "●", "Checking…"),
    "verified": ("is-verified", "●", "Verified"),
    "mismatch": ("is-mismatch", "●", "Mismatch"),
    "failed": ("is-failed", "●", "Failed"),
    "key_unregistered": ("is-key-unregistered", "●", "SSH key not registered"),
    "registering": ("is-checking", "●", "Registering SSH key…"),
    "verifying": ("is-checking", "●", "SSH key registered — verifying access…"),
}

#: password-bootstrap outcome -> (status-chip kind, registration-box message).
#: An empty message keeps whatever guidance is already shown.
_BOOTSTRAP_UI = {
    "registering":      ("registering", ""),
    "verifying":        ("verifying", ""),
    "verified":         ("verified", ""),
    "password_failed":  ("key_unregistered",
                         "Password authentication failed. Check the password you "
                         "entered. Some resources also require an active VPN or a "
                         "second factor (2FA/Duo) that a one-time password "
                         "bootstrap cannot satisfy."),
    "connector_failed": ("failed",
                         "The CryoStack Connector could not run the bootstrap "
                         "command. Make sure the Connector is still connected, "
                         "then try again."),
    "not_permitted":    ("key_unregistered",
                         "This resource does not permit one-time password "
                         "bootstrap. Register the CryoStack public key with the "
                         "resource, then Check SSH Access."),
    "timed_out":        ("failed",
                         "Timed out while registering the SSH key. The resource "
                         "did not respond in time — check VPN / network and try "
                         "again."),
}

# B3 AccessState value -> status-chip kind (AccessState is a str enum, compared
# by value so this module needs no import from cryostack_src).
_ACCESS_STATE_KIND = {
    "ssh_verified": "verified",
    "ready": "verified",
    "identity_mismatch": "mismatch",
    "access_failed": "failed",
}


def access_state_to_status_kind(state) -> str:
    """Map a B3 AccessState (or its value) to a Status-chip kind."""
    return _ACCESS_STATE_KIND.get(getattr(state, "value", state), "unchecked")


def classify_bootstrap_result(result) -> str:
    """Map a password-bootstrap result (connector reason codes, or a relay
    error envelope) to a :meth:`RemoteConnectionPanel.set_bootstrap_state`
    state. ``"installed"`` means the public key is on the resource and the
    caller should now run the real B3 identity check.
    """
    if not isinstance(result, dict):
        return "connector_failed"
    if result.get("ok") or result.get("reason") == "ok" or result.get("key_installed"):
        return "installed"

    reason = (result.get("reason") or "").strip()
    mapped = {
        "password_auth_failed": "password_failed",
        "paramiko_missing": "not_permitted",
        "connect_failed": "timed_out",
        "install_failed": "connector_failed",
        "verify_failed": "connector_failed",
    }.get(reason)
    if mapped:
        return mapped

    blob = f"{result.get('detail', '')} {result.get('error', '')}".lower()
    if "tim" in blob and "out" in blob:
        return "timed_out"
    return "connector_failed"


def _status_html(kind: str) -> str:
    mod, dot, label = _STATUS.get(kind, _STATUS["unchecked"])
    return (
        f"<span class='cryostack-conn-status {mod}'>"
        f"<span class='cryostack-conn-status__dot'>{dot}</span>"
        f"<span class='cryostack-conn-status__label'>{label}</span>"
        "</span>"
    )


def _group_title(text: str) -> W.HTML:
    return W.HTML(f"<div class='cryostack-group-title'>{text}</div>")


def connector_pairing_status_html(
    *, session_id: str | None, pairing_code: str | None, online: bool,
) -> str:
    """One compact line -- the ONLY thing shown while pairing is in
    progress (never a second boxed "CRYOSTACK CONNECTOR" card). Empty
    when there is nothing to say yet (no session started)."""
    if online:
        return "<div class='cryostack-help'>&#10003; CryoStack Connector connected.</div>"
    if not session_id:
        return ""
    return (
        "<div class='cryostack-help'>Pairing code: "
        f"<code style='font-size:13px;background:#eef1f4;padding:1px 7px;"
        f"border-radius:6px;'>{pairing_code or '—'}</code> "
        "&mdash; enter it in the CryoStack Connector on your workstation "
        "(&ldquo;Pair with CryoStack&hellip;&rdquo;).</div>"
    )


def connector_pairing_link_html(*, session_id: str | None, app: str) -> str:
    """The one actual navigation control (an ipywidgets Button cannot open
    a new browser tab itself) -- reuses the existing portal-link style
    already used for "Register your key", never a second large duplicate
    "Open CryoStack Connector Setup" button next to the real one."""
    if not session_id:
        return ""
    return (
        "<a class='cryostack-portal-link' href="
        f"'https://cryostack.eas.gatech.edu/connect/?session={session_id}"
        f"&app={app}' target='_blank' rel='noopener'>Open the Connector "
        "pairing page</a>"
    )


def connector_diagnostics_html(
    *, session_id: str | None, ws_url: str | None, relay_state: str | None,
) -> str:
    """Session id / ws path / relay state -- genuinely technical, never
    shown in the compact Remote view. Lives only inside the existing
    Advanced accordion."""
    if not session_id:
        return ""
    return (
        "<div class='cryostack-diag'>"
        f"<span class='cryostack-diag__k'>Connector session:</span> {session_id}<br>"
        f"<span class='cryostack-diag__k'>ws path:</span> {ws_url or '—'}<br>"
        f"<span class='cryostack-diag__k'>relay state:</span> {relay_state or 'unknown'}"
        "</div>"
    )


def _field(label: str, widget: W.Widget, help_text: str = "") -> W.VBox:
    widget.layout = W.Layout(width="100%")
    children = [W.HTML(f"<div class='cryostack-field-label'>{label}</div>"), widget]
    if help_text:
        children.append(W.HTML(f"<div class='cryostack-help'>{help_text}</div>"))
    box = W.VBox(children, layout=W.Layout(width="100%", gap="2px"))
    box.add_class("cryostack-field")
    return box


def _row(*fields: W.Widget) -> W.HBox:
    row = W.HBox(list(fields), layout=W.Layout(width="100%", gap="14px"))
    row.add_class("cryostack-field-row")
    return row


@dataclass
class RemoteConnectionPanel:
    container: W.VBox
    status_chip: W.HTML
    registration_box: W.VBox
    auth_method: W.Widget
    _state: dict = field(default_factory=dict)
    _profile: object = None

    def set_status(self, kind: str) -> None:
        self.status_chip.value = _status_html(kind)
        self._state["status"] = kind
        # A verified identity supersedes any "register your key" guidance.
        if kind == "verified":
            self.registration_box.children = ()
            self.registration_box.layout.display = "none"

    def set_status_from_access(self, state) -> None:
        self.set_status(access_state_to_status_kind(state))

    def set_bootstrap_state(self, state: str, detail: str = "") -> None:
        """Drive the panel through a password-bootstrap attempt so the user is
        never left with a button that appears to do nothing.

        ``state`` is one of: ``registering``, ``verifying``, ``verified``,
        ``password_failed``, ``connector_failed``, ``not_permitted``,
        ``timed_out``.
        """
        kind, message = _BOOTSTRAP_UI.get(state, ("failed", ""))
        self.set_status(kind)
        if kind in ("registering", "verifying", "verified"):
            return
        body = message
        if detail:
            body += f"<div class='cryostack-help'>{detail}</div>"
        self.registration_box.children = (
            W.HTML(
                "<div class='cryostack-group-title'>SSH key registration</div>"
                f"<div class='cryostack-help'>{body}</div>"
            ),
        )
        self.registration_box.layout.display = "flex"

    def set_key_unregistered(self, profile=None) -> None:
        """The Connector reached the resource but the server rejected the
        CryoStack public key (``Permission denied (publickey``). Show an
        actionable "register your key" state instead of a bare red Failed.

        * password-bootstrap resources  -> point at Password bootstrap (one-time)
        * manual/portal resources       -> show the existing manual checklist
        * anything else                 -> neutral "register it, then re-check"
        """
        profile = profile if profile is not None else self._profile
        self.set_status("key_unregistered")

        if profile is not None and requires_manual_registration(profile):
            self._render_registration(profile)
            return

        resource = (getattr(profile, "name", "") or "your HPC account").strip() \
            or "your HPC account"
        if profile is not None and supports_password_bootstrap(profile):
            guidance = (
                "<div class='cryostack-help'>Select <b>Authentication method &rarr; "
                "Password bootstrap (one-time)</b>, enter your "
                f"{resource} password once, and click <b>Enable passwordless SSH</b>. "
                "CryoStack registers this key and re-checks access automatically. "
                "Your password is used once and never stored.</div>"
            )
        else:
            guidance = (
                "<div class='cryostack-help'>Add this CryoStack public key wherever "
                f"{resource} manages authorized SSH keys, then Check SSH Access "
                "again.</div>"
            )

        self.registration_box.children = (
            W.HTML(
                "<div class='cryostack-group-title'>SSH key is not registered</div>"
                "<div class='cryostack-help'>The CryoStack Connector is connected, "
                "but this CryoStack credential has not yet been authorized for "
                f"{resource}.</div>"
                f"{guidance}"
            ),
        )
        self.registration_box.layout.display = "flex"

    def apply_profile(self, profile) -> None:
        """Refresh the resource-aware auth options and the manual-registration
        checklist for the newly selected resource. Preserves the current auth
        selection when the new resource still supports it."""
        self._profile = profile
        options = auth_method_options(profile)
        tokens = [t for _, t in options]
        current = getattr(self.auth_method, "value", None)
        try:
            self.auth_method.options = options
        except Exception:
            pass
        if current in tokens:
            self.auth_method.value = current
        elif tokens:
            self.auth_method.value = tokens[0]

        self._render_registration(profile)

    def _render_registration(self, profile) -> None:
        if not requires_manual_registration(profile):
            self.registration_box.children = ()
            self.registration_box.layout.display = "none"
            return
        steps = manual_registration_steps(profile)
        link = portal_link(profile)
        items = "".join(f"<li>{s}</li>" for s in steps)
        if link:
            url, name = link
            portal_html = (
                f"<a class='cryostack-portal-link' href='{url}' target='_blank' "
                f"rel='noopener'>Open {name}</a>"
            )
        else:
            portal_html = (
                "<div class='cryostack-help'>This resource has no configured key "
                "portal. Add the public key wherever your institution manages SSH "
                "keys, then return and Check SSH Access.</div>"
            )
        self.registration_box.children = (
            W.HTML(
                "<div class='cryostack-group-title'>Register your key</div>"
                "<div class='cryostack-help'>This resource needs your CryoStack "
                "public key registered by hand. CryoStack never asks for your "
                "institutional web-portal password.</div>"
                f"<ol class='cryostack-reg-steps'>{items}</ol>"
                f"{portal_html}"
            ),
        )
        self.registration_box.layout.display = "flex"


def build_remote_connection_panel(
    *,
    resource: W.Widget,
    host: W.Widget,
    port: W.Widget,
    hpc_username: W.Widget,
    remote_directory: W.Widget,
    connection_method: W.Widget,
    auth_method: W.Widget,
    check_ssh_button: W.Widget,
    open_connector_button: W.Widget,
    connector_card: W.Widget,
    connector_setup_link: W.Widget,
    disconnect_button: W.Widget | None = None,
    profile=None,
    auth_extra_children: list[W.Widget] | None = None,
    advanced_children: list[W.Widget] | None = None,
) -> RemoteConnectionPanel:
    status_chip = W.HTML(_status_html("unchecked"))
    registration_box = W.VBox(layout=W.Layout(width="100%", gap="4px", display="none"))

    compute_resource = W.VBox(
        [
            _group_title("Compute resource"),
            _row(_field("Resource", resource), _field("Host", host)),
            _row(_field("Port", port)),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    identity = W.VBox(
        [
            _group_title("Your HPC identity"),
            _row(
                _field("HPC username", hpc_username),
                _field("Remote working directory", remote_directory),
            ),
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )

    access_children = [
        _group_title("Access"),
        _row(
            _field("Connection method", connection_method),
            _field("Authentication method", auth_method),
        ),
    ]
    if auth_extra_children:
        access_children.append(
            W.VBox(list(auth_extra_children), layout=W.Layout(width="100%", gap="6px"))
        )
    access_children.append(registration_box)
    access = W.VBox(access_children, layout=W.Layout(width="100%", gap="6px"))

    status_group = W.VBox(
        [
            _group_title("Status"),
            status_chip,
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    status_group.add_class("cryostack-conn-status-group")

    action_buttons = [check_ssh_button, open_connector_button]
    if disconnect_button is not None:
        action_buttons.append(disconnect_button)
    actions = W.HBox(action_buttons, layout=W.Layout(width="100%", gap="12px"))
    actions.add_class("cryostack-conn-actions")

    # Minimum pairing information only -- one status line (connector_card)
    # plus, only while pairing, the one real navigation link
    # (connector_setup_link). Never a second boxed "CRYOSTACK CONNECTOR"
    # card duplicating the Open Connector.../Disconnect actions above.
    # Session/relay diagnostics live in the Advanced accordion instead
    # (see advanced_children), never inline here.
    connector_status = W.VBox(
        [connector_card, connector_setup_link],
        layout=W.Layout(width="100%", gap="2px"),
    )

    sections = [
        compute_resource,
        identity,
        access,
        status_group,
        actions,
        connector_status,
    ]
    if advanced_children:
        adv_inner = W.VBox(list(advanced_children), layout=W.Layout(width="100%", gap="8px"))
        adv_accordion = W.Accordion(children=[adv_inner])
        adv_accordion.set_title(0, "Advanced")
        adv_accordion.selected_index = None
        adv_accordion.add_class("cryostack-advanced-accordion")
        sections.append(adv_accordion)

    container = W.VBox(sections, layout=W.Layout(width="100%", gap="18px"))
    container.add_class("cryostack-remote-connection-panel")

    panel = RemoteConnectionPanel(
        container=container,
        status_chip=status_chip,
        registration_box=registration_box,
        auth_method=auth_method,
    )
    if profile is not None:
        panel.apply_profile(profile)
    return panel
