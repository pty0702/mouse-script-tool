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
WM_KEYDOWN = 0x0100
WH_KEYBOARD_LL = 13
MOD_NOREPEAT = 0x4000
VK_F9, VK_F10 = 0x78, 0x79
VK_ESCAPE = 0x1B

# 修饰键统一用左侧虚拟键码（"同时按下键盘"勾选左右都执行左键）
VK_MOD = {"ctrl": 0xA2, "shift": 0xA0, "alt": 0xA4, "win": 0x5B}

# 键盘点击的键名 → 虚拟键码
KEY_VK = {
    "回车": 0x0D, "Tab": 0x09, "空格": 0x20, "退格": 0x08, "删除": 0x2E,
    "Esc": 0x1B, "上": 0x26, "下": 0x28, "左": 0x25, "右": 0x27,
    "Home": 0x24, "End": 0x23, "上翻页": 0x21, "下翻页": 0x22,
}
KEY_VK.update({f"F{i}": 0x6F + i for i in range(1, 13)})
KEY_VK.update({f"小键盘{i}": 0x60 + i for i in range(10)})


def key_vk(name):
    """键名 → 虚拟键码；单字符按字母/数字处理；未知返回 None。"""
    if name in KEY_VK:
        return KEY_VK[name]
    if len(name) == 1:
        ch = name.upper()
        if "0" <= ch <= "9" or "A" <= ch <= "Z":
            return ord(ch)
    return None


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


def mod_down(name):
    key_down(VK_MOD[name])


def mod_up(name):
    key_up(VK_MOD[name])


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


def exec_actions(actions, stop):
    """按顺序执行解析后的动作元组列表，stop 置位时中止。
    返回 True 表示全部执行完成。"""
    for act in actions:
        if stop.is_set():
            return False
        kind = act[0]
        if kind == "move":
            move_to(act[1], act[2])
        elif kind == "click":
            for _ in range(act[2]):
                if stop.is_set():
                    return False
                click(act[1])
        elif kind == "down":
            mouse_down(act[1])
        elif kind == "up":
            mouse_up(act[1])
        elif kind == "mod":
            (mod_down if act[2] == "down" else mod_up)(act[1])
        elif kind == "keypress":
            vk = key_vk(act[1])
            if vk is None:
                continue
            if act[2] == "down":
                key_down(vk)
            elif act[2] == "up":
                key_up(vk)
            else:  # click（含 double 展开成的两次 click）
                key_down(vk)
                time.sleep(0.03)
                key_up(vk)
        elif kind == "key":
            (key_down if act[2] == "down" else key_up)(act[1])
        elif kind == "wait":
            end = time.time() + act[1] / 1000.0
            while time.time() < end and not stop.is_set():
                time.sleep(0.02)
        elif kind == "type":
            type_text(act[1])
    return True


def start_hotkeys(event_queue, esc_taps=3, esc_window=1.2):
    """注册全局热键并监听 Esc 快速连按，在后台线程运行。

    F9=打开脚本编辑  F10=运行/停止（由主程序根据状态切换）
    Esc 快速连按 esc_taps 次（esc_window 秒内）→ 投递 ("hotkey", "esc_exit")
    强制退出整个软件。低级键盘钩子只观察不拦截，不影响其他软件使用 Esc。
    热键触发/连按触发时向 event_queue 投递 ("hotkey", "f9"/"f10"/"esc_exit")。
    """
    def loop():
        ids = {1: ("f9", VK_F9), 2: ("f10", VK_F10)}
        for i, (_, vk) in ids.items():
            user32.RegisterHotKey(None, i, MOD_NOREPEAT, vk)

        # 低级键盘钩子：Esc 连按检测（仅观察，CallNextHookEx 放行）
        taps = []
        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM,
            ctypes.POINTER(KBDLLHOOKSTRUCT))

        def proc(ncode, wparam, lparam):
            if ncode == 0 and wparam == WM_KEYDOWN \
                    and lparam.contents.vkCode == VK_ESCAPE:
                now = time.time()
                taps[:] = [t for t in taps if now - t < esc_window]
                taps.append(now)
                if len(taps) >= esc_taps:
                    taps.clear()
                    event_queue.put(("hotkey", "esc_exit"))
            return user32.CallNextHookEx(None, ncode, wparam, lparam)

        global _esc_hook_cb
        _esc_hook_cb = HOOKPROC(proc)          # 持有引用防止被垃圾回收
        user32.SetWindowsHookExW(WH_KEYBOARD_LL, _esc_hook_cb, None, 0)

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


_esc_hook_cb = None
