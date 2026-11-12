"""Dictation end to end: the real engine on recordings -> text in Writer and Calc.

    python3 tools/test_voice_office.py --venv <virtualenv with faster-whisper> [--model small]

Installs dist/Aura-*.oxt in a throw-away profile, points the profile's voice
engine at --venv, then starts dictation through the Aura service with a WAV
file playing the part of the microphone (AURA_VOICE_INPUT). Speech is
synthesised with espeak-ng: an English sentence, the command "new paragraph",
then a Spanish sentence (automatic language detection). espeak's French voice
is too robotic for Whisper to be a fair test; the commands of every language
are covered by test_dictation.py.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_templates as bt  # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"[{'ok' if ok else 'FAIL'}] {label}{' — ' + str(detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def speech(folder, parts):
    """espeak-ng clips joined with 1.2 s pauses -> one 16 kHz mono WAV."""
    frames = b""
    for i, (voice, sentence) in enumerate(parts):
        clip = folder / f"part{i}.wav"
        subprocess.run(["espeak-ng", "-v", voice, "-s", "150", "-w", str(clip), sentence], check=True)
        resampled = folder / f"part{i}_16k.wav"
        subprocess.run(["ffmpeg", "-loglevel", "quiet", "-y", "-i", str(clip), "-ac", "1", "-ar", "16000",
                        str(resampled)], check=True)
        with wave.open(str(resampled), "rb") as w:
            frames += w.readframes(w.getnframes()) + b"\0\0" * int(16000 * 1.2)
    out = folder / "dictation.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(frames)
    return out


def wait(predicate, seconds):
    end = time.time() + seconds
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.5)
    return predicate()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--venv", required=True)
    ap.add_argument("--model", default="small")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    oxt = sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "dist" / "Aura-*.oxt")))[-1]
    profile = Path(tempfile.mkdtemp(prefix="aura-voice-"))
    env = f"-env:UserInstallation={profile.as_uri()}"
    r = subprocess.run(["unopkg", "add", "--suppress-license", env, oxt], capture_output=True, text=True)
    check("unopkg add", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])

    voice = profile / "user" / "libreappearance" / "voice"
    voice.mkdir(parents=True)
    (voice / "venv").symlink_to(Path(args.venv).resolve(), target_is_directory=True)
    gpu = subprocess.run([str(Path(args.venv) / "bin" / "python"), "-c",
                          "import importlib.util as u; print(bool(u.find_spec('nvidia.cudnn')))"],
                         capture_output=True, text=True).stdout.strip() == "True"
    (voice / "installed.json").write_text(json.dumps({"gpu": gpu, "mms": False}))
    models = Path(tempfile.gettempdir()) / "aura-voice-test-models"   # kept between runs
    models.mkdir(exist_ok=True)
    (voice / "models").symlink_to(models, target_is_directory=True)
    (profile / "user" / "libreappearance" / "settings.json").write_text(json.dumps(
        {"welcomed": True, "dictation_model": args.model, "dictation_device": args.device}))

    work = Path(tempfile.mkdtemp(prefix="aura-voice-audio-"))
    os.environ["AURA_VOICE_INPUT"] = str(speech(work, [
        ("en", "Hello everyone. This document explains our plan for next year."),
        ("en", "New paragraph."),
        ("es", "Este documento presenta nuestro proyecto para el próximo año."),
    ]))
    os.environ["XDG_DATA_HOME"] = str(profile / "xdg-data")
    office = bt.Office(shutil.which("soffice"), profile)
    try:
        ctx = office.ctx
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        aura = smgr.createInstanceWithContext("org.libreappearance.aura.Aura", ctx)

        doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
        doc.getCurrentController().getFrame().activate()
        aura.trigger("dictation")
        start = time.time()
        paragraphs = wait(lambda: (lambda t: t if "proyecto" in t else "")(doc.getText().getString()), 300)
        text = doc.getText().getString()
        print(f"      Writer ({time.time() - start:.0f} s): {text!r}")
        lines = text.split("\n")
        check("Writer: English sentence dictated", "Hello everyone" in text and "plan" in text, text)
        check("Writer: 'new paragraph' made a new paragraph", len(lines) == 2, lines)
        check("Writer: language switched to Spanish", "documento" in text and "proyecto" in text, text)
        check("Writer: no command words left in the text", "paragraph" not in text.lower())
        check("Writer: second paragraph starts with a capital", len(lines) == 2 and lines[1][:1].isupper(), lines)
        undo = doc.getUndoManager()
        undo.undo()
        after = doc.getText().getString()
        check("Writer: one utterance = one undo step", "proyecto" not in after and after.strip()
              and text.startswith(after.rstrip()), after)
        aura.trigger("dictation")   # toggles off
        log = (voice / "engine.log").read_text(errors="replace") if (voice / "engine.log").exists() else ""
        if not paragraphs:
            print(log[-2000:])
        doc.close(True)

        speech(work, [("en", "Quarterly revenue")])   # same file: the office keeps its environment
        calc = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
        controller = calc.getCurrentController()
        sheet = calc.getSheets().getByIndex(0)
        controller.select(sheet.getCellByPosition(1, 2))   # B3
        aura.trigger("dictation")
        got = wait(lambda: sheet.getCellByPosition(1, 2).getString(), 180)
        check("Calc: dictated into the selected cell", "revenue" in got.lower(), got)
        aura.trigger("dictation")
        calc.close(True)
    finally:
        office.close()
    shutil.rmtree(profile, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    print("\nall checks passed" if not FAILURES else f"\n{len(FAILURES)} check(s) failed")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
