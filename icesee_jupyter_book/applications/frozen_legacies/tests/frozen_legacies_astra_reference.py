"""Headless harness around the unmodified ASTRA reference script.

``Pickers/ASTRA_MAC.py`` runs its GUI at import time, so it cannot be
imported. This harness parses it, executes only its top-level function
definitions in a namespace whose GUI objects are inert stubs, and drives
ASTRA's own functions (``load_image_and_reset``, ``on_click``,
``next_ascope``, ``suggest_picks``, ``save_to_csv``,
``save_tiff_with_all_points`` ...). It is the parity oracle for the
Frozen Legacies ASTRA port: expected values come from ASTRA's code, not
from a re-reading of it.

ASTRA is run in its path-based (CLI) mode, where ``--nav`` names the
navigation CSV and ``--output`` the output directory.
"""
from __future__ import annotations

import ast
import glob
import os
import re
import shutil
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from PIL import Image
from scipy.ndimage import gaussian_filter

ASTRA_PATH = Path(__file__).resolve().parent.parent / "Pickers" / "ASTRA_MAC.py"


class _Inert:
    """Accepts any attribute access or call (matplotlib/Tk stand-in)."""

    def __getattr__(self, name):
        return _Inert()

    def __call__(self, *args, **kwargs):
        return _Inert()


class _Axes(_Inert):
    def get_xlim(self):
        return (-0.5, 2299.5)

    def get_ylim(self):
        return (1549.5, -0.5)


class _Slider:
    def __init__(self, namespace):
        self._ns = namespace
        self.val = 0
        self.valmin = 0
        self.valmax = 0
        self.ax = _Inert()

    def set_val(self, value):
        self.val = value
        self._ns["update"](value)          # Slider.on_changed(update)


def available() -> bool:
    return ASTRA_PATH.is_file()


def _function_defs():
    tree = ast.parse(ASTRA_PATH.read_text(encoding="utf-8"))
    defs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    return compile(ast.Module(body=defs, type_ignores=[]), str(ASTRA_PATH), "exec")


class Astra:
    """One ASTRA session on one TIFF, driven headlessly."""

    def __init__(self, tiff_path: Path, *, nav_path: Path | None, output_dir: Path):
        ns: dict = {
            "np": np, "pd": pd, "Image": Image, "gaussian_filter": gaussian_filter,
            "os": os, "glob": glob, "shutil": shutil, "textwrap": textwrap,
            "sys": sys, "re": re,
            "ax": _Axes(), "canvas": _Inert(), "root": _Inert(),
            # ASTRA module-level state (path-based mode)
            "CLI_MODE": True, "NAV_FILE": str(nav_path) if nav_path else None,
            "OUTPUT_DIR": str(output_dir), "SCRIPT_DIR": str(ASTRA_PATH.parent),
            "data": [], "current_scope": 1, "current_feature": None,
            "crop_start_y": 250, "crop_end_y": 1800, "processed_files": set(),
            "flash_message": None, "flash_counter": 0, "sweep_rate": 2,
            "cbd_title_override": None, "TEXT_SCALE": 1.0,
            "image_path": str(tiff_path),
            "current_filename": os.path.splitext(os.path.basename(str(tiff_path)))[0],
            "tiff_files": [str(tiff_path)], "current_file_index": 0,
        }
        exec(_function_defs(), ns)
        ns["x_slider_control"] = _Slider(ns)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.ns = ns
        ns["load_image_and_reset"]()
        # ASTRA creates the slider after the first load with this range
        ns["x_slider_control"].valmax = ns["cropped_img"].width - ns["zoom_width"]

    # -- GUI actions (the Tk button callbacks) --------------------------
    def call(self, name, *args):
        return self.ns[name](*args)

    def click(self, xdata, ydata):
        self.ns["on_click"](SimpleNamespace(xdata=xdata, ydata=ydata))

    def move(self, value):
        self.ns["x_slider_control"].set_val(value)

    def finish(self) -> None:
        """``done_and_clear_reference`` without loading a next TIFF."""
        self.ns["commit_current_ascope"]()
        self.ns["save_to_csv"]()
        self.ns["save_tiff_with_all_points"]()

    def __getitem__(self, name):
        return self.ns[name]
