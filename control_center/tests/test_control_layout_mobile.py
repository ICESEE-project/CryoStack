"""Control Center navigation stays reachable on phone-width screens."""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from control_center.templates import control_layout  # noqa: E402


def _phone_rules(html: str) -> str:
    match = re.search(r"@media \(max-width: 760px\) \{(.*?)\n    \}\n  </style>", html, re.S)
    assert match, "phone-width rules not found"
    return match.group(1)


def test_phone_layout_keeps_every_navigation_link():
    html = control_layout(title="Users", active="users", content="<p>x</p>")
    rules = _phone_rules(html)
    sidebar = re.search(r"\.control-sidebar \{(.*?)\}", rules, re.S).group(1)
    assert "display: none" not in sidebar
    nav = re.search(r"\.control-nav \{(.*?)\}", rules, re.S).group(1)
    assert "display: flex" in nav and "overflow-x: auto" in nav


def test_storage_is_a_top_level_data_navigation_item():
    html = control_layout(title="Storage & quotas", active="storage", content="")
    assert re.search(r'class="control-nav-item active"\s+href="/control/storage"', html)
    assert "Storage &amp; quotas" in html
    data = html.index("Data")
    storage = html.index('href="/control/storage"')
    frozen = html.index('href="/control/frozen-legacies"')
    assert data < storage < frozen
    for href in ("/control/users", "/control/hpc", "/control/cloud", "/control/livist"):
        assert f'href="{href}"' in html
