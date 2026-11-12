"""Aura UNO component: Tools > Aura > Apply (light/dark) / Restore.

Applying Aura writes a handful of user settings (icon theme, application
colours, compact tabbed UI, default templates). The previous values are
saved to $(user)/libreappearance/backup.json first, so Restore puts the
profile back exactly as it was.

It also places files: the Aura ribbons in the profile's soffice.cfg and, on
Linux, the Aura GTK theme plus launchers that start LibreOffice with it.
Every file created or replaced is listed in $(user)/libreappearance/files.json
(replaced files are kept aside) so Restore removes or puts back each one.

The ribbons depend on the UI language (labels come from LibreOffice's own
catalogs) and on the installed extensions (the Extensions tab has one group
per extension). A start-up job regenerates them when either changes.
"""
import json
import os
import re
import shutil
import sys
from urllib.parse import unquote

import uno
import unohelper
from com.sun.star.beans import PropertyValue
from com.sun.star.task import XJob, XJobExecutor

import aura_ribbon  # python/pythonpath/aura_ribbon.py, shared with the build
import aura_table   # python/pythonpath/aura_table.py: faithful table paste

EXTENSION_ID = "org.libreappearance.aura"
IMPLEMENTATION = "org.libreappearance.aura.Aura"

VARIANTS = {
    "light": {"icons": "aura_svg", "scheme": "Aura Light"},
    "dark": {"icons": "aura_dark_svg", "scheme": "Aura Dark"},
}
VARIANTS["light"]["gtk"], VARIANTS["dark"]["gtk"] = "Aura", "Aura-dark"
# LibreOffice's own light/dark mode (Tools > Options > Application Colors), used for the
# windows on Windows and macOS where the GTK theme does not apply: 1 light, 2 dark
VARIANTS["light"]["appearance"], VARIANTS["dark"]["appearance"] = 1, 2
APPEARANCE = ("/org.openoffice.Office.Common/Misc", "Appearance")
FONT_FAMILIES = ("Inter", "Inter Display")

RIBBON_MODULES = ("swriter", "scalc", "simpress", "sdraw")
# ribbon module -> document services whose add-on commands it shows
CONTEXTS = {
    "swriter": ("com.sun.star.text.TextDocument", "com.sun.star.text.GlobalDocument",
                "com.sun.star.text.WebDocument"),
    "scalc": ("com.sun.star.sheet.SpreadsheetDocument",),
    "simpress": ("com.sun.star.presentation.PresentationDocument",),
    "sdraw": ("com.sun.star.drawing.DrawingDocument",),
}
MANAGE_COMMANDS = ("service:com.sun.star.deployment.ui.PackageManagerDialog", ".uno:RunMacro",
                   ".uno:MacroDialog")
AURA_URL = "service:" + "org.libreappearance.aura.Aura?"
CALC_CLASS_ID = "47bbb4cb-ce4c-4e80-a591-42d9ae74950f"  # spreadsheet documents, any UI language
# words dropped from extension names to keep group titles short
NAME_NOISE = re.compile(r"(?i)\b(libre ?office|open ?office|apache|integration|extension|add-?on|for)\b")

# LibreOffice settings Aura changes (from the user's Aura preferences) and Restore puts back
SETTINGS = {
    "/org.openoffice.Office.Common/Misc": ("ShowTipOfTheDay",),
    "/org.openoffice.Office.Common/Cache/GraphicManager": ("GraphicMemoryLimit",),
}

