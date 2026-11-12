"""Check every command of the Aura ribbons against a running LibreOffice.

For each module (Writer, Calc, Impress, Draw) it opens a document, then for
every command the generated ribbon shows (tabs, tab menus, Extensions tab):
  * the frame must return a dispatcher (LibreOffice knows how to run it here);
  * .uno: commands must have a label in LibreOffice's command descriptions
    (so the button shows text / an icon in the UI language).
The same check runs on LibreOffice's stock ribbon: commands that already fail
there (dead entries in the stock ribbon, or commands that need a selection a
hidden document does not have) are reported as baseline, not as Aura errors.
Every command Aura adds (Extensions tab, Manage group) must pass.

Usage: test_commands.py [profile dir]
  Without a profile, dist/Aura-*.oxt is installed and applied in a throw-away
  one (add more extensions to it first to check their Extensions tab).
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import uno

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_templates as bt  # noqa: E402  (Office helper)

MODULES = {
    "swriter": ("swriter", "com.sun.star.text.TextDocument"),
    "scalc": ("scalc", "com.sun.star.sheet.SpreadsheetDocument"),
    "simpress": ("simpress", "com.sun.star.presentation.PresentationDocument"),
    "sdraw": ("sdraw", "com.sun.star.drawing.DrawingDocument"),
}
STOCK = Path("/usr/lib/libreoffice/share/config/soffice.cfg/modules")


def ribbon_commands(path):
    """Visible commands of a ribbon file (tabs + their menus)."""
    root = ET.parse(path).getroot()
    out = set()

    def walk(e, hidden):
        if e.tag == "object":
            vis = next((p for p in e.findall("property") if p.get("name") == "visible"), None)
            hidden = hidden or (vis is not None and vis.text == "False")
            for p in e.findall("property"):
                if p.get("name") in ("action_name", "action-name") and p.text and not hidden:
                    if not p.text.startswith("private:"):
                        out.add(p.text)
        for child in e:
            walk(child, hidden)

    walk(root, False)
    return out


def main():
    throwaway = len(sys.argv) < 2
    if throwaway:
        profile = Path(tempfile.mkdtemp(prefix="aura-cmds-"))
        os.environ["XDG_DATA_HOME"] = str(profile / "xdg-data")   # never touch the real one
        oxt = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "dist" / "Aura-*.oxt")))[-1]
        subprocess.run(["unopkg", "add", "--suppress-license",
                        f"-env:UserInstallation={profile.as_uri()}", oxt], check=True)
    else:
        profile = Path(sys.argv[1])
    office = bt.Office(shutil.which("soffice"), profile)
    office.profile = None  # removed below only when we created it
    if throwaway:
        office.ctx.ServiceManager.createInstanceWithContext(
            "org.libreappearance.aura.Aura", office.ctx).trigger("apply_light")
    smgr = office.ctx.ServiceManager
    transformer = smgr.createInstanceWithContext("com.sun.star.util.URLTransformer", office.ctx)
    descriptions = office.ctx.getByName("/singletons/com.sun.star.frame.theUICommandDescription")
    failures = 0
    try:
        for module, (factory, service) in MODULES.items():
            ribbon = profile / "user/config/soffice.cfg/modules" / module / "ui/notebookbar_compact.ui"
            commands = sorted(ribbon_commands(ribbon))
            stock = ribbon_commands(STOCK / module / "ui/notebookbar_compact.ui")
            doc = office.new(factory)
            frame = doc.getCurrentController().getFrame()
            generic = descriptions.getByName(service)

            def problem(command):
                url = uno.createUnoStruct("com.sun.star.util.URL")
                url.Complete = command
                _ok, url = transformer.parseStrict(url)
                if frame.queryDispatch(url, "", 0) is None:
                    return "no dispatcher"
                if command.startswith(".uno:"):
                    base = command.split("?", 1)[0]
                    if not (generic.hasByName(command) or generic.hasByName(base)):
                        return "no label"
                return None

            results = {c: problem(c) for c in set(commands) | stock}
            baseline = {c for c in stock if results[c]}
            bad = [f"{results[c]}: {c}" for c in commands if results[c] and c not in baseline]
            doc.close(True)
            failures += len(bad)
            added = sorted(set(commands) - stock)
            status = "ok" if not bad else "FAIL"
            print(f"[{status}] {module}: {len(commands)} commands, "
                  f"{len([c for c in commands if not results[c]])} pass, "
                  f"{len([c for c in commands if c in baseline])} already fail in the stock ribbon; "
                  f"{len(added)} added by Aura, all {'pass' if not any(results[c] for c in added) else 'checked'}")
            for line in bad:
                print(f"         {line}")
    finally:
        office.close()
        if throwaway:
            shutil.rmtree(profile, ignore_errors=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
