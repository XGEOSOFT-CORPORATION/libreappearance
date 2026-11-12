"""Aura dictation engine: microphone -> utterances -> text, as JSON lines on stdout.

Runs in its own Python (the virtual environment Aura creates in
$(user)/libreappearance/voice/venv), never inside LibreOffice, so a heavy model
or a crash cannot freeze or take down the office.

    python aura_voice_engine.py --model auto --language auto --languages en,fr,es,ru,ja,yo,zh

Recognition is OpenAI Whisper through faster-whisper (CTranslate2): offline, on
the GPU when there is one, punctuated, and with language detection limited to
the dictation languages. Yoruba can optionally use Meta's MMS model, trained on
far more Yoruba speech than Whisper.

Events (stdout, one JSON object per line):
    {"event": "status", "state": "loading" | "downloading" | "ready" | "listening" | "speech" | "busy"}
    {"event": "partial", "text": ...}                 while the user speaks (GPU)
    {"event": "final", "text": ..., "lang": ..., "seconds": ...}
    {"event": "level", "value": 0..1}                  microphone level, ~5 per second
    {"event": "error", "message": ...} / {"event": "warning", "message": ...}
Commands (stdin, one JSON object per line):
    {"cmd": "language", "value": "fr" | "auto"}, {"cmd": "pause"}, {"cmd": "resume"}, {"cmd": "stop"}
The engine stops when stdin closes, so it never outlives LibreOffice.
"""
import argparse
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import wave

RATE = 16000
FRAME = 480                      # 30 ms
_out_lock = threading.Lock()

# Context given to Whisper per language: script and punctuation style
PROMPTS = {
    "zh": "以下是普通话的句子，使用简体中文和标点符号。",
    "zh-hant": "以下是普通話的句子，使用繁體中文和標點符號。",
    "ja": "以下は日本語の文章です。句読点を使います。",
    "yo": "Ẹ káàárọ̀. Báwo ni ẹ ṣe wà? Mo fẹ́ kọ ìwé yìí ní èdè Yorùbá.",
}


def emit(event, **data):
    with _out_lock:
        sys.stdout.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


