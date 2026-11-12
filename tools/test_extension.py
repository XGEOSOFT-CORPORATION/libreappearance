"""Smoke-test dist/Aura-*.oxt in a throw-away LibreOffice profile (Linux, Windows, macOS).

Installs the extension with unopkg, starts a headless office and checks that
icon themes, colour schemes and templates are registered, then runs
Apply (light) and Restore through the Aura service and compares settings.
Run it with a Python that can import uno (LibreOffice's own on Windows/macOS);
$AURA_SOFFICE points to soffice when it is not found automatically.
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
import build_templates as bt  # noqa: E402
import uno  # noqa: E402  (provides the Office helper)

FAILURES = []
LINUX = sys.platform.startswith("linux")


def check(label, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {label}{' — ' + str(detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def main():
    oxt = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "dist" / "Aura-*.oxt")))[-1]
    profile = Path(tempfile.mkdtemp(prefix="aura-test-"))
    env = f"-env:UserInstallation={profile.as_uri()}"
    r = subprocess.run([bt.find_unopkg(), "add", "--suppress-license", env, oxt],
                       capture_output=True, text=True)
    check("unopkg add", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])

    data_home = profile / "xdg-data"           # never touch the real ~/.local/share
    os.environ["XDG_DATA_HOME"] = str(data_home)
    office = bt.Office(bt.find_office(), profile)
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
        # another LibreOffice profile already applied Aura: its launcher is shared
        other = data_home / "applications/libreoffice-calc.desktop"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("[Desktop Entry]\nExec=env GTK_THEME=Aura-dark libreoffice --calc %U\n")
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
              "PackageManagerDialog" in xml and "org.libreappearance.aura.Aura?panel" in xml
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
        files = profile / "user/libreappearance/files.json"
        manifest = json.loads(files.read_text())
        check("ribbons built from the installed LibreOffice for every module",
              manifest.get("ribbon_skipped") == [], manifest.get("ribbon_skipped"))
        manifest.pop("ribbon_state", None)
        files.write_text(json.dumps(manifest))
        aura.execute(())
        check("start-up job regenerates a stale ribbon", "ribbon_state" in json.loads(files.read_text()))
        for module in ("com.sun.star.text.TextDocument", "com.sun.star.sheet.SpreadsheetDocument",
                       "com.sun.star.presentation.PresentationDocument"):
            keys = cfg(f"/org.openoffice.Office.Accelerators/PrimaryKeys/Modules/{module}")
            bound = keys.hasByName("SPACE_MOD1_MOD2") and "dictation" in str(
                keys.getByName("SPACE_MOD1_MOD2").getPropertyValue("Command"))
            check(f"start-up job: Ctrl+Alt+Space starts dictation ({module.split('.')[-1]})", bound)
        check("Extensions tab: Aura group has Dictation", "Aura?dictation" in ribbon.read_text(encoding="utf-8"))

        # icons are rebuilt from the installed Colibre after a LibreOffice update
        pip = office.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        ext = Path(uno.fileUrlToSystemPath(pip.getPackageLocation("org.libreappearance.aura")))
        (ext / "iconsets/built-for.txt").write_text("23.0.0.0")
        aura.execute(())
        check("icon themes rebuilt after a LibreOffice version change",
              (ext / "iconsets/built-for.txt").read_text() != "23.0.0.0"
              and (ext / "iconsets/images_aura_svg.zip").stat().st_size > 1000000)

        # security: a tampered files.json cannot make Restore delete other files
        bait = profile / "bait.txt"
        bait.write_text("user data")
        manifest = json.loads(files.read_text())
        manifest["created"].append(str(bait))
        manifest["replaced"][str(profile / "user" / "registrymodifications.xcu")] = str(bait)
        files.write_text(json.dumps(manifest))

        # robustness: corrupt preferences fall back to defaults
        prefs_file = profile / "user/libreappearance/settings.json"
        prefs_file.write_text('{"theme": "rm -rf", "graphic_cache": "huge", "layout": 42, "smart_paste": true}')
        launcher = data_home / "applications/libreoffice-writer.desktop"
        if LINUX:
            check("apply: GTK themes installed", (data_home / "themes/Aura/gtk-3.0/gtk.css").exists()
                  and (data_home / "themes/Aura-dark/gtk-3.0/gtk.css").exists())
            check("apply: launcher uses Aura GTK theme",
                  launcher.exists() and "Exec=env GTK_THEME=Aura " in launcher.read_text())
        else:
            check("apply: no GTK theme nor launcher outside Linux",
                  not (data_home / "themes/Aura").exists() and not launcher.exists())
        fonts = [Path(p) for p in json.loads(files.read_text())["created"] if p.endswith(".otf")]
        installed_fonts = [f for f in fonts if f.exists()]
        check("apply: Inter available (installed for the user when missing)",
              installed_fonts or not fonts, [str(f) for f in fonts][:2])

        aura.trigger("apply_dark")
        check("corrupt preferences: apply still works with safe defaults",
              cfg("/org.openoffice.Office.Common/Cache/GraphicManager").getPropertyValue("GraphicMemoryLimit")
              == 600000000)
        check("apply dark: icon theme", snapshot()[0] == "aura_dark_svg")
        check("apply dark: native dark mode",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("Appearance") == 2)
        if LINUX:
            text = launcher.read_text()
            check("apply dark: launcher switches to Aura-dark",
                  "GTK_THEME=Aura-dark " in text and "GTK_THEME=Aura GTK_THEME" not in text)
        aura.trigger("restore")
        check("security: files outside Aura's own places are never deleted",
              bait.exists() and (profile / "user" / "registrymodifications.xcu").exists())
        check("restore: settings back to original", snapshot() == before, (before, snapshot()))
        check("restore: Ctrl+V back to LibreOffice's paste",
              str(cfg("/org.openoffice.Office.Accelerators/PrimaryKeys/Modules/"
                      "com.sun.star.text.TextDocument/V_MOD1").getPropertyValue("Command")) == ".uno:Paste")
        check("restore: native appearance reverted",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("Appearance") == 0)
        check("restore: light profile reverted",
              cfg("/org.openoffice.Office.Common/Misc").getPropertyValue("ShowTipOfTheDay") is True)
        if LINUX:
            check("two profiles: another profile's Aura launcher is never claimed nor removed",
                  other.exists() and "GTK_THEME=Aura" in other.read_text())
        check("restore: ribbon, themes and launchers removed",
              not ribbon.exists() and not (data_home / "themes/Aura").exists() and not launcher.exists())
        check("restore: fonts Aura installed are removed", not any(f.exists() for f in installed_fonts))
    finally:
        office.close()
    shutil.rmtree(profile, ignore_errors=True)
    print("\nall checks passed" if not FAILURES else f"\n{len(FAILURES)} check(s) failed")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
