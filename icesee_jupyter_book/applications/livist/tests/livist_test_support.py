"""Shared helpers of the LIVIST tests: the generator is replaced at the
subprocess boundary by ``livist_fake_generate.py``."""
import subprocess
import sys
from pathlib import Path

from icesee_jupyter_book.applications.livist import toolchain

FAKE_GENERATE = Path(__file__).with_name("livist_fake_generate.py")
SECRET = "livist-test-secret-value-7f3a"


def fake_popen(calls=None):
    def popen(command, **kwargs):
        assert command[-1].endswith("scripts/generate"), command
        if calls is not None:
            calls.append({"command": command, **kwargs})
        return subprocess.Popen([sys.executable, "-I", str(FAKE_GENERATE)], **kwargs)
    return popen


def ready_health(**_kwargs):
    return {"ready": True, "checks": [], "record": None, "livist_commit": None,
            "checked_at": 0.0}


def not_ready_health(**_kwargs):
    return {"ready": False,
            "checks": [{"id": "gdal_parquet", "label": "GDAL (Geo)Parquet driver", "ok": False,
                        "detail": "missing", "level": "error"}],
            "record": None, "livist_commit": None, "checked_at": 0.0}


def use_ready_toolchain(monkeypatch):
    monkeypatch.setattr(toolchain, "health", ready_health)