# Aura preferences ($(user)/libreappearance/settings.json), edited in the Aura panel
DEFAULTS = {
    "theme": "light",                       # light | dark
    "icons": "auto",                        # auto (follows the theme) | aura | aura_dark | original
    "layout": "notebookbar_compact.ui",     # a .uno:ToolbarMode argument
    "gtk": True,                            # Linux: Aura GTK theme through the launchers
    "extensions_tab": True,                 # one group per installed extension
    "templates": True,                      # new documents start from the Aura templates
    "smart_paste": True,                    # Ctrl+V in Writer keeps spreadsheet formatting
    "tips": False,                          # Tip of the Day at start-up
    "graphic_cache": 600000000,             # bytes
    "welcomed": False,                      # first-run welcome already shown
    "dictation_language": "auto",           # auto | en | fr | es | ru | ja | yo | zh
    "dictation_model": "auto",              # auto (GPU: large-v3-turbo, CPU: small) | a Whisper size
    "dictation_device": "auto",             # auto | cpu | cuda
    "dictation_yoruba": "whisper",          # whisper | mms (Meta MMS, more accurate, +3 GB)
    "dictation_chinese": "simplified",      # simplified | traditional
    "dictation_commands": True,             # "new paragraph", "virgule", "改行"... are commands
    "dictation_glossary": "",               # names and terms the recogniser should know
    "dictation_shortcut": True,             # Ctrl+Alt+Space starts / stops dictation
}
DICTATION_LANGUAGES = ("en", "fr", "es", "ru", "ja", "yo", "zh")
LAYOUTS = ("notebookbar_compact.ui", "notebookbar.ui", "Single", "Default")
ICONS = {"aura": "aura_svg", "aura_dark": "aura_dark_svg"}
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
        "applied": "Aura est appliqué : un redémarrage affiche l'interface, les icônes et le ruban Aura partout.",
        "restored": "L'apparence d'origine est restaurée.\n\nRedémarrez LibreOffice pour finaliser.",
        "nobackup": "Aucune sauvegarde Aura à restaurer : l'apparence d'origine est déjà en place.",
        "refreshed": "Le ruban Aura est à jour (langue et extensions).\n\nIl s'affiche dans les "
                     "nouvelles fenêtres ; redémarrez LibreOffice pour l'avoir partout.",
        "notapplied": "Aura n'est pas appliqué : utilisez d'abord Outils ▸ Aura ▸ Appliquer.",
        "error": "Aura n'a pas pu terminer l'opération.",
        "panel": "Panneau Aura", "restart_now": "Redémarrer LibreOffice maintenant ? (vos documents ouverts vous seront proposés à l'enregistrement)",
        "confirm_restore": "Restaurer l'apparence d'origine de LibreOffice ?",
        "manage": "Gérer", "light": "Clair", "dark": "Sombre", "restore": "Restaurer",
        "refresh": "Actualiser", "paste_table": "Coller le tableau", "dictation": "Dictée vocale",
        "notable": "Le presse-papiers ne contient pas de tableau de tableur (Calc, Excel ou page web).",
    },
    "en": {
        "applied": "Aura is applied: a restart shows the Aura interface, icons and ribbon everywhere.",
        "restored": "The original appearance is restored.\n\nRestart LibreOffice to finish.",
        "nobackup": "No Aura backup to restore: the original appearance is already in place.",
        "refreshed": "The Aura ribbon is up to date (language and extensions).\n\nNew windows show "
                     "it; restart LibreOffice to have it everywhere.",
        "notapplied": "Aura is not applied: use Tools ▸ Aura ▸ Apply first.",
        "error": "Aura could not complete the operation.",
        "panel": "Aura panel", "restart_now": "Restart LibreOffice now? (you will be asked to save open documents)",
        "confirm_restore": "Restore LibreOffice's original appearance?",
        "manage": "Manage", "light": "Light", "dark": "Dark", "restore": "Restore",
        "refresh": "Refresh", "paste_table": "Paste table", "dictation": "Dictation",
        "notable": "The clipboard holds no spreadsheet table (Calc, Excel or a web page).",
    },
    "de": {
        "applied": "Aura ist angewendet: nach einem Neustart erscheinen Oberfläche, Symbole und Menüband von Aura überall.",
        "restored": "Das ursprüngliche Erscheinungsbild ist wiederhergestellt.\n\nStarten Sie "
                    "LibreOffice neu.",
        "nobackup": "Keine Aura-Sicherung vorhanden: das ursprüngliche Erscheinungsbild ist aktiv.",
        "refreshed": "Das Aura-Menüband ist aktuell (Sprache und Erweiterungen).\n\nNeue Fenster "
                     "zeigen es; starten Sie LibreOffice neu, um es überall zu sehen.",
        "notapplied": "Aura ist nicht angewendet: zuerst Extras ▸ Aura ▸ Anwenden.",
        "error": "Aura konnte den Vorgang nicht abschließen.",
        "panel": "Aura-Bedienfeld", "restart_now": "LibreOffice jetzt neu starten? (offene Dokumente können gespeichert werden)",
        "confirm_restore": "Das ursprüngliche Erscheinungsbild von LibreOffice wiederherstellen?",
        "manage": "Verwalten", "light": "Hell", "dark": "Dunkel", "restore": "Wiederherstellen",
        "refresh": "Aktualisieren", "paste_table": "Tabelle einfügen", "dictation": "Diktat",
        "notable": "Die Zwischenablage enthält keine Tabelle (Calc, Excel oder Webseite).",
    },
    "es": {
        "applied": "Aura está aplicado: al reiniciar se mostrarán la interfaz, los iconos y la cinta de Aura en todas partes.",
        "restored": "Se restauró la apariencia original.\n\nReinicie LibreOffice para terminar.",
        "nobackup": "No hay copia de Aura que restaurar: la apariencia original ya está activa.",
        "refreshed": "La cinta Aura está al día (idioma y extensiones).\n\nLas ventanas nuevas la "
                     "muestran; reinicie LibreOffice para verla en todas.",
        "notapplied": "Aura no está aplicado: use primero Herramientas ▸ Aura ▸ Aplicar.",
        "error": "Aura no pudo completar la operación.",
        "panel": "Panel de Aura", "restart_now": "¿Reiniciar LibreOffice ahora? (se le pedirá guardar los documentos abiertos)",
        "confirm_restore": "¿Restaurar la apariencia original de LibreOffice?",
        "manage": "Gestionar", "light": "Claro", "dark": "Oscuro", "restore": "Restaurar",
        "refresh": "Actualizar", "paste_table": "Pegar tabla", "dictation": "Dictado",
        "notable": "El portapapeles no contiene una tabla de hoja de cálculo (Calc, Excel o web).",
    },
    "it": {
        "applied": "Aura è applicato: dopo il riavvio interfaccia, icone e barra Aura appariranno ovunque.",
        "restored": "L'aspetto originale è ripristinato.\n\nRiavvia LibreOffice per completare.",
        "nobackup": "Nessun backup Aura da ripristinare: l'aspetto originale è già attivo.",
        "refreshed": "La barra Aura è aggiornata (lingua ed estensioni).\n\nLe nuove finestre la "
                     "mostrano; riavvia LibreOffice per vederla ovunque.",
        "notapplied": "Aura non è applicato: usa prima Strumenti ▸ Aura ▸ Applica.",
        "error": "Aura non ha potuto completare l'operazione.",
        "panel": "Pannello Aura", "restart_now": "Riavviare LibreOffice ora? (ti verrà chiesto di salvare i documenti aperti)",
        "confirm_restore": "Ripristinare l'aspetto originale di LibreOffice?",
        "manage": "Gestisci", "light": "Chiaro", "dark": "Scuro", "restore": "Ripristina",
        "refresh": "Aggiorna", "paste_table": "Incolla tabella", "dictation": "Dettatura",
        "notable": "Gli appunti non contengono una tabella di foglio di calcolo (Calc, Excel o web).",
    },
    "pt": {
        "applied": "O Aura foi aplicado: ao reiniciar, a interface, os ícones e a faixa Aura aparecem em todo lado.",
        "restored": "A aparência original foi restaurada.\n\nReinicie o LibreOffice para concluir.",
        "nobackup": "Não há cópia do Aura para restaurar: a aparência original já está ativa.",
        "refreshed": "A faixa Aura está atualizada (idioma e extensões).\n\nAs novas janelas "
                     "mostram-na; reinicie o LibreOffice para a ver em todas.",
        "notapplied": "O Aura não está aplicado: use primeiro Ferramentas ▸ Aura ▸ Aplicar.",
        "error": "O Aura não conseguiu concluir a operação.",
        "panel": "Painel Aura", "restart_now": "Reiniciar o LibreOffice agora? (ser-lhe-á pedido para guardar os documentos abertos)",
        "confirm_restore": "Restaurar a aparência original do LibreOffice?",
        "manage": "Gerir", "light": "Claro", "dark": "Escuro", "restore": "Restaurar",
        "refresh": "Atualizar", "paste_table": "Colar tabela", "dictation": "Ditado",
        "notable": "A área de transferência não contém uma tabela de folha de cálculo (Calc, Excel ou web).",
    },
}


