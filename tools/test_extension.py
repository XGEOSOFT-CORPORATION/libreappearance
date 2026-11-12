"""Smoke-test dist/Aura-*.oxt in a throw-away LibreOffice profile.

Installs the extension with unopkg, starts a headless office and checks that
icon themes, colour schemes and templates are registered, then runs
Apply (light) and Restore through the Aura service and compares settings.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_templates as bt  # noqa: E402  (provides the Office helper)

FAILURES = []


def check(label, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {label}{' — ' + str(detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main():
    oxt = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "dist" / "Aura-*.oxt")))[-1]
    profile = Path(tempfile.mkdtemp(prefix="aura-test-"))
    env = f"-env:UserInstallation={profile.as_uri()}"
    r = subprocess.run(["unopkg", "add", "--suppress-license", env, oxt], capture_output=True, text=True)
    check("unopkg add", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])

    data_home = profile / "xdg-data"           # never touch the real ~/.local/share
    os.environ["XDG_DATA_HOME"] = str(data_home)
    office = bt.Office(shutil.which("soffice"), profile)
    try:
        ctx = office.ctx
        smgr = ctx.ServiceManager

        def cfg(path):
            provider = smgr.createInstanceWithContext("com.sun.star.configuration.ConfigurationProvider", ctx)
            return provider.createInstanceWithArguments(
                "com.sun.star.configuration.ConfigurationAccess", bt.props(nodepath=path))

        paths = smgr.createInstanceWithContext("com.sun.star.util.PathSettings", ctx)
        iconset = paths.getPropertyValue("Iconset_internal")
        check("icon themes path registered", any("iconsets" in p for p in iconset), iconset)
        templates = paths.getPropertyValue("Template_internal")
        check("templates path registered", any("templates" in p for p in templates))

        schemes = cfg("/org.openoffice.Office.UI/ColorScheme/ColorSchemes").getElementNames()
        check("colour schemes registered", {"Aura Light", "Aura Dark"} <= set(schemes), schemes)

        def snapshot():
            return (cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("SymbolStyle"),
                    cfg("/org.openoffice.Office.UI/ColorScheme").getPropertyValue("CurrentColorScheme"),
                    cfg("/org.openoffice.Office.UI.ToolbarMode/Applications/Writer").getPropertyValue("Active"),
                    cfg("/org.openoffice.Setup/Office/Factories/com.sun.star.text.TextDocument")
                    .getPropertyValue("ooSetupFactoryTemplateFile"))

        before = snapshot()
        aura = smgr.createInstanceWithContext("org.libreappearance.aura.Aura", ctx)
        check("Aura service instantiates", aura is not None)
        aura.trigger("apply_light")
        after = snapshot()
        check("apply: icon theme", after[0] == "aura_svg", after[0])
        check("apply: colour scheme", after[1] == "Aura Light", after[1])
        check("apply: tabbed compact UI", after[2] == "notebookbar_compact.ui", after[2])
        check("apply: default Writer template", after[3].endswith("aura-document.ott"), after[3])
        sfa = smgr.createInstanceWithContext("com.sun.star.ucb.SimpleFileAccess", ctx)
        check("apply: template copied", sfa.exists(after[3]))

        ribbon = profile / "user/config/soffice.cfg/modules/swriter/ui/notebookbar_compact.ui"
        check("apply: Aura ribbon placed in profile", ribbon.exists())
        xml = ribbon.read_text(encoding="utf-8") if ribbon.exists() else ""
        check("apply: Extensions tab has Manage and Aura groups",
              "PackageManagerDialog" in xml and "org.libreappearance.aura.Aura?apply_dark" in xml
              and "NotebookBarAddonsToolMergePoint" not in xml)
        check("apply: Aura tab labels localised (no msgid left)",
              'context="STR_TOX_AUTH"' not in xml and ">_Arrange<" not in xml)
        for path, name, value in (("/org.openoffice.Office.Common/Misc", "ShowTipOfTheDay", False),
                                  ("/org.openoffice.Office.Common/Cache/GraphicManager",
                                   "GraphicMemoryLimit", 600000000)):
            got = cfg(path).getPropertyValue(name)
            check(f"apply: light profile {name}", got == value, got)
        check("apply: native light mode (Windows/macOS windows)",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("Appearance") == 1)
        check("apply: Ctrl+V in Writer routed to the faithful table paste",
              "smart_paste" in str(cfg("/org.openoffice.Office.Accelerators/PrimaryKeys/Modules/"
                                       "com.sun.star.text.TextDocument/V_MOD1").getPropertyValue("Command")))
        manifest = json.loads((profile / "user/libreappearance/files.json").read_text())
        manifest.pop("ribbon_state", None)
        (profile / "user/libreappearance/files.json").write_text(json.dumps(manifest))
        aura.execute(())
        check("start-up job regenerates a stale ribbon",
              "ribbon_state" in json.loads((profile / "user/libreappearance/files.json").read_text()))
        check("apply: GTK themes installed", (data_home / "themes/Aura/gtk-3.0/gtk.css").exists()
              and (data_home / "themes/Aura-dark/gtk-3.0/gtk.css").exists())
        launcher = data_home / "applications/libreoffice-writer.desktop"
        check("apply: launcher uses Aura GTK theme",
              launcher.exists() and "Exec=env GTK_THEME=Aura " in launcher.read_text())

        aura.trigger("apply_dark")
        check("apply dark: icon theme", snapshot()[0] == "aura_dark_svg")
        check("apply dark: native dark mode",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("Appearance") == 2)
        text = launcher.read_text()
        check("apply dark: launcher switches to Aura-dark",
              "GTK_THEME=Aura-dark " in text and "GTK_THEME=Aura GTK_THEME" not in text)
        aura.trigger("restore")
        check("restore: settings back to original", snapshot() == before, (before, snapshot()))
        check("restore: native appearance reverted",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("Appearance") == 0)
        check("restore: light profile reverted",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("ShowTipOfTheDay") is True)
        check("restore: ribbon, themes and launchers removed",
              not ribbon.exists() and not (data_home / "themes/Aura").exists() and not launcher.exists())
    finally:
        office.close()
    shutil.rmtree(profile, ignore_errors=True)
    print("\nall checks passed" if not FAILURES else f"\n{len(FAILURES)} check(s) failed")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
