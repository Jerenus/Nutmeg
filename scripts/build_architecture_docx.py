#!/usr/bin/env python3
"""把 docs/ARCHITECTURE.md 生成 Word 版（默认 docs/ARCHITECTURE.docx）与 PDF 预览。

依赖都不在 uv 环境里：pandoc ≥ 3、npx（@mermaid-js/mermaid-cli）、LibreOffice（soffice）、
系统 python3 带 python-docx 与 PyMuPDF。用法：

    python3 scripts/build_architecture_docx.py [--out docs/ARCHITECTURE.docx] [--pdf PATH]

流程：渲染 mermaid（2 倍分辨率）→ 预处理 markdown（图换 PNG + 图题、提示框换样式块、
标题加锚点、去掉目录与分隔线）→ 生成参考样式 → pandoc → python-docx 后处理（封面、
目录域、页眉页脚、表格）→ soffice 转 PDF 取各节页码 → 回填目录页码再出一次。
Word 版是快照，内容以 markdown 为准。
"""
from __future__ import annotations

import argparse
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "ARCHITECTURE.md"
MMDC = ["npx", "-y", "@mermaid-js/mermaid-cli@11.4.2"]

LATIN, CJK, MONO = "Helvetica Neue", "PingFang SC", "Menlo"
INK, MUTED, ACCENT, ACCENT_DARK = "1E293B", "64748B", "4F46E5", "1E1B4B"
RULE, RULE_LIGHT, HEAD_FILL, BAND_FILL = "CBD5E1", "E2E8F0", "EEF2FF", "F8FAFC"
# 图例行顺序与 ARCHITECTURE.md 的图例表一致：外部源/采集/事实/判断/面板/人/账务/实验
LEGEND = [("灰", "F1F5F9", "64748B"), ("蓝", "E0F2FE", "0284C7"), ("靛", "EEF2FF", "4F46E5"),
          ("紫", "F3E8FF", "9333EA"), ("青", "CCFBF1", "0D9488"), ("琥珀", "FEF3C7", "D97706"),
          ("绿", "DCFCE7", "16A34A"), ("玫红", "FFE4E6", "E11D48")]

PAGE_W, MARGIN_LR = 21.0, 2.2
TEXT_W_CM = PAGE_W - 2 * MARGIN_LR          # 16.6
MAX_FIG_H_CM = 20.5
CM_PER_PX = 0.0198      # 图里 16px 字 ≈ 9pt：小图不放大到整页宽

PPR = ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
       "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs",
       "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
       "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
       "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
       "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
       "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr",
       "w:pPrChange"]
RPR = ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps",
       "w:strike", "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint",
       "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden", "w:color", "w:spacing",
       "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
       "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
       "w:eastAsianLayout", "w:specVanish", "w:oMath"]
TBLPR = ["w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
         "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd",
         "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook",
         "w:tblCaption", "w:tblDescription"]
TCPR = ["w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd",
        "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark"]
EDGE_ORDER = ["top", "left", "start", "bottom", "right", "end", "insideH", "insideV",
              "tl2br", "tr2bl", "between", "bar"]
TRPR = ["w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter",
        "w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden"]


# ---------------------------------------------------------------- XML helpers
def put(parent, tag: str, order: list[str], **attrs: str):
    """按 schema 顺序替换或插入子元素（Word 对 pPr/rPr 子元素顺序敏感）。"""
    old = parent.find(qn(tag))
    if old is not None:
        parent.remove(old)
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))
    parent.insert_element_before(el, *order[order.index(tag) + 1:])
    return el


def borders(parent, tag: str, order: list[str], **edges: tuple[str, int, str]):
    box = put(parent, tag, order)
    for edge in sorted(edges, key=EDGE_ORDER.index):      # schema 要求固定顺序
        val, size, color = edges[edge]
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), val)
        e.set(qn("w:sz"), str(size))
        e.set(qn("w:space"), "4" if tag == "w:pBdr" else "0")
        e.set(qn("w:color"), color)
        box.append(e)
    return box


