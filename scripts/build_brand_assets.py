#!/usr/bin/env python3
"""Derive every packaging / UI logo asset from ONE canonical CryoStack image.

Canonical source:  icesee_jupyter_book/cryostack.png   (do not hand-edit copies)

Outputs (regenerated, safe to re-run):
    icesee_hpc_connector/assets/cryostack-connector-512.png   tray / window icon (Linux)
    icesee_hpc_connector/assets/cryostack-connector.icns      macOS .app / Dock icon
    icesee_hpc_connector/assets/cryostack-connector.ico       Windows .exe icon
    deployment/deploy_web_nginx/web/connect/cryostack-logo.png  /connect/ page + app header

Usage:  python3 scripts/build_brand_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "icesee_jupyter_book" / "cryostack.png"

CONNECTOR_ASSETS = REPO / "icesee_hpc_connector" / "assets"
CONNECT_WEB = REPO / "deployment" / "deploy_web_nginx" / "web" / "connect"


def _square(im):
    """Pad to a square canvas (never crop) on a transparent ground."""
    from PIL import Image

    im = im.convert("RGBA")
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas


def main() -> int:
    try:
        from PIL import Image
    except Exception:
        print("Pillow is required: pip install pillow", file=sys.stderr)
        return 2

    if not CANONICAL.is_file():
        print(f"canonical logo not found: {CANONICAL}", file=sys.stderr)
        return 1

    CONNECTOR_ASSETS.mkdir(parents=True, exist_ok=True)
    src = Image.open(CANONICAL)
    sq = _square(src)

    # Linux tray / window icon
    sq.resize((512, 512), Image.LANCZOS).save(CONNECTOR_ASSETS / "cryostack-connector-512.png")

    # macOS .icns  (Pillow synthesises the required sizes from a >=512 image)
    sq.resize((1024, 1024), Image.LANCZOS).save(CONNECTOR_ASSETS / "cryostack-connector.icns")

    # Windows .ico
    sq.save(
        CONNECTOR_ASSETS / "cryostack-connector.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # Web: the /connect/ page + the CryoStack app header. Natural aspect,
    # header-sized. Same canonical source -> no independently-edited file.
    CONNECT_WEB.mkdir(parents=True, exist_ok=True)
    w = 480
    h = round(src.height * (w / src.width))
    src.convert("RGBA").resize((w, h), Image.LANCZOS).save(CONNECT_WEB / "cryostack-logo.png")

    print("brand assets regenerated from", CANONICAL.relative_to(REPO))
    for p in (
        CONNECTOR_ASSETS / "cryostack-connector-512.png",
        CONNECTOR_ASSETS / "cryostack-connector.icns",
        CONNECTOR_ASSETS / "cryostack-connector.ico",
        CONNECT_WEB / "cryostack-logo.png",
    ):
        print("  ", p.relative_to(REPO), f"({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
