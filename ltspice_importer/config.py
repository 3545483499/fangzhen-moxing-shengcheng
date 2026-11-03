"""本地配置：默认目标目录、冲突策略等。完全离线，仅读写本地 JSON。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HOME = Path.home()

# Documents 自定义库（备份副本）
DEFAULT_USER_LIB = HOME / "Documents" / "10LTspice" / "userDate"
# LTspice macOS Application Support 库
DEFAULT_APP_SUPPORT_LIB = HOME / "Library" / "Application Support" / "LTspice" / "lib"
# CrossOver / LTspice 24 瓶内 Local 库（实际被读取的主库）
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
DEFAULT_LTSPICE_INI = (
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
    / "Roaming"
    / "LTspice.ini"
)

CONFIG_FILENAME = "config.json"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    return project_root() / CONFIG_FILENAME


@dataclass
class AppConfig:
    """持久化配置。

    LTspice 24（瓶）实际读的是 bottle Local lib；Documents/userDate 作副本。
    """

    # 主写入目标：瓶内 Local/LTspice/lib
    primary_lib_root: str = str(DEFAULT_BOTTLE_LIB)
    # 同时写入 Documents/10LTspice/userDate
    also_write_userdate: bool = True
    userdate_lib_root: str = str(DEFAULT_USER_LIB)
    # 同时写入 Application Support/LTspice/lib
    also_write_app_support: bool = True
    app_support_lib_root: str = str(DEFAULT_APP_SUPPORT_LIB)
    # 导入后自动修正 LTspice.ini 的 Symbol/Library Search Paths
    auto_fix_ini_paths: bool = True
    ltspice_ini_path: str = str(DEFAULT_LTSPICE_INI)
    # 子目录名
    sub_dir_name: str = "sub"
    sym_dir_name: str = "sym"
    # 分类子文件夹
    category: str = "UserImported"
    # 冲突：skip | overwrite | rename
    conflict_policy: str = "rename"
    backup_on_overwrite: bool = True
    auto_generate_asy: bool = True
    last_import_source: str = ""

    def _cat(self, root: Path, kind: str) -> Path:
        base = root.expanduser() / kind
        return base / self.category if self.category else base

    def primary_sub(self) -> Path:
        return self._cat(Path(self.primary_lib_root), self.sub_dir_name)

    def primary_sym(self) -> Path:
        return self._cat(Path(self.primary_lib_root), self.sym_dir_name)

    def userdate_sub(self) -> Path:
        return self._cat(Path(self.userdate_lib_root), self.sub_dir_name)

    def userdate_sym(self) -> Path:
        return self._cat(Path(self.userdate_lib_root), self.sym_dir_name)

    def app_support_sub(self) -> Path:
        return self._cat(Path(self.app_support_lib_root), self.sub_dir_name)

    def app_support_sym(self) -> Path:
        return self._cat(Path(self.app_support_lib_root), self.sym_dir_name)

    def all_lib_roots(self) -> list[Path]:
        """按写入顺序返回所有库根目录（去重）。"""
        roots: list[Path] = [Path(self.primary_lib_root).expanduser()]
        if self.also_write_userdate:
            roots.append(Path(self.userdate_lib_root).expanduser())
        if self.also_write_app_support:
            roots.append(Path(self.app_support_lib_root).expanduser())
        # 保序去重
        seen: set[str] = set()
        out: list[Path] = []
        for r in roots:
            key = str(r.resolve()) if r.exists() else str(r)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    def all_sub_dirs(self) -> list[Path]:
        return [self._cat(r, self.sub_dir_name) for r in self.all_lib_roots()]

    def all_sym_dirs(self) -> list[Path]:
        return [self._cat(r, self.sym_dir_name) for r in self.all_lib_roots()]

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
                cfg = AppConfig.from_dict(data)
                return _migrate_legacy_config(cfg)
        except (OSError, json.JSONDecodeError):
            pass
    return AppConfig()


def _migrate_legacy_config(cfg: AppConfig) -> AppConfig:
    """旧版默认把 userDate 当主库；若瓶存在则切到瓶内主库并打开双写。"""
    bottle = DEFAULT_BOTTLE_LIB
    user = DEFAULT_USER_LIB
    primary = Path(cfg.primary_lib_root).expanduser()
    # 旧配置：主库是 userDate，且未写 bottle
    if bottle.is_dir() and primary.resolve() == user.resolve():
        cfg.primary_lib_root = str(bottle)
        cfg.also_write_userdate = True
        cfg.userdate_lib_root = str(user)
        if not hasattr(cfg, "also_write_app_support") or cfg.also_write_app_support is False:
            # 保持用户显式 False 也可；迁移时建议打开 App Support 双写
            cfg.also_write_app_support = True
        cfg.auto_fix_ini_paths = True
        if not cfg.ltspice_ini_path:
            cfg.ltspice_ini_path = str(DEFAULT_LTSPICE_INI)
    # 补全新字段默认（from_dict 已用 dataclass 默认；这里兜底空字符串）
    if not cfg.userdate_lib_root:
        cfg.userdate_lib_root = str(DEFAULT_USER_LIB)
    if not cfg.ltspice_ini_path:
        cfg.ltspice_ini_path = str(DEFAULT_LTSPICE_INI)
    return cfg


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
        "bottle (LTspice 24 主库)": DEFAULT_BOTTLE_LIB,
        "userDate": DEFAULT_USER_LIB,
        "app_support": DEFAULT_APP_SUPPORT_LIB,
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
    ini = DEFAULT_LTSPICE_INI
    result["LTspice.ini"] = {
        "path": str(ini),
        "exists": ini.is_file(),
        "sub": "",
        "sym": "",
    }
    return result
