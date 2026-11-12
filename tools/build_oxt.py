"""Assemble build/oxt (static sources + generated assets) into dist/Aura-<version>.oxt."""
import argparse
import shutil
import zipfile
from pathlib import Path

from tokens import ROOT, load_tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default=str(ROOT / "build" / "oxt"))
    ap.add_argument("--dist", default=str(ROOT / "dist"))
    args = ap.parse_args()

    version = load_tokens()["version"]
    stage = Path(args.stage)
    shutil.copytree(ROOT / "src" / "extension", stage, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    desc = stage / "description.xml"
    desc.write_text(desc.read_text(encoding="utf-8").replace("@VERSION@", version), encoding="utf-8")
    shutil.copy(ROOT / "LICENSE", stage / "LICENSE")

    for required in ("iconsets/images_aura_svg.zip", "registry/ColorSchemes.xcu",
                     "templates/Aura/aura-document.ott", "gtk/Aura/gtk-3.0/gtk.css",
                     "ui/fr/swriter/ui/notebookbar_compact.ui"):
        if not (stage / required).exists():
            raise SystemExit(f"missing generated asset: {required} (run `make assets`)")

    out = Path(args.dist) / f"Aura-{version}.oxt"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                # icon theme archives are already compressed
                z.write(f, f.relative_to(stage).as_posix(),
                        zipfile.ZIP_STORED if f.suffix == ".zip" else zipfile.ZIP_DEFLATED)
    print(f"extension -> {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
