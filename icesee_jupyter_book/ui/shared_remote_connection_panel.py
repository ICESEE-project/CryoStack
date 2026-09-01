"""Shared "Remote Connection" panel -- reusable by IceSheets, ICESEE and future
Icepack UIs.

Reorganised around the user's workflow instead of the transport internals:

    Compute resource      Resource / Host / Port
    Your HPC identity     HPC username / Remote working directory
    Access                Connection method / Authentication method
    Status                * Not checked / Verified / Mismatch / Failed
    [ Check SSH Access ] [ Open Connector Setup ]

    CryoStack Connector   Status: Waiting / Connected + Pairing code
    > Diagnostics         session id / websocket path / relay + raw state

This is a presentation helper. It takes the gateway's existing widget
instances and arranges them; it never changes transport behaviour, the B3
AccessState machine, identity verification, or the Run gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W

from icesee_jupyter_book.ui.shared_auth_ux import (
    auth_method_options,
    manual_registration_steps,
    portal_link,
    requires_manual_registration,
)

# status chip: (css-modifier, dot, label)
_STATUS = {
    "unchecked": ("is-unchecked", "●", "Not checked"),
    "checking": ("is-checking", "●", "Checking…"),
    "verified": ("is-verified", "●", "Verified"),
    "mismatch": ("is-mismatch", "●", "Mismatch"),
    "failed": ("is-failed", "●", "Failed"),
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
    diagnostics: W.HTML
    registration_box: W.VBox
    auth_method: W.Widget
    _state: dict = field(default_factory=dict)

    def set_status(self, kind: str) -> None:
        self.status_chip.value = _status_html(kind)
        self._state["status"] = kind

    def set_status_from_access(self, state) -> None:
        self.set_status(access_state_to_status_kind(state))

    def set_diagnostics(self, *, session_id="", ws_path="", relay_state="", raw_state="") -> None:
        rows = [
            ("session id", session_id or "—"),
            ("websocket path", ws_path or "—"),
            ("relay state", relay_state or "—"),
            ("raw connector state", raw_state or "—"),
        ]
        body = "".join(
            f"<div><span class='cryostack-diag__k'>{k}:</span> "
            f"<code>{v}</code></div>"
            for k, v in rows
        )
        self.diagnostics.value = f"<div class='cryostack-diag'>{body}</div>"

    def apply_profile(self, profile) -> None:
        """Refresh the resource-aware auth options and the manual-registration
        checklist for the newly selected resource. Preserves the current auth
        selection when the new resource still supports it."""
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
    profile=None,
    auth_extra_children: list[W.Widget] | None = None,
    advanced_children: list[W.Widget] | None = None,
) -> RemoteConnectionPanel:
    status_chip = W.HTML(_status_html("unchecked"))
    diagnostics = W.HTML()
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

    actions = W.HBox(
        [check_ssh_button, open_connector_button],
        layout=W.Layout(width="100%", gap="12px"),
    )
    actions.add_class("cryostack-conn-actions")

    connector_section = W.VBox(
        [
            _group_title("CryoStack Connector"),
            connector_card,
            connector_setup_link,
        ],
        layout=W.Layout(width="100%", gap="6px"),
    )
    connector_section.add_class("cryostack-connector-card")

    diag_children = [diagnostics]
    if advanced_children:
        diag_children.extend(advanced_children)
    diag_inner = W.VBox(diag_children, layout=W.Layout(width="100%", gap="8px"))
    diag_accordion = W.Accordion(children=[diag_inner])
    diag_accordion.set_title(0, "Diagnostics")
    diag_accordion.selected_index = None
    diag_accordion.add_class("cryostack-diagnostics-accordion")

    container = W.VBox(
        [
            compute_resource,
            identity,
            access,
            status_group,
            actions,
            connector_section,
            diag_accordion,
        ],
        layout=W.Layout(width="100%", gap="18px"),
    )
    container.add_class("cryostack-remote-connection-panel")

    panel = RemoteConnectionPanel(
        container=container,
        status_chip=status_chip,
        diagnostics=diagnostics,
        registration_box=registration_box,
        auth_method=auth_method,
    )
    panel.set_diagnostics()
    if profile is not None:
        panel.apply_profile(profile)
    return panel
