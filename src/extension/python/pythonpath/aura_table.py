"""Faithful table paste: a spreadsheet range (LibreOffice Calc, Excel, a web
page) becomes a native Writer or Impress/Draw table that keeps borders,
fills, fonts, alignment, merged cells, column widths and row heights.

Sources
  * Calc  -> the clipboard's embedded ODF spreadsheet (exact formatting);
  * other -> the clipboard's HTML, with CSS (inline styles and Excel's
             class rules such as `.xl65 { border:.5pt solid windowtext }`).
Targets
  * Writer          -> com.sun.star.text.TextTable at the cursor;
  * Impress / Draw  -> com.sun.star.drawing.TableShape on the current slide.

The model (`Table`) is plain Python so the HTML side is testable without UNO.
"""
import re
from html.parser import HTMLParser

PX = 26.458   # 1/100 mm per CSS pixel
PT = 35.278   # 1/100 mm per point
HTML_SIZES = {1: 8, 2: 10, 3: 12, 4: 14, 5: 18, 6: 24, 7: 36}  # <font size=n> in pt
NAMED = {"black": 0x000000, "white": 0xFFFFFF, "windowtext": 0x000000, "red": 0xFF0000,
         "green": 0x008000, "blue": 0x0000FF, "yellow": 0xFFFF00, "gray": 0x808080,
         "grey": 0x808080, "silver": 0xC0C0C0, "navy": 0x000080, "maroon": 0x800000,
         "orange": 0xFFA500, "purple": 0x800080, "teal": 0x008080}
LINE_STYLES = {"solid": 0, "dotted": 1, "dashed": 2, "double": 3}
MAX_CELLS = 5000    # larger ranges go through LibreOffice's normal paste
MAX_SPAN = 200      # a rowspan / colspan beyond this is not a real table


class Border:
    __slots__ = ("width", "color", "style")

    def __init__(self, width=0, color=0, style=0):
        self.width, self.color, self.style = width, color, style  # 1/100 mm, 0xRRGGBB, LineStyle

    def __bool__(self):
        return self.width > 0


class Cell:
    def __init__(self):
        self.text = ""
        self.font = None        # family name
        self.size = None        # pt
        self.bold = self.italic = self.underline = False
        self.color = None       # 0xRRGGBB or None (automatic)
        self.fill = None        # 0xRRGGBB or None (transparent)
        self.align = None       # "left" | "center" | "right" | "justify"
        self.valign = None      # "top" | "middle" | "bottom"
        self.numeric = False
        self.borders = {"top": Border(), "bottom": Border(), "left": Border(), "right": Border()}
        self.span = (1, 1)      # (rows, cols) for the top-left cell of a merged area
        self.covered = False    # inside a merged area, not its top-left cell


class Table:
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.cells = [[Cell() for _ in range(cols)] for _ in range(rows)]
        self.col_widths = [2260] * cols     # 1/100 mm
        self.row_heights = [452] * rows

    def merges(self):
        for r, row in enumerate(self.cells):
            for c, cell in enumerate(row):
                if cell.span != (1, 1):
                    yield r, c, cell.span


# ------------------------------------------------------------- HTML source
def parse_color(value):
    if value is None:
        return None
    v = value.strip().lower().strip('"\'')
    if v in ("", "auto", "transparent", "none", "inherit"):
        return None
    if v in NAMED:
        return NAMED[v]
    m = re.fullmatch(r"#?([0-9a-f]{6})", v)
    if m:
        return int(m.group(1), 16)
    m = re.fullmatch(r"#?([0-9a-f]{3})", v)
    if m:
        return int("".join(ch * 2 for ch in m.group(1)), 16)
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)", v)
    if m:
        if m.group(4) is not None and float(m.group(4)) == 0:
            return None
        r, g, b = (min(255, int(x)) for x in m.groups()[:3])
        return (r << 16) | (g << 8) | b
    return None


