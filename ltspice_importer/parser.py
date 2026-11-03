"""解析 SPICE 模型文件中的 .SUBCKT / .MODEL 定义。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MODEL_EXTENSIONS = {".lib", ".sub", ".cir", ".mod", ".spi", ".spice"}
SYMBOL_EXTENSIONS = {".asy"}
ARCHIVE_EXTENSIONS = {".zip"}

# .SUBCKT name n1 n2 ...  或  .subckt name(n1 n2)
_SUBCKT_RE = re.compile(
    r"^\s*\.SUBCKT\s+(\S+)\s*(.*)$",
    re.IGNORECASE,
)
# .MODEL name type(params)  或  .model name D(...)
_MODEL_RE = re.compile(
    r"^\s*\.MODEL\s+(\S+)\s+([A-Za-z]+)(.*)$",
    re.IGNORECASE,
)
_ENDS_RE = re.compile(r"^\s*\.ENDS\b", re.IGNORECASE)
_COMMENT_STRIP = re.compile(r"[;$].*$")


@dataclass
class SubcktInfo:
    name: str
    pins: list[str] = field(default_factory=list)
    line_no: int = 0


@dataclass
class ModelInfo:
    name: str
    model_type: str  # D, NPN, PNP, NMOS, PMOS, VDMOS, ...
    line_no: int = 0


@dataclass
class ParseResult:
    path: Path
    subckts: list[SubcktInfo] = field(default_factory=list)
    models: list[ModelInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def primary_name(self) -> str | None:
        if self.subckts:
            return self.subckts[0].name
        if self.models:
            return self.models[0].name
        return None


def _split_tokens(rest: str) -> list[str]:
    rest = _COMMENT_STRIP.sub("", rest).strip()
    if not rest:
        return []
    # 支持 name(pin1 pin2) 写法
    if rest.startswith("(") and ")" in rest:
        inner = rest[1 : rest.index(")")]
        return [t for t in re.split(r"[\s,]+", inner.strip()) if t]
    return [t for t in re.split(r"[\s,]+", rest) if t and not t.startswith("PARAMS:")]


def parse_spice_text(text: str, path: Path | None = None) -> ParseResult:
    """从文本解析 SUBCKT / MODEL。嵌套在 SUBCKT 内的 .MODEL 仍记录，但优先暴露顶层 SUBCKT。"""
    result = ParseResult(path=path or Path("<memory>"))
    depth = 0
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if _ENDS_RE.match(line):
            depth = max(0, depth - 1)
            continue
        m_sub = _SUBCKT_RE.match(line)
        if m_sub:
            name = m_sub.group(1)
            pins = _split_tokens(m_sub.group(2) or "")
            # 去掉 PARAMS: 之后的参数名（已在 _split_tokens 粗过滤）
            clean_pins: list[str] = []
            for p in pins:
                up = p.upper()
                if up.startswith("PARAMS"):
                    break
                if "=" in p:
                    break
                clean_pins.append(p)
            result.subckts.append(SubcktInfo(name=name, pins=clean_pins, line_no=i))
            depth += 1
            continue
        m_mod = _MODEL_RE.match(line)
        if m_mod:
            # 子电路内部的 .MODEL 也解析，便于报告；导入时仍整文件拷贝
            result.models.append(
                ModelInfo(
                    name=m_mod.group(1),
                    model_type=m_mod.group(2).upper(),
                    line_no=i,
                )
            )
    return result


def parse_spice_file(path: Path) -> ParseResult:
    path = Path(path)
    try:
        # 尝试常见编码
        data: str | None = None
        for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
            try:
                data = path.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        if data is None:
            data = path.read_text(encoding="utf-8", errors="replace")
        return parse_spice_text(data, path)
    except OSError as exc:
        r = ParseResult(path=path)
        r.errors.append(str(exc))
        return r


def is_model_file(path: Path) -> bool:
    return path.suffix.lower() in MODEL_EXTENSIONS


def is_symbol_file(path: Path) -> bool:
    return path.suffix.lower() in SYMBOL_EXTENSIONS


def collect_import_candidates(sources: list[Path]) -> tuple[list[Path], list[Path], list[str]]:
    """
    从文件/文件夹/zip 收集模型与符号路径。
    返回 (model_files, symbol_files, notes)
    zip 会解压说明由 importer 处理；此处只列路径意图。
    """
    models: list[Path] = []
    symbols: list[Path] = []
    notes: list[str] = []
    for src in sources:
        src = Path(src)
        if not src.exists():
            notes.append(f"不存在: {src}")
            continue
        if src.is_file():
            low = src.suffix.lower()
            if low in ARCHIVE_EXTENSIONS:
                notes.append(f"zip: {src}")
                models.append(src)  # importer 特殊处理
            elif is_model_file(src):
                models.append(src)
            elif is_symbol_file(src):
                symbols.append(src)
            else:
                notes.append(f"跳过未知类型: {src.name}")
        elif src.is_dir():
            for p in sorted(src.rglob("*")):
                if not p.is_file():
                    continue
                if p.name.startswith("."):
                    continue
                if is_model_file(p):
                    models.append(p)
                elif is_symbol_file(p):
                    symbols.append(p)
    return models, symbols, notes
