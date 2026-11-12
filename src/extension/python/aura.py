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

# "light and fast" profile: settings changed by Apply and put back by Restore
SETTINGS = {
    "/org.openoffice.Office.Common/Misc": {"ShowTipOfTheDay": False},
    "/org.openoffice.Office.Common/Cache/GraphicManager": {"GraphicMemoryLimit": 600000000},
}
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
        "refreshed": "Le ruban Aura est à jour (langue et extensions).\n\nIl s'affiche dans les "
                     "nouvelles fenêtres ; redémarrez LibreOffice pour l'avoir partout.",
        "notapplied": "Aura n'est pas appliqué : utilisez d'abord Outils ▸ Aura ▸ Appliquer.",
        "error": "Aura n'a pas pu terminer l'opération.",
        "manage": "Gérer", "light": "Clair", "dark": "Sombre", "restore": "Restaurer",
        "refresh": "Actualiser", "paste_table": "Coller le tableau",
        "notable": "Le presse-papiers ne contient pas de tableau de tableur (Calc, Excel ou page web).",
    },
    "en": {
        "applied": "Aura is applied.\n\nQuit LibreOffice completely and start it again from the "
                   "applications menu: the Aura interface, icons and ribbon will show everywhere.\n"
                   "Use Tools ▸ Aura ▸ Restore to undo.",
        "restored": "The original appearance is restored.\n\nRestart LibreOffice to finish.",
        "nobackup": "No Aura backup to restore: the original appearance is already in place.",
        "refreshed": "The Aura ribbon is up to date (language and extensions).\n\nNew windows show "
                     "it; restart LibreOffice to have it everywhere.",
        "notapplied": "Aura is not applied: use Tools ▸ Aura ▸ Apply first.",
        "error": "Aura could not complete the operation.",
        "manage": "Manage", "light": "Light", "dark": "Dark", "restore": "Restore",
        "refresh": "Refresh", "paste_table": "Paste table",
        "notable": "The clipboard holds no spreadsheet table (Calc, Excel or a web page).",
    },
    "de": {
        "applied": "Aura ist angewendet.\n\nBeenden Sie LibreOffice vollständig und starten Sie es "
                   "über das Anwendungsmenü neu: Oberfläche, Symbole und Aura-Menüband erscheinen "
                   "überall.\nExtras ▸ Aura ▸ Wiederherstellen macht es rückgängig.",
        "restored": "Das ursprüngliche Erscheinungsbild ist wiederhergestellt.\n\nStarten Sie "
                    "LibreOffice neu.",
        "nobackup": "Keine Aura-Sicherung vorhanden: das ursprüngliche Erscheinungsbild ist aktiv.",
        "refreshed": "Das Aura-Menüband ist aktuell (Sprache und Erweiterungen).\n\nNeue Fenster "
                     "zeigen es; starten Sie LibreOffice neu, um es überall zu sehen.",
        "notapplied": "Aura ist nicht angewendet: zuerst Extras ▸ Aura ▸ Anwenden.",
        "error": "Aura konnte den Vorgang nicht abschließen.",
        "manage": "Verwalten", "light": "Hell", "dark": "Dunkel", "restore": "Wiederherstellen",
        "refresh": "Aktualisieren", "paste_table": "Tabelle einfügen",
        "notable": "Die Zwischenablage enthält keine Tabelle (Calc, Excel oder Webseite).",
    },
    "es": {
        "applied": "Aura está aplicado.\n\nCierre LibreOffice por completo y ábralo de nuevo desde "
                   "el menú de aplicaciones: la interfaz, los iconos y la cinta Aura se mostrarán en "
                   "todas partes.\nHerramientas ▸ Aura ▸ Restaurar para deshacer.",
        "restored": "Se restauró la apariencia original.\n\nReinicie LibreOffice para terminar.",
        "nobackup": "No hay copia de Aura que restaurar: la apariencia original ya está activa.",
        "refreshed": "La cinta Aura está al día (idioma y extensiones).\n\nLas ventanas nuevas la "
                     "muestran; reinicie LibreOffice para verla en todas.",
        "notapplied": "Aura no está aplicado: use primero Herramientas ▸ Aura ▸ Aplicar.",
        "error": "Aura no pudo completar la operación.",
        "manage": "Gestionar", "light": "Claro", "dark": "Oscuro", "restore": "Restaurar",
        "refresh": "Actualizar", "paste_table": "Pegar tabla",
        "notable": "El portapapeles no contiene una tabla de hoja de cálculo (Calc, Excel o web).",
    },
    "it": {
        "applied": "Aura è applicato.\n\nChiudi completamente LibreOffice e riavvialo dal menu "
                   "delle applicazioni: interfaccia, icone e barra Aura appariranno ovunque.\n"
                   "Strumenti ▸ Aura ▸ Ripristina per annullare.",
        "restored": "L'aspetto originale è ripristinato.\n\nRiavvia LibreOffice per completare.",
        "nobackup": "Nessun backup Aura da ripristinare: l'aspetto originale è già attivo.",
        "refreshed": "La barra Aura è aggiornata (lingua ed estensioni).\n\nLe nuove finestre la "
                     "mostrano; riavvia LibreOffice per vederla ovunque.",
        "notapplied": "Aura non è applicato: usa prima Strumenti ▸ Aura ▸ Applica.",
        "error": "Aura non ha potuto completare l'operazione.",
        "manage": "Gestisci", "light": "Chiaro", "dark": "Scuro", "restore": "Ripristina",
        "refresh": "Aggiorna", "paste_table": "Incolla tabella",
        "notable": "Gli appunti non contengono una tabella di foglio di calcolo (Calc, Excel o web).",
    },
    "pt": {
        "applied": "O Aura foi aplicado.\n\nFeche totalmente o LibreOffice e abra-o novamente pelo "
                   "menu de aplicações: a interface, os ícones e a faixa Aura aparecerão em todo "
                   "lado.\nFerramentas ▸ Aura ▸ Restaurar para desfazer.",
        "restored": "A aparência original foi restaurada.\n\nReinicie o LibreOffice para concluir.",
        "nobackup": "Não há cópia do Aura para restaurar: a aparência original já está ativa.",
        "refreshed": "A faixa Aura está atualizada (idioma e extensões).\n\nAs novas janelas "
                     "mostram-na; reinicie o LibreOffice para a ver em todas.",
        "notapplied": "O Aura não está aplicado: use primeiro Ferramentas ▸ Aura ▸ Aplicar.",
        "error": "O Aura não conseguiu concluir a operação.",
        "manage": "Gerir", "light": "Claro", "dark": "Escuro", "restore": "Restaurar",
        "refresh": "Atualizar", "paste_table": "Colar tabela",
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

    def _backup_url(self):
        return self._expand("$(user)/libreappearance/backup.json")

    def _locale(self):
        """UI language tag as LibreOffice uses it ('fr', 'pt-BR', 'en-US'...)."""
        locale = self._get("/org.openoffice.Setup/L10N", "ooLocale") or ""
        if not locale:  # "same as the system"
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
        text = self._text(key) + (f"\n\n{detail}" if detail else "")
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
            "Settings": {path: {name: self._get(path, name) for name in values}
                         for path, values in SETTINGS.items()},
            "Appearance": self._get(*APPEARANCE),
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
            self._set(path, values)
        if "Appearance" in snap:
            self._set(APPEARANCE[0], {APPEARANCE[1]: uno.Any("short", snap["Appearance"])})

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

        self._write_ribbons(manifest, root, user)
        self._install_fonts(manifest, root)

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
        aura = [(AURA_URL + "paste_table", self._text("paste_table"))] if module != "scalc" else []
        aura += [(AURA_URL + "apply_light", self._text("light")),
                (AURA_URL + "apply_dark", self._text("dark")),
                (AURA_URL + "refresh", self._text("refresh")),
                (AURA_URL + "restore", self._text("restore"))]
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
        return {"locale": self._locale(), "version": version, "tabs": tabs}

    def _write_ribbons(self, manifest, root, user, state=None):
        state = state or self._ribbon_state(root)
        budget = manifest.get("budget") or self._ribbon_budget()
        manifest["budget"] = budget
        with open(os.path.join(root, "ui", "overrides.json"), encoding="utf-8") as f:
            overrides = json.load(f)
        resources = self._system(self._expand("$(prog)/resource"))
        lang = state["locale"].split("-")[0].lower()
        for module in RIBBON_MODULES:
            src = os.path.join(root, "ui", module, "ui", "notebookbar_compact.ui")
            tree = aura_ribbon.ET.parse(src)
            ribbon = tree.getroot()
            aura_ribbon.localize(ribbon, module, state["locale"], resources,
                                 overrides.get(module, {}).get(lang, {}))
            manage, groups, aura = state["tabs"][module]
            aura_ribbon.extensions_page(ribbon, list(groups) + [("Aura", aura)],
                                        self._text("manage"), manage, budget=budget)
            dst = os.path.join(user, "config", "soffice.cfg", "modules", module, "ui",
                               "notebookbar_compact.ui")
            self._place(manifest, dst,
                        lambda d, t=tree: t.write(d, encoding="UTF-8", xml_declaration=True))
        manifest["ribbon_state"] = json.loads(json.dumps(state))

    def refresh(self, silent=False):
        """Regenerate the ribbons if the language or the extensions changed."""
        if not os.path.exists(self._manifest_path()):
            if not silent:
                self._message("notapplied")
            return False
        pip = self.ctx.getByName("/singletons/com.sun.star.deployment.PackageInformationProvider")
        root = self._system(pip.getPackageLocation(EXTENSION_ID))
        manifest = self._load_manifest()
        state = self._ribbon_state(root)
        if silent and manifest.get("ribbon_state") == json.loads(json.dumps(state)):
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
            doc = aura_table.load_calc_from_bytes(desktop, data, _props)
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
        for path, values in SETTINGS.items():
            self._set(path, values)
        self._set(APPEARANCE[0], {APPEARANCE[1]: uno.Any("short", spec["appearance"])})
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
            elif arg == "refresh":
                self.refresh()
            elif arg == "paste_table":
                self.paste_table()
            elif arg == "smart_paste":
                self.paste_table(smart=True)
        except Exception as e:  # never let an error take the office down
            self._message("error", detail=str(e))

    # ------------------------------------------------------------------ XJob
    def execute(self, args):
        """Start-up job: keep the ribbons in step with the UI language and extensions."""
        try:
            self.refresh(silent=True)
        except Exception as e:
            print(f"Aura: ribbon refresh failed: {e}")
        return ()


g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(Aura, IMPLEMENTATION, (IMPLEMENTATION,))
