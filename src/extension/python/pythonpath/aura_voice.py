"""Aura dictation: what to do with a recognised utterance (no UNO, shared with the tests).

The recogniser returns one utterance at a time, already punctuated. This module
decides whether the utterance is a voice command ("new paragraph", "virgule",
"改行"...) or text, and how the text joins what is already in the document:
spaces between words except in Japanese and Chinese, a no-break space before
French high punctuation, a capital letter at the start of a sentence.

Commands are matched on the whole utterance (a short pause before and after, as
in every dictation software), in the utterance's language first, then in
English, which works in every language. A paragraph or line command said at the
end of a longer sentence ("... nouveau paragraphe") is split off too.
Users can add or change phrases in $(user)/libreappearance/voice/commands.json:
{"fr": {"saut de page": "page_break"}, "yo": {"ìlà tuntun": "newline"}}.
"""
import re
import unicodedata

# Recognition languages: Whisper code -> (native name, English name)
LANGUAGES = {
    "en": ("English", "English"),
    "fr": ("Français", "French"),
    "es": ("Español", "Spanish"),
    "ru": ("Русский", "Russian"),
    "ja": ("日本語", "Japanese"),
    "yo": ("Èdè Yorùbá", "Yoruba"),
    "zh": ("中文", "Chinese"),
}
NO_SPACE_LANGUAGES = ("ja", "zh")

# What each action inserts or does. Strings are inserted as they are; other
# actions are carried out by the document side (aura_dictation).
PUNCTUATION = {
    "period": {"*": ".", "ja": "。", "zh": "。"},
    "comma": {"*": ",", "ja": "、", "zh": "，"},
    "enumeration_comma": {"*": ",", "ja": "、", "zh": "、"},
    "question": {"*": "?", "ja": "？", "zh": "？"},
    "exclamation": {"*": "!", "ja": "！", "zh": "！"},
    "colon": {"*": ":", "ja": "：", "zh": "："},
    "semicolon": {"*": ";", "ja": "；", "zh": "；"},
    "ellipsis": {"*": "…", "ja": "…", "zh": "……"},
    "open_quote": {"*": "“", "fr": "«", "ru": "«", "es": "«", "ja": "「", "zh": "“"},
    "close_quote": {"*": "”", "fr": "»", "ru": "»", "es": "»", "ja": "」", "zh": "”"},
    "open_paren": {"*": "(", "ja": "（", "zh": "（"},
    "close_paren": {"*": ")", "ja": "）", "zh": "）"},
    "open_question": {"*": "¿"},
    "open_exclamation": {"*": "¡"},
    "dash": {"*": " – ", "ja": "—", "zh": "——"},
    "hyphen": {"*": "-"},
    "apostrophe": {"*": "’"},
}
ACTIONS = ("newline", "paragraph", "page_break", "tab", "delete_last", "undo", "redo", "stop",
           "bold", "italic", "underline", "save", "select_all", "capitalize_next", "space")

