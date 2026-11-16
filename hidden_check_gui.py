"""隠し命令チェッカー（仮称）の入力画面 v0。標準ライブラリの tkinter だけ。
実行: python -I hidden_check_gui.py
- ファイル（PDF / docx / txt）を選ぶか、文章を貼り付けて「調べる」
- 結果は画面にだけ出す。保存は「結果を保存」を押したときだけ（JSON）
- 外部通信なし。調べた文書は保存しない
"""
import json
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I は実行フォルダを探さないため
import hidden_check as hc  # noqa: E402

WARN = "見つかった文字は、そのまま AI に貼らないでください（中身が命令として働く可能性があります）。"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("隠し命令チェッカー（仮称）")
        self.geometry("900x640")
        self.results = []

        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        ttk.Label(top, text="AI に渡す前に、人に見えない文字が混ざっていないかを調べます。"
                            "この PC の中だけで処理し、文書はどこにも送りません。").pack(anchor="w")

        btns = ttk.Frame(self, padding=(10, 0)); btns.pack(fill="x")
        ttk.Button(btns, text="ファイルを選ぶ（PDF / Word）", command=self.pick).pack(side="left")
        ttk.Button(btns, text="貼り付けた文章を調べる", command=self.check_pasted).pack(side="left", padx=8)
        self.save_btn = ttk.Button(btns, text="結果を保存（JSON）", command=self.save, state="disabled")
        self.save_btn.pack(side="right")

        ttk.Label(self, text="文章を貼り付ける欄", padding=(10, 8, 10, 0)).pack(anchor="w")
        self.paste = tk.Text(self, height=5); self.paste.pack(fill="x", padx=10)

        ttk.Label(self, text="結果", padding=(10, 8, 10, 0)).pack(anchor="w")
        cols = ("sev", "type", "where", "detail")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for c, t, w in (("sev", "重さ", 60), ("type", "種類", 280), ("where", "場所", 110), ("detail", "内容", 400)):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10)

        self.status = tk.StringVar(value="ファイルを選ぶか、文章を貼り付けてください。")
        ttk.Label(self, textvariable=self.status, padding=(10, 6)).pack(anchor="w")
        self.note = tk.Label(self, text=hc.NOTE + "\n" + WARN, wraplength=860, justify="left", fg="#8a4b00")
        self.note.pack(anchor="w", padx=10)
        # この帯は常に表示する（検出の有無に関係なく）
        tk.Label(self, text=hc.BANNER, wraplength=860, justify="left", bg="#fff3cd", fg="#5c4400",
                 padx=8, pady=6).pack(fill="x", padx=10, pady=10)

    def show(self, results):
        self.results = results
        self.tree.delete(*self.tree.get_children())
        total = 0
        for r in results:
            if r.get("error"):
                self.tree.insert("", "end", values=("注意", "調べられませんでした", r["file"], r["error"]))
                total += 1
            for x in r["findings"]:
                total += 1
                self.tree.insert("", "end", values=(x["severity"], x["type"], f"{r['file']} / {x['where']}", x["detail"]))
        self.status.set("検出あり: %d 件。場所を人が確かめてください。" % total if total
                        else "検出なし。ただし安全という意味ではありません（下の黄色い帯を読んでください）。")
        self.save_btn.config(state="normal" if results else "disabled")

    def run(self, path):
        try:
            return hc.scan_file(path)
        except Exception as e:
            return {"file": Path(path).name, "error": f"{type(e).__name__}: {e}", "findings": []}

    def pick(self):
        paths = filedialog.askopenfilenames(title="調べるファイル", filetypes=[("PDF / Word", "*.pdf *.docx"), ("すべて", "*.*")])
        rs = [r for r in (self.run(p) for p in paths) if r]
        if rs:
            self.show(rs)

    def check_pasted(self):
        text = self.paste.get("1.0", "end")
        found = hc.dedupe(hc.scan_text(text, "貼り付け文"))
        self.show([{"file": "貼り付け文", "units": 1, "findings": found}])

    def save(self):
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            Path(p).write_text(json.dumps({"banner": hc.BANNER, "results": self.results}, ensure_ascii=False, indent=1),
                               encoding="utf-8")
            messagebox.showinfo("保存しました", "結果には、見つかった文字の一部が含まれます。扱いに注意してください。")


if __name__ == "__main__":
    App().mainloop()
