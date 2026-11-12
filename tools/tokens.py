"""Shared helpers: load design/tokens.json and convert colours for LibreOffice."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_tokens():
    return json.loads((ROOT / "design" / "tokens.json").read_text(encoding="utf-8"))


def lo_color(hexstr):
    """'#RRGGBB' -> LibreOffice's integer colour (0xRRGGBB)."""
    return int(hexstr.lstrip("#"), 16)