# Phrases are written naturally; they are normalised (case, accents, punctuation) before matching.
COMMANDS = {
    "en": {
        "new line": "newline", "next line": "newline", "line break": "newline",
        "new paragraph": "paragraph", "next paragraph": "paragraph",
        "page break": "page_break", "new page": "page_break",
        "tab key": "tab", "press tab": "tab", "insert tab": "tab",
        "delete that": "delete_last", "scratch that": "delete_last", "delete last": "delete_last",
        "undo": "undo", "undo that": "undo", "redo": "redo", "redo that": "redo",
        "stop dictation": "stop", "stop listening": "stop", "end dictation": "stop",
        "bold": "bold", "bold that": "bold", "italic": "italic", "italics": "italic",
        "underline": "underline", "save document": "save", "save the document": "save",
        "select all": "select_all", "cap next": "capitalize_next", "capital next": "capitalize_next",
        "period": "period", "full stop": "period", "comma": "comma", "question mark": "question",
        "exclamation mark": "exclamation", "exclamation point": "exclamation", "colon": "colon",
        "semicolon": "semicolon", "semi colon": "semicolon", "ellipsis": "ellipsis", "dot dot dot": "ellipsis",
        "open quote": "open_quote", "open quotes": "open_quote", "quote": "open_quote",
        "close quote": "close_quote", "close quotes": "close_quote", "end quote": "close_quote",
        "unquote": "close_quote", "open parenthesis": "open_paren", "open bracket": "open_paren",
        "close parenthesis": "close_paren", "close bracket": "close_paren", "dash": "dash",
        "hyphen": "hyphen", "apostrophe": "apostrophe", "space bar": "space",
    },
    "fr": {
        "à la ligne": "newline", "nouvelle ligne": "newline", "retour à la ligne": "newline",
        "ligne suivante": "newline", "nouveau paragraphe": "paragraph", "paragraphe suivant": "paragraph",
        "saut de page": "page_break", "nouvelle page": "page_break", "tabulation": "tab",
        "efface ça": "delete_last", "effacer ça": "delete_last", "supprime ça": "delete_last",
        "supprimer ça": "delete_last", "efface la dernière phrase": "delete_last",
        "annuler": "undo", "annule": "undo", "annule ça": "undo", "rétablir": "redo", "refaire": "redo",
        "arrête la dictée": "stop", "arrêter la dictée": "stop", "fin de la dictée": "stop",
        "stop dictée": "stop", "gras": "bold", "mettre en gras": "bold", "italique": "italic",
        "souligné": "underline", "souligner": "underline", "enregistrer": "save",
        "enregistre le document": "save", "enregistrer le document": "save", "sauvegarder": "save",
        "tout sélectionner": "select_all", "majuscule": "capitalize_next",
        "point": "period", "point final": "period", "virgule": "comma",
        "point d'interrogation": "question", "point d'exclamation": "exclamation",
        "deux points": "colon", "deux-points": "colon", "point virgule": "semicolon",
        "point-virgule": "semicolon", "points de suspension": "ellipsis",
        "ouvrez les guillemets": "open_quote", "ouvrir les guillemets": "open_quote",
        "ouvre les guillemets": "open_quote", "fermez les guillemets": "close_quote",
        "fermer les guillemets": "close_quote", "ferme les guillemets": "close_quote",
        "ouvrez la parenthèse": "open_paren", "ouvrir la parenthèse": "open_paren",
        "ouvre la parenthèse": "open_paren", "fermez la parenthèse": "close_paren",
        "fermer la parenthèse": "close_paren", "ferme la parenthèse": "close_paren",
        "tiret": "dash", "trait d'union": "hyphen", "apostrophe": "apostrophe", "espace": "space",
    },
    "es": {
        "nueva línea": "newline", "nueva linea": "newline", "salto de línea": "newline",
        "nuevo párrafo": "paragraph", "punto y aparte": ["period", "paragraph"],
        "salto de página": "page_break", "tabulación": "tab", "tabulador": "tab",
        "borrar eso": "delete_last", "borra eso": "delete_last", "elimina eso": "delete_last",
        "deshacer": "undo", "deshaz": "undo", "rehacer": "redo",
        "detener dictado": "stop", "parar dictado": "stop", "terminar dictado": "stop",
        "negrita": "bold", "cursiva": "italic", "subrayado": "underline", "subrayar": "underline",
        "guardar": "save", "guardar documento": "save", "seleccionar todo": "select_all",
        "mayúscula": "capitalize_next",
        "punto": "period", "punto final": "period", "punto y seguido": "period", "coma": "comma",
        "signo de interrogación": "question", "cerrar interrogación": "question",
        "abrir interrogación": "open_question", "signo de exclamación": "exclamation",
        "cerrar exclamación": "exclamation", "abrir exclamación": "open_exclamation",
        "dos puntos": "colon", "punto y coma": "semicolon", "puntos suspensivos": "ellipsis",
        "abrir comillas": "open_quote", "abre comillas": "open_quote", "cerrar comillas": "close_quote",
        "cierra comillas": "close_quote", "abrir paréntesis": "open_paren", "abre paréntesis": "open_paren",
        "cerrar paréntesis": "close_paren", "cierra paréntesis": "close_paren",
        "guion": "dash", "raya": "dash", "apóstrofo": "apostrophe", "espacio": "space",
    },
    "ru": {
        "новая строка": "newline", "с новой строки": "newline", "перенос строки": "newline",
        "новый абзац": "paragraph", "абзац": "paragraph", "новая страница": "page_break",
        "табуляция": "tab", "удалить это": "delete_last", "удали это": "delete_last",
        "стереть это": "delete_last", "сотри это": "delete_last",
        "отменить": "undo", "отмена": "undo", "повторить": "redo", "вернуть": "redo",
        "остановить диктовку": "stop", "стоп диктовка": "stop", "закончить диктовку": "stop",
        "жирный": "bold", "полужирный": "bold", "курсив": "italic", "подчеркнуть": "underline",
        "подчёркнутый": "underline", "сохранить": "save", "сохранить документ": "save",
        "выделить всё": "select_all", "с большой буквы": "capitalize_next",
        "точка": "period", "запятая": "comma", "вопросительный знак": "question",
        "восклицательный знак": "exclamation", "двоеточие": "colon", "точка с запятой": "semicolon",
        "многоточие": "ellipsis", "открыть кавычки": "open_quote", "открыть кавычку": "open_quote",
        "закрыть кавычки": "close_quote", "закрыть кавычку": "close_quote",
        "открыть скобку": "open_paren", "закрыть скобку": "close_paren", "тире": "dash",
        "дефис": "hyphen", "апостроф": "apostrophe", "пробел": "space",
    },
    "ja": {
        "改行": "newline", "次の行": "newline", "新しい段落": "paragraph", "段落": "paragraph",
        "改段落": "paragraph", "改ページ": "page_break", "タブ": "tab",
        "削除": "delete_last", "今のを消して": "delete_last", "消して": "delete_last",
        "元に戻す": "undo", "取り消し": "undo", "やり直し": "redo",
        "音声入力停止": "stop", "ディクテーション停止": "stop", "入力終了": "stop",
        "太字": "bold", "斜体": "italic", "イタリック": "italic", "下線": "underline",
        "保存": "save", "保存して": "save", "全て選択": "select_all", "すべて選択": "select_all",
        "まる": "period", "丸": "period", "句点": "period", "てん": "comma", "点": "comma",
        "読点": "comma", "はてな": "question", "疑問符": "question", "クエスチョンマーク": "question",
        "びっくりマーク": "exclamation", "感嘆符": "exclamation", "コロン": "colon",
        "セミコロン": "semicolon", "三点リーダー": "ellipsis",
        "かぎかっこ": "open_quote", "かぎ括弧": "open_quote", "かぎかっこ閉じ": "close_quote",
        "かぎ括弧閉じ": "close_quote", "かっこ": "open_paren", "括弧": "open_paren",
        "かっこ閉じ": "close_paren", "括弧閉じ": "close_paren", "ダッシュ": "dash", "スペース": "space",
    },
    "zh": {
        "换行": "newline", "換行": "newline", "下一行": "newline",
        "新段落": "paragraph", "另起一段": "paragraph", "分段": "paragraph",
        "分页": "page_break", "分頁": "page_break", "制表符": "tab",
        "删除": "delete_last", "刪除": "delete_last", "删掉": "delete_last", "刪掉": "delete_last",
        "撤销": "undo", "撤銷": "undo", "重做": "redo",
        "停止听写": "stop", "停止聽寫": "stop", "结束听写": "stop", "結束聽寫": "stop",
        "加粗": "bold", "粗体": "bold", "粗體": "bold", "斜体": "italic", "斜體": "italic",
        "下划线": "underline", "底線": "underline", "保存": "save", "儲存": "save",
        "全选": "select_all", "全選": "select_all",
        "句号": "period", "句號": "period", "逗号": "comma", "逗號": "comma",
        "顿号": "enumeration_comma", "頓號": "enumeration_comma", "问号": "question", "問號": "question",
        "感叹号": "exclamation", "感嘆號": "exclamation", "冒号": "colon", "冒號": "colon",
        "分号": "semicolon", "分號": "semicolon", "省略号": "ellipsis", "省略號": "ellipsis",
        "左引号": "open_quote", "左引號": "open_quote", "右引号": "close_quote", "右引號": "close_quote",
        "左括号": "open_paren", "左括號": "open_paren", "右括号": "close_paren", "右括號": "close_paren",
        "破折号": "dash", "破折號": "dash", "空格": "space",
    },
    # Standard Yoruba; to be enriched by native speakers through commands.json
    "yo": {
        "ìlà tuntun": "newline", "ìlà míràn": "newline",
        "ìpínrọ̀ tuntun": "paragraph", "ojú ìwé tuntun": "page_break",
        "pa á rẹ́": "delete_last", "pa ìyẹn rẹ́": "delete_last",
        "dá a padà": "undo", "ṣe é padà": "redo",
        "dá ìkọ̀wé dúró": "stop", "dúró": "stop",
        "fi pamọ́": "save", "fipamọ́": "save",
        "àmì ìdánudúró": "period", "àmì ìdánudúró díẹ̀": "comma",
        "àmì ìbéèrè": "question", "àmì ìyanu": "exclamation",
    },
}
# Structural commands that may also close a longer utterance ("... new paragraph")
TRAILING = ("newline", "paragraph", "page_break")

