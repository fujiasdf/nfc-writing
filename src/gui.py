from __future__ import annotations

import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from .csv_queue import WriteItem, load_csv
from .nfc_backends.base import NfcWriter
from .nfc_backends.mock import MockWriter
from .sound import beep_error, beep_ok


@dataclass
class AppState:
    items: list[WriteItem]
    cursor: int = 0
    running: bool = False
    last_message: str = ""


class NfcBatchApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NFC 連続書き込みツール")
        self.geometry("760x420")

        self.state = AppState(items=[])
        self._writer: NfcWriter | None = None
        self._worker_thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

        self._build_ui()
        self._render()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)

        self.csv_path_var = tk.StringVar(value="")
        ttk.Label(top, text="CSV:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.csv_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        ttk.Button(top, text="選択", command=self._pick_csv).pack(side=tk.LEFT)

        opts = ttk.Frame(root)
        opts.pack(fill=tk.X, pady=(10, 0))

        self.mock_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="モックモード（実機なし）", variable=self.mock_var).pack(side=tk.LEFT)

        self.fail_every_var = tk.StringVar(value="0")
        ttk.Label(opts, text="モック失敗頻度(n件ごと,0=なし):").pack(side=tk.LEFT, padx=(16, 6))
        ttk.Entry(opts, width=6, textvariable=self.fail_every_var).pack(side=tk.LEFT)

        mid = ttk.Frame(root)
        mid.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.tree = ttk.Treeview(mid, columns=("type", "payload", "status"), show="headings", height=12)
        self.tree.heading("type", text="type")
        self.tree.heading("payload", text="payload")
        self.tree.heading("status", text="status")
        self.tree.column("type", width=80, stretch=False)
        self.tree.column("payload", width=520, stretch=True)
        self.tree.column("status", width=120, stretch=False)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        bottom = ttk.Frame(root)
        bottom.pack(fill=tk.X, pady=(12, 0))

        self.progress_var = tk.StringVar(value="未読み込み")
        ttk.Label(bottom, textvariable=self.progress_var).pack(side=tk.LEFT)

        self.msg_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.msg_var).pack(side=tk.LEFT, padx=(16, 0))

        btns = ttk.Frame(root)
        btns.pack(fill=tk.X, pady=(12, 0))

        self.start_btn = ttk.Button(btns, text="開始", command=self._start)
        self.stop_btn = ttk.Button(btns, text="停止", command=self._stop)
        self.reset_btn = ttk.Button(btns, text="先頭へ戻す", command=self._reset_cursor)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.reset_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(btns, text="CSV読込", command=self._load_from_ui).pack(side=tk.RIGHT)

    def _pick_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if path:
            self.csv_path_var.set(path)

    def _load_from_ui(self) -> None:
        try:
            items = load_csv(self.csv_path_var.get())
        except Exception as e:
            messagebox.showerror("CSV読込エラー", str(e))
            return

        self.state = AppState(items=items, cursor=0, running=False, last_message="")
        self._rebuild_table()
        self._render()

    def _rebuild_table(self) -> None:
        for x in self.tree.get_children():
            self.tree.delete(x)
        for it in self.state.items:
            self.tree.insert("", tk.END, iid=str(it.index), values=(it.type, it.payload, "pending"))

    def _render(self) -> None:
        total = len(self.state.items)
        cur = self.state.cursor
        if total == 0:
            self.progress_var.set("未読み込み")
        else:
            self.progress_var.set(f"{cur+1 if cur < total else total}/{total}")

        self.msg_var.set(self.state.last_message)
        self.start_btn.configure(state=("disabled" if self.state.running or total == 0 else "normal"))
        self.stop_btn.configure(state=("normal" if self.state.running else "disabled"))

        for it in self.state.items:
            iid = str(it.index)
            tags = ()
            if it.index == self.state.cursor and self.state.running:
                tags = ("current",)
            self.tree.item(iid, tags=tags)
        self.tree.tag_configure("current", background="#e8f2ff")

    def _reset_cursor(self) -> None:
        if self.state.running:
            return
        self.state.cursor = 0
        for it in self.state.items:
            self.tree.set(str(it.index), "status", "pending")
        self.state.last_message = "先頭に戻しました"
        self._render()

    def _start(self) -> None:
        if not self.state.items:
            self._load_from_ui()
            if not self.state.items:
                return

        if self.state.cursor >= len(self.state.items):
            self.state.cursor = 0

        self._writer = self._make_writer()
        self._stop_flag.clear()
        self.state.running = True
        self.state.last_message = "タグをかざしてください"
        self._render()

        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def _stop(self) -> None:
        self._stop_flag.set()
        self.state.running = False
        self.state.last_message = "停止しました"
        self._render()

    def _make_writer(self) -> NfcWriter:
        if self.mock_var.get():
            try:
                fail_every = int(self.fail_every_var.get() or "0")
            except ValueError:
                fail_every = 0
            return MockWriter(fail_every=max(0, fail_every))

        raise RuntimeError("実機モードは未実装です。まずはモックモードを使ってください。")

    def _set_status(self, idx: int, status: str) -> None:
        iid = str(idx)
        if self.tree.exists(iid):
            self.tree.set(iid, "status", status)

    def _worker(self) -> None:
        assert self._writer is not None

        while not self._stop_flag.is_set() and self.state.cursor < len(self.state.items):
            it = self.state.items[self.state.cursor]
            self._ui(lambda: self._set_status(it.index, "writing"))

            try:
                if it.type == "uri":
                    res = self._writer.write_uri(it.payload, timeout_s=None)
                else:
                    res = self._writer.write_text(it.payload, timeout_s=None)
            except Exception as e:
                res_ok = False
                msg = str(e)
            else:
                res_ok = res.ok
                msg = res.message

            if res_ok:
                beep_ok()
                self._ui(lambda: self._set_status(it.index, "ok"))
                self.state.cursor += 1
                self.state.last_message = f"成功: {msg}"
                self._ui(self._render)
            else:
                beep_error()
                self._ui(lambda: self._set_status(it.index, "error"))
                self.state.last_message = f"失敗: {msg}（同じ行を再試行）"
                self._ui(self._render)
                time.sleep(0.2)

        self.state.running = False
        if self.state.cursor >= len(self.state.items):
            self.state.last_message = "完了しました"
        self._ui(self._render)

    def _ui(self, fn) -> None:
        self.after(0, fn)


def run_gui(*, csv_path: str, mock: bool) -> int:
    app = NfcBatchApp()
    if csv_path:
        app.csv_path_var.set(csv_path)
    if mock:
        app.mock_var.set(True)
    app.mainloop()
    return 0

