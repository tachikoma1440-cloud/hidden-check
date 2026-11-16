"""隠し命令チェッカー（仮称）の検出部分 v0。自前実装。

PDF / docx / 貼り付けた文章に、「人に見えないのに AI には読める文字」が混ざっていないかを調べる。
- 外部通信なし。文書は保存しない（一時ファイルも作らない）。
- 「検出なし」は安全を意味しない（BANNER を必ず表示）。
実行: python -I hidden_check.py [--json] <file.pdf|file.docx|file.txt> ...
依存: pymupdf（AGPL v3）。docx は標準ライブラリだけで読む。
"""
import json
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

NOTE = ("「重大」は悪意があるという意味ではありません。図の書き出しで残った見えない文字や、"
        "はみ出して隠れた表の文字でも出ます。見つかった場所を人が確かめてください。")
BANNER = ("検出なし＝安全ではありません。見える文字で書かれた命令、画像の中の文字、"
          "フォントの細工は検出できません。")
MIN_SPREAD = 32          # 描画後の明暗差（0-255）がこれ未満なら「見えない」とみなす
MIN_FONT_PT = 2.0
LONG_META = 200
MAX_XML_BYTES = 20_000_000
SCALE = 2                # 描画倍率

SEV = {"重大": 0, "注意": 1, "情報": 2}


def f(sev, kind, where, detail):
    return {"severity": sev, "type": kind, "where": where, "detail": detail}


def snip(s, n=120):
    s = " ".join(s.split())
    return s[:n] + ("…" if len(s) > n else "")


# ---------------------------------------------------------------- 文字列
TAG = range(0xE0000, 0xE0080)
VS_SUP = range(0xE0100, 0xE01F0)
BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
ZERO = {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x180E}


def scan_text(text, where):
    out = []
    tags = [c for c in text if ord(c) in TAG]
    if tags:
        decoded = "".join(chr(ord(c) - 0xE0000) for c in tags if 0x20 <= ord(c) - 0xE0000 < 0x7F)
        out.append(f("重大", "Unicode タグ文字（人に見えない文字列）", where,
                     f"{len(tags)} 文字。デコード結果: {snip(decoded, 100)!r}"))
    if any(ord(c) in VS_SUP for c in text):
        out.append(f("重大", "異体字セレクタ補助面（人に見えない符号化に使われる）", where, "含まれています"))
    bidi = [c for c in text if ord(c) in BIDI]
    if bidi:
        out.append(f("注意", "双方向制御文字（表示順の入れ替え）", where, f"{len(bidi)} 文字"))
    # ゼロ幅・書式文字は 3 個以上の連続だけ警告（絵文字の ZWJ などの通常利用を避ける）
    for m in re.finditer(r"[​-‍⁠﻿᠎­]{3,}", text):
        out.append(f("注意", "ゼロ幅文字などの連続", where, f"{len(m.group())} 文字が連続（位置 {m.start()}）"))
    return out


# ---------------------------------------------------------------- PDF
def _spread(pix, bbox, page_rect):
    r = pymupdf.Rect(bbox) & page_rect
    if r.is_empty:
        return None
    x0 = max(int((r.x0 - page_rect.x0) * SCALE), 0)
    y0 = max(int((r.y0 - page_rect.y0) * SCALE), 0)
    x1 = min(int((r.x1 - page_rect.x0) * SCALE) + 1, pix.width)
    y1 = min(int((r.y1 - page_rect.y0) * SCALE) + 1, pix.height)
    if x1 <= x0 or y1 <= y0:
        return None
    s, st = pix.samples, pix.stride
    lo, hi = 255, 0
    for y in range(y0, y1):
        row = s[y * st + x0: y * st + x1]
        lo, hi = min(lo, min(row)), max(hi, max(row))
    return hi - lo


def scan_pdf(path):
    out = []
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            return [f("注意", "暗号化された PDF", "文書", "中身を調べられませんでした")], 0
        try:
            ocgs = doc.get_ocgs() or {}
        except Exception:
            ocgs = {}
        off = [v.get("name", "?") for v in ocgs.values() if not v.get("on", True)]
        if off:
            out.append(f("重大", "初期状態で非表示のレイヤー", "文書",
                         f"{len(off)} 個: {snip(', '.join(off), 100)}（中の文字は表示上は見えない）"))
        for pno, page in enumerate(doc, 1):
            where = f"{pno} ページ"
            rect = page.rect
            pix = page.get_pixmap(matrix=pymupdf.Matrix(SCALE, SCALE), colorspace=pymupdf.csGRAY, annots=False)
            try:
                spans = page.get_texttrace()
            except Exception:
                spans = []
            mode3, total = [], 0
            for sp in spans:
                text = "".join(chr(c[0]) for c in sp.get("chars", []))
                t = text.strip()
                if not t:
                    continue
                total += 1
                size, op, mode, bb = sp.get("size", 0), sp.get("opacity", 1), sp.get("type", 0), sp.get("bbox")
                if mode == 3:
                    mode3.append(t)
                elif op is not None and op < 0.1:
                    out.append(f("重大", "ほぼ透明な文字", where, f"不透明度 {op:.2f}: {snip(t)!r}"))
                elif 0 < size < MIN_FONT_PT:
                    out.append(f("重大", "極小の文字", where, f"{size:.1f}pt: {snip(t)!r}"))
                elif bb and (bb[2] < rect.x0 - 1 or bb[0] > rect.x1 + 1 or bb[3] < rect.y0 - 1 or bb[1] > rect.y1 + 1):
                    out.append(f("重大", "ページの外に置かれた文字", where, f"{snip(t)!r}"))
                elif bb:
                    sp_ = _spread(pix, bb, rect)
                    if sp_ is not None and sp_ < MIN_SPREAD:
                        out.append(f("重大", "描画しても見えない文字（背景と同化／上から覆われている）", where,
                                     f"明暗差 {sp_}/255: {snip(t)!r}"))
            if mode3:
                if total and len(mode3) / total > 0.8:
                    out.append(f("情報", "ページ全体が不可視モード（スキャン文書の OCR 層の可能性）", where,
                                 f"{len(mode3)} 個。ふつうは無害"))
                else:
                    for t in mode3[:20]:
                        out.append(f("重大", "不可視の描画モードの文字", where, f"{snip(t)!r}"))
            out += scan_text(page.get_text(), where)
        for k, v in (doc.metadata or {}).items():
            if isinstance(v, str):
                # 著者名の一覧は論文で長くなるのがふつう（実在の論文で誤検出が出たため緩める）
                limit = 1500 if k in ("author", "keywords") else LONG_META
                if len(v.strip()) > limit:
                    out.append(f("注意", f"異常に長いメタデータ（{k}）", "文書情報", f"{len(v)} 文字: {snip(v)!r}"))
                out += scan_text(v, f"文書情報/{k}")
        return out, len(doc)


