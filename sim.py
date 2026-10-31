# -*- coding: utf-8 -*-
"""Windows 原生输入模拟：鼠标移动/点击、键盘打字、全局热键。

全部通过 ctypes 调用 user32，无第三方依赖。
打字采用 KEYEVENTF_UNICODE 方式，中文、符号都能输入到当前焦点控件。
"""

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUnion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUnion)]


INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000
VK_F9, VK_F10, VK_F11 = 0x78, 0x79, 0x7A


def _send(*units):
    """发送一组输入事件。units 元素为 (类型, MOUSEINPUT 或 KEYBDINPUT)。"""
    arr = (INPUT * len(units))()
    for i, (t, u) in enumerate(units):
        arr[i].type = t
        if t == INPUT_KEYBOARD:
            arr[i].union.ki = u
        else:
            arr[i].union.mi = u
    user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))


def _mouse(flags):
    _send((INPUT_MOUSE, MOUSEINPUT(0, 0, 0, flags, 0, 0)))


def move_to(x, y):
    user32.SetCursorPos(int(x), int(y))


def mouse_down(button="left"):
    _mouse({"left": MOUSEEVENTF_LEFTDOWN, "right": MOUSEEVENTF_RIGHTDOWN,
            "middle": MOUSEEVENTF_MIDDLEDOWN}[button])


def mouse_up(button="left"):
    _mouse({"left": MOUSEEVENTF_LEFTUP, "right": MOUSEEVENTF_RIGHTUP,
            "middle": MOUSEEVENTF_MIDDLEUP}[button])


def click(button="left"):
    mouse_down(button)
    time.sleep(0.03)
    mouse_up(button)


def double_click(button="left"):
    click(button)
    time.sleep(0.06)
    click(button)


def key_down(vk):
    _send((INPUT_KEYBOARD, KEYBDINPUT(vk, 0, 0, 0, 0)))


def key_up(vk):
    _send((INPUT_KEYBOARD, KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0)))


def type_text(text, interval=0.012):
    """逐字符把 text 打字输入到当前焦点位置，支持中文与常见符号。"""
    for ch in text:
        if ch == "\n":
            key_down(0x0D)  # 回车
            key_up(0x0D)
        elif ch == "\t":
            key_down(0x09)  # Tab
            key_up(0x09)
        else:
            code = ord(ch)
            if code > 0xFFFF:  # 增补平面字符拆成 UTF-16 代理对
                code -= 0x10000
                pair = (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
            else:
                pair = (code,)
            for c in pair:
                _send((INPUT_KEYBOARD, KEYBDINPUT(0, c, KEYEVENTF_UNICODE, 0, 0)))
                _send((INPUT_KEYBOARD,
                       KEYBDINPUT(0, c, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)))
        time.sleep(interval)


def start_hotkeys(event_queue):
    """注册全局热键并在后台线程监听。

    F9=新建脚本  F10=运行  F11=停止
    热键触发时向 event_queue 投递 ("hotkey", "f9"/"f10"/"f11")。
    """
    def loop():
        ids = {1: ("f9", VK_F9), 2: ("f10", VK_F10), 3: ("f11", VK_F11)}
        for i, (_, vk) in ids.items():
            user32.RegisterHotKey(None, i, MOD_NOREPEAT, vk)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    item = ids.get(msg.wParam)
                    if item:
                        event_queue.put(("hotkey", item[0]))
        finally:
            for i in ids:
                user32.UnregisterHotKey(None, i)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
