"""B5 -- end-user "Configure access to your HPC system" documentation.

Verifies the public CryoLauncher docs against the actually-implemented
architecture (ComputeProfile, shared_auth_ux, AccessState, ssh_identity,
connector v2, Slurm validation, B2 persistence) and guards against personal
values, private-key examples and secrets.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_APP = _REPO / "icesee_jupyter_book" / "applications" / "icesheets"
_UM = _APP / "user_manual.md"
_GS = _APP / "getting_started.md"
_RES = _APP / "resources.md"
_CRYOLAUNCHER_DOCS = (_UM, _GS, _RES)

_FORBIDDEN = (
    "bankyanjo", "arobel3", "r-arobel3", "gts-arobel3", "bkyanjo3",
    "login-phoenix",  # a real resource host must not be pasted as an example
    "BEGIN OPENSSH PRIVATE KEY", "BEGIN RSA PRIVATE KEY",
)
_SECRET_ASSIGN = re.compile(
    r"(password|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{12,}",
    re.IGNORECASE,
)


def _slug(heading: str) -> str:
    # Sphinx/MyST drops a leading "N. " section number from the anchor slug.
    heading = re.sub(r"^\d+\.\s+", "", heading.strip())
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


# ── the section exists and covers the required ground ─────────────────
def test_user_manual_has_the_hpc_access_section():
    src = _UM.read_text()
    assert "## 9. Configure access to your HPC system" in src
    for sub in (
        "### The trust model",
        "### Recommended path — the CryoStack Connector",
        "### Direct SSH from server",
        "### SSH keys",
        "#### Password bootstrap (one-time)",
        "#### Manual / web-portal registration",
        "### VPN, MFA, campus network",
        "### SSH agent",
        "### Remote working directory",
        "### Slurm resources",
        "### Check SSH Access",
        "### Run protection",
        "### Security and isolation",
    ):
        assert sub in src, sub


def test_getting_started_has_the_hpc_access_step():
    src = _GS.read_text()
    assert "## 6. Configure access to your HPC resource (Remote)" in src


def test_resources_links_the_access_guide_and_connector():
    src = _RES.read_text()
    assert "user_manual.html#configure-access-to-your-hpc-system" in src
    assert 'href="/connect/"' in src
    assert "/downloads/connectors/" in src


# ── trust model stated correctly ─────────────────────────────────────
def test_trust_model_is_explicit():
    src = _UM.read_text()
    assert "does **not** create an HPC account" in src
    assert "acts entirely as **you**" in src
    assert re.search(r"blocks the run.*does not match the HPC username", src, re.S)
    # never implies execution through a developer account
    assert "developer's account" in src and "never execute through a CryoStack developer" in src


def test_private_key_is_never_asked_for_and_portal_password_never_requested():
    src = _UM.read_text().replace("\n", " ")
    assert "private key** must **never**" in src
    assert "never asks for the portal's web password" in src
    assert "typed input only" in src  # bootstrap password not persisted


# ── claims match the implementation ──────────────────────────────────
def test_credential_namespace_claim_matches_ssh_identity():
    src = _UM.read_text()
    assert "namespaced by user × resource × HPC identity" in src
    assert "~/.ssh/cryostack/" in src
    # legacy key mentioned as not-adopted
    assert "id_ed25519_icesee_<cluster>" in src and "never adopted" in src


def test_verification_command_claim_matches_access_state():
    from cryostack_src.remote.access_state import _first_line  # noqa: F401
    from cryostack_src.resources.profiles import get_compute_profile
    assert get_compute_profile("pace").verification_command == "whoami"
    src = _UM.read_text()
    assert "identity command (whoami)" in src
    for state in ("Not checked", "Checking…", "Verified", "Identity mismatch", "Failed"):
        assert state in src


def test_auth_methods_are_only_the_implemented_ones():
    from cryostack_src.resources.profiles import get_compute_profile
    assert set(get_compute_profile("pace").auth_modes) == {"ssh_key", "password_bootstrap"}
    src = _UM.read_text()
    # no unimplemented mechanisms advertised
    for bad in ("institution certificate", "token-based auth", "OAuth", "Kerberos ticket"):
        assert bad.lower() not in src.lower()
    # ssh-agent stated honestly
    assert "no currently configured resource does" in src.lower()
    assert "Connector uses a dedicated key file, not your ssh-agent" in src


def test_slurm_layout_matches_b4():
    src = _UM.read_text()
    for f in ("Job name", "Wall time", "Nodes", "Tasks", "Tasks / node",
              "Partition", "Memory", "Account", "Email"):
        assert f in src
    assert "MM:SS`, `HH:MM:SS`, or `D-HH:MM:SS" in src
    assert "512M`, `4G`, `16GB`, `1T" in src
    assert "tasks / node ≤ tasks" in src


def test_connector_download_source_is_the_manifest():
    src = _UM.read_text()
    assert "/downloads/connectors/manifest.json" in src
    assert "not been published for it yet" in src


def test_macos_known_issues_are_present_but_concise():
    src = _UM.read_text()
    assert "/Applications" in src and "responsiveness issue" in src
    assert "pairing field" in src
    # concise: the honest-notes paragraph is short
    para = src.split("Known macOS notes", 1)[1].split("###", 1)[0]
    assert len(para) < 700


# ── hygiene ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", _CRYOLAUNCHER_DOCS)
def test_no_personal_values_private_keys_or_secrets(path):
    src = path.read_text()
    for bad in _FORBIDDEN:
        assert bad not in src, f"{bad} in {path.name}"
    m = _SECRET_ASSIGN.search(src)
    assert m is None, f"possible secret in {path.name}: {m.group(0)!r}"
    # placeholders, not real identifiers
    if "scratch/" in src:
        assert "/scratch/<your-username>/" in src


# ── numbering + anchors ─────────────────────────────────────────────
def test_user_manual_sections_are_contiguous():
    nums = [int(m) for m in re.findall(r"^## (\d+)\. ", _UM.read_text(), re.M)]
    assert nums == list(range(1, len(nums) + 1)), nums


def test_getting_started_sections_are_contiguous():
    nums = [int(m) for m in re.findall(r"^## (\d+)\. ", _GS.read_text(), re.M)]
    assert nums == list(range(1, len(nums) + 1)), nums


def test_internal_anchor_links_resolve_to_headings():
    um = _UM.read_text()
    gs = _GS.read_text()
    um_slugs = {_slug(h) for h in re.findall(r"^#{2,4} (.+)$", um, re.M)}
    gs_slugs = {_slug(h) for h in re.findall(r"^#{2,4} (.+)$", gs, re.M)}
    # links into the user manual
    for anchor in re.findall(r"user_manual(?:\.html)?#([a-z0-9-]+)", gs + um + _RES.read_text()):
        assert anchor in um_slugs, anchor
    # same-page links in getting started
    for anchor in re.findall(r'href="#([a-z0-9-]+)"', gs):
        assert anchor in gs_slugs, anchor


def test_developer_guide_stays_public_and_maintainer_guide_stays_protected():
    toc = (_REPO / "icesee_jupyter_book" / "_toc.yml").read_text()
    assert "docs/developer_guide" in toc
    assert "maintainer_guide" not in toc