# ---------------------------------------------------------------- docx
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WHITE = {"FFFFFF", "FEFEFE", "FDFDFD"}
PARTS = re.compile(r"^word/(document|header\d*|footer\d*|comments|footnotes|endnotes)\.xml$")


def scan_docx(path):
    out, n_runs = [], 0
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not PARTS.match(name):
                continue
            info = z.getinfo(name)
            if info.file_size > MAX_XML_BYTES:
                out.append(f("注意", "大きすぎる XML は調べていません", name, f"{info.file_size} バイト"))
                continue
            data = z.read(name)
            if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                out.append(f("注意", "DTD/ENTITY を含む XML は調べていません（安全のため）", name, ""))
                continue
            where = name.removeprefix("word/").removesuffix(".xml")
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                out.append(f("注意", "壊れた XML", name, ""))
                continue
            for r in root.iter(W + "r"):
                text = "".join(t.text or "" for t in r.iter(W + "t"))
                if not text.strip():
                    continue
                n_runs += 1
                rpr = r.find(W + "rPr")
                if rpr is not None:
                    if rpr.find(W + "vanish") is not None:
                        out.append(f("重大", "非表示に設定された文字（w:vanish）", where, f"{snip(text)!r}"))
                        continue
                    sz = rpr.find(W + "sz")
                    if sz is not None and sz.get(W + "val", "").isdigit() and int(sz.get(W + "val")) / 2 < MIN_FONT_PT:
                        out.append(f("重大", "極小の文字", where, f"{int(sz.get(W + 'val'))/2:.1f}pt: {snip(text)!r}"))
                        continue
                    col = rpr.find(W + "color")
                    if col is not None and col.get(W + "val", "").upper() in WHITE:
                        out.append(f("重大", "白い文字", where, f"{snip(text)!r}"))
                        continue
            out += scan_text("".join(t.text or "" for t in root.iter(W + "t")), where)
    return out, n_runs


# ---------------------------------------------------------------- 共通
def dedupe(items):
    seen = {}
    for x in items:
        k = (x["type"], x["detail"])
        if k in seen:
            seen[k]["where"] += f", {x['where']}"
        else:
            seen[k] = dict(x)
    return sorted(seen.values(), key=lambda x: SEV.get(x["severity"], 9))


def scan_file(path):
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        res, n = scan_pdf(p)
    elif ext in (".docx", ".docm"):
        res, n = scan_docx(p)
    elif ext in (".txt", ".md"):
        res, n = scan_text(p.read_text(encoding="utf-8", errors="replace"), "本文"), 1
    else:
        return None
    return {"file": p.name, "units": n, "findings": dedupe(res)}


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")   # python -I は PYTHONUTF8 を無視するため
        except Exception:
            pass
    args =[a for a in sys.argv[1:] if a != "--json"]
    results = []
    for a in args:
        try:
            r = scan_file(a)
        except Exception as e:
            r = {"file": Path(a).name, "error": f"{type(e).__name__}: {e}", "findings": []}
        if r:
            results.append(r)
    if "--json" in sys.argv:
        print(json.dumps({"banner": BANNER, "results": results}, ensure_ascii=False, indent=1))
        return
    for r in results:
        crit = [x for x in r["findings"] if x["severity"] == "重大"]
        verdict = ("調べられませんでした" if r.get("error") else
                   "要確認" if crit else ("注意あり" if r["findings"] else "検出なし"))
        print(f"■ {r['file']}: {verdict}" + (f"  {r.get('error','')}" if r.get("error") else ""))
        for x in r["findings"]:
            print(f"   [{x['severity']}] {x['type']} ({x['where']}) {x['detail']}")
    if any(r["findings"] for r in results):
        print("\n" + NOTE)
    print("\n" + BANNER)


if __name__ == "__main__":
    main()