# Whisper's well-known hallucinations on silence or noise, dropped when they are the whole utterance
HALLUCINATIONS = {
    "thank you", "thanks for watching", "thank you for watching", "you", "bye",
    "sous-titres réalisés par la communauté d'amara.org", "sous-titrage st' 501",
    "merci d'avoir regardé cette vidéo", "merci", "subtítulos realizados por la comunidad de amara.org",
    "gracias por ver el video", "редактор субтитров а.семкин корректор а.егорова",
    "продолжение следует", "ご視聴ありがとうございました", "字幕由amara.org社区提供",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "謝謝觀看", "谢谢观看",
}

_PUNCT = re.compile(r"[\s\.,;:!?¿¡…\"'“”«»„‚‘’()\[\]{}\-–—。、，！？：；「」『』（）《》〈〉·・～~]+")
SENTENCE_END = ".!?…。！？"
OPENERS = "([{«“‘„¿¡「『（《〈\"'"
NO_SPACE_BEFORE = ",.;:!?…)]}»”’%。、，！？：；」』）》〉"
FRENCH_HIGH = ";:!?»"
FRENCH_AFTER_OPEN = "«"


def _is_cjk(ch):
    o = ord(ch)
    return (0x3000 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF or 0x20000 <= o <= 0x2FA1F)


