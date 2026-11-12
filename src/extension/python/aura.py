"""Aura UNO component: Tools > Aura > Apply (light/dark) / Restore.

Applying Aura writes a handful of user settings (icon theme, application
colours, compact tabbed UI, default templates). The previous values are
saved to $(user)/libreappearance/backup.json first, so Restore puts the
profile back exactly as it was.

It also places files: the Aura ribbons in the profile's soffice.cfg and, on
Linux, the Aura GTK theme plus launchers that start LibreOffice with it.
Every file created or replaced is listed in $(user)/libreappearance/files.json
(replaced files are kept aside) so Restore removes or puts back each one.
"""
import json
import os
import re
import shutil
import sys

import uno
import unohelper
from com.sun.star.beans import PropertyValue
from com.sun.star.task import XJobExecutor

EXTENSION_ID = "org.libreappearance.aura"
IMPLEMENTATION = "org.libreappearance.aura.Aura"

VARIANTS = {
    "light": {"icons": "aura_svg", "scheme": "Aura Light"},
    "dark": {"icons": "aura_dark_svg", "scheme": "Aura Dark"},
}
VARIANTS["light"]["gtk"], VARIANTS["dark"]["gtk"] = "Aura", "Aura-dark"

RIBBON_MODULES = ("swriter", "scalc", "simpress", "sdraw")
LAUNCHERS = ("startcenter", "writer", "calc", "impress", "draw", "math", "base")

# module -> (ToolbarMode suffix, Applications node, WindowState package)
MODULES = {
    "com.sun.star.text.TextDocument": ("Writer", "Writer", "WriterWindowState"),
    "com.sun.star.sheet.SpreadsheetDocument": ("Calc", "Calc", "CalcWindowState"),
    "com.sun.star.presentation.PresentationDocument": ("Impress", "Impress", "ImpressWindowState"),
    "com.sun.star.drawing.DrawingDocument": ("Draw", "Draw", "DrawWindowState"),
}
# Applications/<App>/Active holds the mode's CommandArg, which is also the
# argument of the .uno:ToolbarMode dispatch.
UI_MODE = "notebookbar_compact.ui"

# document service -> template shipped in the extension
TEMPLATES = {
    "com.sun.star.text.TextDocument": "aura-document.ott",
    "com.sun.star.sheet.SpreadsheetDocument": "aura-classeur.ots",
    "com.sun.star.presentation.PresentationDocument": "aura-presentation.otp",
}

MESSAGES = {
    "fr": {
        "applied": "Aura est appliqué.\n\nFermez complètement LibreOffice puis relancez-le depuis le "
                   "menu des applications : l'interface, les icônes et le ruban Aura s'afficheront "
                   "partout.\nOutils ▸ Aura ▸ Restaurer pour revenir en arrière.",
        "restored": "L'apparence d'origine est restaurée.\n\nRedémarrez LibreOffice pour finaliser.",
        "nobackup": "Aucune sauvegarde Aura à restaurer : l'apparence d'origine est déjà en place.",
        "error": "Aura n'a pas pu terminer l'opération.",
    },
    "en": {
        "applied": "Aura is applied.\n\nQuit LibreOffice completely and start it again from the "
                   "applications menu: the Aura interface, icons and ribbon will show everywhere.\n"
                   "Use Tools ▸ Aura ▸ Restore to undo.",
        "restored": "The original appearance is restored.\n\nRestart LibreOffice to finish.",
        "nobackup": "No Aura backup to restore: the original appearance is already in place.",
        "error": "Aura could not complete the operation.",
    },
}


def _props(**kw):
    out = []
    for k, v in kw.items():
        p = PropertyValue()
        p.Name, p.Value = k, v
        out.append(p)
    return tuple(out)


