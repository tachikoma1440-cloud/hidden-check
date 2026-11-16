"""合成の試験ファイルを作る（隠し文字は無害な目印「隠しテスト」だけ。命令文は入れない）。
実行: python -I make_samples.py <出力フォルダ>
"""
import sys
import zipfile
from pathlib import Path

import pymupdf
import docx
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

MARK = "隠しテスト目印"
BODY = ["抄読会の資料（合成データ）", "対象: 成人 120 例、介入群と対照群に無作為に割り付けた。",
        "主要評価項目は 90 日後の機能的転帰とした。"]


def base_page(doc):
    page = doc.new_page(width=595, height=842)
    y = 80
    for line in BODY:
        page.insert_text((60, y), line, fontsize=12, fontname="japan")
        y += 24
    return page


def save(doc, path, **kw):
    doc.save(path, **kw)
    doc.close()


def pdf_samples(out):
    # 0 対照（隠しなし）
    d = pymupdf.open(); base_page(d); save(d, out / "pdf_00_clean.pdf")
    # 1 白文字（白い背景）
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 200), MARK + "_白", fontsize=12, fontname="japan", color=(1, 1, 1))
    save(d, out / "pdf_01_white.pdf")
    # 2 極小フォント
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 220), MARK + "_極小", fontsize=1, fontname="japan")
    save(d, out / "pdf_02_tiny.pdf")
    # 3 ページ外
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((700, 240), MARK + "_ページ外", fontsize=12, fontname="japan")
    save(d, out / "pdf_03_offpage.pdf")
    # 4 不可視の描画モード（孤立）
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 260), MARK + "_モード3", fontsize=12, fontname="japan", render_mode=3)
    save(d, out / "pdf_04_mode3.pdf")
    # 5 図形で覆う
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 280), MARK + "_覆い", fontsize=12, fontname="japan")
    p.draw_rect(pymupdf.Rect(50, 262, 400, 290), color=(1, 1, 1), fill=(1, 1, 1))
    save(d, out / "pdf_05_covered.pdf")
    # 6 透明に近い
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 300), MARK + "_透明", fontsize=12, fontname="japan", fill_opacity=0.02)
    save(d, out / "pdf_06_transparent.pdf")
    # 7 長いメタデータ
    d = pymupdf.open(); base_page(d)
    d.set_metadata({"title": "doc", "subject": "hidden-test-marker " * 40})
    save(d, out / "pdf_07_metadata.pdf")
    # 8 薄い灰色（見えにくいが読める。対照の境界: 検出されるべきでない）
    d = pymupdf.open(); p = base_page(d)
    p.insert_text((60, 320), "注: 図の出典は別紙（薄い灰色の注記）", fontsize=9, fontname="japan", color=(0.55, 0.55, 0.55))
    save(d, out / "pdf_08_grey_note_control.pdf")
    # 9 テキスト: タグ文字・双方向制御・ゼロ幅（PDF の標準フォントには入れられないので txt で）
    (out / "txt_00_clean.txt").write_text("通常の文章。絵文字の結合 \U0001F468‍⚕️ を含む。", encoding="utf-8")
    (out / "txt_01_tags.txt").write_text("正常な文" + "".join(chr(0xE0000 + ord(c)) for c in "hidden test") + "の途中", encoding="utf-8")
    (out / "txt_02_bidi.txt").write_text("正常な文‮反転‬の途中", encoding="utf-8")
    (out / "txt_03_zerowidth.txt").write_text("正常な文" + "​‌‍" * 4 + "の途中", encoding="utf-8")


def docx_samples(out):
    def new():
        d = docx.Document()
        for line in BODY:
            d.add_paragraph(line)
        return d

    new().save(out / "docx_00_clean.docx")

    d = new(); r = d.add_paragraph().add_run(MARK + "_白")
    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); d.save(out / "docx_01_white.docx")

    d = new(); r = d.add_paragraph().add_run(MARK + "_極小")
    r.font.size = Pt(1); d.save(out / "docx_02_tiny.docx")

    d = new(); r = d.add_paragraph().add_run(MARK + "_vanish")
    rpr = r._element.get_or_add_rPr(); rpr.append(OxmlElement("w:vanish")); d.save(out / "docx_03_vanish.docx")

    d = new(); d.sections[0].header.paragraphs[0].add_run(MARK + "_ヘッダー").font.color.rgb = RGBColor(255, 255, 255)
    d.save(out / "docx_04_header_white.docx")

    d = new(); d.add_paragraph("正常な文" + "​‌" * 6 + "の途中"); d.save(out / "docx_05_zerowidth.docx")


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    pdf_samples(out); docx_samples(out)
    print("made", len(list(out.iterdir())), "files in", out)


if __name__ == "__main__":
    main()
