"""B4: shared Remote Connection panel -- user-workflow layout, connector
internals behind Diagnostics, B3 status preserved."""
from __future__ import annotations

import sys
from pathlib import Path

import ipywidgets as W
import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.resources.profiles import ComputeProfile, get_compute_profile
from icesee_jupyter_book.ui.shared_remote_connection_panel import (
    access_state_to_status_kind,
    build_remote_connection_panel,
    classify_bootstrap_result,
    connector_diagnostics_html,
    connector_pairing_link_html,
    connector_pairing_status_html,
)


def _panel(profile=None, disconnect_button=None):
    return build_remote_connection_panel(
        resource=W.Text(value="pace"),
        host=W.Text(value="login.example.edu"),
        port=W.IntText(value=22),
        hpc_username=W.Text(value=""),
        remote_directory=W.Text(value=""),
        connection_method=W.Dropdown(options=[("Auto", "auto")], value="auto"),
        auth_method=W.Dropdown(options=[("SSH key", "key")], value="key"),
        check_ssh_button=W.Button(description="Check SSH Access"),
        open_connector_button=W.Button(description="Open Connector..."),
        connector_card=W.HTML(),
        connector_setup_link=W.HTML(),
        disconnect_button=disconnect_button,
        profile=profile if profile is not None else get_compute_profile("pace"),
    )


def _all_html(widget) -> str:
    out = []

    def walk(w):
        if isinstance(w, W.HTML):
            out.append(w.value)
        for child in getattr(w, "children", ()):
            walk(child)

    walk(widget)
    return "\n".join(out)


def _titles(widget) -> list[str]:
    out = []

    def walk(w):
        if isinstance(w, W.Accordion):
            out.extend(w.titles if getattr(w, "titles", None) else
                       [w.get_title(i) for i in range(len(w.children))])
        for child in getattr(w, "children", ()):
            walk(child)

    walk(widget)
    return out


def test_workflow_groups_present():
    html = _all_html(_panel().container)
    for group in ("Compute resource", "Your HPC identity", "Access", "Status"):
        assert group in html


def test_no_duplicate_cryostack_connector_card():
    """Restore the Remote Connector UI: no second, large, boxed
    "CRYOSTACK CONNECTOR" section duplicating the compact Connection
    method / Status / Check SSH Access / Open Connector... controls
    above it -- the connector status/pairing link render directly, with
    no separate group heading or bordered card class."""
    panel = _panel()
    html = _all_html(panel.container)
    assert "CryoStack Connector" not in html
    classes = set()
    for w in _walk_all(panel.container):
        classes.update(getattr(w, "_dom_classes", ()) or ())
    assert "cryostack-connector-card" not in classes


def _walk_all(widget):
    out = [widget]

    def walk(w):
        for child in getattr(w, "children", ()):
            out.append(child)
            walk(child)

    walk(widget)
    return out


def test_session_diagnostics_live_only_in_the_connector_card_not_a_second_accordion():
    # the panel no longer renders its own always-empty "Diagnostics" accordion;
    # relay/session diagnostics belong to the connector status card (passed in
    # as connector_card by the gateway).
    panel = _panel()
    assert "Diagnostics" not in _titles(panel.container)
    assert not hasattr(panel, "set_diagnostics")
    assert not hasattr(panel, "diagnostics")


def test_connector_diagnostics_html_only_appears_in_advanced_when_supplied():
    """Session id / ws path / relay state are genuinely technical --
    they must live only inside the existing Advanced accordion, never the
    compact top-level view."""
    diag = W.HTML(connector_diagnostics_html(
        session_id="sess-123", ws_url="/connector/ws/sess-123",
        relay_state="online"))
    plain = _panel()
    assert "sess-123" not in _all_html(plain.container)

    with_diag = build_remote_connection_panel(
        resource=W.Text(value="pace"), host=W.Text(value="h"), port=W.IntText(value=22),
        hpc_username=W.Text(value=""), remote_directory=W.Text(value=""),
        connection_method=W.Dropdown(options=[("Auto", "auto")], value="auto"),
        auth_method=W.Dropdown(options=[("SSH key", "key")], value="key"),
        check_ssh_button=W.Button(), open_connector_button=W.Button(),
        connector_card=W.HTML(), connector_setup_link=W.HTML(),
        profile=get_compute_profile("pace"), advanced_children=[diag],
    )
    assert "Advanced" in _titles(with_diag.container)
    assert "sess-123" in _all_html(with_diag.container)