def parse_length(value, default_unit=PX):
    """CSS length -> 1/100 mm."""
    m = re.fullmatch(r"\s*([\d.]+)\s*(px|pt|cm|mm|in)?\s*", value or "")
    if not m:
        return {"thin": 0.5 * PT, "medium": 1.5 * PT, "thick": 2.25 * PT}.get((value or "").strip(), 0)
    n, unit = float(m.group(1)), m.group(2)
    factor = {"px": PX, "pt": PT, "cm": 1000, "mm": 100, "in": 2540}.get(unit, default_unit)
    return n * factor


def parse_border(value):
    """'1px solid #cbd5e1', '.5pt solid windowtext', 'none' -> Border."""
    value = (value or "").strip().lower()
    if not value or value.startswith(("none", "hidden", "0 ", "0px", "0pt")) or value == "0":
        return Border()
    width, style, color = 0.5 * PT, 0, 0
    for token in re.findall(r"rgba?\([^)]*\)|\S+", value):
        if token in LINE_STYLES:
            style = LINE_STYLES[token]
        elif token in ("none", "hidden"):
            return Border()
        elif re.fullmatch(r"[\d.]+(px|pt|cm|mm|in)?|thin|medium|thick", token):
            width = parse_length(token)
        else:
            c = parse_color(token)
            if c is not None:
                color = c
    return Border(max(int(round(width)), 9), color, style)