def set_fonts(rpr, latin: str = LATIN, east: str = CJK) -> None:
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = put(rpr, "w:rFonts", RPR)
    for attr in list(fonts.attrib):
        del fonts.attrib[attr]
    for key, val in (("ascii", latin), ("hAnsi", latin), ("cs", latin), ("eastAsia", east)):
        fonts.set(qn(f"w:{key}"), val)


def run_el(text: str = "", *, size: float | None = None, color: str | None = None,
           bold: bool = False, font: str | None = None):
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    r.append(rpr)
    if font:
        set_fonts(rpr, font, CJK)
    if bold:
        put(rpr, "w:b", RPR)
    if color:
        put(rpr, "w:color", RPR, val=color)
    if size:
        put(rpr, "w:sz", RPR, val=int(size * 2))
        put(rpr, "w:szCs", RPR, val=int(size * 2))
    if text:
        t = OxmlElement("w:t")
        t.set(qn("xml:space"), "preserve")
        t.text = text
        r.append(t)
    return r


def field_char(kind: str):
    r = OxmlElement("w:r")
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), kind)
    r.append(fc)
    return r


def instr(text: str):
    r = OxmlElement("w:r")
    t = OxmlElement("w:instrText")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    return r


def simple_field(code: str, size: float, color: str):
    f = OxmlElement("w:fldSimple")
    f.set(qn("w:instr"), code)
    f.append(run_el("1", size=size, color=color))
    return f


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return struct.unpack(">II", head[16:24])


def display_len(text: str) -> int:
    return sum(2 if ord(c) > 0x2E80 else 1 for c in text)


# ---------------------------------------------------------------- 1. mermaid
def render_diagrams(md: str, out: Path) -> list[Path]:
    blocks = re.findall(r"```mermaid\n(.*?)```", md, re.S)
    # 字体只能经配置文件传：写在 init 指令里的 fontFamily 会被丢弃，回退成衬线体
    cfg = out / "mermaid-config.json"
    cfg.write_text('{"fontFamily": "PingFang SC, Helvetica Neue, sans-serif"}', encoding="utf-8")
    pngs = []
    for i, body in enumerate(blocks, 1):
        src, png = out / f"arch-{i:02d}.mmd", out / f"arch-{i:02d}.png"
        src.write_text(body, encoding="utf-8")
        kind = next(ln.strip() for ln in body.splitlines()
                    if ln.strip() and not ln.startswith("%%"))
        width = "1100" if kind.startswith("gantt") else "1800"
        subprocess.run([*MMDC, "-i", str(src), "-o", str(png), "-w", width, "-s", "2",
                        "-b", "white", "-c", str(cfg)], check=True, capture_output=True)
        pngs.append(png)
    return pngs


# ---------------------------------------------------------------- 2. markdown
def fig_width_cm(png: Path) -> float:
    w, h = png_size(png)          # 2 倍渲染
    return min(TEXT_W_CM, MAX_FIG_H_CM * w / h, CM_PER_PX * w / 2)


