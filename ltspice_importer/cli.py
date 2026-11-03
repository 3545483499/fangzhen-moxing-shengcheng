"""命令行接口。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import detect_targets, load_config, save_config
from .importer import Importer
from .parser import parse_spice_file


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ltspice-importer",
        description="LTspice 离线 SPICE 模型导入工具（支持 .lib/.sub/.cir/.mod 与厂商包 .asy）",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    p_imp = sub.add_parser("import", help="导入模型/符号到本地 LTspice 库目录")
    p_imp.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="模型文件、.asy、文件夹或 .zip",
    )
    p_imp.add_argument(
        "--target",
        type=Path,
        default=None,
        help="主库根目录（含 sub/sym），默认读 config",
    )
    p_imp.add_argument(
        "--category",
        default=None,
        help="分类子目录名，例如 UserImported",
    )
    p_imp.add_argument(
        "--conflict",
        choices=["skip", "overwrite", "rename"],
        default=None,
        help="重名策略",
    )
    p_imp.add_argument(
        "--also-app-support",
        action="store_true",
        help="同时写入 ~/Library/Application Support/LTspice/lib",
    )
    p_imp.add_argument(
        "--no-auto-asy",
        action="store_true",
        help="不自动生成 .asy",
    )
    p_imp.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析与演练，不写文件",
    )
    p_imp.add_argument(
        "--open-folder",
        action="store_true",
        help="导入后在 Finder 打开目标 sub 目录",
    )

    p_parse = sub.add_parser("parse", help="仅解析模型文件，打印 SUBCKT/MODEL")
    p_parse.add_argument("paths", nargs="+", type=Path)

    sub.add_parser("detect", help="检测本机 LTspice 库路径")
    sub.add_parser("gui", help="启动图形界面")

    return p


def _apply_cli_to_config(args: argparse.Namespace):
    cfg = load_config()
    if getattr(args, "target", None):
        cfg.primary_lib_root = str(args.target.expanduser().resolve())
    if getattr(args, "category", None) is not None:
        cfg.category = args.category
    if getattr(args, "conflict", None):
        cfg.conflict_policy = args.conflict
    if getattr(args, "also_app_support", False):
        cfg.also_write_app_support = True
    if getattr(args, "no_auto_asy", False):
        cfg.auto_generate_asy = False
    return cfg


def cmd_import(args: argparse.Namespace) -> int:
    cfg = _apply_cli_to_config(args)
    save_config(cfg)
    importer = Importer(cfg, progress=lambda m: print(m))
    report = importer.import_paths(list(args.paths), dry_run=args.dry_run)
    print("\n".join(report.summary_lines()))
    if args.open_folder and not args.dry_run:
        folder = cfg.primary_sub()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(folder)], check=False)
    return 1 if report.errors else 0


def cmd_parse(args: argparse.Namespace) -> int:
    rc = 0
    for path in args.paths:
        path = Path(path)
        if path.is_dir():
            files = sorted(
                p
                for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in {".lib", ".sub", ".cir", ".mod", ".spi"}
            )
        else:
            files = [path]
        for f in files:
            pr = parse_spice_file(f)
            print(f"=== {f} ===")
            if pr.errors:
                rc = 1
                for e in pr.errors:
                    print(f"  ERROR: {e}")
            for s in pr.subckts:
                print(f"  .SUBCKT {s.name} {' '.join(s.pins)}  (line {s.line_no})")
            for m in pr.models:
                print(f"  .MODEL {m.name} {m.model_type}  (line {m.line_no})")
            if not pr.subckts and not pr.models and not pr.errors:
                print("  (未找到 .SUBCKT / .MODEL)")
    return rc


def cmd_detect(_: argparse.Namespace) -> int:
    info = detect_targets()
    for key, val in info.items():
        mark = "✓" if val["exists"] else "✗"
        print(f"{mark} {key}: {val['path']}")
        if val["exists"]:
            print(f"    sub={val['sub']}")
            print(f"    sym={val['sym']}")
    return 0


def cmd_gui(_: argparse.Namespace) -> int:
    from .gui import run_gui

    run_gui()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    # 无子命令且无参数 → GUI；有 --help 等交 argparse
    if not argv:
        return cmd_gui(argparse.Namespace())
    # 兼容: python main.py --cli import ...
    if argv and argv[0] == "--cli":
        argv = argv[1:]
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handlers = {
        "import": cmd_import,
        "parse": cmd_parse,
        "detect": cmd_detect,
        "gui": cmd_gui,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