def parse_style(text):
    out = {}
    for decl in (text or "").split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_css_rules(css):
    """{'.xl65': {...}, 'td': {...}} from a <style> block (Excel's classes)."""
    rules = {}
    css = re.sub(r"/\*.*?\*/|<!--|-->", "", css, flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        decls = parse_style(body)
        for sel in selectors.split(","):
            sel = sel.strip().lower()
            if sel:
                rules.setdefault(sel, {}).update(decls)
    return rules


def apply_css(cell, css):
    background = css.get("background-color") or css.get("background")
    if background is not None:
        tokens = re.findall(r"rgba?\([^)]*\)|\S+", background)
        cell.fill = parse_color(tokens[0]) if tokens else None
    if "color" in css:
        cell.color = parse_color(css["color"])
    if "font-family" in css:
        cell.font = css["font-family"].split(",")[0].strip().strip('"\'') or cell.font
    if "font-size" in css:
        size = parse_length(css["font-size"], PT) / PT
        if size:
            cell.size = round(size * 2) / 2
    if "font-weight" in css:
        w = css["font-weight"].strip().lower()
        cell.bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
    if "font-style" in css:
        cell.italic = css["font-style"].strip().lower() in ("italic", "oblique")
    if "text-decoration" in css or "text-underline-style" in css:
        cell.underline = "underline" in css.get("text-decoration", "") or \
            css.get("text-underline-style", "none") not in ("none", "")
    if "text-align" in css:
        cell.align = {"left": "left", "center": "center", "right": "right", "justify": "justify",
                      "start": "left", "end": "right"}.get(css["text-align"].strip().lower(), cell.align)
    if "vertical-align" in css:
        cell.valign = {"top": "top", "middle": "middle", "bottom": "bottom"}.get(
            css["vertical-align"].strip().lower(), cell.valign)
    if "border" in css:
        b = parse_border(css["border"])
        for side in cell.borders:
            cell.borders[side] = b
    for side in ("top", "bottom", "left", "right"):
        if f"border-{side}" in css:
            cell.borders[side] = parse_border(css[f"border-{side}"])


class _HTMLTable(HTMLParser):
    """Collects the first top-level <table> of an HTML fragment."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css = {}
        self.in_style = False
        self.depth = 0
        self.rows = []            # [[(cell, rowspan, colspan)]]
        self.cols = []            # widths from <col>/<colgroup>
        self.row_heights = []
        self.cell = None
        self.inline = []          # stack of inline formatting dicts
        self.outside_text = 0
        self.done = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "style":
            self.in_style = True
            return
        if self.done:
            return
        if tag == "table":
            self.depth += 1
            return
        if self.depth != 1:
            return
        if tag in ("col", "colgroup") and ("width" in a or "width" in parse_style(a.get("style"))):
            width = parse_style(a.get("style")).get("width") or a.get("width")
            for _ in range(int(a.get("span") or 1)):
                self.cols.append(parse_length(width))
        elif tag == "tr":
            self.rows.append([])
            h = parse_style(a.get("style")).get("height") or a.get("height")
            self.row_heights.append(parse_length(h) if h else None)
        elif tag in ("td", "th"):
            if not self.rows:
                self.rows.append([])
                self.row_heights.append(None)
            cell = Cell()
            if tag == "th":
                cell.bold = True
            for sel in ("td", tag):
                if sel in self.css:
                    apply_css(cell, self.css[sel])
            for cls in a.get("class", "").split():
                for sel in ("." + cls.lower(), f"td.{cls.lower()}"):
                    if sel in self.css:
                        apply_css(cell, self.css[sel])
            if a.get("bgcolor"):
                cell.fill = parse_color(a["bgcolor"])
            if a.get("align"):
                cell.align = a["align"].lower()
            if a.get("valign"):
                cell.valign = a["valign"].lower()
            apply_css(cell, parse_style(a.get("style")))
            if "sdval" in a or a.get("x:num") is not None or "data-sheets-value" in a and '"3"' in a.get(
                    "data-sheets-value", ""):
                cell.numeric = True
            if a.get("height") and self.row_heights[-1] is None:
                self.row_heights[-1] = parse_length(a["height"])
            self.cell = cell
            self.rows[-1].append((cell, _span(a.get("rowspan")), _span(a.get("colspan")),
                                  parse_length(a["width"]) if a.get("width") else None))
            self.inline = []
        elif self.cell is not None:
            fmt = {}
            if tag in ("b", "strong"):
                fmt["bold"] = True
            elif tag in ("i", "em"):
                fmt["italic"] = True
            elif tag == "u":
                fmt["underline"] = True
            elif tag == "font":
                if a.get("face"):
                    fmt["font"] = a["face"].split(",")[0].strip()
                if a.get("color"):
                    fmt["color"] = parse_color(a["color"])
                if a.get("size", "").strip().isdigit():
                    fmt["size"] = HTML_SIZES.get(int(a["size"]), None)
            elif tag == "span":
                tmp = Cell()
                tmp.size = tmp.font = tmp.color = None
                apply_css(tmp, parse_style(a.get("style")))
                fmt = {k: v for k, v in (("font", tmp.font), ("size", tmp.size), ("color", tmp.color),
                                         ("bold", tmp.bold or None), ("italic", tmp.italic or None))
                       if v is not None}
            elif tag == "br":
                self.cell.text += "\n"
            for k, v in fmt.items():
                if v is not None:
                    setattr(self.cell, k, v)

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        elif tag == "table" and not self.done:
            self.depth -= 1
            if self.depth == 0 and self.rows:
                self.done = True
        elif tag in ("td", "th"):
            if self.cell is not None:
                self.cell.text = re.sub(r"[ \t\r\f\v]+", " ", self.cell.text).strip(" ")
            self.cell = None

    def handle_data(self, data):
        if self.in_style:
            self.css.update(parse_css_rules(data))
        elif self.cell is not None and self.depth == 1:
            self.cell.text += data.replace("\xa0", " ").replace("\n", " ")
        elif self.depth == 0 and data.strip():
            self.outside_text += len(data.strip())


def _span(value):
    try:
        return max(1, min(MAX_SPAN, int(value or 1)))
    except ValueError:
        return 1


def table_from_html(text):
    """Table from an HTML clipboard fragment, or None when it is not mainly a table."""
    if re.match(r"Version:\d", text):   # Windows CF_HTML: a header of offsets precedes the HTML
        text = text[text.find("<"):] if "<" in text else ""
    text = re.sub(r"(?is)<!--\s*StartFragment\s*-->|<!--\s*EndFragment\s*-->", "", text)
    if len(text) > 20000000:   # 20 MB of HTML is not a clipboard table
        return None
    p = _HTMLTable()
    p.feed(text)
    if not p.rows:
        return None
    inside = sum(len(c.text) for row in p.rows for c, *_ in row)
    if p.outside_text > max(40, inside * 0.2):   # a page that merely contains a table
        return None
    # lay the cells out on a grid, honouring rowspan / colspan
    grid, spans = {}, []
    for r, row in enumerate(p.rows):
        c = 0
        for cell, rs, cs, width in row:
            while (r, c) in grid:
                c += 1
            spans.append((r, c, rs, cs, cell, width))
            for dr in range(rs):
                for dc in range(cs):
                    grid[(r + dr, c + dc)] = cell
            c += cs
    n_rows = max(r for r, _ in grid) + 1
    n_cols = max(c for _, c in grid) + 1
    if n_rows * n_cols < 2 or n_rows * n_cols > MAX_CELLS:
        return None
    table = Table(n_rows, n_cols)
    widths = list(p.cols[:n_cols])
    for r, c, rs, cs, cell, width in spans:
        if r < n_rows and c < n_cols:
            cell.span = (min(rs, n_rows - r), min(cs, n_cols - c))
            table.cells[r][c] = cell
            for dr in range(cell.span[0]):
                for dc in range(cell.span[1]):
                    if dr or dc:
                        table.cells[r + dr][c + dc].covered = True
            if width and cs == 1 and (c >= len(widths) or not widths[c]):
                widths += [None] * (c + 1 - len(widths))
                widths[c] = width
    table.col_widths = [int(w) if w else 2260 for w in (widths + [None] * n_cols)[:n_cols]]
    table.row_heights = [int(h) if h else 452 for h in (p.row_heights + [None] * n_rows)[:n_rows]]
    for row in table.cells:
        for cell in row:
            if cell.align is None:
                cell.align = "right" if cell.numeric else "left"
    return table


# ------------------------------------------------------------- Calc source
def used_range(doc):
    """The range a clipboard spreadsheet holds (first sheet, used area)."""
    sheet = doc.Sheets.getByIndex(0)
    cursor = sheet.createCursor()
    cursor.gotoStartOfUsedArea(False)
    cursor.gotoEndOfUsedArea(True)
    return sheet.getCellRangeByPosition(*_bounds(cursor.getRangeAddress()))


def _bounds(addr):
    return addr.StartColumn, addr.StartRow, addr.EndColumn, addr.EndRow


def live_source(desktop, copied):
    """The open document range the clipboard was copied from, when it can be found.

    LibreOffice's clipboard spreadsheet carries the *default* definitions of
    built-in cell styles, not the document's own (e.g. a customised 'Accent 2'
    comes back grey), so the live selection is the faithful source.
    """
    data = copied.getDataArray()
    rows, cols = len(data), len(data[0]) if data else 0
    for comp in desktop.getComponents():
        try:
            if not comp.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                continue
            selection = comp.getCurrentController().getSelection()
            if not selection.supportsService("com.sun.star.sheet.SheetCellRange"):
                continue
            a = selection.getRangeAddress()
            if (a.EndRow - a.StartRow + 1, a.EndColumn - a.StartColumn + 1) != (rows, cols):
                continue
            if selection.getDataArray() == data:
                return selection
        except Exception:
            continue
    return None


def table_from_calc(cell_range):
    """Table from a Calc cell range (live selection or the clipboard's spreadsheet)."""
    sheet = cell_range.getSpreadsheet()
    addr = cell_range.getRangeAddress()
    n_rows = addr.EndRow - addr.StartRow + 1
    n_cols = addr.EndColumn - addr.StartColumn + 1
    if n_rows * n_cols < 2 or n_rows * n_cols > MAX_CELLS:
        return None
    table = Table(n_rows, n_cols)
    table.col_widths = [sheet.Columns.getByIndex(addr.StartColumn + c).Width for c in range(n_cols)]
    table.row_heights = [sheet.Rows.getByIndex(addr.StartRow + r).Height for r in range(n_rows)]
    hori = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "BLOCK": "justify"}
    for r in range(n_rows):
        for c in range(n_cols):
            src = sheet.getCellByPosition(addr.StartColumn + c, addr.StartRow + r)
            cell = table.cells[r][c]
            if cell.covered:
                continue
            cell.text = src.String
            cell.font = src.CharFontName
            cell.size = src.CharHeight
            cell.bold = src.CharWeight >= 110
            cell.italic = src.CharPosture.value != "NONE"
            cell.underline = src.CharUnderline != 0
            cell.color = None if src.CharColor in (-1, 0xFFFFFFFF) else src.CharColor & 0xFFFFFF
            cell.fill = None if src.IsCellBackgroundTransparent or src.CellBackColor == -1 \
                else src.CellBackColor & 0xFFFFFF
            kind = src.Type.value
            cell.numeric = kind == "VALUE" or (kind == "FORMULA" and src.FormulaResultType2 == 1)
            justify = src.HoriJustify.value
            cell.align = hori.get(justify) or ("right" if cell.numeric else "left")
            cell.valign = {1: "top", 2: "middle", 3: "bottom"}.get(src.VertJustify, "bottom")
            for side, prop in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                               ("left", "LeftBorder"), ("right", "RightBorder")):
                line = src.getPropertyValue(prop)
                width = line.LineWidth or (line.OuterLineWidth + line.InnerLineWidth + line.LineDistance)
                if width:
                    cell.borders[side] = Border(width, line.Color & 0xFFFFFF, line.LineStyle)
            if src.IsMerged:
                merged = sheet.createCursorByRange(src)
                merged.collapseToMergedArea()
                a = merged.getRangeAddress()
                if a.StartRow == src.CellAddress.Row and a.StartColumn == src.CellAddress.Column:
                    cell.span = (min(a.EndRow - a.StartRow + 1, n_rows - r),
                                 min(a.EndColumn - a.StartColumn + 1, n_cols - c))
                    for dr in range(cell.span[0]):
                        for dc in range(cell.span[1]):
                            if dr or dc:
                                table.cells[r + dr][c + dc].covered = True
    merge_overflow(table)
    return table