def test_disconnect_button_appears_in_actions_when_supplied():
    disconnect_btn = W.Button(description="Disconnect")
    panel = _panel(disconnect_button=disconnect_btn)
    found = [w for w in _walk_all(panel.container)
             if isinstance(w, W.Button) and w.description == "Disconnect"]
    assert found and found[0] is disconnect_btn


def test_no_disconnect_button_when_not_supplied():
    panel = _panel()
    found = [w for w in _walk_all(panel.container)
             if isinstance(w, W.Button) and w.description == "Disconnect"]
    assert found == []


# -- minimal pairing information helpers (used in place of the old boxed
# "CRYOSTACK CONNECTOR" card and its duplicate "Open CryoStack Connector
# Setup" anchor) ------------------------------------------------------
def test_pairing_status_html_is_empty_until_a_session_exists():
    assert connector_pairing_status_html(
        session_id=None, pairing_code=None, online=False) == ""


def test_pairing_status_html_shows_the_pairing_code_while_waiting():
    html = connector_pairing_status_html(
        session_id="sess-1", pairing_code="AB12", online=False)
    assert "AB12" in html
    assert "connected" not in html.lower()


def test_pairing_status_html_shows_connected_once_online():
    html = connector_pairing_status_html(
        session_id="sess-1", pairing_code="AB12", online=True)
    assert "connected" in html.lower()
    assert "AB12" not in html


def test_pairing_link_html_is_the_one_navigation_control():
    """Exactly one real "open a new tab" link -- never a second large
    duplicate button next to the real Open Connector... button."""
    assert connector_pairing_link_html(session_id=None, app="icesheets") == ""
    html = connector_pairing_link_html(session_id="sess-1", app="icesheets")
    assert html.count("<a ") == 1
    assert "session=sess-1" in html and "app=icesheets" in html


def test_pairing_and_diagnostics_html_never_leak_implementation_details_by_themselves():
    """The compact pairing line names a code and "the Connector" -- never
    tunnel/relay/WebSocket/token/FlexNet/vendor-daemon/host-port/
    MLM_LICENSE_FILE wording. (Diagnostics -- session id / ws path -- are
    the deliberate exception, and stay confined to Advanced; see above.)"""
    pairing_html = (
        connector_pairing_status_html(
            session_id="sess-1", pairing_code="AB12", online=False)
        + connector_pairing_status_html(
            session_id="sess-1", pairing_code="AB12", online=True)
        + connector_pairing_link_html(session_id="sess-1", app="icesheets")
    ).lower()
    for forbidden in (
        "tunnel", "relay", "websocket", "token", "flexnet", "vendor",
        "mlm_license_file",
    ):
        assert forbidden not in pairing_html, forbidden


def test_advanced_accordion_only_appears_when_extra_controls_are_supplied():
    plain = _panel()
    assert "Advanced" not in _titles(plain.container)

    tag = W.Text(value="icesheets")
    with_extra = build_remote_connection_panel(
        resource=W.Text(value="pace"), host=W.Text(value="h"), port=W.IntText(value=22),
        hpc_username=W.Text(value=""), remote_directory=W.Text(value=""),
        connection_method=W.Dropdown(options=[("Auto", "auto")], value="auto"),
        auth_method=W.Dropdown(options=[("SSH key", "key")], value="key"),
        check_ssh_button=W.Button(), open_connector_button=W.Button(),
        connector_card=W.HTML(), connector_setup_link=W.HTML(),
        profile=get_compute_profile("pace"), advanced_children=[tag],
    )
    assert "Advanced" in _titles(with_extra.container)


def test_key_unregistered_state_is_actionable_for_a_password_bootstrap_resource():
    panel = _panel(profile=get_compute_profile("pace"))   # PACE supports bootstrap
    panel.set_key_unregistered(get_compute_profile("pace"))
    assert "SSH key not registered" in panel.status_chip.value
    assert "is-key-unregistered" in panel.status_chip.value
    html = _all_html(panel.registration_box)
    assert "not yet been authorized" in html
    assert "Password bootstrap (one-time)" in html
    assert panel.registration_box.layout.display != "none"


