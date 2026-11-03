"""核心导入逻辑：复制模型/符号、冲突处理、自动生成 .asy、备份。"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal

from .asy_generator import generate_model_asy, generate_subckt_asy, write_asy
from .config import AppConfig
from .parser import (
    ARCHIVE_EXTENSIONS,
    ParseResult,
    collect_import_candidates,
    is_model_file,
    is_symbol_file,
    parse_spice_file,
)

ConflictPolicy = Literal["skip", "overwrite", "rename"]
ProgressCb = Callable[[str], None]


@dataclass
class FileAction:
    kind: str  # model | symbol | generated_asy | backup
    source: str
    dest: str
    status: str  # copied | skipped | overwritten | renamed | generated | error
    detail: str = ""


@dataclass
class ImportReport:
    actions: list[FileAction] = field(default_factory=list)
    parsed: list[ParseResult] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def add(self, action: FileAction) -> None:
        self.actions.append(action)

    def summary_lines(self) -> list[str]:
        lines = [
            f"{'【演练模式 dry-run】' if self.dry_run else '【导入完成】'}",
            f"处理文件数: {len(self.actions)}",
            f"错误: {len(self.errors)}",
            "",
        ]
        for a in self.actions:
            lines.append(f"- [{a.status}] {a.kind}: {a.dest}" + (f" ({a.detail})" if a.detail else ""))
        if self.parsed:
            lines.append("")
            lines.append("解析到的模型:")
            for p in self.parsed:
                for s in p.subckts:
                    pins = ",".join(s.pins) if s.pins else "?"
                    lines.append(f"  .SUBCKT {s.name}  pins=[{pins}]  ← {p.path.name}")
                # 仅列出不在任何报告噪音中的顶层 model：全部列出
                for m in p.models:
                    lines.append(f"  .MODEL {m.name} {m.model_type}  ← {p.path.name}:{m.line_no}")
        if self.checklist:
            lines.append("")
            lines.append("使用说明:")
            lines.extend(f"  • {c}" for c in self.checklist)
        if self.errors:
            lines.append("")
            lines.append("错误:")
            lines.extend(f"  ! {e}" for e in self.errors)
        return lines


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _resolve_dest(dest: Path, policy: ConflictPolicy, backup: bool, dry_run: bool, report: ImportReport) -> Path | None:
    """返回最终写入路径；skip 时返回 None。"""
    if not dest.exists():
        return dest
    if policy == "skip":
        report.add(
            FileAction(
                kind="?",
                source="",
                dest=str(dest),
                status="skipped",
                detail="目标已存在",
            )
        )
        return None
    if policy == "rename":
        stem, suffix = dest.stem, dest.suffix
        n = 1
        while True:
            candidate = dest.with_name(f"{stem}_imported{n}{suffix}")
            if not candidate.exists():
                return candidate
            n += 1
    # overwrite
    if backup and not dry_run:
        bak = dest.with_name(f"{dest.name}.bak_{_timestamp()}")
        shutil.copy2(dest, bak)
        report.add(
            FileAction(
                kind="backup",
                source=str(dest),
                dest=str(bak),
                status="copied",
                detail="覆盖前备份",
            )
        )
    return dest


def _copy_file(src: Path, dest: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _match_symbol_for_model(model_path: Path, symbols: list[Path], parse: ParseResult) -> Path | None:
    """按文件名或 SUBCKT 名匹配 .asy。"""
    stem = model_path.stem.lower()
    names = {stem}
    for s in parse.subckts:
        names.add(s.name.lower())
    for m in parse.models:
        names.add(m.name.lower())
    for sym in symbols:
        if sym.stem.lower() in names:
            return sym
    return None


def _usage_checklist(config: AppConfig, report: ImportReport) -> None:
    sub = config.primary_sub()
    sym = config.primary_sym()
    report.checklist.extend(
        [
            f"模型已放到: {sub}",
            f"符号已放到: {sym}",
            "在 LTspice 原理图中按 F2（或 Edit → Component）打开元件库。",
            f"若使用分类目录，请在符号浏览器中进入 [{config.category or '根'}] 文件夹。",
            "也可在原理图放置 SPICE Directive：.lib <模型文件名> 或 .include <路径>。",
            "若 LTspice 找不到符号：Control Panel → Sym. & Lib. Search Paths，"
            f"将「Symbol search path」加入 {config.primary_lib_root}/{config.sym_dir_name}，"
            f"将「Library search path」加入 {config.primary_lib_root}/{config.sub_dir_name}。",
            "改库后如未刷新，可重启 LTspice 或重新打开原理图。",
        ]
    )
    if config.also_write_app_support:
        report.checklist.append(
            f"同时已写入 Application Support 库: {config.app_support_lib_root}"
        )


class Importer:
    def __init__(self, config: AppConfig, progress: ProgressCb | None = None) -> None:
        self.config = config
        self.progress = progress or (lambda _msg: None)

    def _log(self, msg: str) -> None:
        self.progress(msg)

    def import_paths(
        self,
        sources: list[Path],
        *,
        dry_run: bool = False,
    ) -> ImportReport:
        report = ImportReport(dry_run=dry_run)
        expanded_models: list[Path] = []
        expanded_symbols: list[Path] = []
        tmp_dirs: list[Path] = []

        try:
            raw_models, raw_symbols, notes = collect_import_candidates(sources)
            for n in notes:
                self._log(n)

            # 展开 zip
            for item in raw_models:
                if item.suffix.lower() in ARCHIVE_EXTENSIONS:
                    self._log(f"解压: {item}")
                    if dry_run:
                        # dry-run 也实际解到临时目录以便解析
                        pass
                    tmp = Path(tempfile.mkdtemp(prefix="ltspice_import_"))
                    tmp_dirs.append(tmp)
                    try:
                        with zipfile.ZipFile(item, "r") as zf:
                            zf.extractall(tmp)
                    except zipfile.BadZipFile as exc:
                        report.errors.append(f"无效 zip: {item} ({exc})")
                        continue
                    m2, s2, _ = collect_import_candidates([tmp])
                    expanded_models.extend(m2)
                    expanded_symbols.extend(s2)
                else:
                    expanded_models.append(item)
            expanded_symbols.extend(raw_symbols)

            # 去重
            expanded_models = list(dict.fromkeys(expanded_models))
            expanded_symbols = list(dict.fromkeys(expanded_symbols))

            policy: ConflictPolicy = self.config.conflict_policy  # type: ignore[assignment]
            if policy not in ("skip", "overwrite", "rename"):
                policy = "rename"

            targets_sub = [self.config.primary_sub()]
            targets_sym = [self.config.primary_sym()]
            if self.config.also_write_app_support:
                targets_sub.append(self.config.app_support_sub())
                targets_sym.append(self.config.app_support_sym())

            # 先解析全部模型
            parses: dict[Path, ParseResult] = {}
            for mp in expanded_models:
                if not is_model_file(mp):
                    continue
                pr = parse_spice_file(mp)
                parses[mp] = pr
                report.parsed.append(pr)
                if pr.errors:
                    report.errors.extend(pr.errors)
                self._log(
                    f"解析 {mp.name}: "
                    f"{len(pr.subckts)} SUBCKT, {len(pr.models)} MODEL"
                )

            used_symbols: set[Path] = set()

            for mp, pr in parses.items():
                matched = _match_symbol_for_model(mp, expanded_symbols, pr)
                if matched:
                    used_symbols.add(matched)

                for sub_root in targets_sub:
                    dest = sub_root / mp.name
                    final = _resolve_dest(
                        dest,
                        policy,
                        self.config.backup_on_overwrite,
                        dry_run,
                        report,
                    )
                    if final is None:
                        continue
                    status = (
                        "copied"
                        if not dest.exists()
                        else ("renamed" if final != dest else "overwritten")
                    )
                    # 修正：上面 dest.exists 在 rename 前已判断；简化状态
                    if dry_run:
                        status = "copied" if status == "copied" else status
                    try:
                        _copy_file(mp, final, dry_run=dry_run)
                        report.add(
                            FileAction(
                                kind="model",
                                source=str(mp),
                                dest=str(final),
                                status=status if not dry_run else f"dry-run:{status}",
                            )
                        )
                    except OSError as exc:
                        report.errors.append(f"复制失败 {mp} → {final}: {exc}")
                        report.add(
                            FileAction(
                                kind="model",
                                source=str(mp),
                                dest=str(final),
                                status="error",
                                detail=str(exc),
                            )
                        )
                        continue

                    # 配对符号
                    if matched:
                        for sym_root in targets_sym:
                            sdest = sym_root / matched.name
                            sfinal = _resolve_dest(
                                sdest,
                                policy,
                                self.config.backup_on_overwrite,
                                dry_run,
                                report,
                            )
                            if sfinal is None:
                                continue
                            try:
                                _copy_file(matched, sfinal, dry_run=dry_run)
                                report.add(
                                    FileAction(
                                        kind="symbol",
                                        source=str(matched),
                                        dest=str(sfinal),
                                        status="copied" if not dry_run else "dry-run:copied",
                                    )
                                )
                            except OSError as exc:
                                report.errors.append(str(exc))

                    elif self.config.auto_generate_asy and (
                        pr.subckts or pr.models
                    ):
                        # 无 .asy：按主 SUBCKT 或首个 MODEL 生成
                        if pr.subckts:
                            main = pr.subckts[0]
                            content = generate_subckt_asy(main, final.name, filename=mp.name)
                            asy_name = f"{main.name}.asy"
                        else:
                            main_m = pr.models[0]
                            content = generate_model_asy(main_m, final.name)
                            asy_name = f"{main_m.name}.asy"
                        for sym_root in targets_sym:
                            adest = sym_root / asy_name
                            afinal = _resolve_dest(
                                adest,
                                policy,
                                self.config.backup_on_overwrite,
                                dry_run,
                                report,
                            )
                            if afinal is None:
                                continue
                            try:
                                if not dry_run:
                                    write_asy(afinal, content)
                                report.add(
                                    FileAction(
                                        kind="generated_asy",
                                        source=str(mp),
                                        dest=str(afinal),
                                        status="generated" if not dry_run else "dry-run:generated",
                                        detail=f"pins/model from {pr.primary_name}",
                                    )
                                )
                            except OSError as exc:
                                report.errors.append(str(exc))

            # 孤立 .asy（无对应模型时仍导入到 sym）
            for sym in expanded_symbols:
                if sym in used_symbols:
                    continue
                for sym_root in targets_sym:
                    sdest = sym_root / sym.name
                    sfinal = _resolve_dest(
                        sdest,
                        policy,
                        self.config.backup_on_overwrite,
                        dry_run,
                        report,
                    )
                    if sfinal is None:
                        continue
                    try:
                        _copy_file(sym, sfinal, dry_run=dry_run)
                        report.add(
                            FileAction(
                                kind="symbol",
                                source=str(sym),
                                dest=str(sfinal),
                                status="copied" if not dry_run else "dry-run:copied",
                                detail="无配对模型，仅导入符号",
                            )
                        )
                    except OSError as exc:
                        report.errors.append(str(exc))

            _usage_checklist(self.config, report)
        finally:
            for d in tmp_dirs:
                shutil.rmtree(d, ignore_errors=True)

        return report