def merge_overflow(table):
    """Like Calc, let a long left-aligned text run over the empty cells on its right."""
    for row in table.cells:
        for c, cell in enumerate(row):
            if not cell.text or cell.covered or cell.span != (1, 1) or cell.numeric \
                    or cell.align not in (None, "left") or "\n" in cell.text:
                continue
            need = len(cell.text) * (cell.size or 10) * 0.55 * PT
            width, end = table.col_widths[c], c
            while width < need and end + 1 < table.cols:
                nxt = row[end + 1]
                if nxt.text or nxt.covered or nxt.span != (1, 1) or nxt.fill is not None \
                        or any(nxt.borders.values()):
                    break
                end += 1
                width += table.col_widths[end]
            if end > c:
                cell.span = (1, end - c + 1)
                for k in range(c + 1, end + 1):
                    row[k].covered = True


def load_calc_from_bytes(desktop, data, props, ctx):
    """Open the clipboard's embedded spreadsheet (ODF bytes) as a hidden document.

    Loaded from memory: no temporary file (which Windows would keep locked) and
    nothing written to disk.
    """
    import uno
    stream = ctx.ServiceManager.createInstanceWithArgumentsAndContext(
        "com.sun.star.io.SequenceInputStream", (uno.ByteSequence(data),), ctx)
    # clipboard data is untrusted: Calc format only, never run macros, never update links
    doc = desktop.loadComponentFromURL(
        "private:stream", "_blank", 0,
        props(InputStream=stream, Hidden=True, ReadOnly=True, FilterName="calc8",
              MacroExecutionMode=uno.Any("short", 0),     # MacroExecMode.NEVER_EXECUTE
              UpdateDocMode=uno.Any("short", 0)))         # UpdateDocMode.NO_UPDATE
    if doc is not None and not doc.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
        doc.close(True)
        return None
    return doc


