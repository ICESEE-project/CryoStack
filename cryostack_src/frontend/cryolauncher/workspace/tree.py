"""Backwards-compatible re-export.

Editable-file discovery lives in :mod:`cryostack_src.workspace.files` so the
workspace layer does not depend on the frontend package.
"""
from __future__ import annotations

from cryostack_src.workspace.files import EDITABLE_SUFFIXES, list_editable_files

__all__ = ["EDITABLE_SUFFIXES", "list_editable_files"]