class Aura(unohelper.Base, XJobExecutor):
    def __init__(self, ctx):
        self.ctx = ctx
        self.smgr = ctx.ServiceManager

    # ---------------------------------------------------------------- helpers
    def _create(self, name):
        return self.smgr.createInstanceWithContext(name, self.ctx)

    def _config(self, path, update=False):
        provider = self._create("com.sun.star.configuration.ConfigurationProvider")
        service = ("com.sun.star.configuration.ConfigurationUpdateAccess" if update
                   else "com.sun.star.configuration.ConfigurationAccess")
        return provider.createInstanceWithArguments(service, _props(nodepath=path))

    def _get(self, path, name):
        return self._config(path).getPropertyValue(name)

    def _set(self, path, values):
        node = self._config(path, update=True)
        for name, value in values.items():
            node.setPropertyValue(name, value)
        node.commitChanges()

    def _expand(self, url):
        return self._create("com.sun.star.util.PathSubstitution").substituteVariables(url, True)

    def _backup_url(self):
        return self._expand("$(user)/libreappearance/backup.json")

    def _lang(self):
        locale = self._get("/org.openoffice.Setup/L10N", "ooLocale") or ""
        return "fr" if locale.startswith("fr") else "en"

    def _message(self, key, detail=""):
        text = MESSAGES[self._lang()][key] + (f"\n\n{detail}" if detail else "")
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            print(f"Aura: {text}")
            return
        window = frame.getContainerWindow()
        toolkit = self._create("com.sun.star.awt.Toolkit")
        box = toolkit.createMessageBox(
            window, uno.Enum("com.sun.star.awt.MessageBoxType",
                             "ERRORBOX" if key == "error" else "INFOBOX"), 1, "Aura", text)
        box.execute()

    # ------------------------------------------------------------ state I/O
    def _toolbar_states(self, package):
        """{resource_url: Visible} for every toolbar of a module."""
        states = self._config(f"/org.openoffice.Office.UI.{package}/UIElements/States")
        out = {}
        for name in states.getElementNames():
            if name.startswith("private:resource/toolbar/"):
                node = states.getByName(name)
                if node.getPropertySetInfo().hasPropertyByName("Visible"):
                    out[name] = bool(node.getPropertyValue("Visible"))
        return out

    def _set_toolbar_states(self, package, visibility):
        states = self._config(f"/org.openoffice.Office.UI.{package}/UIElements/States", update=True)
        for name, visible in visibility.items():
            if states.hasByName(name):
                states.getByName(name).setPropertyValue("Visible", visible)
        states.commitChanges()

    def _snapshot(self):
        snap = {
            "SymbolStyle": self._get("/org.openoffice.Office.Common/Misc", "SymbolStyle"),
            "CurrentColorScheme": self._get("/org.openoffice.Office.UI/ColorScheme", "CurrentColorScheme"),
            "ToolbarMode": {}, "Applications": {}, "Toolbars": {}, "Templates": {},
        }
        for service, (suffix, app, package) in MODULES.items():
            snap["ToolbarMode"][suffix] = self._get("/org.openoffice.Office.UI.ToolbarMode", "Active" + suffix)
            snap["Applications"][app] = self._get(
                f"/org.openoffice.Office.UI.ToolbarMode/Applications/{app}", "Active")
            snap["Toolbars"][package] = self._toolbar_states(package)
        for service in TEMPLATES:
            snap["Templates"][service] = self._get(
                f"/org.openoffice.Setup/Office/Factories/{service}", "ooSetupFactoryTemplateFile")
        return snap

    def _restore_snapshot(self, snap):
        self._set("/org.openoffice.Office.Common/Misc", {"SymbolStyle": snap["SymbolStyle"]})
        self._set("/org.openoffice.Office.UI/ColorScheme", {"CurrentColorScheme": snap["CurrentColorScheme"]})
        self._set("/org.openoffice.Office.UI.ToolbarMode",
                  {"Active" + k: v for k, v in snap["ToolbarMode"].items()})
        for app, mode in snap["Applications"].items():
            self._set(f"/org.openoffice.Office.UI.ToolbarMode/Applications/{app}", {"Active": mode})
        for package, visibility in snap["Toolbars"].items():
            self._set_toolbar_states(package, visibility)
        for service, url in snap["Templates"].items():
            self._set(f"/org.openoffice.Setup/Office/Factories/{service}",
                      {"ooSetupFactoryTemplateFile": url})

    # --------------------------------------------------------------- actions
    def _install_templates(self):
        """Copy the templates to the user profile (stable path across reinstalls)."""
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = pip.getPackageLocation(EXTENSION_ID)
        sfa = self._create("com.sun.star.ucb.SimpleFileAccess")
        target = self._expand("$(user)/libreappearance/templates")
        if not sfa.isFolder(target):
            sfa.createFolder(target)
        out = {}
        for service, name in TEMPLATES.items():
            src = f"{root}/templates/Aura/{name}"
            if not sfa.exists(src):
                continue
            dst = f"{target}/{name}"
            if sfa.exists(dst):
                sfa.kill(dst)
            sfa.copy(src, dst)
            out[service] = dst
        return out

    # ------------------------------------------------------- placed files
    def _system(self, url):
        return uno.fileUrlToSystemPath(url)

    def _manifest_path(self):
        return os.path.join(self._system(self._expand("$(user)")), "libreappearance", "files.json")

    def _load_manifest(self):
        try:
            with open(self._manifest_path(), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"created": [], "replaced": {}}

    def _place(self, manifest, dst, write):
        """Write dst through write(path), recording it so restore can undo it."""
        known = dst in manifest["created"] or dst in manifest["replaced"]
        if not known:
            if os.path.lexists(dst):
                keep = os.path.join(os.path.dirname(self._manifest_path()), "replaced",
                                    str(len(manifest["replaced"])))
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.move(dst, keep)
                manifest["replaced"][dst] = keep
            else:
                manifest["created"].append(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        write(dst)

    def _install_files(self, spec):
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = self._system(pip.getPackageLocation(EXTENSION_ID))
        manifest = self._load_manifest()
        user = self._system(self._expand("$(user)"))

        lang = self._lang()
        for module in RIBBON_MODULES:
            src = os.path.join(root, "ui", lang, module, "ui", "notebookbar_compact.ui")
            if os.path.exists(src):
                dst = os.path.join(user, "config", "soffice.cfg", "modules", module, "ui",
                                   "notebookbar_compact.ui")
                self._place(manifest, dst, lambda d, s=src: shutil.copyfile(s, d))

        if sys.platform.startswith("linux"):
            data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            for name in ("Aura", "Aura-dark"):
                src = os.path.join(root, "gtk", name)
                self._place(manifest, os.path.join(data_home, "themes", name),
                            lambda d, s=src: shutil.copytree(s, d))
            for launcher in LAUNCHERS:
                self._place_launcher(manifest, data_home, f"libreoffice-{launcher}.desktop", spec["gtk"])

        os.makedirs(os.path.dirname(self._manifest_path()), exist_ok=True)
        with open(self._manifest_path(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _place_launcher(self, manifest, data_home, name, theme):
        """User-level copy of a LibreOffice .desktop file that starts it with the Aura GTK theme."""
        dst = os.path.join(data_home, "applications", name)
        source = manifest["replaced"].get(dst) or (dst if os.path.exists(dst) and dst not in
                                                   manifest["created"] else None)
        if source is None:
            dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
            source = next((os.path.join(d, "applications", name) for d in dirs
                           if os.path.exists(os.path.join(d, "applications", name))), None)
        if source is None:
            return
        with open(source, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"^Exec=(?:env GTK_THEME=\S+ )?", f"Exec=env GTK_THEME={theme} ", text, flags=re.M)

        def write(d):
            with open(d, "w", encoding="utf-8") as f:
                f.write(text)
        self._place(manifest, dst, write)

    def _remove_files(self):
        manifest = self._load_manifest()
        for path in manifest["created"]:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                os.remove(path)
        for path, keep in manifest["replaced"].items():
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                os.remove(path)
            if os.path.lexists(keep):
                shutil.move(keep, path)
        if os.path.exists(self._manifest_path()):
            os.remove(self._manifest_path())

    def _switch_current_frame(self, mode):
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            return
        helper = self._create("com.sun.star.frame.DispatchHelper")
        helper.executeDispatch(frame, ".uno:ToolbarMode", "", 0, _props(Mode=mode))

    def apply(self, variant):
        sfa = self._create("com.sun.star.ucb.SimpleFileAccess")
        backup = self._backup_url()
        if not sfa.exists(backup):   # keep the very first snapshot: it is the user's original look
            data = json.dumps(self._snapshot(), indent=2).encode("utf-8")
            pipe = self._create("com.sun.star.io.Pipe")
            pipe.writeBytes(uno.ByteSequence(data))
            pipe.closeOutput()
            sfa.writeFile(backup, pipe)

        self._switch_current_frame(UI_MODE)
        spec = VARIANTS[variant]
        self._set("/org.openoffice.Office.Common/Misc", {"SymbolStyle": spec["icons"]})
        self._set("/org.openoffice.Office.UI/ColorScheme", {"CurrentColorScheme": spec["scheme"]})
        for service, (suffix, app, package) in MODULES.items():
            self._set("/org.openoffice.Office.UI.ToolbarMode", {"Active" + suffix: UI_MODE})
            self._set(f"/org.openoffice.Office.UI.ToolbarMode/Applications/{app}", {"Active": UI_MODE})
            self._set_toolbar_states(package, {k: False for k in self._toolbar_states(package)})
        for service, url in self._install_templates().items():
            self._set(f"/org.openoffice.Setup/Office/Factories/{service}",
                      {"ooSetupFactoryTemplateFile": url})
        self._install_files(spec)
        self._message("applied")

    def restore(self):
        sfa = self._create("com.sun.star.ucb.SimpleFileAccess")
        backup = self._backup_url()
        if not sfa.exists(backup):
            self._message("nobackup")
            return
        stream = sfa.openFileRead(backup)
        chunks = []
        while True:
            n, data = stream.readBytes(None, 65536)
            if n == 0:
                break
            chunks.append(bytes(data.value))
        stream.closeInput()
        snap = json.loads(b"".join(chunks).decode("utf-8"))

        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is not None:
            module = self._create("com.sun.star.frame.ModuleManager").identify(frame)
            if module in MODULES:
                self._switch_current_frame(snap["Applications"].get(MODULES[module][1], "Default"))
        self._restore_snapshot(snap)
        self._remove_files()
        sfa.kill(backup)
        self._message("restored")

    # ----------------------------------------------------------- XJobExecutor
    def trigger(self, arg):
        try:
            if arg == "apply_light":
                self.apply("light")
            elif arg == "apply_dark":
                self.apply("dark")
            elif arg == "restore":
                self.restore()
        except Exception as e:  # never let an error take the office down
            self._message("error", detail=str(e))


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(Aura, IMPLEMENTATION, (IMPLEMENTATION,))
