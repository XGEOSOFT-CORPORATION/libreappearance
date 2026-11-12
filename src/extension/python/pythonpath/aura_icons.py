"""Aura icon themes: LibreOffice's Colibre SVG icons re-coloured with the Aura palette.

Shared by the build (tools/build_icons.py) and the extension, which rebuilds
the themes from the installed LibreOffice after an update so that new
commands get Aura icons too. Standard library only.
"""
import colorsys
import os
import re
import tempfile
import zipfile

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



def build_all(tokens, lo_config, out_dir):
    """Write every variant of tokens['icons'] into out_dir (atomically, file by file)."""
    os.makedirs(out_dir, exist_ok=True)
    built = []
    for variant, spec in tokens["icons"].items():
        source = os.path.join(lo_config, spec["source"])
        if not os.path.exists(source):
            continue
        fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
        os.close(fd)
        try:
            build_theme(source, tmp, Recolorer(tokens["ramps"], spec["overrides"]))
            os.replace(tmp, os.path.join(out_dir, spec["target"]))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        built.append(spec["target"])
    return built
