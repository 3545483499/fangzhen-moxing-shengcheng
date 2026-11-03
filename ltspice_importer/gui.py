"""中文图形界面（tkinter，无额外依赖）。"""

from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import (
    DEFAULT_APP_SUPPORT_LIB,
    DEFAULT_USER_LIB,
    detect_targets,
    load_config,
    save_config,
)
from .importer import Importer


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"LTspice 模型导入工具  v{__version__}")
        self.geometry("920x680")
        self.minsize(760, 560)

        self.config_data = load_config()
        self.source_paths: list[Path] = []

        self._build()
        self._load_fields()
        self._refresh_detect()

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        frm_src = ttk.LabelFrame(self, text="1. 选择要导入的模型 / 厂商包")
        frm_src.pack(fill="x", **pad)

        btn_row = ttk.Frame(frm_src)
        btn_row.pack(fill="x", padx=6, pady=4)
        ttk.Button(btn_row, text="添加文件…", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(btn_row, text="添加文件夹…", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(btn_row, text="添加 ZIP…", command=self._add_zip).pack(side="left", padx=2)
        ttk.Button(btn_row, text="清空列表", command=self._clear_sources).pack(side="left", padx=2)

        self.lst_sources = tk.Listbox(frm_src, height=5, selectmode=tk.EXTENDED)
        self.lst_sources.pack(fill="x", padx=6, pady=4)

        frm_tgt = ttk.LabelFrame(self, text="2. 目标库目录（完全本地 / 离线）")
        frm_tgt.pack(fill="x", **pad)

        row1 = ttk.Frame(frm_tgt)
        row1.pack(fill="x", padx=6, pady=2)
        ttk.Label(row1, text="主库根目录:").pack(side="left")
        self.var_primary = tk.StringVar()
        ttk.Entry(row1, textvariable=self.var_primary).pack(
            side="left", fill="x", expand=True, padx=4
        )
        ttk.Button(row1, text="浏览…", command=self._browse_primary).pack(side="left")
        ttk.Button(row1, text="默认 userDate", command=self._use_userdate).pack(side="left", padx=2)

        row2 = ttk.Frame(frm_tgt)
        row2.pack(fill="x", padx=6, pady=2)
        ttk.Label(row2, text="分类子文件夹:").pack(side="left")
        self.var_category = tk.StringVar()
        ttk.Entry(row2, textvariable=self.var_category, width=24).pack(side="left", padx=4)
        ttk.Label(row2, text="（写入 sub/<分类> 与 sym/<分类>，可留空）").pack(side="left")

        row3 = ttk.Frame(frm_tgt)
        row3.pack(fill="x", padx=6, pady=2)
        self.var_also_app = tk.BooleanVar()
        ttk.Checkbutton(
            row3,
            text="同时写入 Application Support/LTspice/lib（覆盖前自动备份）",
            variable=self.var_also_app,
        ).pack(side="left")

        row3b = ttk.Frame(frm_tgt)
        row3b.pack(fill="x", padx=6, pady=2)
        ttk.Label(row3b, text="App Support 路径:").pack(side="left")
        self.var_app_support = tk.StringVar()
        ttk.Entry(row3b, textvariable=self.var_app_support).pack(
            side="left", fill="x", expand=True, padx=4
        )

        frm_opt = ttk.LabelFrame(self, text="3. 选项")
        frm_opt.pack(fill="x", **pad)

        opt_row = ttk.Frame(frm_opt)
        opt_row.pack(fill="x", padx=6, pady=4)
        ttk.Label(opt_row, text="重名策略:").pack(side="left")
        self.var_conflict = tk.StringVar(value="rename")
        for text, val in (("重命名", "rename"), ("跳过", "skip"), ("覆盖并备份", "overwrite")):
            ttk.Radiobutton(opt_row, text=text, value=val, variable=self.var_conflict).pack(
                side="left", padx=6
            )

        self.var_auto_asy = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_opt,
            text="若无 .asy，根据 .SUBCKT / .MODEL 自动生成简易符号",
            variable=self.var_auto_asy,
        ).pack(anchor="w", padx=6)

        self.var_dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opt,
            text="演练模式（dry-run：只解析，不写入）",
            variable=self.var_dry,
        ).pack(anchor="w", padx=6, pady=2)

        frm_det = ttk.LabelFrame(self, text="本机路径检测")
        frm_det.pack(fill="x", **pad)
        self.txt_detect = tk.Text(frm_det, height=4, wrap="word")
        self.txt_detect.pack(fill="x", padx=6, pady=4)

        frm_act = ttk.Frame(self)
        frm_act.pack(fill="x", **pad)
        ttk.Button(frm_act, text="开始导入", command=self._run_import).pack(side="left", padx=4)
        ttk.Button(frm_act, text="保存设置", command=self._save_settings).pack(side="left", padx=4)
        ttk.Button(frm_act, text="打开主库文件夹", command=self._open_primary).pack(
            side="left", padx=4
        )
        ttk.Button(frm_act, text="重新检测路径", command=self._refresh_detect).pack(
            side="left", padx=4
        )

        frm_log = ttk.LabelFrame(self, text="4. 日志与导入清单")
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = tk.Text(frm_log, wrap="word")
        scroll = ttk.Scrollbar(frm_log, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=4)

    def _load_fields(self) -> None:
        c = self.config_data
        self.var_primary.set(c.primary_lib_root)
        self.var_category.set(c.category)
        self.var_also_app.set(c.also_write_app_support)
        self.var_app_support.set(c.app_support_lib_root or str(DEFAULT_APP_SUPPORT_LIB))
        self.var_conflict.set(c.conflict_policy)
        self.var_auto_asy.set(c.auto_generate_asy)

    def _collect_config(self):
        c = self.config_data
        c.primary_lib_root = self.var_primary.get().strip()
        c.category = self.var_category.get().strip()
        c.also_write_app_support = bool(self.var_also_app.get())
        c.app_support_lib_root = self.var_app_support.get().strip() or str(
            DEFAULT_APP_SUPPORT_LIB
        )
        c.conflict_policy = self.var_conflict.get()
        c.auto_generate_asy = bool(self.var_auto_asy.get())
        c.backup_on_overwrite = True
        return c

    def _log(self, msg: str) -> None:
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.update_idletasks()

    def _refresh_sources_list(self) -> None:
        self.lst_sources.delete(0, "end")
        for p in self.source_paths:
            self.lst_sources.insert("end", str(p))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 SPICE 模型或符号",
            filetypes=[
                ("SPICE / 符号", "*.lib *.sub *.cir *.mod *.spi *.asy *.zip"),
                ("全部", "*.*"),
            ],
        )
        for p in paths:
            path = Path(p)
            if path not in self.source_paths:
                self.source_paths.append(path)
        self._refresh_sources_list()

    def _add_folder(self) -> None:
        d = filedialog.askdirectory(title="选择厂商模型文件夹")
        if d:
            path = Path(d)
            if path not in self.source_paths:
                self.source_paths.append(path)
            self._refresh_sources_list()

    def _add_zip(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择 ZIP 厂商包",
            filetypes=[("ZIP", "*.zip"), ("全部", "*.*")],
        )
        for p in paths:
            path = Path(p)
            if path not in self.source_paths:
                self.source_paths.append(path)
        self._refresh_sources_list()

    def _clear_sources(self) -> None:
        self.source_paths.clear()
        self._refresh_sources_list()

    def _browse_primary(self) -> None:
        d = filedialog.askdirectory(title="选择库根目录（其下应有或将创建 sub / sym）")
        if d:
            self.var_primary.set(d)

    def _use_userdate(self) -> None:
        self.var_primary.set(str(DEFAULT_USER_LIB))

    def _save_settings(self) -> None:
        c = self._collect_config()
        path = save_config(c)
        self.config_data = c
        messagebox.showinfo("已保存", f"配置已写入:\n{path}")

    def _open_primary(self) -> None:
        c = self._collect_config()
        folder = Path(c.primary_lib_root).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(folder)], check=False)

    def _refresh_detect(self) -> None:
        info = detect_targets()
        lines = []
        for key, val in info.items():
            mark = "存在" if val["exists"] else "未找到"
            lines.append(f"[{mark}] {key}: {val['path']}")
        self.txt_detect.delete("1.0", "end")
        self.txt_detect.insert("1.0", "\n".join(lines))

    def _run_import(self) -> None:
        if not self.source_paths:
            messagebox.showwarning("提示", "请先添加要导入的文件、文件夹或 ZIP。")
            return
        c = self._collect_config()
        save_config(c)
        self.config_data = c
        self.txt_log.delete("1.0", "end")
        self._log("开始导入…")
        dry = bool(self.var_dry.get())

        def progress(msg: str) -> None:
            self._log(msg)

        try:
            report = Importer(c, progress=progress).import_paths(
                list(self.source_paths), dry_run=dry
            )
            self._log("")
            self._log("\n".join(report.summary_lines()))
            if report.errors:
                messagebox.showwarning(
                    "完成（有错误）",
                    f"完成，但有 {len(report.errors)} 个错误，请查看日志。",
                )
            else:
                messagebox.showinfo(
                    "完成",
                    "演练完成。" if dry else "导入完成。请查看下方使用说明清单。",
                )
        except Exception as exc:  # noqa: BLE001 — GUI 顶层捕获
            self._log(f"异常: {exc}")
            messagebox.showerror("失败", str(exc))


def run_gui() -> None:
    app = App()
    app.mainloop()
