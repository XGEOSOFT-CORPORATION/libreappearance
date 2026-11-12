"""Build the Aura ribbons (Tabbed Compact notebookbar) for Writer, Calc, Impress and Draw.

Starts from the notebookbar_compact.ui shipped with the installed LibreOffice
and applies design/ribbon.json: tidier Home tab, and
crowded tabs split into themed tabs so every tool shows without the overflow
chevron. Then checks feature coverage: every command the stock ribbon shows
must still be in the new ribbon. The build fails otherwise, so no feature can
be lost. Labels are finalised at run time by the extension for the UI
language (aura_ribbon.localize), and the Extensions tab is filled with what
the user has installed (aura_ribbon.extensions_page).
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from tokens import ROOT

sys.path.insert(0, str(ROOT / "src" / "extension" / "python" / "pythonpath"))
from aura_ribbon import catalog, commands, localize, split_tab, tab_pages  # noqa: E402

RESOURCE = "/usr/lib/libreoffice/program/resource"


def set_visible(obj, value):
    prop = next((p for p in obj.findall("property") if p.get("name") == "visible"), None)
    if prop is None:
        prop = ET.SubElement(obj, "property", name="visible")
    prop.text = value


def build(lo_cfg, module, spec, out_dir):
    src = lo_cfg / "modules" / module / "ui" / "notebookbar_compact.ui"
    tree = ET.parse(src)
    root = tree.getroot()
    fixes = spec.get("fix", {})
    for prop in root.iter("property"):
        if prop.get("name") in ("action_name", "action-name") and prop.text in fixes:
            prop.text = fixes[prop.text]
    # what the stock ribbon actually shows (dead stock commands count as their fixed equivalent)
    original = {fixes.get(c, c) for c in commands(ET.parse(src).getroot(), visible_only=True)}

    home = tab_pages(root)[spec["home"]]
    hide = set(spec["hide"])
    hidden = 0
    for obj in home.iter("object"):
        actions = {p.text for p in obj.findall("property") if p.get("name") in ("action_name", "action-name")}
        if actions & hide:
            set_visible(obj, "False")
            hidden += 1

    new_tabs = []
    for split in spec.get("split", []):
        if "id" in split:
            split_tab(root, split["from"], split["id"], split["label"], split["sections"],
                      split.get("drop", ()))
            new_tabs.append(split["label"][1].replace("~", "").replace("_", ""))
        else:
            split_tab(root, split["from"], None, None, (), split["drop"])

    missing = sorted(original - commands(root, visible_only=True))
    if missing:
        raise SystemExit(f"{module}: features would leave the ribbon: {', '.join(missing)}")

    # every Aura tab label must exist in LibreOffice's catalog (checked with French)
    cat = catalog(RESOURCE, "fr", {"swriter": "sw", "scalc": "sc"}.get(module, "sd"))
    if cat:
        for obj in root.iter("object"):
            label = next((p for p in obj.findall("property") if p.get("name") == "label"), None)
            if (obj.get("id") or "").startswith("Aura") and label is not None:
                if cat.pgettext(label.get("context"), label.text) == label.text:
                    raise SystemExit(f"{module}: label {label.text!r} has no LibreOffice translation")

    out = out_dir / module / "ui" / "notebookbar_compact.ui"
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    print(f"ribbon[{module}] {hidden} buttons tidied, new tabs: {', '.join(new_tabs) or '-'};"
          f" all {len(original)} commands kept")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-cfg", default="/usr/lib/libreoffice/share/config/soffice.cfg")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    spec = json.loads((ROOT / "design" / "ribbon.json").read_text(encoding="utf-8"))
    for module, mspec in spec["modules"].items():
        build(Path(args.lo_cfg), module, mspec, Path(args.out))
    # per-language corrections of stock labels, applied at run time by the extension
    overrides = {m: ms.get("labels", {}) for m, ms in spec["modules"].items()}
    (Path(args.out) / "overrides.json").write_text(json.dumps(overrides, ensure_ascii=False, indent=1),
                                                   encoding="utf-8")


if __name__ == "__main__":
    main()