# ---------------------------------------------------------------- targets
def _line(uno, border):
    line = uno.createUnoStruct("com.sun.star.table.BorderLine2")
    if border:
        line.Color = border.color
        line.LineStyle = border.style
        line.LineWidth = int(border.width)
        line.OuterLineWidth = int(border.width)
    return line


def writer_cell_name(col, row):
    """Writer names columns A..Z then a..z, AA..."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    name, n = "", col
    while True:
        name = letters[n % 52] + name
        n = n // 52 - 1
        if n < 0:
            break
    return f"{name}{row + 1}"


def insert_writer(uno, doc, table):
    """Insert the table at the view cursor; returns the TextTable."""
    view = doc.getCurrentController().getViewCursor()
    text = view.getText()
    if not view.isCollapsed():   # like a normal paste, replace the selected text
        view.setString("")
    tt = doc.createInstance("com.sun.star.text.TextTable")
    tt.initialize(table.rows, table.cols)
    text.insertTextContent(view, tt, False)

    # width: as in the sheet, capped to the text area
    total = sum(table.col_widths)
    style = doc.StyleFamilies.getByName("PageStyles").getByName(view.PageStyleName)
    area = style.Width - style.LeftMargin - style.RightMargin
    tt.HoriOrient = 3 if total < area else 6       # LEFT, or FULL when wider than the page
    if total < area:
        tt.HoriOrient = 7                           # LEFT_AND_WIDTH
        tt.Width = total
    tt.TopMargin = tt.BottomMargin = 0
    rel = tt.TableColumnRelativeSum
    seps = list(tt.TableColumnSeparators)
    acc = 0
    for i, sep in enumerate(seps):
        acc += table.col_widths[i]
        sep.Position = int(round(acc * rel / total))
    tt.TableColumnSeparators = tuple(seps)

    valign = {"top": 1, "middle": 2, "bottom": 3}
    adjust = {"left": 0, "right": 1, "justify": 2, "center": 3}
    for r in range(table.rows):
        row = tt.Rows.getByIndex(r)
        row.IsAutoHeight = True        # the height is a minimum: text never gets clipped
        row.Height = int(table.row_heights[r])
        for c in range(table.cols):
            src = table.cells[r][c]
            cell = tt.getCellByName(writer_cell_name(c, r))
            cell.TopBorder = _line(uno, src.borders["top"])
            cell.BottomBorder = _line(uno, src.borders["bottom"])
            cell.LeftBorder = _line(uno, src.borders["left"])
            cell.RightBorder = _line(uno, src.borders["right"])
            for side in ("Top", "Bottom"):
                cell.setPropertyValue(f"{side}BorderDistance", 35)
            for side in ("Left", "Right"):
                cell.setPropertyValue(f"{side}BorderDistance", 100)
            if src.fill is not None:
                cell.BackColor = src.fill
                cell.BackTransparent = False
            else:
                cell.BackTransparent = True
            cell.VertOrient = valign.get(src.valign or "bottom", 3)
            if src.covered:
                continue
            cell.setString(src.text)
            cur = cell.createTextCursor()
            cur.gotoStart(False)
            cur.gotoEnd(True)
            cur.ParaStyleName = "Table Contents"
            cur.ParaTopMargin = cur.ParaBottomMargin = 0
            cur.ParaAdjust = adjust.get(src.align or "left", 0)
            _char(uno, cur, src)
    # merges last: they renumber Writer's cells
    for r, c, (rs, cs) in sorted(table.merges(), key=lambda m: (-m[0], -m[1])):
        cursor = tt.createCursorByCellName(writer_cell_name(c, r))
        cursor.gotoCellByName(writer_cell_name(c + cs - 1, r + rs - 1), True)
        cursor.mergeRange()
    return tt


def _char(uno, target, src):
    if src.font:
        target.CharFontName = src.font
    if src.size:
        target.CharHeight = float(src.size)
    target.CharWeight = 150.0 if src.bold else 100.0
    target.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "ITALIC" if src.italic else "NONE")
    target.CharUnderline = 1 if src.underline else 0
    target.CharColor = src.color if src.color is not None else -1


def insert_draw(uno, doc, table):
    """Insert the table as a TableShape on the current slide/page; returns the shape."""
    page = doc.getCurrentController().getCurrentPage()
    shape = doc.createInstance("com.sun.star.drawing.TableShape")
    page.add(shape)
    model = shape.Model
    if table.cols > 1:
        model.Columns.insertByIndex(model.Columns.Count, table.cols - model.Columns.Count)
    if table.rows > 1:
        model.Rows.insertByIndex(model.Rows.Count, table.rows - model.Rows.Count)
    for flag in ("UseFirstRowStyle", "UseLastRowStyle", "UseFirstColumnStyle", "UseLastColumnStyle",
                 "UseBandingRowStyle", "UseBandingColumnStyle"):
        try:
            shape.setPropertyValue(flag, False)
        except Exception:
            pass
    total_w = sum(table.col_widths)
    total_h = sum(table.row_heights)
    scale = min(1.0, (page.Width * 0.9) / total_w) if total_w else 1.0
    for c in range(table.cols):
        model.Columns.getByIndex(c).Width = int(table.col_widths[c] * scale)
    for r in range(table.rows):
        model.Rows.getByIndex(r).Height = int(table.row_heights[r] * scale)
    valign = {"top": "TOP", "middle": "CENTER", "bottom": "BOTTOM"}
    adjust = {"left": 0, "right": 1, "justify": 2, "center": 3}
    for r in range(table.rows):
        for c in range(table.cols):
            src = table.cells[r][c]
            cell = model.getCellByPosition(c, r)
            if src.fill is not None:
                cell.FillStyle = uno.Enum("com.sun.star.drawing.FillStyle", "SOLID")
                cell.FillColor = src.fill
            else:
                cell.FillStyle = uno.Enum("com.sun.star.drawing.FillStyle", "NONE")
            for side, prop in (("top", "TopBorder"), ("bottom", "BottomBorder"),
                               ("left", "LeftBorder"), ("right", "RightBorder")):
                cell.setPropertyValue(prop, _line(uno, src.borders[side]))
            cell.TextVerticalAdjust = uno.Enum("com.sun.star.drawing.TextVerticalAdjust",
                                               valign.get(src.valign or "bottom", "BOTTOM"))
            for side in ("Left", "Right"):
                cell.setPropertyValue(f"Text{side}Distance", 100)
            for side in ("Upper", "Lower"):
                cell.setPropertyValue(f"Text{side}Distance", 35)
            if src.covered or not src.text:   # an empty Impress cell has no text to format
                continue
            cell.setString(src.text)
            cur = cell.createTextCursor()
            cur.gotoStart(False)
            cur.gotoEnd(True)
            cur.ParaAdjust = adjust.get(src.align or "left", 0)
            _char(uno, cur, src)
            if src.size:
                cur.CharHeight = float(src.size) * scale if scale < 1 else float(src.size)
    for r, c, (rs, cs) in table.merges():
        model.createCursorByRange(model.getCellRangeByPosition(c, r, c + cs - 1, r + rs - 1)).merge()
    size = uno.createUnoStruct("com.sun.star.awt.Size", int(total_w * scale), int(total_h * scale))
    shape.Size = size
    shape.Position = uno.createUnoStruct("com.sun.star.awt.Point",
                                         max(0, (page.Width - size.Width) // 2),
                                         max(0, (page.Height - size.Height) // 2))
    return shape