def normalize(text):
    """Comparable form of a phrase: lower case, no accents or tone marks (but kana keep
    their dakuten), no punctuation, single spaces."""
    text = unicodedata.normalize("NFKC", text).lower()
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if unicodedata.combining(ch) and out and not _is_cjk(out[-1]):
            continue
        out.append(ch)
    text = unicodedata.normalize("NFC", "".join(out)).replace("ё", "е")
    return _PUNCT.sub(" ", text).strip()


def _key(text):
    """Matching key: normalised, and without spaces at all for Japanese and Chinese."""
    norm = normalize(text)
    return norm.replace(" ", "") if norm and all(_is_cjk(c) or c == " " for c in norm) else norm


def command_table(language, extra=None):
    """{matching key: [actions]} for a language, English last (it works everywhere)."""
    table = {}
    for lang in ("en", language):
        phrases = dict(COMMANDS.get(lang, {}))
        phrases.update((extra or {}).get(lang, {}))
        for phrase, action in phrases.items():
            actions = action if isinstance(action, list) else [action]
            if all(a in ACTIONS or a in PUNCTUATION for a in actions) and _key(phrase):
                table[_key(phrase)] = actions
    return table


def is_hallucination(text):
    return normalize(text) in {normalize(h) for h in HALLUCINATIONS} or not normalize(text)


