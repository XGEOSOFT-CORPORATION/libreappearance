"""Aura dictation inside LibreOffice: Tools ▸ Aura ▸ Dictation, Ctrl+Alt+Space.

The recogniser (aura_voice_engine.py) runs in its own Python environment,
created once in $(user)/libreappearance/voice/venv with faster-whisper; its
models are stored next to it. This module starts it, reads its events on a
background thread and hands each one to LibreOffice's main thread
(com.sun.star.awt.AsyncCallback), where the text goes into the document:

    Writer          at the cursor (replacing a selection), in body text, tables, frames, headers
    Calc            into the selected cell; "new line" moves to the cell below, "tab" to the right
    Impress, Draw   at the end of the selected text box or shape

Each utterance is one undo step, so "delete that" (or Ctrl+Z) removes it whole.
A small floating window shows the state, the microphone level, the text being
recognised, and lets the user switch language, pause or stop.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback

import uno
import unohelper
from com.sun.star.awt import XActionListener, XCallback, XItemListener, XTopWindowListener

import aura_voice

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aura_voice_engine.py")
PACKAGES = ["faster-whisper>=1.1", "sounddevice>=0.4"]
GPU_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]
MMS_PACKAGES = ["torch", "transformers>=4.40", "accelerate"]
MODELS = ("auto", "small", "large-v3-turbo", "large-v3", "base")
DEVICES = ("auto", "cpu", "cuda")
SHORTCUT = ("SPACE", 1284, 2 | 4)          # Ctrl+Alt+Space (KeyModifier MOD1 | MOD2)
SHORTCUT_MODULES = ("com.sun.star.text.TextDocument", "com.sun.star.text.GlobalDocument",
                    "com.sun.star.text.WebDocument", "com.sun.star.sheet.SpreadsheetDocument",
                    "com.sun.star.presentation.PresentationDocument", "com.sun.star.drawing.DrawingDocument")
COMMAND = "service:org.libreappearance.aura.Aura?dictation"
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0   # CREATE_NO_WINDOW
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}

T = {
    "fr": {
        "title": "Dictée", "loading": "Chargement du modèle…", "downloading": "Téléchargement du modèle…",
        "listening": "● Écoute", "speech": "● Vous parlez…", "busy": "◌ Transcription…", "paused": "❚❚ En pause",
        "stopped": "Arrêtée", "auto": "Automatique", "pause": "Pause", "resume": "Reprendre", "stop": "Arrêter",
        "not_installed": "Le moteur de dictée n'est pas encore installé.\n\nL'installer maintenant ? "
                         "Il fonctionne hors ligne ; le téléchargement fait de 0,5 à 3 Go selon le modèle.",
        "installing": "Installation du moteur de dictée…", "installed": "Moteur de dictée installé.",
        "install_failed": "L'installation du moteur a échoué : {e}",
        "no_python": "Aucun Python 3.9 à 3.13 trouvé pour le moteur de dictée. Installez Python "
                     "(python.org) puis réessayez.",
        "no_target": "Placez le curseur dans un texte, une cellule ou une zone de texte.",
        "engine_error": "Le moteur de dictée s'est arrêté : {e}", "removed": "Moteur de dictée supprimé.",
        "model_on": "{model} · {device}",
    },
    "en": {
        "title": "Dictation", "loading": "Loading the model…", "downloading": "Downloading the model…",
        "listening": "● Listening", "speech": "● You are speaking…", "busy": "◌ Transcribing…", "paused": "❚❚ Paused",
        "stopped": "Stopped", "auto": "Automatic", "pause": "Pause", "resume": "Resume", "stop": "Stop",
        "not_installed": "The dictation engine is not installed yet.\n\nInstall it now? It works offline; "
                         "the download is 0.5 to 3 GB depending on the model.",
        "installing": "Installing the dictation engine…", "installed": "Dictation engine installed.",
        "install_failed": "The engine installation failed: {e}",
        "no_python": "No Python 3.9 to 3.13 found for the dictation engine. Install Python (python.org) and "
                     "try again.",
        "no_target": "Put the cursor in text, a cell or a text box.",
        "engine_error": "The dictation engine stopped: {e}", "removed": "Dictation engine removed.",
        "model_on": "{model} · {device}",
    },
    "de": {
        "title": "Diktat", "loading": "Modell wird geladen…", "downloading": "Modell wird heruntergeladen…",
        "listening": "● Hört zu", "speech": "● Sie sprechen…", "busy": "◌ Wird erkannt…", "paused": "❚❚ Pausiert",
        "stopped": "Beendet", "auto": "Automatisch", "pause": "Pause", "resume": "Fortsetzen", "stop": "Beenden",
        "not_installed": "Die Diktat-Engine ist noch nicht installiert.\n\nJetzt installieren? Sie arbeitet "
                         "offline; der Download umfasst je nach Modell 0,5 bis 3 GB.",
        "installing": "Diktat-Engine wird installiert…", "installed": "Diktat-Engine installiert.",
        "install_failed": "Installation fehlgeschlagen: {e}",
        "no_python": "Kein Python 3.9 bis 3.13 für die Diktat-Engine gefunden. Installieren Sie Python "
                     "(python.org) und versuchen Sie es erneut.",
        "no_target": "Setzen Sie den Cursor in Text, eine Zelle oder ein Textfeld.",
        "engine_error": "Die Diktat-Engine wurde beendet: {e}", "removed": "Diktat-Engine entfernt.",
        "model_on": "{model} · {device}",
    },
    "es": {
        "title": "Dictado", "loading": "Cargando el modelo…", "downloading": "Descargando el modelo…",
        "listening": "● Escuchando", "speech": "● Está hablando…", "busy": "◌ Transcribiendo…", "paused": "❚❚ En pausa",
        "stopped": "Detenido", "auto": "Automático", "pause": "Pausa", "resume": "Reanudar", "stop": "Detener",
        "not_installed": "El motor de dictado aún no está instalado.\n\n¿Instalarlo ahora? Funciona sin "
                         "conexión; la descarga es de 0,5 a 3 GB según el modelo.",
        "installing": "Instalando el motor de dictado…", "installed": "Motor de dictado instalado.",
        "install_failed": "La instalación del motor falló: {e}",
        "no_python": "No se encontró Python 3.9 a 3.13 para el motor de dictado. Instale Python (python.org) "
                     "e inténtelo de nuevo.",
        "no_target": "Coloque el cursor en un texto, una celda o un cuadro de texto.",
        "engine_error": "El motor de dictado se detuvo: {e}", "removed": "Motor de dictado eliminado.",
        "model_on": "{model} · {device}",
    },
    "it": {
        "title": "Dettatura", "loading": "Caricamento del modello…", "downloading": "Download del modello…",
        "listening": "● In ascolto", "speech": "● Stai parlando…", "busy": "◌ Trascrizione…", "paused": "❚❚ In pausa",
        "stopped": "Interrotta", "auto": "Automatica", "pause": "Pausa", "resume": "Riprendi", "stop": "Interrompi",
        "not_installed": "Il motore di dettatura non è ancora installato.\n\nInstallarlo ora? Funziona "
                         "offline; il download è di 0,5–3 GB secondo il modello.",
        "installing": "Installazione del motore di dettatura…", "installed": "Motore di dettatura installato.",
        "install_failed": "Installazione non riuscita: {e}",
        "no_python": "Nessun Python da 3.9 a 3.13 trovato per il motore di dettatura. Installa Python "
                     "(python.org) e riprova.",
        "no_target": "Posiziona il cursore in un testo, una cella o una casella di testo.",
        "engine_error": "Il motore di dettatura si è fermato: {e}", "removed": "Motore di dettatura rimosso.",
        "model_on": "{model} · {device}",
    },
    "pt": {
        "title": "Ditado", "loading": "A carregar o modelo…", "downloading": "A transferir o modelo…",
        "listening": "● A ouvir", "speech": "● Está a falar…", "busy": "◌ A transcrever…", "paused": "❚❚ Em pausa",
        "stopped": "Parado", "auto": "Automático", "pause": "Pausa", "resume": "Retomar", "stop": "Parar",
        "not_installed": "O motor de ditado ainda não está instalado.\n\nInstalá-lo agora? Funciona offline; "
                         "a transferência é de 0,5 a 3 GB conforme o modelo.",
        "installing": "A instalar o motor de ditado…", "installed": "Motor de ditado instalado.",
        "install_failed": "A instalação do motor falhou: {e}",
        "no_python": "Não foi encontrado Python 3.9 a 3.13 para o motor de ditado. Instale o Python "
                     "(python.org) e tente de novo.",
        "no_target": "Coloque o cursor num texto, numa célula ou numa caixa de texto.",
        "engine_error": "O motor de ditado parou: {e}", "removed": "Motor de ditado removido.",
        "model_on": "{model} · {device}",
    },
}


def text(aura, key, **kw):
    return T.get(aura._lang(), T["en"])[key].format(**kw)


# ------------------------------------------------------------------ main thread
class _Call(unohelper.Base, XCallback):
    def __init__(self, fn):
        self.fn = fn

    def notify(self, data):
        try:
            self.fn()
        except Exception:
            traceback.print_exc()


def on_main(ctx, fn):
    """Run fn on LibreOffice's main thread (UNO documents are not to be touched from others)."""
    ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.AsyncCallback", ctx).addCallback(_Call(fn), None)


