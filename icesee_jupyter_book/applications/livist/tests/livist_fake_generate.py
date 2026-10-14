"""Stand-in for LIVIST's ``scripts/generate`` in tests (the subprocess boundary).

Run in the job directory with the job environment, like the real script. It
reads ``config.toml`` and writes structurally valid product files for every
attenuation name and mode, plus ``temperature-sources.json``. It also records
its environment (``env.json``) so tests can check nothing leaked into it.

Behaviour switches (files the test creates in the job directory):
``sleep``  -- sleep this many seconds first (cancellation / timeout tests)
``fail``   -- exit with status 3 after printing to stderr
"""
import json
import os
import struct
import sys
import time
import tomllib
from pathlib import Path

MODES = ("conductivity", "pure-ice")


def pmtiles(lat=-75.0) -> bytes:
    header = bytearray(127)
    header[:7] = b"PMTiles"
    header[7] = 3
    # root dir at 127 (len 10), metadata, leaf, tile data at 137 (len 20)
    struct.pack_into("<11Q", header, 8, 127, 10, 137, 0, 0, 0, 137, 20, 1, 1, 1)
    header[96:102] = bytes([1, 2, 2, 1, 0, 4])
    struct.pack_into("<4i", header, 102, int(-120e7), int(-80e7), int(-100e7), int(lat * 1e7))
    return bytes(header) + b"\0" * 30


def main() -> int:
    cwd = Path.cwd()
    (cwd / "env.json").write_text(json.dumps(dict(os.environ)))
    if (cwd / "sleep").exists():
        time.sleep(float((cwd / "sleep").read_text()))
    if (cwd / "fail").exists():
        print("simulated LIVIST failure", file=sys.stderr)
        return 3
    config = tomllib.loads((cwd / "config.toml").read_text())
    data = cwd / config["data_directory"]
    names = list(config["attenuation_paths"])
    for name in names:
        staged = data / config["attenuation_paths"][name]
        print(f"input {name}: {'present' if staged.exists() else 'download'}")
        if not staged.exists():              # like LIVIST: fetch a missing input
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text("x,y,atten_rate_C0\n" + "1,2,5.4\n" * 1000)
        for mode in MODES:
            stem = data / f"temperature-{name}-{mode}"
            for suffix in (".parquet", "-wgs84.parquet"):
                Path(f"{stem}{suffix}").write_bytes(b"PAR1" + os.urandom(16) + b"PAR1")
            Path(f"{stem}.fgb").write_bytes(b"fgb\x03fgb\x01" + b"\0" * 16)
            Path(f"{stem}.pmtiles").write_bytes(pmtiles())
    public = cwd / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    (public / "temperature-sources.json").write_text(json.dumps(
        {m: [{"name": n, "url": f"https://example.invalid/{n}-{m}.pmtiles"} for n in names]
         for m in MODES}))
    print("x" * 5000)       # some bulk output for the bounded log
    return 0


if __name__ == "__main__":
    sys.exit(main())