def parse(text, language, commands=True, extra=None):
    """Split an utterance into steps: [("text", str) | ("action", name)]."""
    text = text.strip()
    if not text:
        return []
    if not commands:
        return [("text", text)]
    table = command_table(language, extra)
    key = _key(text)
    if key in table:
        return [("action", a) for a in table[key]]
    # "... nouveau paragraphe": a structural command closing a longer utterance
    words = normalize(text).split(" ")
    for size in (4, 3, 2):
        if len(words) > size:
            tail = " ".join(words[-size:])
            actions = table.get(tail)
            if actions and all(a in TRAILING or a in PUNCTUATION for a in actions) and \
                    any(a in TRAILING for a in actions):
                body = _strip_tail(text, size)
                if body:
                    return [("text", body)] + [("action", a) for a in actions]
    if language in NO_SPACE_LANGUAGES:
        for phrase_key, actions in table.items():
            if len(phrase_key) >= 2 and key.endswith(phrase_key) and len(key) > len(phrase_key) and \
                    any(a in TRAILING for a in actions) and all(a in TRAILING for a in actions):
                body = _strip_cjk_tail(text, phrase_key)
                if body:
                    return [("text", body)] + [("action", a) for a in actions]
    return [("text", text)]


def _strip_tail(text, words):
    """text without its last `words` words (and the punctuation around them)."""
    tokens = re.findall(r"\S+", text)
    body = " ".join(tokens[:-words])
    return body.rstrip(" ,;:")


def _strip_cjk_tail(text, phrase_key):
    stripped = text.rstrip("".join(set(SENTENCE_END + "，、 ")))
    pos = len(stripped)
    seen = ""
    while pos > 0 and len(seen) < len(phrase_key):
        pos -= 1
        if stripped[pos] not in " ，、":
            seen = stripped[pos] + seen
    return stripped[:pos].rstrip("，、, ")


def punctuation(action, language):
    marks = PUNCTUATION.get(action)
    return None if marks is None else marks.get(language, marks["*"])


def join(previous, text, language, capitalize=None):
    """The string to insert after `previous` (the text just before the cursor).

    capitalize: True / False forces the first letter; None decides from `previous`.
    """
    if not text:
        return ""
    prev = previous.rstrip(" \t  ")
    last = prev[-1:] if prev else ""
    first = text[0]
    at_start = not prev or previous.endswith(("\n", "\r", "\t"))
    if capitalize is None:
        capitalize = at_start or (last in SENTENCE_END) or (last in "»”\"" and prev[-2:-1] in SENTENCE_END)
        if capitalize is False and last and language not in NO_SPACE_LANGUAGES:
            text = _decapitalize(text, language)
    if capitalize:
        text = text[0].upper() + text[1:] if first.isalpha() else text
    # spacing
    space = ""
    previous_spaced = previous[-1:] in (" ", "\t", " ", " ") or at_start or first.isspace()
    if not previous_spaced and last:
        cjk_join = language in NO_SPACE_LANGUAGES or _is_cjk(last) or _is_cjk(first)
        if language == "fr" and first in FRENCH_HIGH:
            space = " "
        elif first in NO_SPACE_BEFORE or last in OPENERS or cjk_join:
            space = " " if language == "fr" and last == FRENCH_AFTER_OPEN else ""
        else:
            space = " "
    elif language == "fr" and first in FRENCH_HIGH and previous[-1:] == " ":
        space = ""   # the user typed a normal space: keep it
    if language == "fr" and first == "«" and len(text) > 1 and text[1] == " ":
        text = "« " + text[2:]
    return space + text


def _decapitalize(text, language):
    """Whisper capitalises each utterance; in the middle of a sentence lower the first
    word, unless it looks like a name or an acronym (or is English 'I')."""
    m = re.match(r"(\w)(\w*)", text)
    if not m:
        return text
    word = m.group(0)
    if len(word) > 1 and word[1:].lower() != word[1:]:
        return text          # ACRONYM or CamelCase
    if language == "en" and word in ("I", "I'm", "I've", "I'll", "I'd"):
        return text
    if word[0].isupper():
        return text[0].lower() + text[1:]
    return text
