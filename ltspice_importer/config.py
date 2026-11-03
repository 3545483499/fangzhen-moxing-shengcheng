"""本地配置：默认目标目录、冲突策略等。完全离线，仅读写本地 JSON。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HOME = Path.home()

# 用户已在用的自定义库（优先）
DEFAULT_USER_LIB = HOME / "Documents" / "10LTspice" / "userDate"
# LTspice macOS 应用支持库
DEFAULT_APP_SUPPORT_LIB = HOME / "Library" / "Application Support" / "LTspice" / "lib"
# CrossOver 瓶内库（仅检测/展示，默认不写入）
DEFAULT_BOTTLE_LIB = (
    HOME
    / "Library"
    / "Application Support"
    / "LTspice"
    / "Bottles"
    / "ltspice"
    / "drive_c"
    / "users"
    / "crossover"
    / "AppData"
    / "Local"
    / "LTspice"
    / "lib"
)

CONFIG_FILENAME = "config.json"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    return project_root() / CONFIG_FILENAME


@dataclass
class AppConfig:
    """持久化配置。"""

    # 主目标：Documents 下自定义库
    primary_lib_root: str = str(DEFAULT_USER_LIB)
    # 是否同时写入 Application Support/LTspice/lib
    also_write_app_support: bool = False
    app_support_lib_root: str = str(DEFAULT_APP_SUPPORT_LIB)
    # 子目录名（相对 primary / app_support）
    sub_dir_name: str = "sub"
    sym_dir_name: str = "sym"
    # 可选分类子文件夹，例如 User / UserImported
    category: str = "UserImported"
    # 冲突：skip | overwrite | rename
    conflict_policy: str = "rename"
    # 导入前备份被覆盖文件
    backup_on_overwrite: bool = True
    # 无 .asy 时自动生成
    auto_generate_asy: bool = True
    last_import_source: str = ""

    def primary_sub(self) -> Path:
        base = Path(self.primary_lib_root).expanduser() / self.sub_dir_name
        return base / self.category if self.category else base

    def primary_sym(self) -> Path:
        base = Path(self.primary_lib_root).expanduser() / self.sym_dir_name
        return base / self.category if self.category else base

    def app_support_sub(self) -> Path:
        base = Path(self.app_support_lib_root).expanduser() / self.sub_dir_name
        return base / self.category if self.category else base

    def app_support_sym(self) -> Path:
        base = Path(self.app_support_lib_root).expanduser() / self.sym_dir_name
        return base / self.category if self.category else base

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or default_config_path()
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return AppConfig.from_dict(data)
        except (OSError, json.JSONDecodeError):
            pass
    return AppConfig()


def save_config(config: AppConfig, path: Path | None = None) -> Path:
    cfg_path = path or default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cfg_path


def detect_targets() -> dict[str, dict[str, Any]]:
    """检测本机常见 LTspice 库路径是否存在。"""
    candidates = {
        "userDate": DEFAULT_USER_LIB,
        "app_support": DEFAULT_APP_SUPPORT_LIB,
        "bottle": DEFAULT_BOTTLE_LIB,
    }
    result: dict[str, dict[str, Any]] = {}
    for key, root in candidates.items():
        exists = root.is_dir()
        result[key] = {
            "path": str(root),
            "exists": exists,
            "sub": str(root / "sub") if exists else "",
            "sym": str(root / "sym") if exists else "",
        }
    return result
