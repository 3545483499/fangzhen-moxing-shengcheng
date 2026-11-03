"""根据 SUBCKT / MODEL 自动生成通俗易懂的 LTspice .asy 符号。

外形尽量贴近官方库：二极管三角、双向 TVS、运放三角、NMOS/PMOS、NPN/PNP、
电阻锯齿、电容双线、电感弧线等；无法识别时才退回矩形 BLOCK。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from .parser import ModelInfo, SubcktInfo


class CompKind(str, Enum):
    DIODE = "diode"
    ZENER = "zener"
    SCHOTTKY = "schottky"
    LED = "led"
    TVS = "tvs"  # bidirectional
    RES = "res"
    CAP = "cap"
    IND = "ind"
    NPN = "npn"
    PNP = "pnp"
    NMOS = "nmos"
    PMOS = "pmos"
    OPAMP3 = "opamp3"
    OPAMP5 = "opamp5"
    BLOCK = "block"


_MODEL_PREFIX = {
    "D": "D",
    "NPN": "QN",
    "PNP": "QP",
    "NJF": "NJF",
    "PJF": "PJF",
    "NMOS": "MN",
    "PMOS": "MP",
    "VDMOS": "MN",
    "R": "R",
    "C": "C",
    "L": "L",
}


@dataclass
class InferResult:
    kind: CompKind
    reason: str


def _norm(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", text).upper()


def _join_haystack(name: str, pins: Sequence[str], extra: str = "") -> str:
    parts = [name, extra, *pins]
    return " ".join(parts).upper()


def infer_kind(
    name: str,
    pins: Sequence[str] | None = None,
    *,
    model_type: str | None = None,
    filename: str = "",
) -> InferResult:
    """从名称、引脚、MODEL 类型、文件名推断器件类别。"""
    pins = list(pins or [])
    n = len(pins)
    hay = _join_haystack(name, pins, filename)
    compact = _norm(name) + _norm(filename)
    mt = (model_type or "").upper()

    # 1) 明确的 .MODEL 类型
    if mt in {"NPN"}:
        return InferResult(CompKind.NPN, "MODEL NPN")
    if mt in {"PNP"}:
        return InferResult(CompKind.PNP, "MODEL PNP")
    if mt in {"NMOS", "VDMOS"}:
        return InferResult(CompKind.NMOS, f"MODEL {mt}")
    if mt in {"PMOS"}:
        return InferResult(CompKind.PMOS, "MODEL PMOS")
    if mt in {"R"}:
        return InferResult(CompKind.RES, "MODEL R")
    if mt in {"C"}:
        return InferResult(CompKind.CAP, "MODEL C")
    if mt in {"L"}:
        return InferResult(CompKind.IND, "MODEL L")
    if mt in {"D"}:
        # 细分二极管
        if any(k in hay for k in ("LED", "LIGHT")):
            return InferResult(CompKind.LED, "MODEL D + LED")
        if any(k in hay for k in ("SCHOTTKY", "BAT", "1N58", "MBR", "SS14")):
            return InferResult(CompKind.SCHOTTKY, "MODEL D + Schottky")
        if any(k in hay for k in ("ZENER", "BZX", "BZT", "1N47", "MMSZ")):
            return InferResult(CompKind.ZENER, "MODEL D + Zener")
        if any(k in hay for k in ("TVS", "PESD", "ESD", "SMBJ", "SMAJ", "P6KE", "BIDIR")):
            return InferResult(CompKind.TVS, "MODEL D + TVS/ESD")
        return InferResult(CompKind.DIODE, "MODEL D")

    # 2) 名称关键字（SUBCKT / 文件）
    rules: list[tuple[CompKind, tuple[str, ...]]] = [
        (CompKind.LED, ("LED", "LIGHT_EMITTING")),
        (CompKind.TVS, ("TVS", "PESD", "ESD", "TRANSIENTVOLTAGE", "BIDIRECTIONAL", "BIDIR")),
        (CompKind.SCHOTTKY, ("SCHOTTKY", "SCHOTKY", "BAT54", "BAT85", "BAT")),
        (CompKind.ZENER, ("ZENER", "ZENNER")),
        (CompKind.DIODE, ("DIODE", "RECTIFIER", "1N400", "1N4148", "UF400")),
        (CompKind.OPAMP5, ("OPAMP", "OP_AMP", "OPERATIONALAMP", "OPA", "TL07", "LM358", "AD8", "AD7")),
        (CompKind.OPAMP3, ("OPAMP", "OP_AMP", "OPERATIONALAMP")),
        (CompKind.NMOS, ("NMOS", "NFET", "NCHANNEL", "N_CH", "NCHMOS", "VDMOS_N")),
        (CompKind.PMOS, ("PMOS", "PFET", "PCHANNEL", "P_CH", "PCHMOS")),
        (CompKind.NPN, ("NPN",)),
        (CompKind.PNP, ("PNP",)),
        (CompKind.RES, ("RESISTOR", "RES_", "_RES", "OHM")),
        (CompKind.CAP, ("CAPACITOR", "CAP_", "_CAP")),
        (CompKind.IND, ("INDUCTOR", "INDUCT", "_IND", "IND_", "CHOKE")),
    ]
    for kind, keys in rules:
        for key in keys:
            if key in compact or key in hay.replace(" ", ""):
                # 运放按引脚数细分
                if kind in {CompKind.OPAMP3, CompKind.OPAMP5}:
                    if n >= 5:
                        return InferResult(CompKind.OPAMP5, f"keyword {key}, pins={n}")
                    if n == 3 or n == 0:
                        return InferResult(CompKind.OPAMP3, f"keyword {key}, pins={n}")
                    if n == 4:
                        # 四脚运放少见，用三角+供电近似为 5 脚模板缺一，仍用三角 3 脚
                        return InferResult(CompKind.OPAMP3, f"keyword {key}, pins={n}")
                    return InferResult(CompKind.OPAMP3, f"keyword {key}")
                if kind in {CompKind.NMOS, CompKind.PMOS, CompKind.NPN, CompKind.PNP} and n not in (0, 3, 4):
                    continue
                return InferResult(kind, f"keyword {key}")

    # MOSFET / BJT 通用词
    if "MOSFET" in hay or "MOS_FET" in compact:
        if "P" in hay and ("CHANNEL" in hay or "PMOS" in compact):
            return InferResult(CompKind.PMOS, "MOSFET P")
        return InferResult(CompKind.NMOS, "MOSFET")
    if "BJT" in hay or "BIPOLAR" in hay:
        if "PNP" in compact:
            return InferResult(CompKind.PNP, "BJT PNP")
        return InferResult(CompKind.NPN, "BJT")

    # 3) 引脚名启发式
    pin_u = " ".join(p.upper() for p in pins)
    if n == 2:
        if any(k in compact for k in ("PESD", "ESD", "TVS", "SMBJ", "SMAJ")):
            return InferResult(CompKind.TVS, "2-pin ESD name")
        if compact.startswith("BAT") or "SCHOTTKY" in hay:
            return InferResult(CompKind.SCHOTTKY, "2-pin Schottky/BAT")
        if any(k in pin_u for k in ("ANODE", "CATHODE")) or (
            set(p.upper() for p in pins) <= {"A", "K", "ANODE", "CATHODE"} and len(pins) == 2
        ):
            if any(k in compact for k in ("ZENER", "BZX", "BZT")):
                return InferResult(CompKind.ZENER, "2-pin zener pins")
            return InferResult(CompKind.DIODE, "2-pin anode/cathode")
    if n == 3:
        if all(x in pin_u for x in ("D", "G", "S")) or "DRAIN" in pin_u:
            if "P" in compact and "N" not in compact[:4]:
                return InferResult(CompKind.PMOS, "pins D/G/S")
            return InferResult(CompKind.NMOS, "pins D/G/S")
        if all(x in pin_u for x in ("C", "B", "E")) or "COLLECTOR" in pin_u:
            if "PNP" in compact:
                return InferResult(CompKind.PNP, "pins C/B/E")
            return InferResult(CompKind.NPN, "pins C/B/E")
        if any(k in pin_u for k in ("IN+", "IN-", "OUT", "INN", "INP", "VOUT")):
            return InferResult(CompKind.OPAMP3, "pins in/out")
    if n >= 5 and any(k in pin_u for k in ("IN+", "IN-", "OUT", "V+", "V-", "VCC", "VEE")):
        return InferResult(CompKind.OPAMP5, "5+ pin opamp-like")

    # 4) 常见命名：PESD* 两脚 → TVS；1N* 两脚 → diode
    if n in (0, 2):
        if compact.startswith("PESD") or "PESD" in compact:
            return InferResult(CompKind.TVS, "PESD* name")
        if re.match(r"BAT\d", name, re.I) or compact.startswith("BAT"):
            return InferResult(CompKind.SCHOTTKY, "BAT* name")
        if re.match(r"1N\d", name, re.I):
            return InferResult(CompKind.DIODE, "1N* name")

    return InferResult(CompKind.BLOCK, "unknown → rectangle")


# ---------------------------------------------------------------------------
# 几何模板（坐标来自 LTspice 官方库，改编为可替换 Value/ModelFile）
# ---------------------------------------------------------------------------

def _header(symbol_type: str = "CELL") -> list[str]:
    return ["Version 4", f"SymbolType {symbol_type}"]


def _attrs(
    *,
    prefix: str,
    value: str,
    model_file: str | None,
    description: str,
    extra: Sequence[str] = (),
) -> list[str]:
    lines = [
        f"SYMATTR Prefix {prefix}",
        f"SYMATTR Value {value}",
    ]
    if model_file:
        lines.append(f"SYMATTR ModelFile {model_file}")
    lines.append(f"SYMATTR Description {description}")
    lines.extend(extra)
    return lines


def _pin(x: int, y: int, side: str, length: int, name: str, order: int) -> list[str]:
    return [
        f"PIN {x} {y} {side} {length}",
        f"PINATTR PinName {name}",
        f"PINATTR SpiceOrder {order}",
    ]


def _map_two_pins(pins: Sequence[str]) -> tuple[str, str]:
    if len(pins) >= 2:
        return pins[0], pins[1]
    if len(pins) == 1:
        return pins[0], "2"
    return "1", "2"


def _map_three(
    pins: Sequence[str],
    aliases: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    defaults: tuple[str, str, str] = ("1", "2", "3"),
) -> tuple[str, str, str]:
    """按别名匹配三端；失败则按声明顺序。"""
    if len(pins) >= 3:
        used = [False] * len(pins)
        out: list[str] = []
        for group in aliases:
            found = None
            for i, p in enumerate(pins):
                if used[i]:
                    continue
                pu = p.upper()
                if pu in group or any(a in pu for a in group if len(a) > 1):
                    found = p
                    used[i] = True
                    break
            if found is None:
                # 按序取未用
                for i, p in enumerate(pins):
                    if not used[i]:
                        found = p
                        used[i] = True
                        break
            out.append(found or defaults[len(out)])
        return out[0], out[1], out[2]
    # 不足三脚：填充
    base = list(pins) + list(defaults)
    return base[0], base[1], base[2]


def template_diode(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, k = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 0 44 32 44",
        "LINE Normal 0 20 32 20",
        "LINE Normal 32 20 16 44",
        "LINE Normal 0 20 16 44",
        "LINE Normal 16 0 16 20",
        "LINE Normal 16 44 16 64",
        "WINDOW 0 40 16 Left 2",
        "WINDOW 3 40 56 Left 2",
    ]
    lines += _attrs(
        prefix=prefix,
        value=value,
        model_file=model_file,
        description="Diode (auto)",
    )
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, k, 2)
    return "\n".join(lines) + "\n"


def template_zener(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, k = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 0 44 -4 48",
        "LINE Normal 32 44 36 40",
        "LINE Normal 0 44 32 44",
        "LINE Normal 0 20 32 20",
        "LINE Normal 32 20 16 44",
        "LINE Normal 0 20 16 44",
        "LINE Normal 16 0 16 20",
        "LINE Normal 16 44 16 64",
        "WINDOW 0 40 16 Left 2",
        "WINDOW 3 40 56 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Zener diode (auto)")
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, k, 2)
    return "\n".join(lines) + "\n"


def template_schottky(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, k = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 0 36 4 36",
        "LINE Normal 0 44 0 36",
        "LINE Normal 0 44 32 44",
        "LINE Normal 32 44 32 52",
        "LINE Normal 32 52 28 52",
        "LINE Normal 0 20 32 20",
        "LINE Normal 32 20 16 44",
        "LINE Normal 0 20 16 44",
        "LINE Normal 16 0 16 20",
        "LINE Normal 16 44 16 64",
        "WINDOW 0 40 16 Left 2",
        "WINDOW 3 40 56 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Schottky diode (auto)")
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, k, 2)
    return "\n".join(lines) + "\n"


def template_led(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, k = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 0 44 32 44",
        "LINE Normal 0 20 32 20",
        "LINE Normal 32 20 16 44",
        "LINE Normal 0 20 16 44",
        "LINE Normal 16 0 16 20",
        "LINE Normal 16 44 16 64",
        "LINE Normal 72 32 68 40",
        "LINE Normal 72 32 64 32",
        "LINE Normal 72 48 68 56",
        "LINE Normal 72 48 64 48",
        "ARC Normal 40 20 56 36 56 28 40 24",
        "ARC Normal 56 20 72 36 56 28 72 32",
        "ARC Normal 40 36 56 52 56 44 40 40",
        "ARC Normal 56 36 72 52 56 44 72 48",
        "WINDOW 0 40 8 Left 2",
        "WINDOW 3 40 60 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="LED (auto)")
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, k, 2)
    return "\n".join(lines) + "\n"


def template_tvs(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    """双向 TVS（官方 TVSdiode.asy 造型）。"""
    a, k = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 0 32 -4 36",
        "LINE Normal 32 32 36 28",
        "LINE Normal 0 32 32 32",
        "LINE Normal 0 8 32 8",
        "LINE Normal 32 8 16 32",
        "LINE Normal 0 8 16 32",
        "LINE Normal 0 56 32 56",
        "LINE Normal 32 56 16 32",
        "LINE Normal 0 56 16 32",
        "LINE Normal 16 0 16 8",
        "LINE Normal 16 56 16 64",
        "WINDOW 0 40 0 Left 2",
        "WINDOW 3 40 64 Left 2",
    ]
    lines += _attrs(
        prefix=prefix,
        value=value,
        model_file=model_file,
        description="Bidirectional TVS/ESD (auto)",
    )
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, k, 2)
    return "\n".join(lines) + "\n"


def template_res(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, b = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 16 88 16 96",
        "LINE Normal 0 80 16 88",
        "LINE Normal 32 64 0 80",
        "LINE Normal 0 48 32 64",
        "LINE Normal 32 32 0 48",
        "LINE Normal 16 16 16 24",
        "LINE Normal 16 24 32 32",
        "WINDOW 0 40 40 Left 2",
        "WINDOW 3 40 76 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Resistor (auto)")
    lines += _pin(16, 16, "NONE", 0, a, 1)
    lines += _pin(16, 96, "NONE", 0, b, 2)
    return "\n".join(lines) + "\n"


def template_cap(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, b = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "LINE Normal 16 36 16 64",
        "LINE Normal 16 28 16 0",
        "LINE Normal 0 28 32 28",
        "LINE Normal 0 36 32 36",
        "WINDOW 0 40 8 Left 2",
        "WINDOW 3 40 56 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Capacitor (auto)")
    lines += _pin(16, 0, "NONE", 0, a, 1)
    lines += _pin(16, 64, "NONE", 0, b, 2)
    return "\n".join(lines) + "\n"


def template_ind(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    a, b = _map_two_pins(pins)
    lines = _header("CELL")
    lines += [
        "ARC Normal 0 40 32 72 4 68 4 44",
        "ARC Normal 0 64 32 96 16 96 4 68",
        "ARC Normal 0 16 32 48 4 44 16 16",
        "WINDOW 0 40 40 Left 2",
        "WINDOW 3 40 80 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Inductor (auto)")
    lines += _pin(16, 16, "NONE", 0, a, 1)
    lines += _pin(16, 96, "NONE", 0, b, 2)
    return "\n".join(lines) + "\n"


def template_npn(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    c, b, e = _map_three(
        pins,
        (("C", "COLLECTOR", "1"), ("B", "BASE", "2"), ("E", "EMITTER", "3")),
    )
    # SpiceOrder 必须对应 SUBCKT 引脚顺序，不能强制 C=1
    order = {p: i + 1 for i, p in enumerate(pins)} if pins else {c: 1, b: 2, e: 3}
    lines = _header("CELL")
    lines += [
        "LINE Normal 44 76 36 84",
        "LINE Normal 64 96 44 76",
        "LINE Normal 64 96 36 84",
        "LINE Normal 40 80 16 64",
        "LINE Normal 16 80 16 16",
        "LINE Normal 16 32 64 0",
        "LINE Normal 16 48 0 48",
        "WINDOW 0 72 32 Left 2",
        "WINDOW 3 72 68 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="NPN BJT (auto)")
    lines += _pin(64, 0, "NONE", 0, c, order.get(c, 1))
    lines += _pin(0, 48, "NONE", 0, b, order.get(b, 2))
    lines += _pin(64, 96, "NONE", 0, e, order.get(e, 3))
    return "\n".join(lines) + "\n"


def template_pnp(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    c, b, e = _map_three(
        pins,
        (("C", "COLLECTOR", "1"), ("B", "BASE", "2"), ("E", "EMITTER", "3")),
    )
    order = {p: i + 1 for i, p in enumerate(pins)} if pins else {c: 1, b: 2, e: 3}
    lines = _header("CELL")
    lines += [
        "LINE Normal 16 64 44 76",
        "LINE Normal 44 76 36 84",
        "LINE Normal 16 64 36 84",
        "LINE Normal 40 80 64 96",
        "LINE Normal 16 80 16 16",
        "LINE Normal 16 32 64 0",
        "LINE Normal 16 48 0 48",
        "WINDOW 0 84 32 Left 2",
        "WINDOW 3 84 68 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="PNP BJT (auto)")
    lines += _pin(64, 0, "NONE", 0, c, order.get(c, 1))
    lines += _pin(0, 48, "NONE", 0, b, order.get(b, 2))
    lines += _pin(64, 96, "NONE", 0, e, order.get(e, 3))
    return "\n".join(lines) + "\n"


def template_nmos(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    d, g, s = _map_three(
        pins,
        (("D", "DRAIN", "1"), ("G", "GATE", "2"), ("S", "SOURCE", "3")),
    )
    order = {p: i + 1 for i, p in enumerate(pins)} if pins else {d: 1, g: 2, s: 3}
    lines = _header("CELL")
    lines += [
        "LINE Normal 48 48 48 96",
        "LINE Normal 16 80 48 80",
        "LINE Normal 40 48 48 48",
        "LINE Normal 16 48 40 44",
        "LINE Normal 16 48 40 52",
        "LINE Normal 40 44 40 52",
        "LINE Normal 16 8 16 24",
        "LINE Normal 16 40 16 56",
        "LINE Normal 16 72 16 88",
        "LINE Normal 0 80 8 80",
        "LINE Normal 8 16 8 80",
        "LINE Normal 48 16 16 16",
        "LINE Normal 48 0 48 16",
        "WINDOW 0 56 32 Left 2",
        "WINDOW 3 56 72 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="NMOS (auto)")
    lines += _pin(48, 0, "NONE", 0, d, order.get(d, 1))
    lines += _pin(0, 80, "NONE", 0, g, order.get(g, 2))
    lines += _pin(48, 96, "NONE", 0, s, order.get(s, 3))
    return "\n".join(lines) + "\n"


def template_pmos(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    d, g, s = _map_three(
        pins,
        (("D", "DRAIN", "1"), ("G", "GATE", "2"), ("S", "SOURCE", "3")),
    )
    order = {p: i + 1 for i, p in enumerate(pins)} if pins else {d: 1, g: 2, s: 3}
    lines = _header("CELL")
    lines += [
        "LINE Normal 48 48 48 96",
        "LINE Normal 16 80 48 80",
        "LINE Normal 16 48 24 48",
        "LINE Normal 48 48 24 44",
        "LINE Normal 48 48 24 52",
        "LINE Normal 24 44 24 52",
        "LINE Normal 16 8 16 24",
        "LINE Normal 16 40 16 56",
        "LINE Normal 16 72 16 88",
        "LINE Normal 0 80 8 80",
        "LINE Normal 8 16 8 80",
        "LINE Normal 48 16 16 16",
        "LINE Normal 48 0 48 16",
        "WINDOW 0 56 32 Left 2",
        "WINDOW 3 56 72 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="PMOS (auto)")
    lines += _pin(48, 0, "NONE", 0, d, order.get(d, 1))
    lines += _pin(0, 80, "NONE", 0, g, order.get(g, 2))
    lines += _pin(48, 96, "NONE", 0, s, order.get(s, 3))
    return "\n".join(lines) + "\n"


def _pick_opamp_pins(pins: Sequence[str], want: int) -> list[str]:
    """尽量按 In-/In+/Out[/V+/V-] 语义挑选；否则按顺序。"""
    if not pins:
        defaults = ["In-", "In+", "OUT", "V+", "V-"]
        return defaults[:want]

    def find_one(cands: tuple[str, ...], pool: list[str]) -> str | None:
        for i, p in enumerate(pool):
            pu = p.upper().replace(" ", "")
            for c in cands:
                if pu == c or c in pu:
                    return pool.pop(i)
        return None

    pool = list(pins)
    inn = find_one(("IN-", "INN", "INVERTING", "VM", "-IN", "INM"), pool)
    inp = find_one(("IN+", "INP", "NONINV", "VP", "+IN", "INP"), pool)
    out = find_one(("OUT", "VOUT", "OUTPUT", "O"), pool)
    vp = find_one(("V+", "VCC", "VDD", "VS+", "VCC+"), pool)
    vn = find_one(("V-", "VEE", "VSS", "VS-", "VCC-"), pool)

    chosen: list[str | None] = [inn, inp, out]
    if want >= 5:
        chosen.extend([vp, vn])
    # 填补
    result: list[str] = []
    for c in chosen[:want]:
        if c is not None:
            result.append(c)
        elif pool:
            result.append(pool.pop(0))
        else:
            result.append(str(len(result) + 1))
    # 若 pins 多于 want，多余脚不画进基础模板（避免破坏运放外形）
    return result


def template_opamp3(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    """理想运放三角（官方 opamp.asy）：In- In+ Out。"""
    p = _pick_opamp_pins(pins, 3)
    # SpiceOrder：若能在原 pins 找到则用原序，否则 1..3
    def order_of(name: str, fallback: int) -> int:
        for i, x in enumerate(pins):
            if x == name:
                return i + 1
        return fallback

    lines = _header("CELL")
    lines += [
        "LINE Normal -32 32 32 64",
        "LINE Normal -32 96 32 64",
        "LINE Normal -32 32 -32 96",
        "LINE Normal -28 48 -20 48",
        "LINE Normal -28 80 -20 80",
        "LINE Normal -24 84 -24 76",
        "WINDOW 0 8 24 Left 2",
        "WINDOW 3 8 104 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Op-amp triangle (auto)")
    # 官方：上 In- (48)，下 In+ (80)，右 Out —— 但 AD711 是 In+ 在下… 
    # 官方 opamp.asy: invin@48 SpiceOrder1, noninvin@80 Order2, out Order3
    lines += _pin(-32, 48, "NONE", 0, p[0], order_of(p[0], 1))
    lines += _pin(-32, 80, "NONE", 0, p[1], order_of(p[1], 2))
    lines += _pin(32, 64, "NONE", 0, p[2], order_of(p[2], 3))
    return "\n".join(lines) + "\n"


def template_opamp5(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    """五脚运放三角（参考 AD711.asy）。"""
    p = _pick_opamp_pins(pins, 5)

    def order_of(name: str, fallback: int) -> int:
        for i, x in enumerate(pins):
            if x == name:
                return i + 1
        return fallback

    lines = _header("CELL")
    lines += [
        "LINE Normal -32 32 32 64",
        "LINE Normal -32 96 32 64",
        "LINE Normal -32 32 -32 96",
        "LINE Normal -28 48 -20 48",
        "LINE Normal -28 80 -20 80",
        "LINE Normal -24 84 -24 76",
        "LINE Normal 0 32 0 48",
        "LINE Normal 0 96 0 80",
        "LINE Normal 4 44 12 44",
        "LINE Normal 8 40 8 48",
        "LINE Normal 4 84 12 84",
        "WINDOW 0 16 24 Left 2",
        "WINDOW 3 16 104 Left 2",
    ]
    lines += _attrs(prefix=prefix, value=value, model_file=model_file, description="Op-amp 5-pin (auto)")
    # AD711: In+ order1 @80, In- order2 @48, V+@32, V-@96, OUT@64
    # 我们按 p = [In-, In+, OUT, V+, V-] 布置几何，SpiceOrder 跟原 SUBCKT
    lines += _pin(-32, 48, "NONE", 0, p[0], order_of(p[0], 1))  # In-
    lines += _pin(-32, 80, "NONE", 0, p[1], order_of(p[1], 2))  # In+
    lines += _pin(32, 64, "NONE", 0, p[2], order_of(p[2], 3))  # OUT
    lines += _pin(0, 32, "NONE", 0, p[3], order_of(p[3], 4))  # V+
    lines += _pin(0, 96, "NONE", 0, p[4], order_of(p[4], 5))  # V-
    return "\n".join(lines) + "\n"


def template_block(value: str, model_file: str | None, pins: Sequence[str], *, prefix: str = "X") -> str:
    """未知器件：矩形 BLOCK，左右分布引脚。"""
    pins = list(pins) if pins else ["1", "2"]
    n = len(pins)
    half = (n + 1) // 2
    left_pins = pins[:half]
    right_pins = pins[half:]
    body_top = -48
    body_bot = 48 if n <= 4 else -48 + 32 * ((n + 1) // 2)
    left_x, right_x = -64, 64
    box_l, box_r = -32, 32
    lines = _header("BLOCK")
    lines += [
        f"LINE Normal {box_l} {body_top} {box_r} {body_top}",
        f"LINE Normal {box_r} {body_top} {box_r} {body_bot}",
        f"LINE Normal {box_r} {body_bot} {box_l} {body_bot}",
        f"LINE Normal {box_l} {body_bot} {box_l} {body_top}",
        f"WINDOW 0 0 {body_top - 16} Left 2",
        f"WINDOW 3 0 {body_bot + 16} Left 2",
    ]
    lines += _attrs(
        prefix=prefix,
        value=value,
        model_file=model_file,
        description="Generic block (auto; unrecognized type)",
    )

    def place(side_pins: list[str], x_pin: int, x_box: int, side: str) -> None:
        if not side_pins:
            return
        span = max(body_bot - body_top, 32)
        step = span / (len(side_pins) + 1)
        for idx, pname in enumerate(side_pins, start=1):
            y = int(body_top + step * idx)
            lines.append(f"LINE Normal {x_pin} {y} {x_box} {y}")
            lines.extend(_pin(x_pin, y, side, 8, pname, pins.index(pname) + 1))

    place(left_pins, left_x, box_l, "LEFT")
    place(right_pins, right_x, box_r, "RIGHT")
    return "\n".join(lines) + "\n"


_TEMPLATES = {
    CompKind.DIODE: template_diode,
    CompKind.ZENER: template_zener,
    CompKind.SCHOTTKY: template_schottky,
    CompKind.LED: template_led,
    CompKind.TVS: template_tvs,
    CompKind.RES: template_res,
    CompKind.CAP: template_cap,
    CompKind.IND: template_ind,
    CompKind.NPN: template_npn,
    CompKind.PNP: template_pnp,
    CompKind.NMOS: template_nmos,
    CompKind.PMOS: template_pmos,
    CompKind.OPAMP3: template_opamp3,
    CompKind.OPAMP5: template_opamp5,
    CompKind.BLOCK: template_block,
}


def render_symbol(
    *,
    name: str,
    pins: Sequence[str],
    model_file_name: str | None,
    kind: CompKind | None = None,
    model_type: str | None = None,
    filename: str = "",
    prefix: str | None = None,
) -> tuple[str, InferResult]:
    """生成 .asy 文本，并返回推断结果。"""
    inferred = (
        InferResult(kind, "forced")
        if kind is not None
        else infer_kind(name, pins, model_type=model_type, filename=filename)
    )
    use_prefix = prefix or "X"
    fn = _TEMPLATES[inferred.kind]
    text = fn(name, model_file_name, pins, prefix=use_prefix)
    return text, inferred


def generate_subckt_asy(
    subckt: SubcktInfo,
    model_file_name: str,
    *,
    symbol_type: str = "CELL",  # kept for API compat; templates choose CELL/BLOCK
    filename: str = "",
) -> str:
    """为 .SUBCKT 生成符号（Prefix X + ModelFile）。"""
    text, _ = render_symbol(
        name=subckt.name,
        pins=subckt.pins,
        model_file_name=model_file_name,
        filename=filename or model_file_name,
        prefix="X",
    )
    return text


def generate_model_asy(model: ModelInfo, model_file_name: str) -> str:
    """为独立 .MODEL 生成符号；Prefix 按器件类型。"""
    prefix = _MODEL_PREFIX.get(model.model_type.upper(), "X")
    # 按类型给默认引脚数
    mt = model.model_type.upper()
    if mt in {"D"}:
        pins: list[str] = ["+", "-"]
    elif mt in {"R", "C", "L"}:
        pins = ["1", "2"]
    elif mt in {"NPN", "PNP", "NMOS", "PMOS", "VDMOS"}:
        pins = ["1", "2", "3"]
    else:
        pins = ["1", "2"]
    text, _ = render_symbol(
        name=model.name,
        pins=pins,
        model_file_name=model_file_name,
        model_type=model.model_type,
        filename=model_file_name,
        prefix=prefix,
    )
    return text


def write_asy(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def list_templates() -> list[str]:
    return [k.value for k in CompKind]
