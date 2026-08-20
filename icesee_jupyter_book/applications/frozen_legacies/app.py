from __future__ import annotations

from pathlib import Path
from flask import Blueprint, send_from_directory

HERE = Path(__file__).resolve().parent

frozen_legacies_bp = Blueprint(
    "frozen_legacies",
    __name__,
    url_prefix="/frozen-legacies",
)


@frozen_legacies_bp.route("/")
def index():
    return send_from_directory(
        HERE,
        "index.html",
    )


@frozen_legacies_bp.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(
        HERE / "assets",
        filename,
    )


@frozen_legacies_bp.route("/data/<path:filename>")
def data(filename):
    return send_from_directory(
        HERE / "data",
        filename,
    )