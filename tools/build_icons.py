"""Build the Aura icon themes by re-colouring LibreOffice's Colibre SVG theme.

Every colour found in the source SVGs is mapped onto the Aura palette:
explicit overrides first, then the nearest shade (by lightness) of the ramp
whose hue family matches. Shapes are untouched, so coverage is complete
(every command, dialog and sidebar icon of the installed LibreOffice).

Colibre is licensed CC BY-SA 4.0; the derived themes keep that licence.
"""
import argparse
import colorsys
import re
import zipfile
from pathlib import Path

from tokens import load_tokens

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")


def to_rgb(hexstr):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lightness(hexstr):
    return colorsys.rgb_to_hls(*to_rgb(hexstr))[1]


def family_for(hue_deg, sat):
    if sat < 0.15:
        return "slate"
    if hue_deg < 18 or hue_deg >= 330:
        return "rose"
    if hue_deg < 60:
        return "amber"
    if hue_deg < 170:
        return "emerald"
    if hue_deg < 195:
        return "sky"
    if hue_deg < 255:
        return "indigo"
    return "violet"


class Recolorer:
    def __init__(self, ramps, overrides):
        self.ramps = ramps
        self.overrides = {k.lower(): v for k, v in overrides.items()}
        self.cache = {}

    def map(self, hexstr):
        key = "#" + hexstr.lower().lstrip("#")
        if len(key) == 4:
            key = "#" + "".join(c * 2 for c in key[1:])
        if key in self.overrides:
            return self.overrides[key]
        if key not in self.cache:
            h, l, s = colorsys.rgb_to_hls(*to_rgb(key))
            if l > 0.97 or l < 0.03:   # pure white / black: keep contrast anchors
                self.cache[key] = key.upper()
            else:
                ramp = self.ramps[family_for(h * 360, s)]
                self.cache[key] = min(ramp, key=lambda c: abs(lightness(c) - l))
        return self.cache[key]

    def svg(self, text):
        text = HEX.sub(lambda m: self.map(m.group(0)), text)
        return RGB.sub(lambda m: self.map("#%02x%02x%02x" % tuple(int(g) for g in m.groups())), text)


def build_theme(src_zip, dst_zip, recolorer):
    with zipfile.ZipFile(src_zip) as src, zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename.endswith(".svg"):
                data = recolorer.svg(data.decode("utf-8")).encode("utf-8")
            dst.writestr(info.filename, data)
    return dst_zip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-config", default="/usr/lib/libreoffice/share/config",
                    help="directory holding LibreOffice's images_*.zip")
    ap.add_argument("--out", required=True, help="output iconsets directory")
    args = ap.parse_args()

    tokens = load_tokens()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for variant, spec in tokens["icons"].items():
        rec = Recolorer(tokens["ramps"], spec["overrides"])
        dst = build_theme(Path(args.lo_config) / spec["source"], out / spec["target"], rec)
        print(f"icons[{variant}] -> {dst} ({len(rec.cache)} derived colours)")


if __name__ == "__main__":
    main()
