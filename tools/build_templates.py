"""Build the Aura document templates (Writer, Calc, Impress) with LibreOffice itself.

Runs a private headless LibreOffice (its own throw-away profile), styles new
documents through UNO from design/tokens.json and stores them as ODF
templates. With --samples it also writes filled example documents and their
PDF exports, used to review the design.

Needs a Python that can `import uno` (on Debian/Ubuntu: /usr/bin/python3).
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue
from com.sun.star.connection import NoConnectException
from com.sun.star.lang import Locale
from com.sun.star.style import LineSpacing
from com.sun.star.table import BorderLine2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tokens import load_tokens, lo_color  # noqa: E402

TOK = load_tokens()
D = TOK["document"]
T = TOK["typography"]
C = {k: lo_color(v) for k, v in D.items()}

BOLD, NORMAL = 150.0, 100.0  # com.sun.star.awt.FontWeight
LEFT, RIGHT, CENTER = 0, 1, 3  # com.sun.star.style.ParagraphAdjust


def props(**kw):
    out = []
    for k, v in kw.items():
        p = PropertyValue()
        p.Name, p.Value = k, v
        out.append(p)
    return tuple(out)


def line(color, width=18):
    b = BorderLine2()
    b.Color, b.LineWidth, b.OuterLineWidth, b.LineStyle = color, width, width, 0
    return b


NO_LINE = BorderLine2()


def setp(obj, **kw):
    for k, v in kw.items():
        obj.setPropertyValue(k, v)


# --------------------------------------------------------------- office I/O
class Office:
    def __init__(self, soffice, profile=None):
        self.profile = Path(profile) if profile else Path(tempfile.mkdtemp(prefix="aura-lo-"))
        self.pipe = f"aura_build_{os.getpid()}"
        self.proc = subprocess.Popen([
            soffice, "--headless", "--invisible", "--norestore", "--nologo", "--nodefault",
            f"-env:UserInstallation={self.profile.as_uri()}",
            f"--accept=pipe,name={self.pipe};urp;StarOffice.ComponentContext",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local)
        for _ in range(120):
            try:
                self.ctx = resolver.resolve(
                    f"uno:pipe,name={self.pipe};urp;StarOffice.ComponentContext")
                break
            except NoConnectException:
                time.sleep(0.5)
        else:
            raise RuntimeError("LibreOffice did not start")
        self.desktop = self.ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", self.ctx)

    def new(self, kind):
        return self.desktop.loadComponentFromURL(f"private:factory/{kind}", "_blank", 0,
                                                 props(Hidden=True))

    def close(self):
        try:
            self.desktop.terminate()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)


def store(doc, path, flt):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.storeToURL(path.resolve().as_uri(), props(FilterName=flt, Overwrite=True))
    print(f"  {path}")


def metadata(doc, title, description):
    p = doc.DocumentProperties
    p.Title, p.Description, p.Author = title, description, "Aura"


# ------------------------------------------------------------------ Writer
def writer_styles(doc):
    paras = doc.StyleFamilies.getByName("ParagraphStyles")
    chars = doc.StyleFamilies.getByName("CharacterStyles")
    pages = doc.StyleFamilies.getByName("PageStyles")

    def para(name, parent="Standard", **kw):
        if not paras.hasByName(name):
            st = doc.createInstance("com.sun.star.style.ParagraphStyle")
            paras.insertByName(name, st)
            if parent:
                st.ParentStyle = parent
        st = paras.getByName(name)
        setp(st, **kw)
        return st

    spacing = lambda pct: LineSpacing(0, pct)  # noqa: E731

    para("Standard", CharFontName=T["sans"], CharHeight=10.5, CharColor=C["text"],
         ParaLineSpacing=spacing(150), ParaBottomMargin=0, ParaTopMargin=0,
         ParaOrphans=2, ParaWidows=2, ParaIsHyphenation=False)
    for name in ("Text body", "List", "Index", "Caption", "Table Contents", "Header", "Footer",
                 "Footnote", "Endnote", "List Contents", "Signature", "Salutation"):
        if paras.hasByName(name):
            para(name, CharFontName=T["sans"])
    para("Text body", ParaBottomMargin=260, ParaTopMargin=0, ParaLineSpacing=spacing(150))
    para("Heading", CharFontName=T["displaySemibold"], CharColor=C["ink"], ParaTopMargin=600,
         ParaBottomMargin=180, ParaKeepTogether=True, ParaSplit=False,
         ParaLineSpacing=spacing(115), CharWeight=NORMAL)
    para("Title", CharFontName=T["display"], CharHeight=32, CharWeight=BOLD, CharColor=C["ink"],
         CharKerning=-35, ParaAdjust=LEFT, ParaTopMargin=0, ParaBottomMargin=160,
         ParaLineSpacing=spacing(105))
    para("Subtitle", CharFontName=T["sans"], CharHeight=14, CharWeight=NORMAL, CharColor=C["muted"],
         ParaAdjust=LEFT, ParaTopMargin=0, ParaBottomMargin=900, ParaLineSpacing=spacing(130))
    sizes = {1: (20, -20, 800, 200), 2: (15, -10, 600, 160), 3: (12.5, 0, 500, 120),
             4: (11, 0, 400, 100), 5: (10.5, 0, 300, 80), 6: (10.5, 0, 300, 80)}
    for lvl, (size, kern, top, bottom) in sizes.items():
        para(f"Heading {lvl}", CharHeight=size, CharKerning=kern, CharWeight=NORMAL,
             CharFontName=T["displaySemibold"] if lvl <= 2 else T["sansSemibold"],
             CharColor=C["ink"], ParaTopMargin=top, ParaBottomMargin=bottom,
             CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    para("Heading 3", CharColor=C["accent"])
    para("Heading 5", CharColor=C["muted"])
    para("Heading 6", CharColor=C["muted"], CharCaseMap=1, CharHeight=9, CharKerning=40)

    para("Quotations", CharHeight=12, CharColor=C["text"], ParaLeftMargin=0, ParaRightMargin=0,
         LeftBorder=line(C["accent"], 53), LeftBorderDistance=450, ParaTopMargin=300,
         ParaBottomMargin=400, ParaLineSpacing=spacing(145),
         CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    para("Preformatted Text", CharFontName=T["mono"], CharHeight=9, CharColor=C["ink"],
         ParaBackColor=C["surface"], ParaBackTransparent=False,
         LeftBorder=line(C["hairline"]), RightBorder=line(C["hairline"]),
         TopBorder=line(C["hairline"]), BottomBorder=line(C["hairline"]),
         BorderDistance=250, ParaLineSpacing=spacing(135), ParaBottomMargin=300)
    para("Header", CharHeight=8.5, CharColor=C["subtle"])
    para("Footer", CharHeight=8.5, CharColor=C["subtle"])
    para("Caption", CharHeight=9, CharColor=C["muted"], ParaTopMargin=120, ParaBottomMargin=300,
         CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    para("Table Contents", CharHeight=9.5, ParaLineSpacing=spacing(125), ParaTopMargin=60,
         ParaBottomMargin=60)
    para("Table Heading", CharHeight=8, CharWeight=NORMAL, CharFontName=T["sansSemibold"], CharColor=C["muted"], CharCaseMap=1,
         CharKerning=40, ParaAdjust=LEFT,
         CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    para("List 1", "List", ParaBottomMargin=100, ParaLineSpacing=spacing(145),
         NumberingStyleName="List 1")
    para("Footnote", CharHeight=8.5, CharColor=C["muted"], ParaLineSpacing=spacing(130))

    # Aura-specific paragraph styles
    para("Aura Eyebrow", "Standard", CharHeight=8.5, CharFontName=T["sansSemibold"], CharColor=C["accent"],
         CharCaseMap=1, CharKerning=60, ParaBottomMargin=200)
    para("Aura Lead", "Text body", CharHeight=13, CharColor=C["muted"],
         ParaLineSpacing=spacing(145), ParaBottomMargin=400)
    para("Aura Callout", "Text body", ParaBackColor=C["accentSoft"], ParaBackTransparent=False,
         LeftBorder=line(C["accent"], 53), LeftBorderDistance=400, RightBorderDistance=400,
         TopBorderDistance=250, BottomBorderDistance=250, CharColor=C["accentStrong"],
         ParaTopMargin=200, ParaBottomMargin=400)
    para("Aura Metric", "Standard", CharFontName=T["display"], CharHeight=26, CharWeight=BOLD,
         CharColor=C["ink"], CharKerning=-30, ParaLineSpacing=spacing(100))
    para("Aura Small", "Standard", CharHeight=8.5, CharColor=C["muted"])

    def char(name, **kw):
        if not chars.hasByName(name):
            chars.insertByName(name, doc.createInstance("com.sun.star.style.CharacterStyle"))
        setp(chars.getByName(name), **kw)

    char("Strong Emphasis", CharFontName=T["sansSemibold"], CharColor=C["ink"])
    char("Internet link", CharColor=C["accent"], CharUnderline=0)
    char("Visited Internet Link", CharColor=lo_color("#6D28D9"), CharUnderline=0)
    char("Source Text", CharFontName=T["mono"], CharHeight=9, CharColor=C["accentStrong"],
         CharBackColor=C["accentSoft"], CharBackTransparent=False)
    char("Aura Highlight", CharBackColor=lo_color("#FEF3C7"), CharBackTransparent=False)
    char("Aura Muted", CharColor=C["muted"])

    page = pages.getByName("Standard")
    setp(page, Width=21000, Height=29700, LeftMargin=2200, RightMargin=2200,
         TopMargin=2000, BottomMargin=1500, FooterIsOn=True, FooterBodyDistance=700,
         FooterIsDynamicHeight=True)
    footer = page.FooterText
    footer.setString("")
    cursor = footer.createTextCursor()
    cursor.ParaStyleName = "Footer"
    cursor.ParaAdjust = RIGHT
    field = doc.createInstance("com.sun.star.text.TextField.PageNumber")
    field.NumberingType = 4  # ARABIC
    field.SubType = uno.Enum("com.sun.star.text.PageNumberType", "CURRENT")
    footer.insertTextContent(cursor, field, False)

    first = pages.getByName("First Page")
    setp(first, Width=21000, Height=29700, LeftMargin=2200, RightMargin=2200,
         TopMargin=3200, BottomMargin=1500, FooterIsOn=False, HeaderIsOn=False)

    # Lists: accent-coloured bullets, airy indents
    lists = doc.StyleFamilies.getByName("NumberingStyles")
    for name in ("List 1", "Numbering 123"):
        if not lists.hasByName(name):
            continue
        st = lists.getByName(name)
        rules = st.NumberingRules
        for lvl in range(rules.Count):
            wanted = {"BulletColor": C["accent"], "IndentAt": 600 * (lvl + 1),
                      "FirstLineIndent": -450}
            if name == "List 1":
                wanted["BulletChar"] = "•" if lvl % 2 == 0 else "–"
            level = {p.Name: p.Value for p in rules.getByIndex(lvl)}
            changes = {k: v for k, v in wanted.items() if k in level}
            uno.invoke(rules, "replaceByIndex",
                       (lvl, uno.Any("[]com.sun.star.beans.PropertyValue", props(**changes))))
        st.NumberingRules = rules

    settings = doc.createInstance("com.sun.star.text.DocumentSettings")
    settings.setPropertyValue("AddParaTableSpacing", True)


def writer_table(doc, text, cursor, rows):
    table = doc.createInstance("com.sun.star.text.TextTable")
    table.initialize(len(rows), len(rows[0]))
    text.insertTextContent(cursor, table, False)
    table.HoriOrient = 0  # FULL
    table.BackTransparent = True
    names = table.getCellNames()
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = table.getCellByName(names[r * len(row) + c])
            cur = cell.createTextCursor()
            cur.ParaStyleName = "Table Heading" if r == 0 else "Table Contents"
            if c > 0 and r > 0 and any(ch.isdigit() for ch in value):
                cur.ParaAdjust = RIGHT
            elif c > 0 and r == 0:
                cur.ParaAdjust = RIGHT
            cell.setString(value)
            bottom = line(C["hairline"]) if r else line(lo_color("#CBD5E1"), 26)
            setp(cell, TopBorder=NO_LINE, LeftBorder=NO_LINE, RightBorder=NO_LINE,
                 BottomBorder=bottom, TopBorderDistance=110, BottomBorderDistance=110,
                 LeftBorderDistance=0 if c == 0 else 150, RightBorderDistance=0)
            if r == 0:
                cell.BackTransparent = True
    return table


def writer_sample(doc):
    text = doc.Text
    cur = text.createTextCursor()

    def p(style, content=""):
        cur.ParaStyleName = style
        text.insertString(cur, content, False)
        text.insertControlCharacter(cur, 0, False)  # PARAGRAPH_BREAK

    cur.PageDescName = "First Page"
    p("Aura Eyebrow", "Rapport trimestriel · T3 2026")
    p("Title", "Une croissance maîtrisée, une équipe recentrée")
    p("Subtitle", "Synthèse des résultats, priorités du prochain trimestre et indicateurs clés "
                  "pour le comité de direction.")
    p("Aura Lead", "Le troisième trimestre confirme la trajectoire engagée en début d'année : "
                   "les revenus récurrents progressent, la marge opérationnelle se stabilise et "
                   "le délai de livraison moyen recule de neuf jours.")
    p("Heading 1", "Faits marquants")
    p("Text body", "Le lancement de l'offre Entreprise a dépassé les objectifs fixés, porté par "
                   "trois contrats signés dans le secteur public. Les équipes produit ont livré "
                   "quatorze améliorations majeures, dont la refonte complète de l'export.")
    p("List 1", "Revenus récurrents annuels : 4,8 M€ (+18 % sur un an)")
    p("List 1", "Taux de rétention net : 112 %")
    p("List 1", "Satisfaction client (NPS) : 61, en hausse de 7 points")
    p("Heading 2", "Indicateurs clés")
    p("Text body", "Les indicateurs ci-dessous comparent le trimestre écoulé au précédent.")
    writer_table(doc, text, cur, [
        ["Indicateur", "T2 2026", "T3 2026", "Évolution"],
        ["Revenus récurrents", "4,52 M€", "4,80 M€", "+6,2 %"],
        ["Marge opérationnelle", "17,4 %", "18,1 %", "+0,7 pt"],
        ["Clients actifs", "1 284", "1 362", "+78"],
        ["Délai de livraison", "31 j", "22 j", "−9 j"],
    ])
    p("Caption", "Tableau 1 — Indicateurs consolidés, périmètre groupe.")
    p("Aura Callout", "À retenir : la hausse de la marge provient pour moitié de l'automatisation "
                      "du support de niveau 1, déployée en juillet.")
    p("Heading 2", "Priorités du quatrième trimestre")
    p("Heading 3", "Industrialiser l'offre Entreprise")
    p("Text body", "Standardiser l'intégration, documenter les parcours d'administration et "
                   "former deux équipes partenaires.")
    p("Quotations", "« Nous avons gagné en vitesse sans rien céder sur la qualité ; c'est "
                    "exactement l'équilibre que nous recherchions. »")
    p("Heading 3", "Réduire la dette technique")
    p("Text body", "Migrer le moteur de rendu, supprimer les dépendances obsolètes et viser une "
                   "couverture de tests de 85 %.")
    p("Preformatted Text", "aura build --target production --report q3-2026.pdf")
    p("Aura Small", "Document interne — diffusion restreinte au comité de direction.")
    with_lists(doc)


def with_lists(doc):
    """Attach the bullet list style to 'List Bullet' paragraphs."""
    enum = doc.Text.createEnumeration()
    while enum.hasMoreElements():
        par = enum.nextElement()
        if par.supportsService("com.sun.star.text.Paragraph") and par.ParaStyleName == "List 1":
            par.NumberingStyleName = "List 1"


def build_writer(office, out, samples):
    doc = office.new("swriter")
    writer_styles(doc)
    metadata(doc, "Aura — Document", "Modèle Writer Aura : typographie Inter, styles Premium.")
    store(doc, out / "aura-document.ott", "writer8_template")
    if samples:
        writer_sample(doc)
        metadata(doc, "Aura — Rapport", "Exemple de rapport Aura.")
        store(doc, out / "aura-rapport.ott", "writer8_template")
        store(doc, samples / "aura-rapport.odt", "writer8")
        store(doc, samples / "aura-rapport.pdf", "writer_pdf_Export")
    doc.close(True)


# -------------------------------------------------------------------- Calc
def calc_styles(doc):
    cells = doc.StyleFamilies.getByName("CellStyles")
    formats = doc.NumberFormats
    loc = Locale("fr", "FR", "")

    def fmt(code):
        key = formats.queryKey(code, loc, False)
        return key if key != -1 else formats.addNew(code, loc)

    def style(name, parent="Default", **kw):
        if not cells.hasByName(name):
            cells.insertByName(name, doc.createInstance("com.sun.star.style.CellStyle"))
            cells.getByName(name).ParentStyle = parent
        setp(cells.getByName(name), **kw)

    style("Default", CharFontName=T["sans"], CharHeight=10, CharColor=C["text"],
          VertJustify=2)  # com.sun.star.table.CellVertJustify2.CENTER
    style("Heading", CharFontName=T["display"], CharHeight=20, CharWeight=BOLD, CharColor=C["ink"])
    style("Heading 1", CharFontName=T["displaySemibold"], CharHeight=14,
          CharColor=C["ink"])
    style("Heading 2", CharHeight=10, CharFontName=T["sansSemibold"], CharColor=C["accent"],
          CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    style("Text", CharColor=C["text"])
    style("Note", CellBackColor=lo_color("#FFFBEB"), CharColor=lo_color("#92400E"),
          TopBorder=line(lo_color("#FDE68A")), BottomBorder=line(lo_color("#FDE68A")),
          LeftBorder=line(lo_color("#FDE68A")), RightBorder=line(lo_color("#FDE68A")))
    style("Footnote", CharHeight=8, CharColor=C["muted"],
          CharPosture=uno.Enum("com.sun.star.awt.FontSlant", "NONE"))
    style("Hyperlink", CharColor=C["accent"], CharUnderline=0)
    style("Accent", CharFontName=T["sansSemibold"], CharColor=C["ink"])
    style("Accent 1", CharFontName=T["sansSemibold"], CharColor=lo_color("#FFFFFF"), CellBackColor=C["ink"])
    style("Accent 2", CharFontName=T["sansSemibold"], CharColor=lo_color("#FFFFFF"), CellBackColor=C["accent"])
    style("Accent 3", CharFontName=T["sansSemibold"], CharColor=C["accentStrong"], CellBackColor=C["accentSoft"])
    style("Good", CharColor=C["success"], CellBackColor=C["successSoft"])
    style("Bad", CharColor=C["danger"], CellBackColor=C["dangerSoft"])
    style("Neutral", CharColor=C["warning"], CellBackColor=C["warningSoft"])
    style("Error", CharColor=C["danger"], CharFontName=T["sansSemibold"], CellBackColor=C["dangerSoft"])
    style("Warning", CharColor=C["warning"], CellBackColor=C["warningSoft"])
    style("Result", CharFontName=T["sansSemibold"], CharColor=C["ink"], TopBorder=line(C["ink"], 26),
          CharUnderline=0)

    style("Aura Header", CharHeight=8, CharFontName=T["sansSemibold"], CharColor=C["muted"],
          CellBackColor=C["surface"], BottomBorder=line(lo_color("#CBD5E1"), 26))
    style("Aura Row", BottomBorder=line(C["hairline"]))
    style("Aura Number", "Aura Row", NumberFormat=fmt("# ##0,00"), HoriJustify=uno.Enum(
        "com.sun.star.table.CellHoriJustify", "RIGHT"))
    style("Aura Integer", "Aura Row", NumberFormat=fmt("# ##0"), HoriJustify=uno.Enum(
        "com.sun.star.table.CellHoriJustify", "RIGHT"))
    style("Aura Currency", "Aura Row", NumberFormat=fmt("# ##0,00 [$€-40C]"), HoriJustify=uno.Enum(
        "com.sun.star.table.CellHoriJustify", "RIGHT"))
    style("Aura Percent", "Aura Row", NumberFormat=fmt("0,0%"), HoriJustify=uno.Enum(
        "com.sun.star.table.CellHoriJustify", "RIGHT"))
    style("Aura Date", "Aura Row", NumberFormat=fmt("JJ/MM/AAAA"), HoriJustify=uno.Enum(
        "com.sun.star.table.CellHoriJustify", "RIGHT"))
    style("Aura Total", "Aura Currency", CharFontName=T["sansSemibold"], CharColor=C["ink"],
          TopBorder=line(C["ink"], 26), BottomBorder=NO_LINE)
    style("Aura KPI", CharFontName=T["display"], CharHeight=22, CharWeight=BOLD, CharColor=C["ink"],
          HoriJustify=uno.Enum("com.sun.star.table.CellHoriJustify", "LEFT"))
    style("Aura Label", CharHeight=8, CharFontName=T["sansSemibold"], CharColor=C["muted"])

    pages = doc.StyleFamilies.getByName("PageStyles")
    for name in pages.getElementNames():
        page = pages.getByName(name)
        setp(page, LeftMargin=1500, RightMargin=1500, TopMargin=1500, BottomMargin=1500,
             HeaderIsOn=False)


def calc_sample(doc):
    sheet = doc.Sheets.getByIndex(0)
    sheet.Name = "Synthèse"
    cell = lambda ref: sheet.getCellRangeByName(ref)  # noqa: E731
    cols = sheet.Columns
    for i, w in enumerate([600, 5200, 3200, 3200, 3200, 3400]):
        cols.getByIndex(i).Width = w
    sheet.Rows.Height = 620
    sheet.Rows.getByIndex(1).Height = 1100

    def put(ref, value, st):
        c = cell(ref)
        if isinstance(value, str) and not value.startswith("="):
            c.String = value
        elif isinstance(value, str):
            c.Formula = value
        else:
            c.Value = value
        c.CellStyle = st

    put("B2", "Ventes par région", "Heading")
    put("B3", "Exercice 2026 · montants hors taxes", "Footnote")
    put("B5", "CHIFFRE D'AFFAIRES", "Aura Label")
    put("D5", "CROISSANCE", "Aura Label")
    put("B6", "=SUM(E10:E14)", "Aura KPI")
    cell("B6").NumberFormat = doc.NumberFormats.addNew("# ##0 [$€-40C]", Locale("fr", "FR", ""))
    put("D6", 0.142, "Aura KPI")
    cell("D6").NumberFormat = doc.NumberFormats.addNew("+0,0%", Locale("fr", "FR", ""))
    headers = ["Région", "T1", "T2", "T3", "Total"]
    for col, h in zip("BCDEF", headers):
        put(f"{col}9", h, "Aura Header")
    cell("C9:F9").HoriJustify = uno.Enum("com.sun.star.table.CellHoriJustify", "RIGHT")
    data = [("Île-de-France", 412300, 438900, 471200), ("Auvergne-Rhône-Alpes", 233400, 251800, 262300),
            ("Nouvelle-Aquitaine", 158700, 149200, 171900), ("Occitanie", 141900, 156400, 168800),
            ("Hauts-de-France", 118200, 124700, 131500)]
    for i, (region, *vals) in enumerate(data, start=10):
        put(f"B{i}", region, "Aura Row")
        for col, v in zip("CDE", vals):
            put(f"{col}{i}", v, "Aura Currency")
        put(f"F{i}", f"=SUM(C{i}:E{i})", "Aura Currency")
    put("B15", "Total", "Aura Total")
    cell("B15").HoriJustify = uno.Enum("com.sun.star.table.CellHoriJustify", "LEFT")
    for col in "CDEF":
        put(f"{col}15", f"=SUM({col}10:{col}14)", "Aura Total")
    cell("B6").Formula = "=F15"
    put("B17", "Objectif atteint", "Good")
    put("C17", "Sous l'objectif", "Bad")
    put("D17", "À surveiller", "Neutral")
    put("E17", "Mise en avant", "Accent 3")
    put("F17", "Titre", "Accent 2")


def build_calc(office, out, samples):
    doc = office.new("scalc")
    calc_styles(doc)
    metadata(doc, "Aura — Classeur", "Modèle Calc Aura : styles de cellules Premium.")
    store(doc, out / "aura-classeur.ots", "calc8_template")
    if samples:
        calc_sample(doc)
        sheet = doc.Sheets.getByIndex(0)
        setp(doc.StyleFamilies.getByName("PageStyles").getByName(sheet.PageStyle),
             IsLandscape=True, Width=29700, Height=21000, FooterIsOn=False,
             PrintGrid=False, CenterHorizontally=False)
        store(doc, samples / "aura-classeur.ods", "calc8")
        store(doc, samples / "aura-classeur.pdf", "calc_pdf_Export")
    doc.close(True)


# ----------------------------------------------------------------- Impress
W, H = 28000, 15750  # 16:9
MARGIN = 1800


def rect(doc, page, x, y, w, h, color):
    shape = doc.createInstance("com.sun.star.drawing.RectangleShape")
    page.add(shape)
    shape.Position = uno.createUnoStruct("com.sun.star.awt.Point", x, y)
    shape.Size = uno.createUnoStruct("com.sun.star.awt.Size", w, h)
    setp(shape, FillColor=color, LineStyle=uno.Enum("com.sun.star.drawing.LineStyle", "NONE"),
         FillStyle=uno.Enum("com.sun.star.drawing.FillStyle", "SOLID"))
    shape.MoveProtect = True
    return shape


def style_master(doc, master, bg, title, body, muted, accent):
    background = doc.createInstance("com.sun.star.drawing.Background")
    setp(background, FillStyle=uno.Enum("com.sun.star.drawing.FillStyle", "SOLID"), FillColor=bg)
    master.Background = background
    rect(doc, master, MARGIN, 1100, 900, 90, accent)

    fam = doc.StyleFamilies.getByName(master.Name)
    setp(fam.getByName("title"), CharFontName=T["display"], CharHeight=34, CharWeight=BOLD,
         CharColor=title, CharKerning=-40, ParaAdjust=LEFT,
         TextVerticalAdjust=uno.Enum("com.sun.star.drawing.TextVerticalAdjust", "TOP"))
    setp(fam.getByName("subtitle"), CharFontName=T["sans"], CharHeight=18, CharColor=muted,
         ParaAdjust=LEFT,
         TextVerticalAdjust=uno.Enum("com.sun.star.drawing.TextVerticalAdjust", "TOP"))
    for lvl in range(1, 10):
        st = fam.getByName(f"outline{lvl}")
        size = 20 if lvl == 1 else 16 if lvl == 2 else 14
        setp(st, CharFontName=T["sans"], CharHeight=size,
             CharColor=body if lvl == 1 else muted, ParaLineSpacing=LineSpacing(0, 125),
             ParaTopMargin=250 if lvl == 1 else 120, ParaBottomMargin=0)
        if lvl == 1:
            st.CharWeight = NORMAL

    for i in range(master.Count):
        shape = master.getByIndex(i)
        kind = shape.ShapeType
        if kind == "com.sun.star.presentation.TitleTextShape":
            shape.Position = uno.createUnoStruct("com.sun.star.awt.Point", MARGIN, 1500)
            shape.Size = uno.createUnoStruct("com.sun.star.awt.Size", W - 2 * MARGIN, 2200)
        elif kind == "com.sun.star.presentation.OutlinerShape":
            shape.Position = uno.createUnoStruct("com.sun.star.awt.Point", MARGIN, 4200)
            shape.Size = uno.createUnoStruct("com.sun.star.awt.Size", W - 2 * MARGIN, H - 4200 - 1800)
        elif kind in ("com.sun.star.presentation.FooterShape",
                      "com.sun.star.presentation.SlideNumberShape",
                      "com.sun.star.presentation.DateTimeShape"):
            setp(shape, CharFontName=T["sans"], CharHeight=9, CharColor=muted)


def impress_styles(doc):
    for page in (doc.DrawPages.getByIndex(0),):
        setp(page, Width=W, Height=H)
    masters = doc.MasterPages
    m = masters.getByIndex(0)
    setp(m, Width=W, Height=H)
    m.Name = "Aura"
    style_master(doc, m, lo_color("#FFFFFF"), C["ink"], C["text"], C["muted"], C["accent"])

    variants = [("Aura Nuit", C["ink"], lo_color("#F8FAFC"), lo_color("#E2E8F0"),
                 lo_color("#94A3B8"), lo_color("#818CF8")),
                ("Aura Accent", C["accent"], lo_color("#FFFFFF"), lo_color("#EEF2FF"),
                 lo_color("#C7D2FE"), lo_color("#FFFFFF"))]
    for i, (name, *colors) in enumerate(variants, start=1):
        master = masters.insertNewByIndex(i)
        setp(master, Width=W, Height=H)
        master.Name = name
        # a master only gets its placeholders once a slide uses it
        temp = doc.DrawPages.insertNewByIndex(doc.DrawPages.Count - 1)
        temp.MasterPage = master
        temp.Layout = 1
        style_master(doc, master, *colors)
        doc.DrawPages.remove(temp)

    gfx = doc.StyleFamilies.getByName("graphics")
    std = gfx.getByName("standard")
    setp(std, CharFontName=T["sans"], CharHeight=16, CharColor=C["ink"],
         FillColor=C["accentSoft"], LineColor=lo_color("#A5B4FC"), LineWidth=0)
    families = {"Blue": "indigo", "Green": "emerald", "Red": "rose", "Yellow": "amber"}
    ramps = TOK["ramps"]
    for hue, ramp in families.items():
        if gfx.hasByName(f"Filled {hue}"):
            setp(gfx.getByName(f"Filled {hue}"), FillColor=lo_color(ramps[ramp][6]),
                 LineColor=lo_color(ramps[ramp][7]), CharColor=lo_color("#FFFFFF"))
        if gfx.hasByName(f"Outlined {hue}"):
            setp(gfx.getByName(f"Outlined {hue}"), LineColor=lo_color(ramps[ramp][6]))
    if gfx.hasByName("Filled"):
        setp(gfx.getByName("Filled"), FillColor=C["accent"], LineColor=C["accentStrong"],
             CharColor=lo_color("#FFFFFF"))
    if gfx.hasByName("Outlined"):
        setp(gfx.getByName("Outlined"), LineColor=C["accent"])
    tables = doc.StyleFamilies.getByName("cell") if doc.StyleFamilies.hasByName("cell") else None
    if tables is not None and tables.hasByName("default"):
        setp(tables.getByName("default"), CharFontName=T["sans"])


def impress_sample(doc):
    pages = doc.DrawPages
    masters = doc.MasterPages

    def slide(index, master, layout, title, body=None):
        page = pages.getByIndex(index) if index < pages.Count else pages.insertNewByIndex(index - 1)
        page.MasterPage = masters.getByName(master) if hasattr(masters, "getByName") else \
            next(masters.getByIndex(i) for i in range(masters.Count) if masters.getByIndex(i).Name == master)
        page.Layout = layout
        for i in range(page.Count):
            shp = page.getByIndex(i)
            if shp.ShapeType == "com.sun.star.presentation.TitleTextShape":
                shp.String = title
            elif body is not None and shp.ShapeType in ("com.sun.star.presentation.OutlinerShape",
                                                        "com.sun.star.presentation.SubtitleShape"):
                shp.String = body
        return page

    slide(0, "Aura", 0, "Rapport trimestriel T3 2026",
          "Une croissance maîtrisée, une équipe recentrée")
    slide(1, "Aura", 1, "Faits marquants",
          "Revenus récurrents : 4,8 M€ (+18 %)\nRétention nette : 112 %\n"
          "Satisfaction client : NPS 61\nDélai de livraison : −9 jours")
    slide(2, "Aura Accent", 0, "Priorités du quatrième trimestre", "Industrialiser · Simplifier · Accélérer")
    slide(3, "Aura Nuit", 1, "Feuille de route",
          "Industrialiser l'offre Entreprise\nRéduire la dette technique\n"
          "Former deux équipes partenaires")


def build_impress(office, out, samples):
    doc = office.new("simpress")
    impress_styles(doc)
    first = doc.DrawPages.getByIndex(0)
    first.Layout = 0
    metadata(doc, "Aura — Présentation", "Modèle Impress Aura 16:9 : masques clair, nuit et accent.")
    store(doc, out / "aura-presentation.otp", "impress8_template")
    if samples:
        impress_sample(doc)
        store(doc, samples / "aura-presentation.odp", "impress8")
        store(doc, samples / "aura-presentation.pdf", "impress_pdf_Export")
    doc.close(True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="templates output directory")
    ap.add_argument("--samples", help="also write example documents + PDFs here")
    ap.add_argument("--soffice", default=shutil.which("soffice") or "soffice")
    ap.add_argument("--only", choices=["writer", "calc", "impress"])
    args = ap.parse_args()

    out = Path(args.out)
    samples = Path(args.samples) if args.samples else None
    office = Office(args.soffice)
    try:
        for name, build in (("writer", build_writer), ("calc", build_calc), ("impress", build_impress)):
            if args.only in (None, name):
                print(f"{name}:")
                build(office, out, samples)
    finally:
        office.close()


if __name__ == "__main__":
    main()