def test_key_unregistered_uses_the_manual_checklist_for_portal_resources():
    portal = ComputeProfile(
        name="m", key_registration_method="portal",
        portal_url="https://keys.example.edu", portal_name="Example Portal",
    )
    panel = _panel(profile=portal)
    panel.set_key_unregistered(portal)
    html = _all_html(panel.registration_box)
    assert "Example Portal" in html
    assert "Password bootstrap" not in html


def test_bootstrap_state_gives_immediate_and_final_feedback():
    panel = _panel(profile=get_compute_profile("pace"))

    panel.set_bootstrap_state("registering")
    assert "Registering SSH key" in panel.status_chip.value

    panel.set_bootstrap_state("verifying")
    assert "verifying access" in panel.status_chip.value

    panel.set_bootstrap_state("password_failed")
    assert "is-key-unregistered" in panel.status_chip.value
    assert "Password authentication failed" in _all_html(panel.registration_box)

    panel.set_bootstrap_state("timed_out")
    assert "is-failed" in panel.status_chip.value
    assert "Timed out" in _all_html(panel.registration_box)

    panel.set_bootstrap_state("connector_failed", "Connector dropped.")
    html = _all_html(panel.registration_box)
    assert "could not run the bootstrap command" in html
    assert "Connector dropped." in html


@pytest.mark.parametrize("result,expected", [
    ({"ok": True, "reason": "ok", "key_installed": True}, "installed"),
    ({"ok": False, "reason": "verify_failed", "key_installed": True}, "installed"),
    ({"ok": False, "reason": "password_auth_failed"}, "password_failed"),
    ({"ok": False, "reason": "paramiko_missing"}, "not_permitted"),
    ({"ok": False, "reason": "connect_failed"}, "timed_out"),
    ({"ok": False, "reason": "install_failed"}, "connector_failed"),
    ({"detail": "Connector command timed out."}, "timed_out"),
    ({"weird": 1}, "connector_failed"),
    ("not a dict", "connector_failed"),
])
def test_classify_bootstrap_result(result, expected):
    assert classify_bootstrap_result(result) == expected


def test_verified_status_clears_any_registration_guidance():
    panel = _panel(profile=get_compute_profile("pace"))
    panel.set_key_unregistered(get_compute_profile("pace"))
    assert panel.registration_box.children != ()
    panel.set_status("verified")
    assert panel.registration_box.children == ()
    assert panel.registration_box.layout.display == "none"


def test_status_chip_starts_not_checked_and_reflects_checks():
    panel = _panel()
    assert "Not checked" in panel.status_chip.value
    panel.set_status("verified")
    assert "Verified" in panel.status_chip.value and "is-verified" in panel.status_chip.value
    panel.set_status("mismatch")
    assert "Mismatch" in panel.status_chip.value
    panel.set_status("failed")
    assert "Failed" in panel.status_chip.value


def test_status_maps_from_b3_access_state():
    assert access_state_to_status_kind("ssh_verified") == "verified"
    assert access_state_to_status_kind("identity_mismatch") == "mismatch"
    assert access_state_to_status_kind("access_failed") == "failed"
    assert access_state_to_status_kind("credential_missing") == "unchecked"


def test_auth_options_follow_the_selected_resource():
    panel = _panel(profile=get_compute_profile("pace"))
    assert [t for _, t in panel.auth_method.options] == ["key", "bootstrap"]
    panel.apply_profile(get_compute_profile("totally-unknown"))
    assert [t for _, t in panel.auth_method.options] == ["key"]


def test_manual_registration_checklist_only_when_profile_requires_it():
    auto = _panel(profile=ComputeProfile(name="a", key_registration_method="automatic"))
    assert auto.registration_box.layout.display == "none"
    assert auto.registration_box.children == ()

    manual = _panel(profile=ComputeProfile(
        name="m", key_registration_method="portal",
        portal_url="https://keys.example.edu", portal_name="Example Portal",
    ))
    assert manual.registration_box.layout.display != "none"
    html = _all_html(manual.registration_box)
    assert "Example Portal" in html
    assert "never asks for your institutional web-portal password" in html


def test_manual_registration_without_portal_url_stays_neutral():
    panel = _panel(profile=ComputeProfile(name="m", key_registration_method="manual"))
    html = _all_html(panel.registration_box)
    assert "no configured key" in html.lower()
    assert "http" not in html