def _natural(name):
    """Sort key so that m2 comes before m10."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _props(**kw):
    out = []
    for k, v in kw.items():
        p = PropertyValue()
        p.Name, p.Value = k, v
        out.append(p)
    return tuple(out)


class Aura(unohelper.Base, XJobExecutor, XJob):
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

    def _get_optional(self, path, name):
        """None when this LibreOffice version has no such setting."""
        try:
            node = self._config(path)
            return node.getPropertyValue(name) if node.getPropertySetInfo().hasPropertyByName(name) else None
        except Exception:
            return None

    def _set_optional(self, path, values):
        """Write settings that may not exist in every LibreOffice version; skip missing ones."""
        try:
            node = self._config(path, update=True)
            info = node.getPropertySetInfo()
            for name, value in values.items():
                if value is None or not info.hasPropertyByName(name):
                    continue
                if isinstance(value, uno.Any):
                    uno.invoke(node, "setPropertyValue", (name, value))
                else:
                    node.setPropertyValue(name, value)
            node.commitChanges()
        except Exception as e:
            print(f"Aura: setting {path} skipped ({e})")

    def _set(self, path, values):
        node = self._config(path, update=True)
        for name, value in values.items():
            if isinstance(value, uno.Any):   # typed value (e.g. a short)
                uno.invoke(node, "setPropertyValue", (name, value))
            else:
                node.setPropertyValue(name, value)
        node.commitChanges()

    def _expand(self, url):
        return self._create("com.sun.star.util.PathSubstitution").substituteVariables(url, True)

    def _settings_path(self):
        return os.path.join(self._system(self._expand("$(user)")), "libreappearance", "settings.json")

    def settings(self):
        try:
            with open(self._settings_path(), encoding="utf-8") as f:
                stored = json.load(f)
        except (OSError, ValueError):
            stored = {}
        valid = {
            "theme": lambda v: v in VARIANTS, "icons": lambda v: v in ("auto", "original", *ICONS),
            "layout": lambda v: v in LAYOUTS,
            "graphic_cache": lambda v: isinstance(v, int) and 100000000 <= v <= 4000000000,
            "dictation_language": lambda v: v == "auto" or v in DICTATION_LANGUAGES,
            "dictation_model": lambda v: re.fullmatch(r"[\w.\-/]{1,80}", v) is not None,
            "dictation_device": lambda v: v in ("auto", "cpu", "cuda"),
            "dictation_yoruba": lambda v: v in ("whisper", "mms"),
            "dictation_chinese": lambda v: v in ("simplified", "traditional"),
            "dictation_glossary": lambda v: len(v) <= 400,
        }
        prefs = dict(DEFAULTS)
        for key, value in stored.items() if isinstance(stored, dict) else ():
            if key in DEFAULTS and type(value) is type(DEFAULTS[key]) and valid.get(key, lambda v: True)(value):
                prefs[key] = value
        return prefs

    def save_settings(self, values):
        merged = {**self.settings(), **values}
        os.makedirs(os.path.dirname(self._settings_path()), exist_ok=True)
        with open(self._settings_path(), "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        return merged

    def is_applied(self):
        return os.path.exists(self._manifest_path())

    def _backup_url(self):
        return self._expand("$(user)/libreappearance/backup.json")

    def _locale(self):
        """UI language tag as LibreOffice uses it ('fr', 'pt-BR', 'en-US'...)."""
        locale = self._get("/org.openoffice.Setup/L10N", "ooLocale") or ""
        if not locale:  # "same as the system": LibreOffice's own reading of the OS (all platforms)
            locale = self._get_optional("/org.openoffice.System/L10N", "UILocale") or ""
        if not locale:
            env = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES")
                   or os.environ.get("LANG") or "en-US")
            locale = env.split(".")[0].replace("_", "-")
        return locale

    def _lang(self):
        base = self._locale().split("-")[0].lower()
        return base if base in MESSAGES else "en"

    def _text(self, key):
        return MESSAGES[self._lang()][key]

    def _message(self, key, detail=""):
        self._message_text(self._text(key) + (f"\n\n{detail}" if detail else ""), error=key == "error")

    def _message_text(self, text, error=False):
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            print(f"Aura: {text}")
            return
        window = frame.getContainerWindow()
        toolkit = self._create("com.sun.star.awt.Toolkit")
        box = toolkit.createMessageBox(
            window, uno.Enum("com.sun.star.awt.MessageBoxType",
                             "ERRORBOX" if error else "INFOBOX"), 1, "Aura", text)
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
            "Settings": {path: {name: self._get_optional(path, name) for name in names}
                         for path, names in SETTINGS.items()},
            "Appearance": self._get_optional(*APPEARANCE),
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
        for path, values in snap.get("Settings", {}).items():
            self._set_optional(path, values)
        if snap.get("Appearance") is not None:
            self._set_optional(APPEARANCE[0], {APPEARANCE[1]: uno.Any("short", snap["Appearance"])})
        self._bind_paste(False)

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

    @staticmethod
    def _is_aura_file(path):
        """A shared file another Aura profile placed (theme or launcher): update it in place."""
        try:
            if os.path.isdir(path):
                with open(os.path.join(path, "gtk-3.0", "gtk.css"), encoding="utf-8") as f:
                    return "Generated by tools/build_gtk.py" in f.read(200)
            if path.endswith(".desktop"):
                with open(path, encoding="utf-8") as f:
                    return "GTK_THEME=Aura" in f.read()
        except OSError:
            pass
        return False

    def _place(self, manifest, dst, write):
        """Write dst through write(path), recording it so restore can undo it."""
        known = dst in manifest["created"] or dst in manifest["replaced"]
        if not known and self._is_aura_file(dst):
            known = True   # owned by another Aura profile's manifest: never claim or back it up
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

    def _install_files(self, spec, prefs):
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = self._system(pip.getPackageLocation(EXTENSION_ID))
        manifest = self._load_manifest()
        user = self._system(self._expand("$(user)"))

        self._write_ribbons(manifest, root, user)
        self._install_fonts(manifest, root)

        if sys.platform.startswith("linux"):
            data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            themes = [os.path.join(data_home, "themes", n) for n in ("Aura", "Aura-dark")]
            launchers = [os.path.join(data_home, "applications", f"libreoffice-{n}.desktop")
                         for n in LAUNCHERS]
            if prefs["gtk"]:
                for name, dst in zip(("Aura", "Aura-dark"), themes):
                    src = os.path.join(root, "gtk", name)
                    self._place(manifest, dst, lambda d, s=src: shutil.copytree(s, d))
                for launcher in LAUNCHERS:
                    self._place_launcher(manifest, data_home, f"libreoffice-{launcher}.desktop", spec["gtk"])
            else:
                self._unplace(manifest, themes + launchers)

        os.makedirs(os.path.dirname(self._manifest_path()), exist_ok=True)
        with open(self._manifest_path(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    # ------------------------------------------------------------- versions
    def version(self):
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = self._system(pip.getPackageLocation(EXTENSION_ID))
        with open(os.path.join(root, "description.xml"), encoding="utf-8") as f:
            return re.search(r'<version value="([^"]+)"', f.read()).group(1)

    def office_version(self):
        return self._get_optional("/org.openoffice.Setup/Product", "ooSetupVersionAboutBox") or "?"

    def dispatch(self, command):
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is not None:
            self._create("com.sun.star.frame.DispatchHelper").executeDispatch(frame, command, "", 0, ())

    def _ensure_icons(self, root):
        """Rebuild the Aura icon themes from the installed Colibre after a LibreOffice update,
        so new commands get Aura icons too. Silently skipped when not writable (shared install)."""
        folder = os.path.join(root, "iconsets")
        marker = os.path.join(folder, "built-for.txt")
        office = self.office_version()
        try:
            with open(marker, encoding="utf-8") as f:
                if f.read().strip() == office:
                    return
        except OSError:
            pass
        try:
            import aura_icons
            with open(os.path.join(root, "design", "tokens.json"), encoding="utf-8") as f:
                tokens = json.load(f)
            config = self._brand("$BRAND_SHARE_SUBDIR/config")
            aura_icons.build_all(tokens, config, folder)
            with open(marker, "w", encoding="utf-8") as f:
                f.write(office)
        except Exception as e:
            print(f"Aura: icon themes kept as shipped ({e})")

    def uninstall(self):
        """Restore the original look, remove the extension, restart."""
        self.restore(silent=True)
        self.save_settings({"welcomed": True})
        import aura_dictation
        aura_dictation.bind_shortcut(self, False)
        aura_dictation.remove(self)
        manager = self.ctx.getByName("/singletons/com.sun.star.deployment.ExtensionManager")
        manager.removeExtension(EXTENSION_ID, "", "user", None, None)
        self.ctx.getByName("/singletons/com.sun.star.task.OfficeRestartManager").requestRestart(None)

    # ------------------------------------------------------------- ribbons
    def _command_label(self, module_id, command):
        """LibreOffice's own (translated) label for a command."""
        try:
            desc = self.ctx.getByName("/singletons/com.sun.star.frame.theUICommandDescription")
            for scope in (module_id, "com.sun.star.text.TextDocument"):
                cmds = desc.getByName(scope)
                if cmds.hasByName(command):
                    props = {p.Name: p.Value for p in cmds.getByName(command)}
                    label = props.get("PopupLabel") or props.get("Label") or ""
                    if label:
                        return label.replace("~", "").rstrip(".…").strip()
        except Exception:
            pass
        return command.rsplit(":", 1)[-1].rsplit(".", 1)[-1]

    def _extension_names(self):
        """Deployed extensions as (add-on node names they declare, normalised id + name, short name)."""
        out = []
        try:
            manager = self.ctx.getByName("/singletons/com.sun.star.deployment.ExtensionManager")
        except Exception:
            return out
        for scope in ("user", "shared"):
            try:
                packages = manager.getDeployedExtensions(scope, None, None)
            except Exception:
                continue
            for package in packages:
                if package is None:
                    continue
                ident = package.getIdentifier().Value or ""
                name = package.getDisplayName() or ""
                short = re.sub(r"\([^)]*\)", "", NAME_NOISE.sub("", name))
                short = re.sub(r"\s{2,}", " ", short).strip(" -–:") or name
                out.append((self._declared_nodes(package.getURL()),
                            re.sub(r"[^a-z0-9]", "", (ident + name).lower()), short))
        return out

    def _declared_nodes(self, url):
        """Names of the add-on UI nodes an extension declares in its .xcu files."""
        nodes = set()
        try:
            if url.startswith("vnd.sun.star.expand:"):
                expander = self.ctx.getByName("/singletons/com.sun.star.util.theMacroExpander")
                url = expander.expandMacros(unquote(url[len("vnd.sun.star.expand:"):]))
            root = self._system(url)
        except Exception:
            return nodes
        for folder, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".xcu"):
                    continue
                try:
                    with open(os.path.join(folder, name), encoding="utf-8", errors="ignore") as f:
                        text = f.read(400000)
                except OSError:
                    continue
                if 'oor:name="AddonUI"' in text or "AddonUI" in text:
                    nodes.update(re.findall(r'<node\s+oor:name="([^"]+)"', text))
        return nodes

    def _group_title(self, node, names):
        for declared, _haystack, short in names:  # the extension that declares this node
            if node in declared:
                return short
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", aura_ribbon.group_key(node))
                  if len(t) >= 4 and t.lower() not in ("org", "com", "net", "office", "addon")]
        for token in sorted(tokens, key=len, reverse=True):
            needle = token.lower()
            for _declared, haystack, short in names:
                if needle in haystack:
                    return short
        return aura_ribbon.pretty_name(node)

    def _addon_groups(self):
        """{group key: (node name, [(url, title, contexts)])} from every installed extension."""
        ui = self._config("/org.openoffice.Office.Addons/AddonUI")
        groups = {}

        def take(node_name, items):
            key = aura_ribbon.group_key(node_name)
            node, entries = groups.setdefault(key, (node_name, []))
            seen = {u for u, _t, _c in entries}
            for name in sorted(items.getElementNames(), key=_natural):
                item = items.getByName(name)
                fields = item.getElementNames()
                url = item.getByName("URL") if "URL" in fields else ""
                if not url or url.startswith("private:") or url in seen or url.startswith(AURA_URL):
                    continue
                title = (item.getByName("Title") if "Title" in fields else "") or ""
                contexts = (item.getByName("Context") if "Context" in fields else "") or ""
                seen.add(url)
                entries.append((url, title.strip() or url.rsplit("?", 1)[-1], contexts))

        for part in ("OfficeNotebookBar", "OfficeToolBar"):
            if ui.hasByName(part):
                section = ui.getByName(part)
                for name in section.getElementNames():
                    take(name, section.getByName(name))
        if ui.hasByName("OfficeToolbarMerging"):
            section = ui.getByName("OfficeToolbarMerging")
            for name in section.getElementNames():
                ext = section.getByName(name)
                for instruction in ext.getElementNames():
                    node = ext.getByName(instruction)
                    if node.hasByName("ToolBarItems"):
                        take(name, node.getByName("ToolBarItems"))
        return groups

    def _extension_tab(self, module):
        """(manage items, groups, aura items) for a module's Extensions tab."""
        services = CONTEXTS[module]
        module_id = services[0]
        names = self._extension_names()
        groups = []
        for key, (node, entries) in sorted(self._addon_groups().items()):
            items = [(url, title) for url, title, contexts in entries
                     if not contexts.strip() or any(s in contexts for s in services)]
            if items:
                groups.append((self._group_title(node, names), items))
        groups.sort(key=lambda g: g[0].lower())
        manage = [(c, self._command_label(module_id, c)) for c in MANAGE_COMMANDS]
        aura = [(AURA_URL + "dictation", self._text("dictation")), (AURA_URL + "panel", self._text("panel"))]
        if module != "scalc":
            aura.append((AURA_URL + "paste_table", self._text("paste_table")))
        return manage, groups, aura

    def _ribbon_budget(self):
        """Width (px) available to the Extensions tab, from the current window."""
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is not None:
            width = frame.getContainerWindow().getPosSize().Width
            if width > 600:
                return width - 380
        return 1500

    def _ribbon_state(self, root):
        """Everything the generated ribbons depend on (to detect when to regenerate)."""
        tabs = {m: self._extension_tab(m) for m in RIBBON_MODULES}
        with open(os.path.join(root, "description.xml"), encoding="utf-8") as f:
            version = re.search(r'<version value="([^"]+)"', f.read()).group(1)
        return {"locale": self._locale(), "version": version, "office": self.office_version(),
                "tabs": tabs,
                "extensions_tab": self.settings()["extensions_tab"]}

    def _brand(self, path):
        """A path inside the LibreOffice installation, on every platform (macOS bundles too)."""
        expander = self.ctx.getByName("/singletons/com.sun.star.util.theMacroExpander")
        return self._system(expander.expandMacros("$BRAND_BASE_DIR/" + path))

    def _write_ribbons(self, manifest, root, user, state=None):
        """Customise the *installed* LibreOffice's stock ribbons (any version >= 24.2).

        A module whose stock ribbon cannot be customised safely keeps it untouched.
        """
        state = state or self._ribbon_state(root)
        budget = manifest.get("budget") or self._ribbon_budget()
        manifest["budget"] = budget
        with open(os.path.join(root, "ui", "ribbon.json"), encoding="utf-8") as f:
            spec = json.load(f)["modules"]
        resources = self._brand("$BRAND_SHARE_RESOURCE_SUBDIR")
        lang = state["locale"].split("-")[0].lower()
        skipped = []
        for module in RIBBON_MODULES:
            dst = os.path.join(user, "config", "soffice.cfg", "modules", module, "ui",
                               "notebookbar_compact.ui")
            try:
                stock = self._brand(f"$BRAND_SHARE_SUBDIR/config/soffice.cfg/modules/{module}/ui/"
                                    "notebookbar_compact.ui")
                tree = aura_ribbon.ET.parse(stock)
                ribbon = tree.getroot()
                aura_ribbon.customize(ribbon, spec.get(module, {}))
                aura_ribbon.localize(ribbon, module, state["locale"], resources,
                                     spec.get(module, {}).get("labels", {}).get(lang, {}))
            except Exception as e:   # unknown layout: keep LibreOffice's own ribbon
                print(f"Aura: {module} ribbon left as shipped by LibreOffice ({e})")
                self._unplace(manifest, [dst])
                skipped.append(module)
                continue
            if state.get("extensions_tab", True):
                manage, groups, aura = state["tabs"][module]
                try:
                    aura_ribbon.extensions_page(ribbon, list(groups) + [("Aura", aura)],
                                                self._text("manage"), manage, budget=budget)
                except Exception as e:
                    print(f"Aura: {module} Extensions tab left as shipped ({e})")
            self._place(manifest, dst,
                        lambda d, t=tree: t.write(d, encoding="UTF-8", xml_declaration=True))
        manifest["ribbon_state"] = json.loads(json.dumps(state))
        manifest["ribbon_skipped"] = skipped

    def refresh(self, silent=False, force=False):
        """Regenerate the ribbons if the language, the extensions or LibreOffice changed."""
        if not os.path.exists(self._manifest_path()):
            if not silent:
                self._message("notapplied")
            return False
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = self._system(pip.getPackageLocation(EXTENSION_ID))
        manifest = self._load_manifest()
        state = self._ribbon_state(root)
        self._ensure_icons(root)
        if silent and not force and manifest.get("ribbon_state") == json.loads(json.dumps(state)):
            return False
        if not silent:
            manifest["budget"] = self._ribbon_budget()
        self._write_ribbons(manifest, root, self._system(self._expand("$(user)")), state)
        with open(self._manifest_path(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        if not silent:
            self._message("refreshed")
        return True

    # ---------------------------------------------------------- table paste
    TEXT_DOC = "com.sun.star.text.TextDocument"
    DRAW_DOCS = ("com.sun.star.presentation.PresentationDocument", "com.sun.star.drawing.DrawingDocument")

    def _clipboard_table(self):
        """The clipboard's spreadsheet range as an aura_table.Table, or None."""
        clip = self._create("com.sun.star.datatransfer.clipboard.SystemClipboard")
        contents = clip.getContents()
        if contents is None:
            return None
        flavors = {f.MimeType.split(";")[0]: f for f in contents.getTransferDataFlavors()}
        embed = flavors.get("application/x-openoffice-embed-source-xml")
        if embed is not None:
            descriptor = flavors.get("application/x-openoffice-objectdescriptor-xml")
            if descriptor is None or CALC_CLASS_ID not in descriptor.MimeType.lower():
                return None   # copied from Writer, Impress...: LibreOffice's own paste is right
            data = contents.getTransferData(embed)
            data = bytes(data.value) if hasattr(data, "value") else bytes(data)
            desktop = self._create("com.sun.star.frame.Desktop")
            doc = aura_table.load_calc_from_bytes(desktop, data, _props, self.ctx)
            if doc is None:
                return None
            try:
                copied = aura_table.used_range(doc)
                live = aura_table.live_source(desktop, copied)
                return aura_table.table_from_calc(live if live is not None else copied)
            finally:
                doc.close(True)
        html_flavor = flavors.get("text/html")
        if html_flavor is not None:
            data = contents.getTransferData(html_flavor)
            raw = bytes(data.value) if hasattr(data, "value") else data
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if "<table" in text.lower():
                return aura_table.table_from_html(text)
        return None

    def _bind_paste(self, smart):
        """Ctrl+V in Writer: Aura's table-aware paste, or LibreOffice's own paste."""
        try:
            supplier = self._create("com.sun.star.ui.ModuleUIConfigurationManagerSupplier")
            shortcuts = supplier.getUIConfigurationManager(self.TEXT_DOC).getShortCutManager()
            key = uno.createUnoStruct("com.sun.star.awt.KeyEvent")
            key.KeyCode = 512 + 21          # com.sun.star.awt.Key.V
            key.Modifiers = 2               # KeyModifier.MOD1: Ctrl, Cmd on macOS
            shortcuts.setKeyEvent(key, AURA_URL + "smart_paste" if smart else ".uno:Paste")
            shortcuts.store()
        except Exception as e:
            print(f"Aura: Ctrl+V binding unchanged ({e})")

    def _normal_paste(self, frame):
        self._create("com.sun.star.frame.DispatchHelper").executeDispatch(frame, ".uno:Paste", "", 0, ())

    def paste_table(self, smart=False):
        """Paste the clipboard's spreadsheet range as a native, fully formatted table.

        smart=True is Ctrl+V in Writer: anything that is not a spreadsheet range
        (text, Writer content, a paste inside an existing table) goes through
        LibreOffice's normal paste.
        """
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            return
        if smart and not self.settings()["smart_paste"]:
            return self._normal_paste(frame)
        doc = frame.getController().getModel()
        module = self._create("com.sun.star.frame.ModuleManager").identify(frame)
        if module == self.TEXT_DOC:
            view = frame.getController().getViewCursor()
            selection = frame.getController().getSelection()
            in_text = selection is not None and selection.supportsService("com.sun.star.text.TextRanges")
            if smart and (not in_text or view.TextTable is not None):
                return self._normal_paste(frame)
        elif module not in self.DRAW_DOCS:
            return self._normal_paste(frame)
        try:
            table = self._clipboard_table()
        except Exception:
            table = None
        if table is None:
            return self._normal_paste(frame) if smart else self._message("notable")
        undo = doc.getUndoManager()
        undo.enterUndoContext(self._text("paste_table"))
        try:
            if module == self.TEXT_DOC:
                aura_table.insert_writer(uno, doc, table)
            else:
                aura_table.insert_draw(uno, doc, table)
        finally:
            undo.leaveUndoContext()

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

    # --------------------------------------------------------------- fonts
    def _installed_families(self):
        device = self._create("com.sun.star.awt.Toolkit").createScreenCompatibleDevice(1, 1)
        return {f.Name for f in device.getFontDescriptors()}

    def _install_fonts(self, manifest, root):
        """Install Inter for the user when the system lacks it (Windows, macOS, Linux)."""
        if all(f in self._installed_families() for f in FONT_FAMILIES):
            return
        src = os.path.join(root, "fonts")
        files = sorted(f for f in os.listdir(src) if f.endswith(".otf"))
        if sys.platform.startswith("win"):
            target = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
        elif sys.platform == "darwin":
            target = os.path.expanduser("~/Library/Fonts")
        else:
            data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            target = os.path.join(data_home, "fonts", "Aura")
        for name in files + ["LICENSE-Inter.txt"]:
            self._place(manifest, os.path.join(target, name),
                        lambda d, s=os.path.join(src, name): shutil.copyfile(s, d))
        if sys.platform.startswith("win"):   # per-user fonts must be registered
            import winreg
            key = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                for name in files:
                    value = name[:-4].replace("-", " ") + " (OpenType)"
                    winreg.SetValueEx(k, value, 0, winreg.REG_SZ, os.path.join(target, name))
                    manifest.setdefault("registry", []).append(value)

    def _allowed(self, path):
        """Aura only ever deletes or moves the files it creates, at known places.

        files.json could be edited by anyone with access to the profile: a path
        outside these places is ignored, so Restore can never be turned against
        the user's files.
        """
        real = os.path.realpath(path)
        name = os.path.basename(real)
        user = os.path.realpath(self._system(self._expand("$(user)")))
        data_home = os.path.realpath(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))

        def under(root, *parts):
            return os.path.dirname(real) == os.path.realpath(os.path.join(root, *parts))

        if name == "notebookbar_compact.ui":
            return any(under(user, "config", "soffice.cfg", "modules", m, "ui") for m in RIBBON_MODULES)
        if name in ("Aura", "Aura-dark"):
            return under(data_home, "themes")
        if re.fullmatch(r"libreoffice-[a-z]+\.desktop", name):
            return under(data_home, "applications")
        if re.fullmatch(r"Inter(Display)?-[A-Za-z]+\.otf|LICENSE-Inter\.txt", name):
            return (under(data_home, "fonts", "Aura") or under(os.path.expanduser("~"), "Library", "Fonts")
                    or under(os.environ.get("LOCALAPPDATA", "/nonexistent"), "Microsoft", "Windows", "Fonts"))
        return re.fullmatch(r"\d+", name) is not None and under(user, "libreappearance", "replaced")

    def _unplace(self, manifest, paths):
        """Undo _place for some paths only (an option switched off)."""
        for path in paths:
            if not self._allowed(path):
                continue
            if path in manifest["created"]:
                manifest["created"].remove(path)
                keep = None
            elif path in manifest["replaced"]:
                keep = manifest["replaced"].pop(path)
            else:
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.lexists(path):
                os.remove(path)
            if keep and self._allowed(keep) and os.path.lexists(keep):
                shutil.move(keep, path)

    def _remove_files(self):
        manifest = self._load_manifest()
        if manifest.get("registry") and sys.platform.startswith("win"):
            import winreg
            key = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                for value in manifest["registry"]:
                    try:
                        winreg.DeleteValue(k, value)
                    except OSError:
                        pass
        self._unplace(manifest, list(manifest.get("created", [])) + list(manifest.get("replaced", {})))
        if os.path.exists(self._manifest_path()):
            os.remove(self._manifest_path())

    def _switch_current_frame(self, mode):
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            return
        helper = self._create("com.sun.star.frame.DispatchHelper")
        helper.executeDispatch(frame, ".uno:ToolbarMode", "", 0, _props(Mode=mode))

    def _read_backup(self):
        sfa = self._create("com.sun.star.ucb.SimpleFileAccess")
        backup = self._backup_url()
        if not sfa.exists(backup):
            return None
        stream = sfa.openFileRead(backup)
        chunks = []
        while True:
            n, data = stream.readBytes(None, 65536)
            if n == 0:
                break
            chunks.append(bytes(data.value))
        stream.closeInput()
        return json.loads(b"".join(chunks).decode("utf-8"))

    def apply(self, variant=None, silent=False):
        """Apply Aura with the user's preferences (variant: 'light' | 'dark' overrides the theme)."""
        sfa = self._create("com.sun.star.ucb.SimpleFileAccess")
        backup = self._backup_url()
        if not sfa.exists(backup):   # keep the very first snapshot: it is the user's original look
            data = json.dumps(self._snapshot(), indent=2).encode("utf-8")
            pipe = self._create("com.sun.star.io.Pipe")
            pipe.writeBytes(uno.ByteSequence(data))
            pipe.closeOutput()
            sfa.writeFile(backup, pipe)
        snap = self._read_backup()
        prefs = self.save_settings({"theme": variant} if variant else {})
        spec = VARIANTS[prefs["theme"]]
        layout = prefs["layout"] if prefs["layout"] in LAYOUTS else UI_MODE

        self._switch_current_frame(layout)
        icons = {"auto": spec["icons"], "original": snap["SymbolStyle"]}.get(prefs["icons"]) \
            or ICONS.get(prefs["icons"], spec["icons"])
        self._set("/org.openoffice.Office.Common/Misc", {"SymbolStyle": icons})
        self._set("/org.openoffice.Office.UI/ColorScheme", {"CurrentColorScheme": spec["scheme"]})
        tabbed = layout.endswith(".ui")
        for service, (suffix, app, package) in MODULES.items():
            if tabbed:
                self._set("/org.openoffice.Office.UI.ToolbarMode", {"Active" + suffix: layout})
            self._set(f"/org.openoffice.Office.UI.ToolbarMode/Applications/{app}", {"Active": layout})
            if tabbed:   # the ribbon replaces the toolbars
                self._set_toolbar_states(package, {k: False for k in self._toolbar_states(package)})
            else:        # classic layouts keep the user's own toolbars
                self._set_toolbar_states(package, snap["Toolbars"].get(package, {}))
        if prefs["templates"]:
            for service, url in self._install_templates().items():
                self._set(f"/org.openoffice.Setup/Office/Factories/{service}",
                          {"ooSetupFactoryTemplateFile": url})
        else:
            for service, url in snap["Templates"].items():
                self._set(f"/org.openoffice.Setup/Office/Factories/{service}",
                          {"ooSetupFactoryTemplateFile": url})
        self._set_optional("/org.openoffice.Office.Common/Misc", {"ShowTipOfTheDay": bool(prefs["tips"])})
        self._set_optional("/org.openoffice.Office.Common/Cache/GraphicManager",
                           {"GraphicMemoryLimit": int(prefs["graphic_cache"])})
        self._set_optional(APPEARANCE[0], {APPEARANCE[1]: uno.Any("short", spec["appearance"])})
        self._bind_paste(prefs["smart_paste"])
        self._install_files(spec, prefs)
        if not silent:
            self._offer_restart("applied")

    def restore(self, silent=False):
        snap = self._read_backup()
        if snap is None:
            if not silent:
                self._message("nobackup")
            return False
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is not None:
            module = self._create("com.sun.star.frame.ModuleManager").identify(frame)
            if module in MODULES:
                self._switch_current_frame(snap["Applications"].get(MODULES[module][1], "Default"))
        self._restore_snapshot(snap)
        self._remove_files()
        self._create("com.sun.star.ucb.SimpleFileAccess").kill(self._backup_url())
        if not silent:
            self._offer_restart("restored")
        return True

    def _confirm(self, key):
        """Yes/No question; commands can be dispatched by any document, so destructive ones ask."""
        return self._confirm_text(self._text(key))

    def _confirm_text(self, text):
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            return True   # no UI (automation, tests)
        box = self._create("com.sun.star.awt.Toolkit").createMessageBox(
            frame.getContainerWindow(), uno.Enum("com.sun.star.awt.MessageBoxType", "QUERYBOX"),
            3, "Aura", text)
        return box.execute() == 2

    # ------------------------------------------------------------- restart
    def _offer_restart(self, key):
        """Tell what happened and offer to restart LibreOffice right away."""
        text = self._text(key) + "\n\n" + self._text("restart_now")
        frame = self._create("com.sun.star.frame.Desktop").getCurrentFrame()
        if frame is None:
            print(f"Aura: {text}")
            return
        box = self._create("com.sun.star.awt.Toolkit").createMessageBox(
            frame.getContainerWindow(), uno.Enum("com.sun.star.awt.MessageBoxType", "QUERYBOX"),
            3, "Aura", text)   # 3 = BUTTONS_YES_NO
        if box.execute() == 2:   # YES
            self.restart()

    def restart(self):
        """Restart LibreOffice. On Linux the new instance gets the Aura GTK theme."""
        prefs = self.settings()
        if sys.platform.startswith("linux") and self.is_applied() and prefs["gtk"]:
            import subprocess
            theme = VARIANTS[prefs["theme"]]["gtk"]
            program = os.path.join(self._system(self._expand("$(prog)")), "soffice")
            # wait (at most 2 minutes) for this instance to quit, then start a themed one;
            # values travel as arguments ($1..$3), never inside the script text
            script = ('i=0; while kill -0 "$1" 2>/dev/null && [ $i -lt 400 ]; do sleep 0.3; i=$((i+1)); done; '
                      'kill -0 "$1" 2>/dev/null || exec env GTK_THEME="$2" "$3"')
            subprocess.Popen(["sh", "-c", script, "aura-restart", str(os.getpid()), theme, program],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._create("com.sun.star.frame.Desktop").terminate()
        else:
            self.ctx.getByName("/singletons/com.sun.star.task.OfficeRestartManager").requestRestart(None)

    # ----------------------------------------------------------- XJobExecutor
    def trigger(self, arg):
        try:
            if arg == "panel":
                import aura_panel
                aura_panel.show(self)
            elif arg == "apply_light":
                self.apply("light")
            elif arg == "apply_dark":
                self.apply("dark")
            elif arg == "restore":
                if self._confirm("confirm_restore"):
                    self.restore()
            elif arg == "refresh":
                self.refresh()
            elif arg == "paste_table":
                self.paste_table()
            elif arg == "smart_paste":
                self.paste_table(smart=True)
            elif arg == "dictation":
                import aura_dictation
                aura_dictation.toggle(self)
        except Exception as e:  # never let an error take the office down
            self._message("error", detail=str(e))

    # ------------------------------------------------------------------ XJob
    def execute(self, args):
        """Jobs: at start-up keep the ribbons in step with the UI language and extensions;
        on the first visible window, welcome a user who has not applied Aura yet."""
        event = ""
        for arg in args:
            if arg.Name == "Environment":
                event = next((v.Value for v in arg.Value if v.Name == "EventName"), "")
        try:
            if event == "onFirstVisibleTask":
                if not self.is_applied() and not self.settings()["welcomed"]:
                    self.save_settings({"welcomed": True})
                    import aura_panel
                    aura_panel.welcome(self)
            else:
                self.refresh(silent=True)
                import aura_dictation
                aura_dictation.bind_shortcut(self, self.settings()["dictation_shortcut"])
        except Exception as e:
            print(f"Aura: start-up job failed: {e}")
        return ()


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(Aura, IMPLEMENTATION, (IMPLEMENTATION,))
