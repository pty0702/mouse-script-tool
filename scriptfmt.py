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
  ("wait", ms)                等待毫秒
  ("type", text)              输入一串文字
  ("key", vk, phase)          原始按键 phase=down/up，vk 为虚拟键码
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
