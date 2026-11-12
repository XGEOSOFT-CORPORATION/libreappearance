"""Build the Aura ribbons (Tabbed Compact notebookbar) for Writer, Calc, Impress and Draw.

Starts from the notebookbar_compact.ui shipped with the installed LibreOffice,
renames tabs per language and hides rarely used buttons of the Home tab, as
described in design/ribbon.json. Then checks feature coverage: every command
the stock ribbon shows must still be in the new ribbon (in another tab or in a
tab's drop-down menu). The build fails otherwise, so no feature can be lost.
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from tokens import ROOT

LANGS = ("fr", "en")
TAB_CONTROL = "sfxlo-NotebookbarTabControl"


def commands(element, visible_only=False):
    """.uno: commands under element (optionally skipping hidden widgets)."""
    out = set()

    def walk(e, hidden):
        if e.tag == "object":
            vis = next((p for p in e.findall("property") if p.get("name") == "visible"), None)
            hidden = hidden or (vis is not None and vis.text == "False")
            for p in e.findall("property"):
                if p.get("name") in ("action_name", "action-name") and (p.text or "").startswith(".uno:"):
                    if not (visible_only and hidden):
                        out.add(p.text)
        for child in e:
            walk(child, hidden)

    walk(element, False)
    return out


def tab_pages(root):
    """{label id: page element} of the notebookbar tabs."""
    control = next(o for o in root.iter("object") if o.get("class") == TAB_CONTROL)
    kids = control.findall("child")
    pages = {}
    for page, tab in zip(kids[0::2], kids[1::2]):
        label = next(tab.iter("object"))
        pages[label.get("id")] = page
    return pages


def set_visible(obj, value):
    prop = next((p for p in obj.findall("property") if p.get("name") == "visible"), None)
    if prop is None:
        prop = ET.SubElement(obj, "property", name="visible")
    prop.text = value


def build(lo_cfg, module, spec, lang, out_dir):
    src = lo_cfg / "modules" / module / "ui" / "notebookbar_compact.ui"
    tree = ET.parse(src)
    root = tree.getroot()
    original = commands(root, visible_only=True)  # what the stock ribbon actually shows

    labels = spec.get("labels", {}).get(lang, {})
    for prop in root.iter("property"):
        key = (prop.get("context") or "").rpartition("|")[2]
        if prop.get("name") == "label" and key in labels:
            prop.text = labels[key]

    home = tab_pages(root)[spec["home"]]
    hide = set(spec["hide"])
    hidden = 0
    for obj in home.iter("object"):
        actions = {p.text for p in obj.findall("property") if p.get("name") in ("action_name", "action-name")}
        if actions & hide:
            set_visible(obj, "False")
            hidden += 1

    missing = sorted(original - commands(root, visible_only=True))
    if missing:
        raise SystemExit(f"{module}: features would leave the ribbon: {', '.join(missing)}")

    out = out_dir / lang / module / "ui" / "notebookbar_compact.ui"
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    print(f"ribbon[{lang}/{module}] {hidden} buttons tidied, all {len(original)} commands kept")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-cfg", default="/usr/lib/libreoffice/share/config/soffice.cfg")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    spec = json.loads((ROOT / "design" / "ribbon.json").read_text(encoding="utf-8"))
    for module, mspec in spec["modules"].items():
        for lang in LANGS:
            build(Path(args.lo_cfg), module, mspec, lang, Path(args.out))


if __name__ == "__main__":
    main()
