#!/usr/bin/env python3
"""Convert e-Gov 法令標準XML (bulk download + API v2 law list) to LawCodex Markdown.

Input  (from scripts/fetch.py): <raw>/laws_list.json and <raw>/xml/**.xml
Output: <out>/{constitution,laws,cabinet-orders,imperial-ordinances,ministerial-ordinances,rules}/
        <year>/<LawId>.md   (constitution: constitution/<LawId>.md)

Laws whose repeal_status is not "None" (repealed / expired / lost effect) are skipped.
XML missing from the bulk archive is fetched from API v2 /law_data and cached in <raw>/api/.

Usage: python scripts/convert.py [--raw DIR] [--out DIR] [--only LAWID ...]
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import time
from collections import Counter

import requests
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RAW = os.path.normpath(os.path.join(HERE, "..", "..", "_raw", "jp"))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, ".."))
UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
API_DATA = "https://laws.e-gov.go.jp/api/2/law_data/{}"
SOURCE = "https://laws.e-gov.go.jp/law/{}"

CATEGORY = {
    "Constitution": ("constitution", "constitution"),
    "Act": ("laws", "act"),
    "CabinetOrder": ("cabinet-orders", "cabinet_order"),
    "ImperialOrder": ("imperial-ordinances", "imperial_ordinance"),
    "MinisterialOrdinance": ("ministerial-ordinances", "ministerial_ordinance"),
    "Rule": ("rules", "rule"),
}

STRUCT = {"Part": "PartTitle", "Chapter": "ChapterTitle", "Section": "SectionTitle",
          "Subsection": "SubsectionTitle", "Division": "DivisionTitle"}
SENTENCE_CONTAINERS = {"ParagraphSentence", "ItemSentence", "ClassSentence", "ListSentence",
                       "AmendProvisionSentence", "Sentence", "RemarksLabel"} | \
    {f"Subitem{i}Sentence" for i in range(1, 11)} | {f"Sublist{i}Sentence" for i in range(1, 4)}
ITEMS = {"Item"} | {f"Subitem{i}" for i in range(1, 11)}
SUBLISTS = {f"Sublist{i}" for i in range(1, 4)}
APPDX = {"AppdxTable", "AppdxNote", "AppdxStyle", "AppdxFormat", "AppdxFig", "Appdx",
         "SupplProvisionAppdxTable", "SupplProvisionAppdxStyle", "SupplProvisionAppdx"}
TITLE_TAGS = {"AppdxTableTitle", "AppdxNoteTitle", "AppdxStyleTitle", "AppdxFormatTitle",
              "AppdxFigTitle", "ArithFormulaNum", "SupplProvisionAppdxTableTitle",
              "SupplProvisionAppdxStyleTitle", "TableStructTitle", "FigStructTitle",
              "StyleStructTitle", "FormatStructTitle", "NoteStructTitle", "ClassTitle"}

MD_ESC = re.compile(r"([\\`*_\[\]<>|])")


def esc(s):
    return MD_ESC.sub(r"\\\1", s)


def html_esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def norm_ws(s):
    # XML pretty-printing whitespace (ASCII only; keep full-width spaces verbatim)
    return re.sub(r"[ \t\r\n]+", " ", s)


class Renderer:
    def __init__(self, html=False):
        self.html = html  # inline rendering inside HTML table cells
        self.stats = Counter()

    # ---------- inline ----------
    def inline(self, el):
        """Inline text of an element (Sentence-like), with Ruby/Sup/Sub etc."""
        e = html_esc if self.html else esc
        out = []
        if el.text and el.text.strip(" \t\r\n"):
            out.append(e(norm_ws(el.text)))
        for c in el:
            if not isinstance(c.tag, str):
                pass
            else:
                tag = c.tag
                if tag == "Ruby":
                    base = (c.text or "") + "".join(
                        (x.text or "") + (x.tail or "") if x.tag != "Rt" else (x.tail or "")
                        for x in c)
                    rt = "".join("".join(x.itertext()) for x in c if x.tag == "Rt")
                    out.append(f"<ruby>{html_esc(norm_ws(base))}<rt>{html_esc(norm_ws(rt))}</rt></ruby>")
                elif tag == "Sup":
                    out.append(f"<sup>{html_esc(norm_ws(''.join(c.itertext())))}</sup>")
                elif tag == "Sub":
                    out.append(f"<sub>{html_esc(norm_ws(''.join(c.itertext())))}</sub>")
                elif tag == "Fig":
                    out.append(self.fig(c))
                elif tag == "Column":
                    if out and out[-1].strip():
                        out.append("　")
                    out.append(self.inline(c))
                elif tag in ("Sentence", "Line", "QuoteStruct", "ArithFormula") or tag in SENTENCE_CONTAINERS:
                    out.append(self.inline(c))
                elif tag in ("TableStruct", "Table", "FigStruct", "StyleStruct", "List"):
                    # Rare: block structure inside a sentence; flatten
                    out.append(" ".join(self.flat_lines(c)))
                else:
                    out.append(self.inline(c))
            if c.tail and c.tail.strip(" \t\r\n"):
                out.append(e(norm_ws(c.tail)))
        s = "".join(out)
        return s

    def fig(self, el):
        src = el.get("src", "")
        self.stats["figures"] += 1
        return f"［図：{html_esc(src)}］" if src else "［図］"

    def sentences(self, el):
        """Text for a *Sentence container: Sentences concatenated, Columns joined by 　."""
        if el is None:
            return ""
        return self.inline(el).strip(" ")

    def flat_lines(self, el):
        sub = Renderer(html=True)
        lines = sub.block(el, 7, 0)
        self.stats.update(sub.stats)
        return [ln.strip() for ln in lines if ln.strip()]

    # ---------- blocks ----------
    def heading(self, level, text):
        text = text.strip()
        if not text:
            return []
        if self.html:
            return [text, ""]
        if level <= 6:
            return ["#" * level + " " + text, ""]
        return [f"**{text}**", ""]

    def child_text(self, el, tag):
        c = el.find(tag)
        return self.inline(c).strip() if c is not None else ""

    def block(self, el, level, indent):
        """Return list of Markdown lines for a block element."""
        tag = el.tag if isinstance(el.tag, str) else None
        if tag is None:
            return []
        m = getattr(self, "b_" + tag, None)
        if m:
            return m(el, level, indent)
        if tag in STRUCT:
            return self.b_struct(el, level, indent)
        if tag in ITEMS:
            return self.b_item(el, level, indent)
        if tag in SUBLISTS:
            return self.b_sublist(el, level, indent)
        if tag in APPDX:
            return self.b_appdx(el, level, indent)
        if tag in SENTENCE_CONTAINERS or tag in TITLE_TAGS or tag in ("RelatedArticleNum",):
            t = self.sentences(el)
            return [("  " * indent) + t, ""] if t else []
        if tag in ("Fig",):
            return [self.fig(el), ""]
        # generic container: recurse
        self.stats["generic:" + tag] += 1
        lines = []
        if el.text and el.text.strip():
            lines += [self.inline(el).strip(), ""]
            return lines
        for c in el:
            lines += self.block(c, level, indent)
        return lines

    def children(self, el, level, indent, skip=()):
        lines = []
        prev_list = False
        for c in el:
            if isinstance(c.tag, str) and c.tag not in skip:
                is_list = c.tag in ITEMS or c.tag == "List"
                if prev_list and not is_list:
                    lines.append("")
                lines += self.block(c, level, indent)
                prev_list = is_list
        if prev_list:
            lines.append("")
        return lines

    def b_struct(self, el, level, indent):
        title = self.child_text(el, STRUCT[el.tag])
        return self.heading(level, title) + self.children(el, level + 1, 0, skip=(STRUCT[el.tag],))

    def b_MainProvision(self, el, level, indent):
        return self.children(el, level, 0)

    def b_Article(self, el, level, indent):
        title = self.child_text(el, "ArticleTitle")
        cap = self.child_text(el, "ArticleCaption")
        lines = self.heading(level, title + cap)
        lines += self.children(el, level + 1, 0, skip=("ArticleTitle", "ArticleCaption"))
        return lines

    def b_SupplNote(self, el, level, indent):
        t = self.sentences(el)
        return [t, ""] if t else []

    def b_Paragraph(self, el, level, indent):
        lines = []
        cap = self.child_text(el, "ParagraphCaption")
        if cap:
            lines += [cap, ""]
        num = self.child_text(el, "ParagraphNum")
        sent = self.sentences(el.find("ParagraphSentence"))
        text = (num + "　" + sent) if (num and sent) else (num or sent)
        if text:
            lines += [text, ""]
        rest = self.children(el, level, 0, skip=("ParagraphCaption", "ParagraphNum", "ParagraphSentence"))
        return lines + rest

    def b_item(self, el, level, indent):
        t = el.tag
        ttag = "ItemTitle" if t == "Item" else t + "Title"
        stag = "ItemSentence" if t == "Item" else t + "Sentence"
        title = self.child_text(el, ttag)
        sent = self.sentences(el.find(stag))
        text = (title + "　" + sent) if (title and sent) else (title or sent)
        pad = "  " * indent
        lines = [f"{pad}- {text}"] if not self.html else [pad + text]
        for c in el:
            if not isinstance(c.tag, str) or c.tag in (ttag, stag):
                continue
            if c.tag in ITEMS or c.tag == "List":
                lines += [x for x in self.block(c, level, indent + 1) if x != ""]
            else:
                lines += [""] + self.block(c, level, 0) + [""]
        return lines

    def b_List(self, el, level, indent):
        pad = "  " * indent
        lines = []
        for c in el:
            if c.tag == "ListSentence":
                t = self.sentences(c)
                lines.append(f"{pad}- {t}" if not self.html else pad + t)
            elif c.tag in SUBLISTS:
                lines += self.b_sublist(c, level, indent + 1)
        return lines

    def b_sublist(self, el, level, indent):
        pad = "  " * indent
        lines = []
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag.endswith("Sentence"):
                t = self.sentences(c)
                lines.append(f"{pad}- {t}" if not self.html else pad + t)
            elif c.tag in SUBLISTS:
                lines += self.b_sublist(c, level, indent + 1)
        return lines

    def b_Class(self, el, level, indent):
        title = self.child_text(el, "ClassTitle")
        sent = self.sentences(el.find("ClassSentence"))
        text = (title + "　" + sent) if (title and sent) else (title or sent)
        return [text, ""] + self.children(el, level, 0, skip=("ClassTitle", "ClassSentence"))

    def b_AmendProvision(self, el, level, indent):
        lines = []
        for c in el:
            if c.tag == "AmendProvisionSentence":
                lines += [self.sentences(c), ""]
            elif c.tag == "NewProvision":
                inner = self.children(c, 7, 0)
                if self.html:
                    lines += inner
                else:
                    lines += [("> " + ln) if ln else ">" for ln in inner]
                    lines.append("")
        return lines

    def b_Remarks(self, el, level, indent):
        lines = []
        label = self.child_text(el, "RemarksLabel")
        if label:
            lines += [label, ""]
        return lines + self.children(el, level, 0, skip=("RemarksLabel",))

    def b_Sentence(self, el, level, indent):
        t = self.sentences(el)
        return [t, ""] if t else []

    def b_TableStruct(self, el, level, indent):
        lines = []
        for c in el:
            if c.tag == "TableStructTitle":
                t = self.inline(c).strip()
                if t:
                    lines += [t, ""]
            elif c.tag == "Table":
                lines += self.table(c) + [""]
            else:
                lines += self.block(c, level, 0)
        return lines

    def b_Table(self, el, level, indent):
        return self.table(el) + [""]

    def _figlike(self, el, level, indent):
        return self.children(el, level, 0)

    b_FigStruct = b_StyleStruct = b_FormatStruct = b_NoteStruct = _figlike
    b_Style = b_Format = b_Note = _figlike

    def b_ArithFormula(self, el, level, indent):
        if len(el) and all(isinstance(c.tag, str) and c.tag in ("Fig",) for c in el):
            return [self.fig(el[0]), ""]
        lines = self.children(el, level, 0)
        if not lines:
            t = self.inline(el).strip()
            lines = [t, ""] if t else []
        return lines

    b_QuoteStruct = b_ArithFormula

    def b_appdx(self, el, level, indent):
        title = ""
        rel = ""
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag.endswith("Title") and c.tag in TITLE_TAGS:
                title = self.inline(c).strip()
            elif c.tag == "RelatedArticleNum":
                rel = self.inline(c).strip()
        if not title:
            title = {"AppdxTable": "別表", "AppdxNote": "別記", "AppdxStyle": "様式",
                     "AppdxFormat": "書式", "AppdxFig": "別図", "Appdx": "付録"}.get(
                         el.tag.replace("SupplProvision", ""), "")
        lines = self.heading(level, title + rel)
        lines += self.children(el, level + 1, 0,
                               skip=TITLE_TAGS | {"RelatedArticleNum"})
        return lines

    def b_SupplProvision(self, el, level, indent):
        label = self.child_text(el, "SupplProvisionLabel")
        amend = el.get("AmendLawNum")
        h = label
        if amend:
            h += f"（{amend}）"
        if el.get("Extract") == "true":
            h += "　抄"
        lines = self.heading(level, h)
        lines += self.children(el, level + 1, 0, skip=("SupplProvisionLabel",))
        return lines

    def b_EnactStatement(self, el, level, indent):
        return [self.sentences(el), ""]

    def b_Preamble(self, el, level, indent):
        return self.children(el, level, 0)

    # ---------- TOC ----------
    def b_TOC(self, el, level, indent):
        lines = []
        label = self.child_text(el, "TOCLabel") or "目次"
        lines += [label, ""]
        for c in el:
            if isinstance(c.tag, str) and c.tag != "TOCLabel":
                lines += self.toc_entry(c, 0)
        lines.append("")
        return lines

    def toc_entry(self, el, indent):
        tag = el.tag
        title = ""
        rng = ""
        kids = []
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag.endswith("Title") or c.tag.endswith("Label"):
                title = self.inline(c).strip()
            elif c.tag == "ArticleRange":
                rng = self.inline(c).strip()
            elif c.tag.startswith("TOC") or c.tag in ("Article",):
                kids.append(c)
        if not title and el.text and el.text.strip():
            title = self.inline(el).strip()
        lines = []
        if title or rng:
            lines.append("  " * indent + "- " + title + rng)
        for k in kids:
            lines += self.toc_entry(k, indent + 1)
        return lines

    # ---------- tables ----------
    def cell_content(self, col):
        sub = Renderer(html=True)
        parts = []
        if col.text and col.text.strip():
            parts.append(html_esc(norm_ws(col.text).strip()))
        for c in col:
            if not isinstance(c.tag, str):
                continue
            if c.tag == "Sentence" or c.tag == "Column":
                parts.append(sub.inline(c).strip())
            else:
                parts += [ln.strip() for ln in sub.block(c, 7, 0) if ln.strip()]
        self.stats.update(sub.stats)
        return [p for p in parts if p]

    def table(self, el):
        rows = []
        complex_ = False
        for r in el:
            if not isinstance(r.tag, str) or r.tag not in ("TableRow", "TableHeaderRow"):
                continue
            cells = []
            for col in r:
                if not isinstance(col.tag, str):
                    continue
                if col.tag == "TableHeaderColumn":
                    content = [Renderer(html=True).inline(col).strip()]
                else:
                    content = self.cell_content(col)
                rs, cs = col.get("rowspan"), col.get("colspan")
                if (rs and rs != "1") or (cs and cs != "1") or len(content) > 1:
                    complex_ = True
                cells.append((col.tag, content, rs, cs))
            rows.append((r.tag, cells))
        if not rows:
            return []
        widths = {len(c) for _, c in rows}
        if len(widths) != 1:
            complex_ = True
        if self.html:
            complex_ = True
        self.stats["tables_html" if complex_ else "tables_md"] += 1
        if not complex_:
            n = widths.pop()
            out = []

            def mdcell(content):
                return (content[0] if content else "").replace("|", "\\|") or " "
            # use first row as header only if it is a header row; else empty header
            if rows[0][0] == "TableHeaderRow":
                hdr, body = rows[0], rows[1:]
                out.append("| " + " | ".join(mdcell(c[1]) for c in hdr[1]) + " |")
            else:
                body = rows
                out.append("|" + " |" * n)
            out.append("|" + " --- |" * n)
            for _, cells in body:
                out.append("| " + " | ".join(mdcell(c[1]) for c in cells) + " |")
            return out
        out = ["<table>"]
        for rtag, cells in rows:
            out.append("<tr>")
            for ctag, content, rs, cs in cells:
                t = "th" if rtag == "TableHeaderRow" or ctag == "TableHeaderColumn" else "td"
                attrs = ""
                if rs and rs != "1":
                    attrs += f' rowspan="{rs}"'
                if cs and cs != "1":
                    attrs += f' colspan="{cs}"'
                out.append(f"<{t}{attrs}>" + "<br>".join(content) + f"</{t}>")
            out.append("</tr>")
        out.append("</table>")
        return out


def yaml_str(s):
    s = "" if s is None else str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_law(law_el, meta, retrieved):
    li, ri = meta["law_info"], meta["revision_info"]
    r = Renderer()
    body = law_el.find("LawBody")
    title = ri["law_title"] or "".join(body.find("LawTitle").itertext()).strip()
    cat_key = li["law_type"].split(",")[0]
    _, typ = CATEGORY[cat_key]
    status = "in_force"
    if ri["repeal_status"] != "None":
        status = "repealed"
    elif ri["current_revision_status"] == "UnEnforced":
        status = "unknown"  # promulgated, not yet in force (未施行)
    fm = [
        "---",
        f"title: {yaml_str(title)}",
        f"identifier: {yaml_str(li['law_id'])}",
        f"law_number: {yaml_str(li['law_num'])}",
        f"type: {typ}",
        "jurisdiction: jp",
        "language: ja",
    ]
    if li.get("promulgation_date"):
        fm.append(f"date: {li['promulgation_date']}")
    if ri.get("amendment_enforcement_date"):
        fm.append(f"last_amended: {ri['amendment_enforcement_date']}")
    fm.append(f"status: {status}")
    if ri.get("law_title_kana"):
        fm.append(f"title_kana: {yaml_str(ri['law_title_kana'])}")
    if ri.get("abbrev"):
        fm.append(f"abbrev: {yaml_str(ri['abbrev'])}")
    if ri.get("category"):
        fm.append(f"category: {yaml_str(ri['category'])}")
    fm.append(f"revision_id: {yaml_str(ri['law_revision_id'])}")
    if ri.get("amendment_law_num"):
        fm.append(f"last_amendment_law: {yaml_str(ri['amendment_law_num'])}")
    if ri["current_revision_status"] == "UnEnforced":
        fm.append('enforcement: "未施行"')
    fm += [
        f"source: {yaml_str(SOURCE.format(li['law_id']))}",
        f"retrieved: {retrieved}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    lines = []
    ln = law_el.find("LawNum")
    if ln is not None and (ln.text or "").strip():
        lines += [r.inline(ln).strip(), ""]
    for c in body:
        if not isinstance(c.tag, str) or c.tag == "LawTitle":
            continue
        lines += r.block(c, 2, 0)
    # collapse multiple blank lines
    out = []
    for x in lines:
        x = x.rstrip()
        if x == "" and (not out or out[-1] == ""):
            continue
        out.append(x)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(fm + out) + "\n", r.stats


def index_xml(xml_dir):
    idx = {}
    for p in glob.glob(os.path.join(xml_dir, "**", "*.xml"), recursive=True):
        base = os.path.splitext(os.path.basename(p))[0]
        idx[base] = p
    return idx


def fetch_api_xml(raw, rev_id, session):
    d = os.path.join(raw, "api")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, rev_id + ".xml")
    if os.path.exists(p):
        return p
    for attempt in range(5):
        try:
            r = session.get(API_DATA.format(rev_id), timeout=120,
                            params={"law_full_text_format": "xml", "response_format": "xml"})
            if r.status_code == 200:
                with open(p, "wb") as f:
                    f.write(r.content)
                time.sleep(1)
                return p
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(5 * 2 ** attempt)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=DEFAULT_RAW)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--category", help="only this output directory (e.g. laws)")
    ap.add_argument("--retrieved", default=datetime.date.today().isoformat())
    a = ap.parse_args()

    laws = json.load(open(os.path.join(a.raw, "laws_list.json"), encoding="utf-8"))
    idx = index_xml(os.path.join(a.raw, "xml"))
    print(f"{len(laws)} laws in list, {len(idx)} XML files in bulk archive")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    counts, skipped, stats, missing, errors = Counter(), Counter(), Counter(), [], []
    for meta in laws:
        li, ri = meta["law_info"], meta["revision_info"]
        lid = li["law_id"]
        if a.only and lid not in a.only:
            continue
        if ri["repeal_status"] != "None":
            skipped[ri["repeal_status"]] += 1
            continue
        cat_key = li["law_type"].split(",")[0]
        cat, _ = CATEGORY[cat_key]
        if a.category and cat != a.category:
            continue
        rev = ri["law_revision_id"]
        path = idx.get(rev)
        if path is None:
            cands = [k for k in idx if k.startswith(lid + "_")]
            if cands:
                path = idx[sorted(cands)[-1]]
                if not cands[-1] == rev:
                    print(f"  note: {lid}: bulk has {sorted(cands)[-1]}, list says {rev}; using API")
                    path = None
        if path is None:
            path = fetch_api_xml(a.raw, rev, session)
        if path is None:
            missing.append(lid)
            continue
        try:
            tree = etree.parse(path, etree.XMLParser(huge_tree=True, remove_comments=True))
            root = tree.getroot()
            law_el = root if root.tag == "Law" else root.find(".//Law")
            md, st = render_law(law_el, meta, a.retrieved)
        except Exception as e:  # noqa
            errors.append((lid, repr(e)))
            print(f"  ERROR {lid}: {e!r}", file=sys.stderr)
            continue
        stats.update(st)
        if cat == "constitution":
            rel = os.path.join(cat, lid + ".md")
        else:
            year = (li.get("promulgation_date") or "0000")[:4]
            rel = os.path.join(cat, year, lid + ".md")
        dst = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline="\n") as f:
            f.write(md)
        counts[cat] += 1
    print("written:", dict(counts))
    print("skipped (not in force):", dict(skipped))
    print("missing XML:", missing)
    print("errors:", errors)
    print("stats:", dict(stats))
    with open(os.path.join(a.raw, "convert_report.json"), "w") as f:
        json.dump({"counts": counts, "skipped": skipped, "missing": missing,
                   "errors": errors, "stats": stats}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
