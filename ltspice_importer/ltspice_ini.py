"""读写 LTspice.ini：修正 SymbolSearchPath / LibrarySearchPath（UTF-16）。"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_LTSPICE_INI, AppConfig


@dataclass
class IniFixReport:
    ini_path: str
    backup_path: str = ""
    symbol_paths: list[str] | None = None
    library_paths: list[str] | None = None
    changed: bool = False
    messages: list[str] | None = None

    def __post_init__(self) -> None:
        self.symbol_paths = self.symbol_paths or []
        self.library_paths = self.library_paths or []
        self.messages = self.messages or []


def _detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # NUL-heavy → likely UTF-16 LE without clear BOM handling
    if b"\x00" in raw[:200]:
        return "utf-16"
    return "utf-8"


def _split_paths(value: str) -> list[str]:
    parts = []
    for p in value.split(";"):
        p = p.strip().strip('"')
        if p:
            parts.append(p)
    return parts


def _merge_paths(existing: list[str], required: list[str]) -> list[str]:
    """保留已有顺序，追加缺失项；顺带去掉明显错误的「把 sym 指到 sub」重复。"""
    seen: set[str] = set()
    out: list[str] = []
    for p in existing + required:
        key = p.rstrip("/\\")
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append(p)
    return out


def desired_search_paths(config: AppConfig) -> tuple[list[str], list[str]]:
    """返回 (symbol_paths, library_paths)。必须含 sym 根与分类，以及 sub 根与分类。"""
    syms: list[str] = []
    libs: list[str] = []
    for root in config.all_lib_roots():
        sym_root = root / config.sym_dir_name
        sub_root = root / config.sub_dir_name
        syms.append(str(sym_root))
        libs.append(str(sub_root))
        if config.category:
            syms.append(str(sym_root / config.category))
            libs.append(str(sub_root / config.category))
    # 去重保序
    def uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in xs:
            k = x.rstrip("/\\").lower()
            if k not in seen:
                seen.add(k)
                out.append(x)
        return out

    return uniq(syms), uniq(libs)


def update_ltspice_ini(
    config: AppConfig,
    *,
    ini_path: Path | None = None,
    dry_run: bool = False,
) -> IniFixReport:
    """备份并更新 SymbolSearchPath / LibrarySearchPath。

    - SymbolSearchPath 必须指向 .../sym 与 .../sym/<category>
    - LibrarySearchPath 必须指向 .../sub 与 .../sub/<category>
    绝不把 SymbolSearchPath 指到 sub。
    """
    path = Path(ini_path or config.ltspice_ini_path or DEFAULT_LTSPICE_INI).expanduser()
    report = IniFixReport(ini_path=str(path))
    want_sym, want_lib = desired_search_paths(config)
    report.symbol_paths = want_sym
    report.library_paths = want_lib

    if not path.is_file():
        report.messages.append(f"未找到 LTspice.ini: {path}")
        return report

    raw = path.read_bytes()
    enc = _detect_encoding(raw)
    text = raw.decode(enc)

    lines = text.splitlines(keepends=True)
    # 统一用 \n 处理逻辑，写回时尽量保留原换行
    def strip_nl(s: str) -> tuple[str, str]:
        if s.endswith("\r\n"):
            return s[:-2], "\r\n"
        if s.endswith("\n"):
            return s[:-1], "\n"
        if s.endswith("\r"):
            return s[:-1], "\r"
        return s, "\n"

    sym_idx = lib_idx = None
    cur_sym: list[str] = []
    cur_lib: list[str] = []
    for i, line in enumerate(lines):
        body, _ = strip_nl(line)
        if body.startswith("SymbolSearchPath=") and not body.startswith(
            "SymbolSearchPathDisabled"
        ):
            sym_idx = i
            cur_sym = _split_paths(body.split("=", 1)[1])
        elif body.startswith("LibrarySearchPath=") and not body.startswith(
            "LibrarySearchPathDisabled"
        ):
            lib_idx = i
            cur_lib = _split_paths(body.split("=", 1)[1])

    new_sym = _merge_paths(cur_sym, want_sym)
    new_lib = _merge_paths(cur_lib, want_lib)

    # 纠错：若 Symbol 路径误指到 /sub（且不是名字里碰巧含 sub 的 sym），尽量剔除明显错误项
    fixed_sym: list[str] = []
    for p in new_sym:
        norm = p.replace("\\", "/").lower()
        if norm.rstrip("/").endswith("/sub") or "/sub/" in norm and "/sym" not in norm:
            # 误把 sub 写进 SymbolSearchPath —— 跳过该错误项
            report.messages.append(f"已从 SymbolSearchPath 移除错误的 sub 路径: {p}")
            continue
        fixed_sym.append(p)
    # 确保 want_sym 仍在
    new_sym = _merge_paths(fixed_sym, want_sym)

    changed = new_sym != cur_sym or new_lib != cur_lib or sym_idx is None or lib_idx is None
    report.symbol_paths = new_sym
    report.library_paths = new_lib
    report.changed = changed

    if not changed:
        report.messages.append("LTspice.ini 搜索路径已正确，无需修改。")
        return report

    if dry_run:
        report.messages.append("dry-run：将更新 SymbolSearchPath / LibrarySearchPath。")
        return report

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{ts}")
    shutil.copy2(path, backup)
    report.backup_path = str(backup)
    report.messages.append(f"已备份 ini → {backup}")

    sym_line = "SymbolSearchPath=" + ";".join(new_sym)
    lib_line = "LibrarySearchPath=" + ";".join(new_lib)

    # 重建行（保留原换行符风格）
    sample_nl = "\n"
    for line in lines:
        _, nl = strip_nl(line)
        if nl:
            sample_nl = nl
            break

    if sym_idx is not None:
        lines[sym_idx] = sym_line + sample_nl
    else:
        # 插在 Options 段较前位置
        lines.append(sym_line + sample_nl)
        report.messages.append("原 ini 无 SymbolSearchPath，已追加。")

    if lib_idx is not None:
        lines[lib_idx] = lib_line + sample_nl
    else:
        lines.append(lib_line + sample_nl)
        report.messages.append("原 ini 无 LibrarySearchPath，已追加。")

    # 确保 Disabled=false
    def ensure_flag(name: str, value: str = "false") -> None:
        nonlocal lines
        key = f"{name}="
        for i, line in enumerate(lines):
            body, nl = strip_nl(line)
            if body.startswith(key):
                lines[i] = f"{name}={value}" + nl
                return
        lines.append(f"{name}={value}" + sample_nl)

    ensure_flag("SymbolSearchPathDisabled", "false")
    ensure_flag("LibrarySearchPathDisabled", "false")

    new_text = "".join(lines)
    path.write_bytes(new_text.encode(enc))
    report.messages.append("已更新 SymbolSearchPath（sym）与 LibrarySearchPath（sub）。")
    return report


def post_import_fix(config: AppConfig, *, dry_run: bool = False) -> IniFixReport:
    """导入成功后调用：修正 ini（若开启）。"""
    if not config.auto_fix_ini_paths:
        r = IniFixReport(ini_path=config.ltspice_ini_path)
        r.messages.append("已跳过 ini 修复（auto_fix_ini_paths=false）。")
        return r
    return update_ltspice_ini(config, dry_run=dry_run)
