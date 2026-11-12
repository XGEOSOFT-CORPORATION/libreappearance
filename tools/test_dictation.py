"""Dictation text handling in the 7 languages: voice commands, spacing, capitals (no office needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "extension" / "python" / "pythonpath"))
import aura_voice as v  # noqa: E402

FAILURES = []


def check(label, got, expected):
    ok = got == expected
    print(f"[{'ok' if ok else 'FAIL'}] {label}" + ("" if ok else f" — got {got!r}, expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def actions(text, lang):
    return [x for k, x in v.parse(text, lang) if k == "action"]


# whole-utterance commands, as Whisper writes them (capitals, final punctuation)
for lang, said, expected in (
        ("en", "New paragraph.", ["paragraph"]), ("en", "Delete that!", ["delete_last"]),
        ("en", "Question mark.", ["question"]), ("fr", "Nouveau paragraphe.", ["paragraph"]),
        ("fr", "À la ligne.", ["newline"]), ("fr", "Virgule", ["comma"]),
        ("fr", "Point d'interrogation ?", ["question"]), ("fr", "Efface ça.", ["delete_last"]),
        ("fr", "Ouvrez les guillemets.", ["open_quote"]), ("es", "Punto y aparte.", ["period", "paragraph"]),
        ("es", "Nueva línea", ["newline"]), ("es", "Abrir interrogación", ["open_question"]),
        ("ru", "Новый абзац.", ["paragraph"]), ("ru", "Запятая", ["comma"]),
        ("ru", "Выделить всё.", ["select_all"]), ("ja", "改行。", ["newline"]), ("ja", "まる", ["period"]),
        ("ja", "かぎかっこ閉じ", ["close_quote"]), ("zh", "换行。", ["newline"]), ("zh", "逗号", ["comma"]),
        ("zh", "撤銷", ["undo"]), ("yo", "Ìpínrọ̀ tuntun.", ["paragraph"]),
        ("yo", "Ipinro tuntun", ["paragraph"]),            # Whisper often drops the tone marks
        ("yo", "àmì ìbéèrè", ["question"]), ("yo", "New line.", ["newline"]),  # English works everywhere
        ("fr", "Stop dictation.", ["stop"])):
    check(f"{lang}: command {said!r}", actions(said, lang), expected)

# ordinary sentences stay text
for lang, said in (("en", "The period of the year was cold."), ("fr", "Le point de vue est clair."),
                   ("fr", "Il faut annuler la réunion."), ("ru", "Точка зрения ясна."),
                   ("zh", "我们明天换行程。"), ("ja", "今日は保存食を買いました。")):
    check(f"{lang}: text {said!r}", v.parse(said, lang), [("text", said)])

# a paragraph command closing a longer utterance
check("fr: trailing paragraph", v.parse("Bonjour à tous, nouveau paragraphe.", "fr"),
      [("text", "Bonjour à tous"), ("action", "paragraph")])
check("en: trailing new line", v.parse("Dear John, new line.", "en"),
      [("text", "Dear John"), ("action", "newline")])
check("zh: trailing paragraph", v.parse("今天天气很好。新段落。", "zh"),
      [("text", "今天天气很好。"), ("action", "paragraph")])
check("commands off", v.parse("Nouveau paragraphe.", "fr", commands=False), [("text", "Nouveau paragraphe.")])
check("user phrase from commands.json", v.parse("Saut de section.", "fr", extra={"fr": {"saut de section": "page_break"}}),
      [("action", "page_break")])

# joining text to what is before the cursor
for label, prev, text, lang, expected in (
        ("start of paragraph capitalised", "", "bonjour.", "fr", "Bonjour."),
        ("space between sentences", "Bonjour.", "Comment ça va ?", "fr", " Comment ça va ?"),
        ("French no-break space before ?", "Vraiment", "?", "fr", " ?"),
        ("French guillemets", "Il a dit", "« Bonjour »", "fr", " « Bonjour »"),
        ("English comma glued", "Hello", ",", "en", ","),
        ("mid-sentence lower case", "I think that", "The weather is fine.", "en", " the weather is fine."),
        ("English I kept", "and then", "I left.", "en", " I left."),
        ("acronym kept", "we use", "NASA data.", "en", " NASA data."),
        ("after a typed space", "Hello ", "world.", "en", "world."),
        ("Japanese: no spaces", "今日は晴れです。", "明日は雨です。", "ja", "明日は雨です。"),
        ("Chinese: no spaces", "今天很好。", "明天下雨。", "zh", "明天下雨。"),
        ("Latin word after Chinese", "我喜欢", "Python。", "zh", "Python。"),
        ("Russian sentence", "Привет.", "как дела?", "ru", " Как дела?"),
        ("Spanish inverted mark", "Hola.", "¿Qué tal?", "es", " ¿Qué tal?"),
        ("Yoruba tone marks kept", "Ẹ káàárọ̀.", "báwo ni?", "yo", " Báwo ni?"),
        ("opening parenthesis", "Voir (", "page deux", "fr", "page deux"),
        ("dash keeps its own spaces", "un mot", " – ", "fr", " – ")):
    check(f"join: {label}", v.join(prev, text, lang), expected)

check("forced capital", v.join("and", "paris", "en", capitalize=True), " Paris")
check("punctuation per language", [v.punctuation("comma", l) for l in ("en", "ja", "zh")], [",", "、", "，"])
check("guillemets per language", [v.punctuation("open_quote", l) for l in ("en", "fr", "ja")], ["“", "«", "「"])
for said in ("Sous-titres réalisés par la communauté d'Amara.org", "Thank you.", "ご視聴ありがとうございました", "..."):
    check(f"hallucination dropped: {said!r}", v.is_hallucination(said), True)
check("real sentence kept", v.is_hallucination("Thank you for the report."), False)
check("kana keep their dakuten", v.normalize("が") != v.normalize("か"), True)

print("\nall checks passed" if not FAILURES else f"\n{len(FAILURES)} check(s) failed")
sys.exit(1 if FAILURES else 0)
