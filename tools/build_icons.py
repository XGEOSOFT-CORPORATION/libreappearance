"""Build the Aura icon themes by re-colouring LibreOffice's Colibre SVG theme.

The logic lives in src/extension/python/pythonpath/aura_icons.py, shared with
the extension (which rebuilds the themes after a LibreOffice update).
Colibre is licensed CC BY-SA 4.0; the derived themes keep that licence.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from tokens import ROOT, load_tokens

sys.path.insert(0, str(ROOT / "src" / "extension" / "python" / "pythonpath"))
from aura_icons import build_all  # noqa: E402


def office_version():
    try:
        out = subprocess.run(["soffice", "--version"], capture_output=True, text=True).stdout
        return out.split()[1]
    except (OSError, IndexError):
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-config", default="/usr/lib/libreoffice/share/config",
                    help="directory holding LibreOffice's images_*.zip")
    ap.add_argument("--out", required=True, help="output iconsets directory")
    args = ap.parse_args()
    for target in build_all(load_tokens(), args.lo_config, args.out):
        print(f"icons -> {Path(args.out) / target}")
    # the extension rebuilds the themes when the user's LibreOffice differs from this one
    (Path(args.out) / "built-for.txt").write_text(office_version(), encoding="utf-8")


if __name__ == "__main__":
    main()
