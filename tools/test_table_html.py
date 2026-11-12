"""Unit test of the HTML side of the faithful table paste (no LibreOffice needed).

Uses the shape of what Microsoft Excel puts on the clipboard: CSS classes in a
<style> block (.xl65 ...), borders in points, 'windowtext' colours, merged
cells, column widths from <col>, Calibri 11 pt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "extension" / "python" / "pythonpath"))
from aura_table import PT, table_from_html  # noqa: E402

EXCEL = """<html xmlns:o="urn:schemas-microsoft-com:office:office">
<head><style><!--
td {padding-top:1px; color:black; font-size:11.0pt; font-family:Calibri, sans-serif;
    vertical-align:bottom; border:none;}
.xl65 {font-weight:700; color:white; background:#4472C4; border:.5pt solid windowtext;
       text-align:center; vertical-align:middle;}
.xl66 {border-top:none; border-right:.5pt solid windowtext; border-bottom:.5pt solid windowtext;
       border-left:.5pt solid windowtext;}
.xl67 {mso-number-format:"\\#\\,\\#\\#0\\.00"; text-align:right; border:.5pt solid windowtext;
       border-top:none; background:#FFF2CC;}
.xl68 {font-size:14.0pt; font-weight:700; font-style:italic;}
--></style></head>
<body><!--StartFragment--><table border=0 cellpadding=0 cellspacing=0 width=256>
 <col width=128 style='width:96pt'><col width=64 span=2 style='width:48pt'>
 <tr height=20 style='height:15.0pt'>
  <td colspan=3 class=xl68 height=20>Budget 2026</td></tr>
 <tr height=20 style='height:15.0pt'>
  <td class=xl65>Poste</td><td class=xl65>T1</td><td class=xl65>T2</td></tr>
 <tr height=20 style='height:15.0pt'>
  <td class=xl66>Loyer &amp; charges</td><td class=xl67 x:num>1200</td><td class=xl67 x:num>1250.5</td></tr>
</table><!--EndFragment--></body></html>"""

WEB_PAGE = "<p>" + "Long article text. " * 40 + "</p><table><tr><td>a</td><td>b</td></tr></table>"


def main():
    failures = []

    def check(label, ok, detail=""):
        print(f"[{'ok' if ok else 'FAIL'}] {label}{' — ' + str(detail) if detail else ''}")
        if not ok:
            failures.append(label)

    t = table_from_html(EXCEL)
    check("grid size 3x3", t is not None and (t.rows, t.cols) == (3, 3), t and (t.rows, t.cols))
    title, head, body = t.cells[0][0], t.cells[1][0], t.cells[2][1]
    check("merged title spans 3 columns", title.span == (1, 3) and t.cells[0][2].covered)
    check("title 14 pt bold italic", (title.size, title.bold, title.italic) == (14.0, True, True))
    check("default font from td rule", head.font == "Calibri" and t.cells[2][0].size == 11.0)
    check("header fill + white bold text", (head.fill, head.color, head.bold) == (0x4472C4, 0xFFFFFF, True))
    check("header centred", head.align == "center" and head.valign == "middle")
    check("header borders 0.5 pt black",
          all(abs(b.width - 0.5 * PT) < 1 and b.color == 0 for b in head.borders.values()))
    check("body: no top border, others kept",
          not t.cells[2][0].borders["top"] and t.cells[2][0].borders["left"])
    check("numbers right-aligned on yellow", body.align == "right" and body.fill == 0xFFF2CC)
    check("entities decoded", t.cells[2][0].text == "Loyer & charges", t.cells[2][0].text)
    check("column widths from <col>",
          [round(w / PT) for w in t.col_widths] == [96, 48, 48], [round(w / PT) for w in t.col_widths])
    check("a web page that merely contains a table is left to the normal paste",
          table_from_html(WEB_PAGE) is None)
    print("\nall checks passed" if not failures else f"\n{len(failures)} check(s) failed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
