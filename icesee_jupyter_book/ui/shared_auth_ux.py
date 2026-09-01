"""Resource-aware authentication UX helpers.

The authentication controls a gateway shows must reflect the selected
:class:`~cryostack_src.resources.profiles.ComputeProfile` -- never a fixed
menu. We only surface mechanisms CryoStack actually implements *and* the
resource declares:

* ``ssh_key``            -> "SSH key"
* ``password_bootstrap`` -> "Password bootstrap (one-time)"
* ``ssh_agent_supported`` -> "SSH agent"

Institution certificates, token-based auth and portal *provisioning* are not
implemented, so they are never advertised here regardless of profile text.

When a resource needs a public key registered by hand
(``key_registration_method`` in ``{"portal", "manual"}``) we show a fixed,
safe, six-step checklist. CryoStack never collects the user's institutional
web-portal password; if the profile has no portal URL we show neutral manual
instructions instead of inventing one.
"""
from __future__ import annotations

# Stable option tokens. "key"/"bootstrap" match what B2 persists; "agent" is
# additive and only ever appears when a profile sets ssh_agent_supported.
_LABELS = {
    "key": "SSH key",
    "bootstrap": "Password bootstrap (one-time)",
    "agent": "SSH agent",
}

#: the six-step manual public-key registration checklist (fixed wording)
MANUAL_REGISTRATION_STEPS = (
    "Generate / view your CryoStack public key",
    "Copy the public key",
    "{open_portal}",
    "Register the key",
    "Return to CryoStack",
    "Check SSH Access",
)


def auth_method_options(profile) -> list[tuple[str, str]]:
    """``[(label, token), ...]`` for the selected resource, in a stable order.

    Always non-empty: an unknown/neutral profile still supports ``ssh_key``.
    """
    declared = tuple(getattr(profile, "auth_modes", ()) or ())
    options: list[tuple[str, str]] = []

    if "ssh_key" in declared or not declared:
        options.append((_LABELS["key"], "key"))
    if "password_bootstrap" in declared:
        options.append((_LABELS["bootstrap"], "bootstrap"))
    if getattr(profile, "ssh_agent_supported", False):
        options.append((_LABELS["agent"], "agent"))

    if not options:  # profile declared only mechanisms we do not implement
        options.append((_LABELS["key"], "key"))
    return options


def supported_auth_tokens(profile) -> set[str]:
    """The set of auth tokens valid for this resource (for restore/validation)."""
    return {token for _, token in auth_method_options(profile)}


def default_auth_method(profile) -> str:
    """Preferred default token for a freshly selected resource."""
    return auth_method_options(profile)[0][1]


def requires_manual_registration(profile) -> bool:
    """True when the user must register a public key by hand (portal or manual)."""
    return getattr(profile, "key_registration_method", "manual") in ("portal", "manual")


def portal_link(profile) -> tuple[str, str] | None:
    """``(url, label)`` for the resource's key portal, or ``None`` when the
    profile declares no URL (then show neutral manual instructions)."""
    url = (getattr(profile, "portal_url", "") or "").strip()
    if not url:
        return None
    name = (getattr(profile, "portal_name", "") or "").strip() or "the institutional portal"
    return url, name


def manual_registration_steps(profile) -> list[str]:
    """The fixed six-step checklist, with step 3 adapted to the profile."""
    link = portal_link(profile)
    if link:
        _, name = link
        open_step = f"Open {name}"
    else:
        open_step = "Open your institution's SSH public-key page"
    return [s.format(open_portal=open_step) for s in MANUAL_REGISTRATION_STEPS]
