# 仿真模型生成 / LTspice Model Importer

<p align="center">
  <img src="assets/logo.png" alt="Logo" width="160" />
</p>

**离线将 SPICE 模型导入 LTspice 用户库的工具。**  
Offline desktop utility that imports vendor or custom SPICE models (`.lib` / `.sub` / `.asy`) into your local LTspice library — no network required.

![Platform](https://img.shields.io/badge/platform-macOS-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## 功能

- 拖入单个模型文件（`.lib` / `.sub` / `.cir` / `.mod`）或整包（文件夹 / ZIP，可含 `.asy`）
- 解析 `.SUBCKT` / `.MODEL`，写入本地 `sub/` 与 `sym/`
- 无符号时按器件类型自动生成通俗原理图符号（二极管、运放三角、MOS/三极管、阻容感、TVS 等）
- 重名策略：重命名 / 跳过 / 覆盖并备份
- 图形界面 + 命令行；完全离线，仅标准库（tkinter）

## 快速开始（macOS）

### 应用图标

已提供 Logo：`assets/logo.jpg` / `assets/logo.png`，并打包为：

- `/Applications/仿真模型生成.app`
- 桌面：`仿真模型生成.app`

双击即可启动（调用本机 Python 运行本仓库的 `main.py`）。

重新打包应用：

```bash
./scripts/build_macos_app.sh
```

### 源码启动

```bash
cd ~/Documents/仿真模型生成
# 或双击：启动导入工具.command
/Users/yanghaoxiang/miniforge3/bin/python3 main.py
```

无需 `pip install`。

### 命令行示例

```bash
python3 main.py detect
python3 main.py parse /path/to/model.lib
python3 main.py import /path/to/model.lib --category UserImported --dry-run
python3 main.py import /path/to/package.zip --category UserImported
```

## 默认库目录

| 目标 | 路径 |
|------|------|
| 主库（默认） | `~/Documents/10LTspice/userDate` → `sub/` / `sym/` |
| 可选 | `~/Library/Application Support/LTspice/lib` |

默认分类：`UserImported`。本地路径写在 `config.json`（不进 Git）；可复制：

```bash
cp config.example.json config.json
```

导入后在 LTspice 按 **F2** 选择 `UserImported`；若看不到，请在 Control Panel → Sym. & Lib. Search Paths 中加入上述 `sym` / `sub`。

## 项目结构

```text
仿真模型生成/
├─ main.py
├─ 启动导入工具.command
├─ assets/logo.png          # 应用 Logo
├─ config.example.json
├─ scripts/build_macos_app.sh
├─ ltspice_importer/
│  ├─ gui.py
│  ├─ importer.py
│  ├─ parser.py
│  ├─ asy_generator.py      # 通俗符号生成
│  └─ ...
└─ LICENSE
```

## License

MIT — see [LICENSE](LICENSE).

---

*English: Drag SPICE models into the GUI; they are copied into your LTspice user `sub`/`sym` folders. Missing `.asy` symbols are auto-generated with familiar schematic shapes. Fully offline.*
