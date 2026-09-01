"""B4: resource-aware authentication UX helpers."""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from cryostack_src.resources.profiles import ComputeProfile, get_compute_profile
from icesee_jupyter_book.ui.shared_auth_ux import (
    auth_method_options,
    default_auth_method,
    manual_registration_steps,
    portal_link,
    requires_manual_registration,
    supported_auth_tokens,
)


def test_pace_offers_key_and_password_bootstrap_only():
    tokens = supported_auth_tokens(get_compute_profile("pace"))
    assert tokens == {"key", "bootstrap"}


def test_unknown_resource_offers_ssh_key_only():
    tokens = supported_auth_tokens(get_compute_profile("some-unknown-cluster"))
    assert tokens == {"key"}
    assert default_auth_method(get_compute_profile("some-unknown-cluster")) == "key"


def test_ssh_agent_option_appears_only_when_the_profile_declares_it():
    without = ComputeProfile(name="x", auth_modes=("ssh_key",))
    withagent = ComputeProfile(name="y", auth_modes=("ssh_key",), ssh_agent_supported=True)
    assert "agent" not in supported_auth_tokens(without)
    assert "agent" in supported_auth_tokens(withagent)


def test_certificate_or_token_text_in_a_profile_is_never_advertised():
    # even if a profile lists a mechanism we do not implement, it is dropped.
    weird = ComputeProfile(name="z", auth_modes=("institution_cert", "oauth_token"))
    assert [t for _, t in auth_method_options(weird)] == ["key"]


def test_manual_registration_gate_follows_key_registration_method():
    portal = ComputeProfile(name="p", key_registration_method="portal")
    manual = ComputeProfile(name="m", key_registration_method="manual")
    automatic = ComputeProfile(name="a", key_registration_method="automatic")
    assert requires_manual_registration(portal)
    assert requires_manual_registration(manual)
    assert not requires_manual_registration(automatic)


def test_manual_steps_are_the_fixed_six_and_use_the_portal_name_when_present():
    prof = ComputeProfile(
        name="p",
        key_registration_method="portal",
        portal_url="https://keys.example.edu",
        portal_name="Example Key Portal",
    )
    steps = manual_registration_steps(prof)
    assert len(steps) == 6
    assert steps[0].lower().startswith("generate")
    assert "Example Key Portal" in steps[2]
    assert steps[-1] == "Check SSH Access"
    assert portal_link(prof) == ("https://keys.example.edu", "Example Key Portal")


def test_manual_steps_stay_neutral_when_no_portal_url():
    prof = ComputeProfile(name="p", key_registration_method="manual")
    steps = manual_registration_steps(prof)
    assert portal_link(prof) is None
    assert "institution" in steps[2].lower()
    # no invented URL anywhere
    assert not any("http" in s for s in steps)