def preprocess(md: str, pngs: list[Path]) -> tuple[str, dict[str, str], list[tuple]]:
    lines = md.splitlines()
    assert lines[0].startswith("# "), "ARCHITECTURE.md 应以一级标题开头"
    title = lines[0][2:].strip()
    meta, i = {"标题": title}, 1
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    while i < len(lines) and lines[i].startswith("|"):
        cells = [c.strip() for c in lines[i].strip("|").split("|")]
        if cells[0] not in ("项", "---") and not set(cells[0]) <= {"-"}:
            meta[cells[0]] = cells[1].replace("`", "")
        i += 1
    rest = "\n".join(lines[i:])

    # 目录节交给 Word 目录域；分隔线在分页标题下多余
    rest = re.sub(r"\n## 目录\n.*?\n---\n", "\n", rest, count=1, flags=re.S)
    rest = re.sub(r"\n---\n", "\n", rest)

    # 图：mermaid 块 + 紧随的「*图 N　…*」→ 带图题的图片
    fig = iter(pngs)

    def figure(m: re.Match) -> str:
        png = next(fig)
        return f"![{m.group(1)}]({png.name}){{width={fig_width_cm(png):.1f}cm}}\n"

    rest = re.sub(r"```mermaid\n.*?```\n\n\*(图 \d+　.*?)\*\n", figure, rest, flags=re.S)
    assert "```mermaid" not in rest, "有 mermaid 块缺图题（*图 N　…*）"

    # 提示框 → 自定义段落样式
    def callout(m: re.Match) -> str:
        kind = {"IMPORTANT": "Callout Important", "NOTE": "Callout Note",
                "WARNING": "Callout Important", "TIP": "Callout Note"}[m.group(1)]
        body = "\n".join(ln[2:] if ln.startswith("> ") else ln.lstrip(">")
                         for ln in m.group(2).splitlines())
        if not body.lstrip().startswith("**"):
            body = "**说明**　" + body.lstrip()
        return f'::: {{custom-style="{kind}"}}\n{body}\n:::\n'

    rest = re.sub(r"> \[!(\w+)\]\n((?:>.*\n?)+)", callout, rest)

    # 标题：## → 一级（带锚点），### → 二级
    toc: list[tuple[int, str, str]] = [(1, "阅读说明", "s-readme")]
    out = ["# 阅读说明 {#s-readme}", ""]
    for ln in rest.splitlines():
        m2, m3 = re.match(r"^## (.+)$", ln), re.match(r"^### (.+)$", ln)
        if m2:
            text = m2.group(1).strip()
            anchor = "s" + re.match(r"(\d+)", text).group(1)
            toc.append((1, text.replace("`", ""), anchor))
            out.append(f"# {text} {{#{anchor}}}")
        elif m3:
            text = m3.group(1).strip()
            num = re.match(r"(\d+)\.(\d+)", text)
            anchor = f"s{num.group(1)}-{num.group(2)}"
            toc.append((2, text.replace("`", ""), anchor))
            out.append(f"## {text} {{#{anchor}}}")
        else:
            out.append(ln)
    return "\n".join(out).strip() + "\n", meta, toc


# ---------------------------------------------------------------- 3. reference
def style_para(style, *, size=None, color=None, bold=None, before=None, after=None,
               line=None, align=None, keep_next=None, font=LATIN, east=CJK) -> None:
    f = style.font
    if size:
        f.size = Pt(size)
    if color:
        f.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        f.bold = bold
    f.italic = False
    set_fonts(style.element.get_or_add_rPr(), font, east)
    pf = style.paragraph_format
    if before is not None:
        pf.space_before = Pt(before)
    if after is not None:
        pf.space_after = Pt(after)
    if line is not None:
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = line
    if align is not None:
        pf.alignment = align
    if keep_next is not None:
        pf.keep_with_next = keep_next


def exact(pf, points: float) -> None:
    """固定行高：PingFang 的自然行高约 1.8em，按倍数排版过松。"""
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(points)


def get_style(doc, name: str, kind=WD_STYLE_TYPE.PARAGRAPH):
    try:
        return doc.styles[name]
    except KeyError:
        st = doc.styles.add_style(name, kind)
        if kind == WD_STYLE_TYPE.PARAGRAPH:
            st.base_style = doc.styles["Normal"]
        return st


