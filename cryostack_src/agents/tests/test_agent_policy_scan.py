"""The prohibited-symbol scanner (PASS 4 review, security P1): catches stdlib
execution / env-access primitives and dynamic-import evasions, does not
false-positive on ordinary code, and TOOL_MODULES stays complete."""
from __future__ import annotations

import pytest

from cryostack_src.agents.policy import (
    _PROHIBITED_BUILTIN_CALLS,
    _UNSCANNED_OK,
    PROHIBITED_SYMBOLS,
    TOOL_MODULES,
    _referenced_names,
    assert_tool_modules_are_clean,
)

_ALL = PROHIBITED_SYMBOLS | _PROHIBITED_BUILTIN_CALLS


def _hits(src: str):
    return _ALL & _referenced_names(src)


@pytest.mark.parametrize("src", [
    "import os\nx = os.environ['HTTP_X_CRYOSTACK_USER_ID']",
    "from os import environ as e\ne['X']",
    "import os\nos.getenv('AWS_SECRET_ACCESS_KEY')",
    "import subprocess\nsubprocess.run(['id'])",
    "from subprocess import Popen",
    "x = __import__('os').system('id')",
    "eval('1+1')",
    "exec('x=1')",
    "import socket",
    "import ctypes",
    "import pty",
    "import runpy\nrunpy.run_path('x')",
    "from getpass import getuser",
    "import importlib\nimportlib.import_module('os')",
])
def test_dangerous_patterns_are_caught(src):
    assert _hits(src), f"scanner missed: {src!r}"


@pytest.mark.parametrize("src", [
    "import re\nrx = re.compile(r'x')",
    "d = {'system_prompt': 1, 'system': 2, 'messages': []}",
    "def complete(*, system, messages, tools): return system",
    "import json\njson.dumps({'a': 1})",
    "import hashlib\nhashlib.sha256(b'x')",
    "from dataclasses import dataclass",
    "class C:\n    def compile(self): ...",   # a method named compile
])
def test_ordinary_code_does_not_false_positive(src):
    assert not _hits(src), f"scanner false-positived: {src!r}"


def test_the_shipped_agent_package_is_clean():
    assert_tool_modules_are_clean()          # raises on any violation


def test_tool_modules_covers_every_agents_module():
    from pathlib import Path
    import cryostack_src.agents as pkg
    present = {p.stem for p in Path(pkg.__file__).parent.glob("*.py")}
    listed = set(TOOL_MODULES) | _UNSCANNED_OK
    assert present <= listed, f"unlisted agents modules: {sorted(present - listed)}"


def test_a_listed_but_missing_module_is_an_error(monkeypatch):
    import cryostack_src.agents.policy as pol
    monkeypatch.setattr(pol, "TOOL_MODULES", pol.TOOL_MODULES + ("does_not_exist",))
    with pytest.raises(AssertionError):
        pol.assert_tool_modules_are_clean()