class _Listener(unohelper.Base, XActionListener, XItemListener, XTopWindowListener):
    def __init__(self, fn):
        self.fn = fn

    def actionPerformed(self, e):
        self.fn(e)

    def itemStateChanged(self, e):
        self.fn(e)

    def windowClosing(self, e):
        self.fn(e)

    def windowOpened(self, e): pass
    def windowClosed(self, e): pass
    def windowMinimized(self, e): pass
    def windowNormalized(self, e): pass
    def windowActivated(self, e): pass
    def windowDeactivated(self, e): pass
    def disposing(self, e): pass


# ------------------------------------------------------------------ engine files
def voice_dir(aura):
    return os.path.join(aura._system(aura._expand("$(user)")), "libreappearance", "voice")


def venv_python(aura):
    venv = os.path.join(voice_dir(aura), "venv")
    return os.path.join(venv, "Scripts", "python.exe") if sys.platform.startswith("win") \
        else os.path.join(venv, "bin", "python")


def install_info(aura):
    """What was installed ({"gpu": bool, "mms": bool, ...}), or None."""
    try:
        with open(os.path.join(voice_dir(aura), "installed.json"), encoding="utf-8") as f:
            info = json.load(f)
        return info if os.path.exists(venv_python(aura)) else None
    except (OSError, ValueError):
        return None