def build_reference(path: Path) -> None:
    subprocess.run(["pandoc", "-o", str(path), "--print-default-data-file", "reference.docx"],
                   check=True, capture_output=True)
    doc = Document(str(path))
    normal = doc.styles["Normal"]
    style_para(normal, size=10.5, color=INK)
    put(normal.element.get_or_add_rPr(), "w:lang", RPR, val="en-US", eastAsia="zh-CN")
    for name, after in (("Body Text", 6), ("First Paragraph", 6), ("Compact", 3)):
        st = get_style(doc, name)
        style_para(st, size=10.5, color=INK, before=0 if name != "Compact" else 1, after=after)
        exact(st.paragraph_format, 17)
    h1 = get_style(doc, "Heading 1")
    style_para(h1, size=17, color=ACCENT_DARK, bold=True, before=0, after=12, line=1.15,
               keep_next=True)
    h1.paragraph_format.page_break_before = True
    borders(h1.element.get_or_add_pPr(), "w:pBdr", PPR, bottom=("single", 12, ACCENT))
    style_para(get_style(doc, "Heading 2"), size=13, color="4338CA", bold=True, before=16,
               after=6, line=1.15, keep_next=True)
    style_para(get_style(doc, "Heading 3"), size=11, color=INK, bold=True, before=10,
               after=4, keep_next=True)
    for name in ("Captioned Figure", "Figure"):
        style_para(get_style(doc, name), before=10, after=2,
                   align=WD_ALIGN_PARAGRAPH.CENTER, keep_next=True)
    style_para(get_style(doc, "Image Caption"), size=9, color="475569", before=2, after=14,
               align=WD_ALIGN_PARAGRAPH.CENTER)
    style_para(get_style(doc, "Table Caption"), size=9, color="475569")
    vc = get_style(doc, "Verbatim Char", WD_STYLE_TYPE.CHARACTER)
    vc.font.size = Pt(9)
    vc.font.color.rgb = RGBColor.from_string("4338CA")
    set_fonts(vc.element.get_or_add_rPr(), MONO, CJK)
    style_para(get_style(doc, "Source Code"), size=8.5, font=MONO)
    hl = get_style(doc, "Hyperlink", WD_STYLE_TYPE.CHARACTER)
    hl.font.color.rgb = RGBColor.from_string("4338CA")
    hl.font.underline = False
    for name, fill, edge in (("Callout Important", "FEF7E6", "D97706"),
                             ("Callout Note", "F1F3FE", ACCENT)):
        st = get_style(doc, name)
        style_para(st, size=10, color=INK, before=6, after=6)
        exact(st.paragraph_format, 16.5)
        ppr = st.element.get_or_add_pPr()
        borders(ppr, "w:pBdr", PPR, top=("single", 2, fill), bottom=("single", 2, fill),
                left=("single", 24, edge), right=("single", 2, fill))
        put(ppr, "w:shd", PPR, val="clear", color="auto", fill=fill)
        put(ppr, "w:ind", PPR, left=200, right=200)
    for name, size, bold, indent in (("TOC 1", 10.5, True, 0), ("TOC 2", 9.5, False, 420)):
        st = get_style(doc, name)
        style_para(st, size=size, color=INK if bold else "334155", bold=bold,
                   before=5 if bold else 0, after=0)
        exact(st.paragraph_format, 17 if bold else 15)
        ppr = st.element.get_or_add_pPr()
        tabs = put(ppr, "w:tabs", PPR)
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "right")
        tab.set(qn("w:leader"), "dot")
        tab.set(qn("w:pos"), str(int(TEXT_W_CM / 2.54 * 1440)))
        tabs.append(tab)
        put(ppr, "w:ind", PPR, left=indent)
    doc.save(str(path))


# ---------------------------------------------------------------- 4. post-process
def page_setup(doc, meta: dict[str, str]) -> None:
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(PAGE_W), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(MARGIN_LR)
    sec.top_margin, sec.bottom_margin = Cm(2.4), Cm(2.2)
    sec.header_distance, sec.footer_distance = Cm(1.2), Cm(1.0)
    sec.different_first_page_header_footer = True
    hp = sec.header.paragraphs[0]
    hp.text = ""
    ppr = hp._p.get_or_add_pPr()
    borders(ppr, "w:pBdr", PPR, bottom=("single", 4, RULE))
    tabs = put(ppr, "w:tabs", PPR)
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "right")
    tab.set(qn("w:pos"), str(int(TEXT_W_CM / 2.54 * 1440)))
    tabs.append(tab)
    hp._p.append(run_el(meta["标题"], size=8.5, color=MUTED, bold=True))
    r = run_el(size=8.5, color=MUTED)
    r.append(OxmlElement("w:tab"))
    hp._p.append(r)
    hp._p.append(run_el(meta.get("版本", ""), size=8.5, color=MUTED))
    fp = sec.footer.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fp._p.append(run_el("第 ", size=8.5, color=MUTED))
    fp._p.append(simple_field("PAGE", 8.5, MUTED))
    fp._p.append(run_el(" 页 · 共 ", size=8.5, color=MUTED))
    fp._p.append(simple_field("NUMPAGES", 8.5, MUTED))
    fp._p.append(run_el(" 页", size=8.5, color=MUTED))


