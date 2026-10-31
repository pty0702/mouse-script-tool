# -*- coding: utf-8 -*-
"""脚本解析模块。

支持两种格式，逐行解析、可混合：
1. 简单文本格式（推荐，在记事本/Word 里编辑，另存为 .txt 纯文本）：
     # 注释行
     移到 134,87     （鼠标移动到坐标，可选）
     左键点击        （点击一次，可选）
     等待 200        （等待 200 毫秒）
     输入 你的账号    （一次输入整串文字，支持中文）
2. 兼容"全方位鼠标连点器"导出的 .qfwjb 录制格式：
     鼠标移动到：134,87
     鼠标左键按下：0,0
     ms200
     键盘NumPad1键按下：75

解析结果为动作元组列表：
  ("move", x, y)              鼠标移动到绝对坐标
  ("click", button, times)    点击 button=left/right/middle
  ("down", button) / ("up", button)
  ("mod", name, phase)        修饰键 name=ctrl/shift/alt/win，phase=down/up
  ("wait", ms)                等待毫秒
  ("type", text)              输入一串文字
  ("key", vk, phase)          原始按键 phase=down/up，vk 为虚拟键码（qfwjb）
"""

import re

_NUM = r"(-?\d+)"

# 简单格式指令
_P_MOVE = re.compile(rf"^(?:移到|移动到|鼠标移动到)\s*[：:\s]*\s*{_NUM}\s*[，,]\s*{_NUM}\s*$")
_P_WAIT = re.compile(rf"^(?:等待|延时|停|ms)\s*[：:]?\s*{_NUM}\s*(?:ms|毫秒)?\s*$")
_P_TYPE = re.compile(r"^输入\s*(.*)$")
_P_CLICK = {
    "左键点击": ("left", 1),
    "左键单击": ("left", 1),
    "左键双击": ("left", 2),
    "右键点击": ("right", 1),
    "右键双击": ("right", 2),
    "中键点击": ("middle", 1),
}
_P_KEY = re.compile(r"^键盘.+?键(按下|抬起|松开)[：:]\s*(\d+)\s*$")

# 修饰键（编辑器"同时按下键盘"生成）：按下 ctrl / 松开 shift
_P_MOD = re.compile(r"^(按下|松开)\s*[：:]?\s*(ctrl|shift|alt|win)\s*$", re.IGNORECASE)

# qfwjb 的按下/抬起行带坐标后缀，如 "鼠标左键按下：0,0"，坐标忽略
_P_MOUSE_DOWN = re.compile(r"^(?:鼠标)?(左键|右键|中键)按下\s*[：:]?\s*(?:-?\d+\s*[，,]\s*-?\d+\s*)?$")
_P_MOUSE_UP = re.compile(r"^(?:鼠标)?(左键|右键|中键)(?:松开|抬起)\s*[：:]?\s*(?:-?\d+\s*[，,]\s*-?\d+\s*)?$")

_BUTTONS = {"左键": "left", "右键": "right", "中键": "middle"}


def read_text(path):
    """读脚本文件，自动兼容 UTF-8(BOM) / GBK。"""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_line(line):
    """解析单行，返回动作元组列表（一行可能拆成多个动作）或 None（无法识别）。"""
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("//"):
        return []

    m = _P_MOVE.match(s)
    if m:
        return [("move", int(m.group(1)), int(m.group(2)))]

    if s in _P_CLICK:
        b, t = _P_CLICK[s]
        return [("click", b, t)]

    m = _P_MOUSE_DOWN.match(s)
    if m:
        return [("down", _BUTTONS[m.group(1)])]
    m = _P_MOUSE_UP.match(s)
    if m:
        return [("up", _BUTTONS[m.group(1)])]

    m = _P_MOD.match(s)
    if m:
        return [("mod", m.group(2).lower(), "down" if m.group(1) == "按下" else "up")]

    m = _P_KEY.match(s)
    if m:
        phase = "down" if m.group(1) == "按下" else "up"
        return [("key", int(m.group(2)), phase)]

    m = _P_WAIT.match(s)
    if m:
        return [("wait", max(0, int(m.group(1))))]

    m = _P_TYPE.match(s)
    if m:
        text = m.group(1).strip()
        return [("type", text)] if text else []

    return None


def parse(text):
    """解析整份脚本文本。返回 (actions, errors)。
    errors 为无法识别行的说明列表（不阻断执行，跳过即可）。"""
    actions, errors = [], []
    for no, line in enumerate(text.splitlines(), 1):
        result = parse_line(line)
        if result is None:
            errors.append(f"第{no}行无法识别，已跳过：{line.strip()}")
        else:
            actions.extend(result)
    return actions, errors