# ------------------------------------------------------------------ GPU libraries
def preload_cuda_libraries():
    """CUDA libraries installed with pip (nvidia-cublas-cu12, nvidia-cudnn-cu12) are not on the
    loader path: load them by full path so CTranslate2 finds them by name."""
    roots = [p for p in sys.path if p.endswith("site-packages")]
    if sys.platform.startswith("win"):
        for root in roots:
            for folder in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
                try:
                    os.add_dll_directory(folder)
                except OSError:
                    pass
                os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        return
    import ctypes
    for root in roots:
        for pattern in ("cublas/lib/libcublasLt.so.*", "cublas/lib/libcublas.so.*", "cudnn/lib/libcudnn*.so.*"):
            for lib in sorted(glob.glob(os.path.join(root, "nvidia", pattern))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


# ------------------------------------------------------------------ microphone
class Microphone:
    """16 kHz mono float32 frames from the default input, via PortAudio (sounddevice) or,
    when it is missing, a system recorder (PipeWire, PulseAudio, ALSA, FFmpeg)."""

    def __init__(self, device=None):
        self.queue = queue.Queue()
        self.process = None
        self.stream = None
        self.device = device

    def start(self):
        try:
            import sounddevice as sd
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME,
                                         device=self.device or None, callback=self._callback)
            self.stream.start()
            return "portaudio"
        except Exception as e:
            first_error = e
        for cmd in self._recorders():
            if shutil.which(cmd[0]) is None:
                continue
            try:
                self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                continue
            time.sleep(0.3)
            if self.process.poll() is None:
                threading.Thread(target=self._pump, daemon=True).start()
                return cmd[0]
        raise RuntimeError(f"no microphone available ({first_error})")

    @staticmethod
    def _recorders():
        if sys.platform.startswith("linux"):
            return (["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"],
                    ["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le"],
                    ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
                    ["ffmpeg", "-loglevel", "quiet", "-f", "pulse", "-i", "default",
                     "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"])
        if sys.platform == "darwin":
            return (["ffmpeg", "-loglevel", "quiet", "-f", "avfoundation", "-i", ":0",
                     "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                    ["sox", "-q", "-d", "-r", str(RATE), "-c", "1", "-b", "16", "-e", "signed", "-t", "raw", "-"])
        return ()

    def _callback(self, data, frames, time_info, status):
        self.queue.put(data[:, 0].copy())

    def _pump(self):
        import numpy as np
        size = FRAME * 2
        while True:
            chunk = self.process.stdout.read(size)
            if not chunk:
                break
            if len(chunk) % 2:
                chunk = chunk[:-1]
            self.queue.put(np.frombuffer(chunk, dtype="<i2").astype("float32") / 32768.0)

    def read(self, timeout=0.5):
        return self.queue.get(timeout=timeout)

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
        if self.process is not None:
            self.process.terminate()


class WaveFile:
    """A recording played as if it came from the microphone (tests, file transcription)."""

    def __init__(self, path, realtime=False):
        self.path, self.realtime = path, realtime
        self.queue = queue.Queue()

    def start(self):
        import numpy as np
        with wave.open(self.path, "rb") as w:
            rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        data = np.frombuffer(raw, dtype={1: "u1", 2: "<i2", 4: "<i4"}[width]).astype("float32")
        data = (data - 128) / 128 if width == 1 else data / float(2 ** (8 * width - 1))
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        if rate != RATE:
            n = int(len(data) * RATE / rate)
            data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype("float32")
        data = np.concatenate([data, np.zeros(RATE * 2, dtype="float32")])   # trailing silence ends the last utterance
        for i in range(0, len(data) - FRAME + 1, FRAME):
            self.queue.put(data[i:i + FRAME])
        self.queue.put(None)
        return "file"

    def read(self, timeout=0.5):
        item = self.queue.get(timeout=timeout)
        if item is None:
            raise EOFError
        if self.realtime:
            time.sleep(FRAME / RATE)
        return item

    def stop(self):
        pass


# ------------------------------------------------------------------ voice activity
class Segmenter:
    """Cuts the stream into utterances on pauses, with an adaptive noise floor."""

    def __init__(self, silence_ms=700, max_seconds=28.0, min_ms=250):
        import numpy as np
        self.np = np
        self.floor = 0.003
        self.silence_frames = int(silence_ms / 30)
        self.max_frames = int(max_seconds * 1000 / 30)
        self.min_frames = int(min_ms / 30)
        self.preroll = []
        self.frames = []
        self.levels = []
        self.speech = 0
        self.quiet = 0
        self.active = False

    def level(self, frame):
        return float(self.np.sqrt(self.np.mean(frame * frame)) + 1e-9)

    def push(self, frame):
        """Feed a frame; returns a finished utterance (float32 array) or None."""
        rms = self.level(frame)
        threshold = max(self.floor * 3.0, 0.008)
        voiced = rms > threshold
        if not self.active:
            if not voiced:   # follow the background noise slowly
                self.floor = 0.95 * self.floor + 0.05 * min(rms, 0.05)
            self.preroll = (self.preroll + [frame])[-10:]
            self.speech = self.speech + 1 if voiced else 0
            if self.speech >= 3:
                self.active, self.frames, self.quiet = True, list(self.preroll), 0
            return None
        self.frames.append(frame)
        self.levels.append(rms)
        self.quiet = 0 if voiced else self.quiet + 1
        if self.quiet >= self.silence_frames:
            return self.finish()
        if len(self.frames) >= self.max_frames:
            # no pause for 28 s: speech, or a noise louder than the floor (fan, music); in the
            # second case raising the floor to the quieter part of it stops endless "utterances"
            self.floor = max(self.floor, float(self.np.percentile(self.levels, 20)) / 2.0)
            return self.finish()
        return None

    def finish(self):
        frames, voiced = self.frames, len(self.frames) - self.quiet
        self.active, self.frames, self.preroll, self.speech, self.quiet = False, [], [], 0, 0
        self.levels = []
        if voiced < self.min_frames:
            return None
        return self.np.concatenate(frames)

    def current(self):
        return self.np.concatenate(self.frames) if self.frames else None


# ------------------------------------------------------------------ recognisers
class Whisper:
    def __init__(self, model, device, models_dir, threads=0):
        from faster_whisper import WhisperModel
        self.device = device
        cuda = False
        if device in ("auto", "cuda"):
            try:
                import ctranslate2
                cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                cuda = False
        if model == "auto":
            model = "large-v3-turbo" if cuda else "small"
        self.name = model
        attempts = [("cuda", "float16"), ("cuda", "int8_float16")] if cuda else []
        if device != "cuda" or not cuda:
            attempts.append(("cpu", "int8"))
        last = None
        for dev, compute in attempts:
            try:
                self.model = WhisperModel(model, device=dev, compute_type=compute, download_root=models_dir,
                                          cpu_threads=threads)
                self.device, self.compute = dev, compute
                if dev == "cuda":   # a GPU that loads but cannot run (missing cuDNN...) fails here
                    import numpy as np
                    list(self.model.transcribe(np.zeros(RATE, dtype="float32"), language="en", beam_size=1)[0])
                return
            except Exception as e:
                last = e
                emit("warning", message=f"{dev}/{compute}: {e}")
        raise RuntimeError(f"Whisper model {model} could not be loaded: {last}")

    def detect(self, audio, allowed, previous):
        """Best allowed language for this utterance; short utterances keep the previous one."""
        if previous and len(audio) < RATE * 1.2:
            return previous
        try:
            _lang, _p, probs = self.model.detect_language(audio)
        except Exception:
            _segments, info = self.model.transcribe(audio, beam_size=1, without_timestamps=True)
            probs = info.all_language_probs or [(info.language, info.language_probability)]
        ranked = [(lang, p) for lang, p in probs if lang in allowed]
        if not ranked:
            return previous or allowed[0]
        best, p = max(ranked, key=lambda x: x[1])
        if previous in allowed and best != previous:
            prev_p = dict(ranked).get(previous, 0.0)
            if p - prev_p < 0.25:   # hysteresis: do not flip language on a doubtful utterance
                return previous
        return best

    def transcribe(self, audio, lang, prompt, fast=False):
        segments, _info = self.model.transcribe(
            audio, language=lang, task="transcribe", initial_prompt=prompt or None,
            beam_size=1 if fast else 5, best_of=1 if fast else 5, temperature=0.0 if fast else (0.0, 0.2, 0.4, 0.6),
            condition_on_previous_text=False, vad_filter=not fast, without_timestamps=True,
            no_speech_threshold=0.6, log_prob_threshold=-1.0, compression_ratio_threshold=2.4)
        parts = []
        for seg in segments:
            if seg.no_speech_prob > 0.7 and seg.avg_logprob < -0.8:
                continue
            parts.append(seg.text)
        text = "".join(parts).strip()
        if lang in ("ja", "zh"):
            text = text.replace(" ", "") if all(ord(c) > 0x2E80 or not c.isalpha() for c in text) else text
        return text


class MMSYoruba:
    """Meta MMS (wav2vec2, 1 162 languages) with its Yoruba adapter."""

    def __init__(self, models_dir, device):
        import torch
        from transformers import AutoProcessor, Wav2Vec2ForCTC
        self.torch = torch
        name = "facebook/mms-1b-all"
        self.processor = AutoProcessor.from_pretrained(name, cache_dir=models_dir)
        self.model = Wav2Vec2ForCTC.from_pretrained(name, cache_dir=models_dir)
        self.processor.tokenizer.set_target_lang("yor")
        self.model.load_adapter("yor")
        self.device = "cuda" if device != "cpu" and torch.cuda.is_available() else "cpu"
        self.model.to(self.device).eval()

    def transcribe(self, audio):
        inputs = self.processor(audio, sampling_rate=RATE, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            logits = self.model(**inputs).logits
        ids = self.torch.argmax(logits, dim=-1)[0]
        text = self.processor.decode(ids).strip()
        if text:   # MMS writes neither capitals nor final punctuation
            text = text[0].upper() + text[1:] + "."
        return text


# ------------------------------------------------------------------ main loop
class Engine:
    def __init__(self, args):
        self.args = args
        self.allowed = [l for l in args.languages.split(",") if l] or ["en"]
        self.language = args.language
        self.paused = False
        self.stopping = False
        self.previous_lang = None
        self.context = {}               # language -> end of the previous utterance (Whisper prompt)
        self.glossary = args.glossary or ""
        self.mms = None

    def commands(self):
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
            except ValueError:
                continue
            name = cmd.get("cmd")
            if name == "language":
                value = cmd.get("value") or "auto"
                self.language = value
                self.previous_lang = None if value == "auto" else value
                emit("status", state="listening", language=value)
            elif name == "pause":
                self.paused = True
                emit("status", state="paused")
            elif name == "resume":
                self.paused = False
                emit("status", state="listening", language=self.language)
            elif name == "stop":
                self.stopping = True
                return
        if not self.args.input:   # LibreOffice is gone: never keep the microphone open
            self.stopping = True

    def prompt(self, lang):
        key = "zh-hant" if lang == "zh" and self.args.chinese == "traditional" else lang
        parts = [PROMPTS.get(key, ""), self.glossary, self.context.get(lang, "")]
        return " ".join(p for p in parts if p).strip()[-600:]

    def recognise(self, audio, fast=False):
        if self.language == "auto":
            lang = self.whisper.detect(audio, self.allowed, self.previous_lang)
        else:
            lang = self.language
        if lang == "yo" and self.mms is not None and not fast:
            text = self.mms.transcribe(audio)
        else:
            text = self.whisper.transcribe(audio, lang, self.prompt(lang), fast=fast)
        return lang, text

    def run(self):
        args = self.args
        emit("status", state="loading", model=args.model)
        if args.cuda_libs:
            preload_cuda_libraries()
        self.whisper = Whisper(args.model, args.device, args.models_dir, args.threads)
        emit("model", name=self.whisper.name, device=self.whisper.device, compute=self.whisper.compute)
        if args.yoruba == "mms" and "yo" in self.allowed:
            try:
                emit("status", state="loading", model="mms-1b-all")
                self.mms = MMSYoruba(args.models_dir, args.device)
            except Exception as e:
                emit("warning", message=f"MMS Yoruba unavailable, Whisper is used: {e}")
        if args.download_only:
            emit("status", state="ready")
            return
        source = WaveFile(args.input, args.realtime) if args.input else Microphone(args.mic or None)
        backend = source.start()
        emit("status", state="listening", language=self.language, source=backend)
        threading.Thread(target=self.commands, daemon=True).start()
        seg = Segmenter(args.silence_ms)
        partials = args.partials if args.partials != "auto" else ("on" if self.whisper.device == "cuda" else "off")
        last_partial, frames_since_level, levels = 0.0, 0, []
        try:
            while not self.stopping:
                try:
                    frame = source.read()
                except queue.Empty:
                    continue
                except EOFError:
                    break
                if self.paused:
                    continue
                levels.append(seg.level(frame))
                frames_since_level += 1
                if frames_since_level >= 6:
                    emit("level", value=round(min(1.0, max(levels) * 8), 3))
                    frames_since_level, levels = 0, []
                was_active = seg.active
                utterance = seg.push(frame)
                if seg.active and not was_active:
                    emit("status", state="speech")
                if utterance is not None:
                    self.final(utterance)
                elif seg.active and partials == "on" and time.monotonic() - last_partial > 1.0 \
                        and len(seg.frames) > 30:
                    last_partial = time.monotonic()
                    try:
                        _lang, text = self.recognise(seg.current(), fast=True)
                        if text:
                            emit("partial", text=text)
                    except Exception:
                        pass
                elif not seg.active and was_active:
                    emit("status", state="listening", language=self.language)
            rest = seg.finish() if seg.active else None
            if rest is not None:
                self.final(rest)
        finally:
            source.stop()
        emit("status", state="stopped")

    def final(self, audio):
        emit("status", state="busy")
        start = time.monotonic()
        try:
            lang, text = self.recognise(audio)
        except Exception as e:
            emit("error", message=str(e))
            return
        self.previous_lang = lang
        if text:
            self.context[lang] = (self.context.get(lang, "") + " " + text)[-200:]
            emit("final", text=text, lang=lang, seconds=round(len(audio) / RATE, 2),
                 elapsed=round(time.monotonic() - start, 2))
        emit("status", state="listening", language=self.language)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="auto", help="auto | tiny | base | small | medium | large-v3-turbo | large-v3 "
                    "| a CTranslate2 model folder or Hugging Face id")
    ap.add_argument("--device", default="auto", choices=("auto", "cpu", "cuda"))
    ap.add_argument("--language", default="auto")
    ap.add_argument("--languages", default="en,fr,es,ru,ja,yo,zh")
    ap.add_argument("--yoruba", default="whisper", choices=("whisper", "mms"))
    ap.add_argument("--chinese", default="simplified", choices=("simplified", "traditional"))
    ap.add_argument("--glossary", default="", help="names and terms to recognise")
    ap.add_argument("--partials", default="auto", choices=("auto", "on", "off"))
    ap.add_argument("--silence-ms", type=int, default=700)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--models-dir", default=None)
    ap.add_argument("--mic", default="")
    ap.add_argument("--input", help="transcribe a WAV file instead of the microphone")
    ap.add_argument("--realtime", action="store_true", help="play --input at its real speed")
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--cuda-libs", action="store_true", help="load pip-installed CUDA libraries")
    args = ap.parse_args()
    for stream in (sys.stdin, sys.stdout):   # Windows consoles default to a legacy code page
        stream.reconfigure(encoding="utf-8")
    try:
        Engine(args).run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        emit("error", message=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