def column_widths(table) -> list[float]:
    """按内容分宽：短标签列保证不折行，其余按内容长度分剩下的宽度。"""
    cols = len(table.columns)
    floors, weights = [], []
    for c in range(cols):
        lens = [display_len(row.cells[c].text) for row in table.rows]
        short = max([n for n in lens if n <= 18] or [6])
        floors.append(short * 0.165 + 0.45)
        capped = [min(n, 70) for n in lens]
        weights.append(max(0.55 * max(capped) + 0.45 * statistics.mean(capped), 6))
    widths = [max(TEXT_W_CM * w / sum(weights), f) for w, f in zip(weights, floors, strict=True)]
    excess = sum(widths) - TEXT_W_CM
    if excess > 0:
        room = sum(w - f for w, f in zip(widths, floors, strict=True))
        widths = [w - excess * (w - f) / room for w, f in zip(widths, floors, strict=True)]
    return widths


def style_table(table, *, legend: bool = False) -> None:
    tbl = table._tbl
    tblpr = tbl.tblPr
    widths = column_widths(table)
    twips = [int(w / 2.54 * 1440) for w in widths]
    put(tblpr, "w:tblW", TBLPR, w=sum(twips), type="dxa")
    put(tblpr, "w:jc", TBLPR, val="center")
    borders(tblpr, "w:tblBorders", TBLPR, top=("single", 8, RULE), bottom=("single", 8, RULE),
            insideH=("single", 4, RULE_LIGHT), left=("nil", 0, "auto"),
            right=("nil", 0, "auto"), insideV=("nil", 0, "auto"))
    put(tblpr, "w:tblLayout", TBLPR, type="fixed")
    mar = put(tblpr, "w:tblCellMar", TBLPR)
    for edge, val in (("top", 50), ("left", 100), ("bottom", 50), ("right", 100)):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:w"), str(val))
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    for gc, tw in zip(tbl.tblGrid.findall(qn("w:gridCol")), twips, strict=True):
        gc.set(qn("w:w"), str(tw))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_i, row in enumerate(table.rows):
        trpr = row._tr.get_or_add_trPr()
        put(trpr, "w:cantSplit", TRPR)
        if r_i == 0:
            put(trpr, "w:tblHeader", TRPR)
        for c_i, cell in enumerate(row.cells):
            tcpr = cell._tc.get_or_add_tcPr()
            put(tcpr, "w:tcW", TCPR, w=twips[c_i], type="dxa")
            fill = HEAD_FILL if r_i == 0 else (BAND_FILL if r_i % 2 == 0 else None)
            if legend and r_i > 0 and c_i == 0 and r_i - 1 < len(LEGEND):
                name, fill, edge = LEGEND[r_i - 1]
                for p in cell.paragraphs:
                    for r in list(p.runs):
                        r._r.getparent().remove(r._r)
                cell.paragraphs[0].add_run(name)
                borders(tcpr, "w:tcBorders", TCPR, left=("single", 36, edge))
            if fill:
                put(tcpr, "w:shd", TCPR, val="clear", color="auto", fill=fill)
            put(tcpr, "w:vAlign", TCPR, val="center")
            for p in cell.paragraphs:
                pf = p.paragraph_format
                pf.space_before, pf.space_after = Pt(1.5), Pt(1.5)
                exact(pf, 13.5)
                for r in p.runs:
                    code = r.style is not None and r.style.name == "Verbatim Char"
                    r.font.size = Pt(8 if code else 9)
                    if r_i == 0:
                        r.font.bold = True
                        r.font.color.rgb = RGBColor.from_string(ACCENT_DARK)


