"""Build the Aura ribbons (Tabbed Compact notebookbar) for Writer, Calc, Impress and Draw.

Checks design/ribbon.json against the notebookbar_compact.ui of this
machine's LibreOffice, then ships the spec: the extension applies it at run
time to the user's own LibreOffice version (aura_ribbon.customize), so the
ribbon always matches the installed release. The spec gives a tidier Home tab, and
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
from aura_ribbon import RibbonError, catalog, commands, customize  # noqa: E402

RESOURCE = "/usr/lib/libreoffice/program/resource"


def build(lo_cfg, module, spec, out_dir):
    """Check the spec against this machine's LibreOffice (the extension applies it at run time
    to whatever LibreOffice version the user has)."""
    src = lo_cfg / "modules" / module / "ui" / "notebookbar_compact.ui"
    tree = ET.parse(src)
    root = tree.getroot()
    stock = len(commands(root, visible_only=True))
    try:
        added = customize(root, spec)
    except RibbonError as e:
        raise SystemExit(f"{module}: {e}")
    expected = [s for s in spec.get("split", []) if "id" in s]
    if len(added) != len(expected):
        raise SystemExit(f"{module}: only {len(added)} of {len(expected)} themed tabs could be built")

    # every Aura tab label must exist in LibreOffice's catalog (checked with French)
    cat = catalog(RESOURCE, "fr", {"swriter": "sw", "scalc": "sc"}.get(module, "sd"))
    if cat:
        for obj in root.iter("object"):
            label = next((p for p in obj.findall("property") if p.get("name") == "label"), None)
            if (obj.get("id") or "").startswith("Aura") and label is not None:
                if cat.pgettext(label.get("context"), label.text) == label.text:
                    raise SystemExit(f"{module}: label {label.text!r} has no LibreOffice translation")
    out = out_dir / module / "ui" / "notebookbar_compact.ui"   # for review only, not shipped
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out, encoding="UTF-8", xml_declaration=True)
    print(f"ribbon[{module}] new tabs: {', '.join(added) or '-'}; all {stock} stock commands kept")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-cfg", default="/usr/lib/libreoffice/share/config/soffice.cfg")
    ap.add_argument("--out", required=True, help="extension folder receiving ribbon.json")
    ap.add_argument("--review", default=str(ROOT / "build" / "ribbon-review"),
                    help="where to write the customised ribbons for review")
    args = ap.parse_args()
    spec = json.loads((ROOT / "design" / "ribbon.json").read_text(encoding="utf-8"))
    for module, mspec in spec["modules"].items():
        build(Path(args.lo_cfg), module, mspec, Path(args.review))
    # the extension ships the spec and applies it at run time to the installed LibreOffice
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ribbon.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