def extract_copy_text(actions, raw):
    """提取"点击复制"用的内容：脚本中所有"输入"行的文字。
    没有输入行时回退为整份脚本文本。"""
    parts = [a[1] for a in actions if a[0] == "type"]
    if parts:
        return "\n".join(parts)
    return raw


# ---------- 编辑器动作与脚本文本互转 ----------

_BUTTON_CN = {"left": "左键", "right": "右键", "middle": "中键"}
_CLICK_CN = {"click": "点击", "double": "双击", "down": "按下", "up": "松开"}


def serialize_editor_actions(actions):
    """编辑器动作列表 → 简单格式脚本文本。
    执行次数大于 1 的动作展开成重复行；每步延迟写成"等待"行。
    编辑器动作形如：
      {"kind": "move", "x", "y", "delay"}
      {"kind": "wait", "ms"}
      {"kind": "click", "button", "action", "mods", "times", "delay"}
      {"kind": "mod", "name", "phase"}
      {"kind": "type", "text", "times", "delay"}
    """
    lines = []
    for a in actions:
        kind = a["kind"]
        if kind == "move":
            lines.append(f"移到 {int(a['x'])},{int(a['y'])}")
            if int(a.get("delay", 0)) > 0:
                lines.append(f"等待 {int(a['delay'])}")
        elif kind == "wait":
            lines.append(f"等待 {int(a['ms'])}")
        elif kind == "mod":
            word = "按下" if a["phase"] == "down" else "松开"
            lines.append(f"{word} {a['name']}")
        elif kind == "click":
            for _ in range(max(1, int(a.get("times", 1)))):
                for m in a.get("mods", []):
                    lines.append(f"按下 {m}")
                lines.append(_BUTTON_CN[a["button"]] + _CLICK_CN[a["action"]])
                for m in reversed(a.get("mods", [])):
                    lines.append(f"松开 {m}")
                if int(a.get("delay", 0)) > 0:
                    lines.append(f"等待 {int(a['delay'])}")
        elif kind == "type":
            for _ in range(max(1, int(a.get("times", 1)))):
                lines.append(f"输入 {a['text']}")
                if int(a.get("delay", 0)) > 0:
                    lines.append(f"等待 {int(a['delay'])}")
    return "\n".join(lines) + "\n"


def to_editor_actions(parsed):
    """解析后的动作元组 → 编辑器动作列表。
    序列化时写入的"等待 N"行合并回前一动作的延迟；紧邻点击动作的
    按下/松开修饰键合并回该点击的"同时按下键盘"。这样编辑器保存的
    脚本重新打开时参数不丢失。含 qfwjb 数字键码动作时返回 None。"""
    out = []
    i, n = 0, len(parsed)
    while i < n:
        a = parsed[i]
        kind = a[0]
        if kind == "mod" and a[2] == "down":
            # 连续的"按下 X"向后看：紧跟点击 → 合并为"同时按下键盘"；否则保留独立
            downs = [a[1]]
            j = i + 1
            while j < n and parsed[j][0] == "mod" and parsed[j][2] == "down":
                downs.append(parsed[j][1])
                j += 1
            if j < n and parsed[j][0] == "click":
                out.append({"kind": "click", "button": parsed[j][1],
                            "action": "double" if parsed[j][2] >= 2 else "click",
                            "mods": downs, "times": 1, "delay": 0})
                absorbed = downs.copy()
                i = j + 1
                while i < n and parsed[i][0] == "mod" and parsed[i][2] == "up" \
                        and parsed[i][1] in absorbed:
                    absorbed.remove(parsed[i][1])
                    i += 1
                continue
            for nm in downs:
                out.append({"kind": "mod", "name": nm, "phase": "down"})
            i = j
            continue
        if kind == "mod":
            out.append({"kind": "mod", "name": a[1], "phase": a[2]})
        elif kind == "click":
            out.append({"kind": "click", "button": a[1],
                        "action": "double" if a[2] >= 2 else "click",
                        "mods": [], "times": 1, "delay": 0})
        elif kind == "move":
            out.append({"kind": "move", "x": a[1], "y": a[2], "delay": 0})
        elif kind == "down":
            out.append({"kind": "click", "button": a[1], "action": "down",
                        "mods": [], "times": 1, "delay": 0})
        elif kind == "up":
            out.append({"kind": "click", "button": a[1], "action": "up",
                        "mods": [], "times": 1, "delay": 0})
        elif kind == "type":
            out.append({"kind": "type", "text": a[1], "times": 1, "delay": 0})
        elif kind == "wait":
            if out and out[-1]["kind"] in ("move", "click", "type") \
                    and out[-1].get("delay") == 0:
                out[-1]["delay"] = a[1]      # 合并回前一动作的延迟
            else:
                out.append({"kind": "wait", "ms": a[1]})
        else:  # key 等编辑器不支持的动作
            return None
        i += 1
    return out