def add_cover_and_toc(doc, meta: dict[str, str], toc: list[tuple], pages: dict[str, int]):
    body = doc.element.body
    made = []

    def para(text="", *, size=10.5, color=INK, bold=False, before=0, after=0,
             align=None, spacing=None):
        p = doc.add_paragraph()
        p.style = doc.styles["Normal"]
        pf = p.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        if align is not None:
            pf.alignment = align
        if text:
            r = p.add_run(text)
            r.font.size, r.font.bold = Pt(size), bold
            r.font.color.rgb = RGBColor.from_string(color)
            if spacing:
                put(r._r.get_or_add_rPr(), "w:spacing", RPR, val=spacing)
        made.append(p._p)
        return p

    para("NUTMEG  ·  ARCHITECTURE", size=10, color=ACCENT, bold=True, before=150, after=10,
         spacing=40)
    para(meta["标题"], size=30, color=ACCENT_DARK, bold=True, after=8)
    para("竞彩足球与传统足彩的判断、审票、账务与实验系统", size=14, color="475569", after=18)
    rule = para(after=24)
    borders(rule._p.get_or_add_pPr(), "w:pBdr", PPR, bottom=("single", 24, ACCENT))
    tbl = doc.add_table(rows=0, cols=2)
    for key in ("文档", "版本", "读者", "权威关系", "范围"):
        if key not in meta:
            continue
        cells = tbl.add_row().cells
        cells[0].text, cells[1].text = key, meta[key]
    tw = [int(2.6 / 2.54 * 1440), int((TEXT_W_CM - 2.6) / 2.54 * 1440)]
    tblpr = tbl._tbl.tblPr
    put(tblpr, "w:tblW", TBLPR, w=sum(tw), type="dxa")
    borders(tblpr, "w:tblBorders", TBLPR, top=("nil", 0, "auto"), left=("nil", 0, "auto"),
            bottom=("nil", 0, "auto"), right=("nil", 0, "auto"),
            insideH=("single", 4, RULE_LIGHT), insideV=("nil", 0, "auto"))
    put(tblpr, "w:tblLayout", TBLPR, type="fixed")
    for gc, w in zip(tbl._tbl.tblGrid.findall(qn("w:gridCol")), tw, strict=True):
        gc.set(qn("w:w"), str(w))
    for row in tbl.rows:
        for c_i, cell in enumerate(row.cells):
            put(cell._tc.get_or_add_tcPr(), "w:tcW", TCPR, w=tw[c_i], type="dxa")
            for p in cell.paragraphs:
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                for r in p.runs:
                    r.font.size = Pt(9.5)
                    r.font.bold = c_i == 0
                    r.font.color.rgb = RGBColor.from_string(MUTED if c_i == 0 else INK)
    made.append(tbl._tbl)
    para("内容以仓内 docs/ARCHITECTURE.md 为准；本 Word 版由 "
         "scripts/build_architecture_docx.py 生成，是快照。", size=8.5, color=MUTED, before=40)

    head = para("目录", size=17, color=ACCENT_DARK, bold=True, after=14)
    head.paragraph_format.page_break_before = True
    borders(head._p.get_or_add_pPr(), "w:pBdr", PPR, bottom=("single", 12, ACCENT))
    for n, (level, text, anchor) in enumerate(toc):
        p = doc.add_paragraph(style=doc.styles[f"TOC {level}"])
        if n == 0:
            p._p.append(field_char("begin"))
            p._p.append(instr(' TOC \\o "1-2" \\h \\z \\u '))
            p._p.append(field_char("separate"))
        link = OxmlElement("w:hyperlink")
        link.set(qn("w:anchor"), anchor)
        link.set(qn("w:history"), "1")
        link.append(run_el(text))
        tab = run_el()
        tab.append(OxmlElement("w:tab"))
        link.append(tab)
        link.append(run_el(str(pages.get(anchor, ""))))
        p._p.append(link)
        if n == len(toc) - 1:
            p._p.append(field_char("end"))
        made.append(p._p)
    for i, el in enumerate(made):
        body.remove(el)
        body.insert(i, el)


