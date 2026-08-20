from __future__ import annotations


APPLICATIONS = {
    "cryolauncher": {
        "title": "CryoLauncher",
        "url": "/icesheets/",
    },

    "icesee": {
        "title": "ICESEE",
        "url": "/icesee-gui/",
    },

    "livist": {
        "title": "LIVIST",
        "url": "/livist/",
    },

    "cryostack": {
        "title": "CryoStack",
        "url": "/index.html",
    },
}


def get_application(
    name: str | None,
) -> dict:
    key = (
        name or "cryostack"
    ).strip().lower()

    return APPLICATIONS.get(
        key,
        APPLICATIONS["cryostack"],
    )