"""Structural safety checks for reviewed, root-run staging data promotions."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "deployment" / "systemd"


def _text(name: str) -> str:
    return (SYSTEMD / name).read_text(encoding="utf-8")


def test_promotion_and_installer_scripts_parse():
    scripts = [
        SYSTEMD / "promote_staging_navigation.sh",
        SYSTEMD / "promote_staging_riggs.sh",
        SYSTEMD / "install_staging_service.sh",
    ]
    result = subprocess.run(["bash", "-n", *map(str, scripts)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_riggs_promotion_is_verified_immutable_and_staging_only():
    script = _text("promote_staging_riggs.sh")
    assert 'if [ "$(id -u)" -ne 0 ]' in script
    assert "riggs_collection" in script
    assert 'r["summary"]["stations"] > 0' in script
    assert '[[ "${digest}" =~ ^[0-9a-f]{64}$ ]]' in script
    assert "/srv/cryostack-staging/datasets/riggs" in script
    assert 'install -o root -g "${service_group}" -m 0640' in script
    assert 'mv -Tf "${link_tmp}" "${current}"' in script
    assert "/home/bkyanjo3/cryostack-data" not in script
    assert "systemctl" not in script and "nginx" in script


def test_staging_configures_riggs_only_after_a_release_exists():
    installer = _text("install_staging_service.sh")
    assert "if [ -L /srv/cryostack-staging/datasets/riggs/current ]; then" in installer
    assert "CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV=" in installer
    assert "CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST=" in installer


def test_production_launcher_preserves_navigation_after_restart():
    launcher = (ROOT / "deployment" / "services.sh").read_text(encoding="utf-8")
    assert "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT" in launcher
    assert "CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS" in launcher
    assert ("/srv/cryostack/workspace/datasets/frozen-legacies/spri/navigation/"
            "releases/nav-177c92df4cc0f690") in launcher
    assert "protected=\" $$\"" in launcher
    assert 'case " ${protected} "' in launcher