def postprocess(docx_in: Path, docx_out: Path, meta, toc, pages, widths) -> None:
    doc = Document(str(docx_in))
    page_setup(doc, meta)
    shapes = list(doc.inline_shapes)     # pandoc 按自带参考页宽封顶到 14.8cm，这里按 A4 正文重设
    assert len(shapes) == len(widths), (len(shapes), len(widths))
    for shape, cm in zip(shapes, widths, strict=True):
        ratio = shape.width / shape.height
        shape.width, shape.height = Cm(cm), int(Cm(cm) / ratio)
    for table in doc.tables:
        header = table.rows[0].cells[0].text.strip()
        style_table(table, legend=header == "颜色")
        after = table._tbl.getnext()
        if after is not None and after.tag == qn("w:p"):    # 表后正文留白
            ppr = after.get_or_add_pPr()
            put(ppr, "w:spacing", PPR, before=200)
    add_cover_and_toc(doc, meta, toc, pages)
    cp = doc.core_properties
    cp.title, cp.subject = meta["标题"], meta.get("文档", "")
    cp.author, cp.keywords = "Nutmeg", "架构, 竞彩, 足彩, RSI, rubric"
    cp.comments = "由 scripts/build_architecture_docx.py 从 docs/ARCHITECTURE.md 生成"
    doc.save(str(docx_out))


# ---------------------------------------------------------------- 5. PDF + page numbers
def to_pdf(docx: Path, outdir: Path, profile: Path) -> Path:
    soffice = shutil.which("soffice") or "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    subprocess.run([soffice, f"-env:UserInstallation=file://{profile}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(outdir), str(docx)],
                   check=True, capture_output=True)
    return outdir / (docx.stem + ".pdf")


def heading_pages(pdf: Path, toc: list[tuple]) -> dict[str, int]:
    doc = fitz.open(str(pdf))
    texts = [page.get_text().replace(" ", "") for page in doc]
    # 正文从「阅读说明」开始（该节含维护规则）；目录页本身也列着各节标题，要跳过
    start = next(i for i, t in enumerate(texts) if "阅读说明" in t and "维护规则" in t)
    pages, cursor = {}, start
    for _, text, anchor in toc:
        key = text.replace(" ", "")
        for i in range(cursor, len(texts)):
            if key in texts[i]:
                pages[anchor] = i + 1
                cursor = i
                break
    return pages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "ARCHITECTURE.docx")
    ap.add_argument("--pdf", type=Path, help="另存 PDF 预览（LibreOffice 排版）")
    ap.add_argument("--work", type=Path, help="中间文件目录（默认临时目录）")
    args = ap.parse_args()

    work = args.work or Path(tempfile.mkdtemp(prefix="arch-docx-"))
    work.mkdir(parents=True, exist_ok=True)
    md = SRC.read_text(encoding="utf-8")
    pngs = render_diagrams(md, work)
    body_md, meta, toc = preprocess(md, pngs)
    (work / "arch-word.md").write_text(body_md, encoding="utf-8")
    ref = work / "reference.docx"
    build_reference(ref)
    raw = work / "body.docx"
    subprocess.run(["pandoc", str(work / "arch-word.md"),
                    "-f", "markdown-smart-subscript-superscript-tex_math_dollars",
                    "-t", "docx", "--reference-doc", str(ref), "--resource-path", str(work),
                    "-o", str(raw)], check=True)
    draft = work / "draft.docx"
    widths = [fig_width_cm(png) for png in pngs]
    postprocess(raw, draft, meta, toc, {}, widths)
    pages = heading_pages(to_pdf(draft, work, work / "lo-profile"), toc)
    missing = [a for _, _, a in toc if a not in pages]
    if missing:
        print(f"warning: 目录页码没找到 {missing}", file=sys.stderr)
    postprocess(raw, args.out, meta, toc, pages, widths)
    print(f"→ {args.out}")
    if args.pdf:
        pdf = to_pdf(args.out, work, work / "lo-profile")
        shutil.copy(pdf, args.pdf)
        print(f"→ {args.pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
