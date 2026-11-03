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


def _uniq(xs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in xs:
        k = x.rstrip("/\\").lower()
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def search_lib_roots(config: AppConfig) -> list[Path]:
    """进入 Search Paths 的库根：主库 + 可选 userDate。

    Application Support 副本只作镜像写入，不加入搜索路径，避免 F2 出现多套重复入口。
    """
    roots: list[Path] = [Path(config.primary_lib_root).expanduser()]
    if config.also_write_userdate:
        roots.append(Path(config.userdate_lib_root).expanduser())
    return _uniq_paths(roots)


def _uniq_paths(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r.resolve()) if r.exists() else str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def desired_search_paths(config: AppConfig) -> tuple[list[str], list[str]]:
    """返回精简 (symbol_paths, library_paths)。

    Symbol：仅 .../sym 父目录（F2 里出现一个 UserImported 文件夹，而不是把 .asy 摊到顶层）。
    Library：.../sub 与 .../sub/<category>（ModelFile 短文件名可解析）。
    """
    syms: list[str] = []
    libs: list[str] = []
    for root in search_lib_roots(config):
        sym_root = root / config.sym_dir_name
        sub_root = root / config.sub_dir_name
        syms.append(str(sym_root))
        libs.append(str(sub_root))
        if config.category:
            libs.append(str(sub_root / config.category))
    return _uniq(syms), _uniq(libs)


def update_ltspice_ini(
    config: AppConfig,
    *,
    ini_path: Path | None = None,
    dry_run: bool = False,
) -> IniFixReport:
    """备份并用精简列表**替换**（非追加）所有 SymbolSearchPath / LibrarySearchPath。

    - SymbolSearchPath → .../sym（父目录；勿把 UserImported 平铺进顶层）
    - LibrarySearchPath → .../sub 与 .../sub/<category>
    - 更新文件中每一处同名键（ini 可能有重复 [Options] 段）
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

    def strip_nl(s: str) -> tuple[str, str]:
        if s.endswith("\r\n"):
            return s[:-2], "\r\n"
        if s.endswith("\n"):
            return s[:-1], "\n"
        if s.endswith("\r"):
            return s[:-1], "\r"
        return s, "\n"

    sym_idxs: list[int] = []
    lib_idxs: list[int] = []
    cur_sym: list[str] = []
    cur_lib: list[str] = []
    for i, line in enumerate(lines):
        body, _ = strip_nl(line)
        if body.startswith("SymbolSearchPath=") and not body.startswith(
            "SymbolSearchPathDisabled"
        ):
            sym_idxs.append(i)
            cur_sym = _split_paths(body.split("=", 1)[1])
        elif body.startswith("LibrarySearchPath=") and not body.startswith(
            "LibrarySearchPathDisabled"
        ):
            lib_idxs.append(i)
            cur_lib = _split_paths(body.split("=", 1)[1])

    # 直接替换为精简目标，不再无限 merge 旧垃圾路径
    new_sym = list(want_sym)
    new_lib = list(want_lib)
    report.symbol_paths = new_sym
    report.library_paths = new_lib

    changed = (
        new_sym != cur_sym
        or new_lib != cur_lib
        or not sym_idxs
        or not lib_idxs
        or len(sym_idxs) > 1
        or len(lib_idxs) > 1
    )
    # 若多处键值不一致也算需要统一
    for idx in sym_idxs:
        body, _ = strip_nl(lines[idx])
        if _split_paths(body.split("=", 1)[1]) != new_sym:
            changed = True
    for idx in lib_idxs:
        body, _ = strip_nl(lines[idx])
        if _split_paths(body.split("=", 1)[1]) != new_lib:
            changed = True

    report.changed = changed

    if not changed:
        report.messages.append("LTspice.ini 搜索路径已精简且正确，无需修改。")
        return report

    if dry_run:
        report.messages.append("dry-run：将替换 SymbolSearchPath / LibrarySearchPath 为精简列表。")
        return report

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{ts}")
    shutil.copy2(path, backup)
    report.backup_path = str(backup)
    report.messages.append(f"已备份 ini → {backup}")

    sample_nl = "\n"
    for line in lines:
        _, nl = strip_nl(line)
        if nl:
            sample_nl = nl
            break

    sym_line = "SymbolSearchPath=" + ";".join(new_sym)
    lib_line = "LibrarySearchPath=" + ";".join(new_lib)

    for idx in sym_idxs:
        lines[idx] = sym_line + sample_nl
    for idx in lib_idxs:
        lines[idx] = lib_line + sample_nl

    if not sym_idxs:
        lines.append(sym_line + sample_nl)
        report.messages.append("原 ini 无 SymbolSearchPath，已追加。")
    if not lib_idxs:
        lines.append(lib_line + sample_nl)
        report.messages.append("原 ini 无 LibrarySearchPath，已追加。")

    def ensure_flag(name: str, value: str = "false") -> None:
        nonlocal lines
        key = f"{name}="
        found = False
        for i, line in enumerate(lines):
            body, nl = strip_nl(line)
            if body.startswith(key):
                lines[i] = f"{name}={value}" + nl
                found = True
        if not found:
            lines.append(f"{name}={value}" + sample_nl)

    ensure_flag("SymbolSearchPathDisabled", "false")
    ensure_flag("LibrarySearchPathDisabled", "false")

    path.write_bytes("".join(lines).encode(enc))
    report.messages.append(
        "已替换为精简搜索路径：Symbol→sym 父目录；Library→sub + UserImported。"
    )
    if len(sym_idxs) > 1 or len(lib_idxs) > 1:
        report.messages.append(
            f"已同步 ini 内多处键（Symbol×{len(sym_idxs) or 1}, Library×{len(lib_idxs) or 1}）。"
        )
    return report


def post_import_fix(config: AppConfig, *, dry_run: bool = False) -> IniFixReport:
    """导入成功后调用：修正 ini（若开启）。"""
    if not config.auto_fix_ini_paths:
        r = IniFixReport(ini_path=config.ltspice_ini_path)
        r.messages.append("已跳过 ini 修复（auto_fix_ini_paths=false）。")
        return r
    return update_ltspice_ini(config, dry_run=dry_run)