def has_nvidia():
    return sys.platform != "darwin" and shutil.which("nvidia-smi") is not None


def find_python():
    """A Python able to host the engine (CTranslate2 publishes wheels for 3.9 to 3.13)."""
    names = ["python3.12", "python3.11", "python3.13", "python3.10", "python3.9", "python3", "python"]
    candidates = [os.environ.get("AURA_VOICE_PYTHON", "")]
    if sys.platform.startswith("win"):
        candidates += [["py", f"-3.{v}"] for v in (12, 11, 13, 10)] + ["python"]
    else:
        candidates += names + ["/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"]
    probe = "import sys, venv, ensurepip; print('%d.%d' % sys.version_info[:2])"
    for cand in candidates:
        if not cand:
            continue
        cmd = cand if isinstance(cand, list) else [cand]
        if not isinstance(cand, list) and shutil.which(cand) is None and not os.path.isfile(cand):
            continue
        try:
            out = subprocess.run(cmd + ["-c", probe], capture_output=True, text=True, timeout=20,
                                 creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if re.fullmatch(r"3\.(9|1[0-3])", out):
            return cmd
    return None


def install(aura, progress, prefs=None, base_python=None):
    """Create the engine's environment and download its model. Blocking: run it on a thread.

    progress(str) receives one line at a time (pip's output, then the model download).
    """
    prefs = prefs or aura.settings()
    folder = voice_dir(aura)
    os.makedirs(folder, exist_ok=True)
    python = base_python or find_python()
    if python is None:
        raise RuntimeError(text(aura, "no_python"))
    log = open(os.path.join(folder, "install.log"), "a", encoding="utf-8")

    def run(cmd):
        progress(" ".join(os.path.basename(c) for c in cmd[:4]) + "…")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", creationflags=NO_WINDOW, env=ENV)
        tail = []
        for line in proc.stdout:
            log.write(line)
            line = line.strip()
            if line:
                tail = (tail + [line])[-5:]
                progress(line[:120])
        if proc.wait() != 0:
            raise RuntimeError(" / ".join(tail[-2:]) or f"exit {proc.returncode}")

    try:
        if not os.path.exists(venv_python(aura)):
            run(python + ["-m", "venv", os.path.join(folder, "venv")])
        pip = [venv_python(aura), "-m", "pip", "install", "--upgrade"]
        run(pip + ["pip"])
        gpu = has_nvidia() and prefs.get("dictation_device") != "cpu"
        mms = prefs.get("dictation_yoruba") == "mms"
        run(pip + PACKAGES + (GPU_PACKAGES if gpu and not sys.platform == "darwin" else [])
            + (MMS_PACKAGES if mms else []))
        info = {"gpu": gpu, "mms": mms, "python": python}
        with open(os.path.join(folder, "installed.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        progress(text(aura, "downloading"))
        events = []
        proc = subprocess.Popen(engine_command(aura, prefs) + ["--download-only"], stdout=subprocess.PIPE,
                                stderr=log, text=True, creationflags=NO_WINDOW, encoding="utf-8", env=ENV)
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            events.append(event)
            if event.get("event") == "model":
                info["model"] = f"{event['name']} · {event['device']}"
                progress(info["model"])
        proc.wait()
        errors = [e["message"] for e in events if e.get("event") == "error"]
        if errors:
            raise RuntimeError(errors[-1])
        with open(os.path.join(folder, "installed.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        return info
    finally:
        log.close()


def remove(aura):
    """Delete the engine environment and its models (Aura's own folder only)."""
    stop()
    folder = voice_dir(aura)
    if os.path.basename(folder) == "voice" and os.path.isdir(folder):
        keep = os.path.join(folder, "commands.json")
        saved = open(keep, encoding="utf-8").read() if os.path.exists(keep) else None
        shutil.rmtree(folder, ignore_errors=True)
        if saved is not None:
            os.makedirs(folder, exist_ok=True)
            with open(keep, "w", encoding="utf-8") as f:
                f.write(saved)


def engine_command(aura, prefs):
    folder = voice_dir(aura)
    cmd = [venv_python(aura), "-u", ENGINE,
           "--model", prefs["dictation_model"], "--device", prefs["dictation_device"],
           "--language", prefs["dictation_language"], "--languages", ",".join(aura_voice.LANGUAGES),
           "--yoruba", prefs["dictation_yoruba"], "--chinese", prefs["dictation_chinese"],
           "--models-dir", os.path.join(folder, "models")]
    if prefs["dictation_glossary"].strip():
        cmd += ["--glossary", prefs["dictation_glossary"].strip()[:400]]
    if (install_info(aura) or {}).get("gpu"):
        cmd.append("--cuda-libs")
    if os.environ.get("AURA_VOICE_INPUT"):   # tests: a recording instead of the microphone
        cmd += ["--input", os.environ["AURA_VOICE_INPUT"]]
    return cmd


def user_commands(aura):
    """Phrases the user added in voice/commands.json ({language: {phrase: action}})."""
    try:
        with open(os.path.join(voice_dir(aura), "commands.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ keyboard shortcut
def bind_shortcut(aura, on=True):
    """Ctrl+Alt+Space starts / stops dictation in Writer, Calc, Impress and Draw.

    Never takes a key the user (or LibreOffice) already uses for something else.
    """
    name, code, modifiers = SHORTCUT
    key = uno.createUnoStruct("com.sun.star.awt.KeyEvent")
    key.KeyCode, key.Modifiers = code, modifiers
    supplier = aura._create("com.sun.star.ui.ModuleUIConfigurationManagerSupplier")
    for module in SHORTCUT_MODULES:
        try:
            shortcuts = supplier.getUIConfigurationManager(module).getShortCutManager()
            try:
                current = shortcuts.getCommandByKeyEvent(key)
            except Exception:
                current = ""
            if on and not current:
                shortcuts.setKeyEvent(key, COMMAND)
            elif not on and current == COMMAND:
                shortcuts.removeKeyEvent(key)
            else:
                continue
            shortcuts.store()
        except Exception as e:
            print(f"Aura: dictation shortcut unchanged in {module} ({e})")


# ------------------------------------------------------------------ the session
_session = None


def active():
    return _session is not None and _session.running


def toggle(aura):
    if active():
        stop()
    else:
        start(aura)


def start(aura, language=None):
    global _session
    if active():
        return _session
    if install_info(aura) is None:
        if not aura._confirm_text(text(aura, "not_installed")):
            return None
        _session = Session(aura)
        _session.install_then_start()
        return _session
    _session = Session(aura)
    _session.start(language)
    return _session


def stop():
    if _session is not None:
        _session.stop()


class Session:
    def __init__(self, aura):
        self.aura = aura
        self.ctx = aura.ctx
        self.prefs = aura.settings()
        self.process = None
        self.running = False
        self.window = None
        self.listeners = []
        self.language = self.prefs["dictation_language"]
        self.detected = None
        self.paused = False
        self.format = {"bold": False, "italic": False, "underline": False}
        self.capitalize_next = False
        self.extra = user_commands(aura)
        self.frame = aura._create("com.sun.star.frame.Desktop").getCurrentFrame()
        self.last_error = ""

    # ------------------------------------------------------------ lifecycle
    def start(self, language=None):
        if language:
            self.language = language
        prefs = dict(self.prefs, dictation_language=self.language)
        cmd = engine_command(self.aura, prefs)
        log = open(os.path.join(voice_dir(self.aura), "engine.log"), "w", encoding="utf-8")
        self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                        text=True, encoding="utf-8", bufsize=1, creationflags=NO_WINDOW, env=ENV)
        log.close()
        self.running = True
        self.show_window()
        self.status("loading")
        threading.Thread(target=self._read, args=(self.process,), daemon=True).start()

    def install_then_start(self):
        self.running = True
        self.show_window()
        self.set_label("state", text(self.aura, "installing"))

        def work():
            try:
                install(self.aura, lambda line: on_main(self.ctx, lambda: self.set_label("text", line)))
                on_main(self.ctx, lambda: self.start() if self.running else None)
            except Exception as e:
                message = text(self.aura, "install_failed", e=e)
                on_main(self.ctx, lambda: self.fail(message))
        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self.running = False
        if self.process is not None:
            try:
                self.send({"cmd": "stop"})
                self.process.stdin.close()
            except Exception:
                pass
            proc = self.process
            self.process = None

            def reap():
                try:
                    proc.wait(timeout=4)
                except Exception:
                    proc.kill()
            threading.Thread(target=reap, daemon=True).start()
        self.close_window()

    def fail(self, message):
        self.stop()
        self.aura._message_text(message, error=True)

    def send(self, cmd):
        if self.process is not None and self.process.poll() is None:
            self.process.stdin.write(json.dumps(cmd) + "\n")
            self.process.stdin.flush()

    def _read(self, process):
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            on_main(self.ctx, lambda e=event: self.handle(e))
        code = process.wait()
        if code and self.running and self.process is process:
            detail = self.last_error or self._log_tail()
            on_main(self.ctx, lambda: self.fail(text(self.aura, "engine_error", e=detail)))

    def _log_tail(self):
        try:
            with open(os.path.join(voice_dir(self.aura), "engine.log"), encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-3:]).strip()[-400:]
        except OSError:
            return ""

    # ------------------------------------------------------------ events
    def handle(self, event):
        if not self.running:
            return
        kind = event.get("event")
        if kind == "status":
            self.status(event.get("state", ""))
        elif kind == "level":
            self.set_level(event.get("value", 0))
        elif kind == "partial":
            self.set_label("text", event.get("text", ""))
        elif kind == "model":
            self.model_label = text(self.aura, "model_on", model=event.get("name"),
                                    device="GPU" if event.get("device") == "cuda" else "CPU")
        elif kind == "final":
            self.detected = event.get("lang")
            self.set_label("text", event.get("text", ""))
            self.status("listening")
            self.dictate(event.get("text", ""), event.get("lang") or "en")
        elif kind == "error":
            self.last_error = event.get("message", "")

    def status(self, state):
        if state in ("listening", "speech", "busy", "paused", "loading", "downloading", "stopped"):
            label = text(self.aura, state)
            if state in ("listening", "speech"):
                lang = self.detected if self.language == "auto" else self.language
                label += f" — {aura_voice.LANGUAGES[lang][0]}" if lang in aura_voice.LANGUAGES else ""
                if getattr(self, "model_label", ""):
                    label += f"  ·  {self.model_label}"
            self.set_label("state", label)

    # ------------------------------------------------------------ text into the document
    def dictate(self, utterance, lang):
        if not utterance or aura_voice.is_hallucination(utterance):
            return
        steps = aura_voice.parse(utterance, lang, self.prefs["dictation_commands"], self.extra)
        frame = self._target_frame()
        if frame is None:
            return
        doc = frame.getController().getModel()
        undo = doc.getUndoManager() if hasattr(doc, "getUndoManager") else None
        actions = [v for k, v in steps if k == "action"]
        if actions and all(a in ("delete_last", "undo", "redo", "stop", "save", "select_all") for a in actions):
            for a in actions:
                self.action(frame, doc, a, lang)
            return
        if undo is not None:
            undo.enterUndoContext(text(self.aura, "title"))
        try:
            for kind, value in steps:
                if kind == "text":
                    self.insert(frame, value, lang)
                else:
                    self.action(frame, doc, value, lang)
        except Exception as e:
            traceback.print_exc()
            self.set_label("text", f"⚠ {e}")
        finally:
            if undo is not None:
                undo.leaveUndoContext()

    def _target_frame(self):
        """The document window the user is working in (they may switch documents while dictating)."""
        frame = self.aura._create("com.sun.star.frame.Desktop").getCurrentFrame() or self.frame
        if frame is not None and frame.getController() is not None:
            self.frame = frame
        return self.frame

    def _module(self, frame):
        return self.aura._create("com.sun.star.frame.ModuleManager").identify(frame)

    def insert(self, frame, value, lang):
        module = self._module(frame)
        capitalize = True if self.capitalize_next else None
        self.capitalize_next = False
        controller = frame.getController()
        if module.startswith("com.sun.star.text."):
            cursor = controller.getViewCursor()
            body = cursor.getText()
            if not cursor.isCollapsed():
                cursor.setString("")
            before = body.createTextCursorByRange(cursor.getStart())
            before.gotoStartOfParagraph(True)
            chunk = aura_voice.join(before.getString()[-60:], value, lang, capitalize)
            body.insertString(cursor, chunk, False)
            self._apply_format(body, cursor, chunk)
        elif module == "com.sun.star.sheet.SpreadsheetDocument":
            cell = self._cell(controller)
            if cell is None:
                return self.set_label("text", text(self.aura, "no_target"))
            current = cell.getString() if cell.getType().value == "TEXT" else ""
            cell.setString(current + aura_voice.join(current, value, lang, capitalize))
        else:
            shape = self._shape(controller)
            if shape is None:
                return self.set_label("text", text(self.aura, "no_target"))
            body = shape.getText()
            chunk = aura_voice.join(body.getString()[-60:], value, lang, capitalize)
            end = body.createTextCursorByRange(body.getEnd())
            body.insertString(end, chunk, False)
            self._apply_format(body, body.getEnd(), chunk)

    def _apply_format(self, body, end, chunk):
        """Bold / italic / underline switched on by voice apply to the text dictated after."""
        if not any(self.format.values()):
            return
        rng = body.createTextCursorByRange(end.getEnd() if hasattr(end, "getEnd") else end)
        rng.goLeft(len(chunk.encode("utf-16-le")) // 2, True)
        if self.format["bold"]:
            rng.setPropertyValue("CharWeight", 150.0)
        if self.format["italic"]:
            rng.setPropertyValue("CharPosture", uno.Enum("com.sun.star.awt.FontSlant", "ITALIC"))
        if self.format["underline"]:
            rng.setPropertyValue("CharUnderline", 1)

    @staticmethod
    def _cell(controller):
        sel = controller.getSelection()
        if sel is None:
            return None
        if sel.supportsService("com.sun.star.sheet.SheetCell"):
            return sel
        if sel.supportsService("com.sun.star.sheet.SheetCellRange"):
            return sel.getCellByPosition(0, 0)
        return None

    @staticmethod
    def _shape(controller):
        sel = controller.getSelection()
        try:
            if sel is not None and hasattr(sel, "getCount") and sel.getCount() == 1:
                shape = sel.getByIndex(0)
                if hasattr(shape, "getText") and shape.getText() is not None:
                    return shape
        except Exception:
            pass
        return None

    def action(self, frame, doc, name, lang):
        mark = aura_voice.punctuation(name, lang)
        if mark is not None or name == "space":
            return self.insert(frame, mark or " ", lang) if name != "space" else self._raw(frame, " ")
        module = self._module(frame)
        controller = frame.getController()
        writer = module.startswith("com.sun.star.text.")
        if name in ("newline", "paragraph", "page_break", "tab"):
            if writer:
                cursor = controller.getViewCursor()
                body = cursor.getText()
                if name == "tab":
                    body.insertString(cursor, "\t", False)
                elif name == "page_break":
                    self.aura.dispatch(".uno:InsertPagebreak")
                else:
                    body.insertControlCharacter(cursor, 1 if name == "newline" else 0, False)
            elif module == "com.sun.star.sheet.SpreadsheetDocument":
                cell = self._cell(controller)
                if cell is not None:
                    addr = cell.getCellAddress()
                    sheet = cell.getSpreadsheet()
                    col, row = (addr.Column + 1, addr.Row) if name == "tab" else (addr.Column, addr.Row + 1)
                    controller.select(sheet.getCellByPosition(col, row))
            else:
                shape = self._shape(controller)
                if shape is not None:
                    body = shape.getText()
                    if name == "tab":
                        body.insertString(body.getEnd(), "\t", False)
                    else:
                        body.insertControlCharacter(body.getEnd(), 1 if name == "newline" else 0, False)
            if name in ("paragraph", "page_break"):
                self.capitalize_next = True
        elif name in ("delete_last", "undo"):
            undo = doc.getUndoManager()
            if undo.isUndoPossible():
                undo.undo()
        elif name == "redo":
            undo = doc.getUndoManager()
            if undo.isRedoPossible():
                undo.redo()
        elif name == "stop":
            self.stop()
        elif name in ("bold", "italic", "underline"):
            selected = False
            if writer:
                selected = not controller.getViewCursor().isCollapsed()
            elif module == "com.sun.star.sheet.SpreadsheetDocument":
                selected = True
            if selected:
                self.aura.dispatch({"bold": ".uno:Bold", "italic": ".uno:Italic",
                                    "underline": ".uno:Underline"}[name])
            else:
                self.format[name] = not self.format[name]
        elif name == "save":
            self.aura.dispatch(".uno:Save")
        elif name == "select_all":
            self.aura.dispatch(".uno:SelectAll")
        elif name == "capitalize_next":
            self.capitalize_next = True

    def _raw(self, frame, chunk):
        if self._module(frame).startswith("com.sun.star.text."):
            cursor = frame.getController().getViewCursor()
            cursor.getText().insertString(cursor, chunk, False)

    # ------------------------------------------------------------ floating window
    def show_window(self):
        aura = self.aura
        smgr = self.ctx.ServiceManager
        model = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialogModel", self.ctx)
        model.Width, model.Height, model.Title = 236, 58, "Aura — " + text(aura, "title")
        model.Closeable, model.Moveable = True, True

        def add(kind, name, x, y, w, h, **props):
            m = model.createInstance(f"com.sun.star.awt.UnoControl{kind}Model")
            m.PositionX, m.PositionY, m.Width, m.Height = x, y, w, h
            for k, v in props.items():
                if k in ("StringItemList", "SelectedItems"):
                    uno.invoke(m, "setPropertyValue",
                               (k, uno.Any("[]string" if k == "StringItemList" else "[]short", tuple(v))))
                else:
                    setattr(m, k, v)
            model.insertByName(name, m)

        langs = ["auto"] + list(aura_voice.LANGUAGES)
        names = [text(aura, "auto")] + [aura_voice.LANGUAGES[k][0] for k in aura_voice.LANGUAGES]
        add("FixedText", "state", 6, 5, 168, 10, Label="", FontWeight=150.0)
        add("ProgressBar", "level", 178, 6, 52, 7, ProgressValueMin=0, ProgressValueMax=100, ProgressValue=0)
        add("FixedText", "text", 6, 18, 224, 18, Label="", MultiLine=True)
        add("ListBox", "lang", 6, 40, 92, 13, Dropdown=True, StringItemList=names,
            SelectedItems=[langs.index(self.language) if self.language in langs else 0])
        add("Button", "pause", 134, 40, 46, 13, Label=text(aura, "pause"))
        add("Button", "stop", 184, 40, 46, 13, Label=text(aura, "stop"), DefaultButton=True)
        dialog = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", self.ctx)
        dialog.setModel(model)
        parent = self.frame.getContainerWindow() if self.frame is not None else None
        dialog.createPeer(aura._create("com.sun.star.awt.Toolkit"), parent)

        def listen(control, method, fn):
            listener = _Listener(lambda e: self._safe(fn, e))
            self.listeners.append(listener)
            getattr(dialog.getControl(control) if control else dialog, method)(listener)

        listen("stop", "addActionListener", lambda e: self.stop())
        listen("pause", "addActionListener", lambda e: self.toggle_pause())
        listen("lang", "addItemListener", lambda e: self.switch_language(langs[e.Selected]))
        listen(None, "addTopWindowListener", lambda e: self.stop())
        if parent is not None:   # top right of the document window
            area = parent.getPosSize()
            size = dialog.getPosSize()
            dialog.setPosSize(area.X + max(0, area.Width - size.Width - 40), area.Y + 110, 0, 0, 3)
        dialog.setVisible(True)
        self.window = dialog
        self._refocus()

    def _safe(self, fn, event):
        try:
            fn(event)
        except Exception:
            traceback.print_exc()

    def _refocus(self):
        try:
            if self.frame is not None:
                self.frame.getComponentWindow().setFocus()
        except Exception:
            pass

    def close_window(self):
        if self.window is not None:
            window, self.window = self.window, None
            try:
                window.setVisible(False)
                window.dispose()
            except Exception:
                pass

    def set_label(self, name, value):
        if self.window is not None:
            self.window.getModel().getByName(name).Label = value

    def set_level(self, value):
        if self.window is not None:
            self.window.getModel().getByName("level").ProgressValue = int(max(0.0, min(1.0, value)) * 100)

    def toggle_pause(self):
        self.paused = not self.paused
        self.send({"cmd": "pause" if self.paused else "resume"})
        self.window.getModel().getByName("pause").Label = text(self.aura, "resume" if self.paused else "pause")
        self._refocus()

    def switch_language(self, lang):
        self.language = lang
        self.detected = None
        self.send({"cmd": "language", "value": lang})
        self.aura.save_settings({"dictation_language": lang})
        self._refocus()
