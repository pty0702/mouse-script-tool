# -*- coding: utf-8 -*-
"""脚本编辑窗口：照参考软件的交互方式做脚本。

左侧操作列表（每项带"添加"按钮）→ 弹出参数对话框（确定/取消）→
动作进入右侧表格 → 保存鼠标宏（存成文本脚本，与导入格式一致）。
支持"选取坐标"：屏幕出准星，鼠标移到哪实时显示坐标，单击取位。
"""

import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import scriptfmt
import sim

MOD_CHOICES = ["左Ctrl", "右Ctrl", "左Shift", "右Shift", "左Alt", "右Alt", "左Win", "右Win"]
_KEY_PLACEHOLDER = "直接按下键盘按键"
MOD_TO_NAME = {"左Ctrl": "ctrl", "右Ctrl": "ctrl", "左Shift": "shift", "右Shift": "shift",
               "左Alt": "alt", "右Alt": "alt", "左Win": "win", "右Win": "win"}
MOD_CN = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
BUTTON_CN = {"left": "鼠标左键", "right": "鼠标右键", "middle": "鼠标中键"}
BUTTONS = {"鼠标左键": "left", "鼠标中键": "middle", "鼠标右键": "right"}
ACTION_CN = {"click": "单击(按下+松开)", "down": "按下", "up": "松开", "double": "双击"}
ACTIONS = {"click": "click", "down": "down", "up": "up", "double": "double"}
ACTION_BY_CN = {v: k for k, v in ACTION_CN.items()}   # 下拉框中文显示 → 内部值

# 左侧操作列表：分组 → (显示名, kind, button, action)
OP_GROUPS = [
    ("鼠标操作", [
        ("鼠标移动到", "move", None, None),
        ("等待", "wait", None, None),
        ("鼠标右键点击", "click", "right", "click"),
        ("鼠标右键按下", "click", "right", "down"),
        ("鼠标右键松开", "click", "right", "up"),
        ("鼠标左键点击", "click", "left", "click"),
        ("鼠标左键按下", "click", "left", "down"),
        ("鼠标左键松开", "click", "left", "up"),
        ("鼠标左键双击", "click", "left", "double"),
        ("鼠标中键点击", "click", "middle", "click"),
        ("鼠标中键按下", "click", "middle", "down"),
        ("鼠标中键松开", "click", "middle", "up"),
    ]),
    ("键盘操作", [
        ("键盘点击", "keypress", None, None),
        ("输入文字", "type", None, None),
    ]),
]

# 编辑器捕获的按键名（keysym → 脚本键名），修饰键本身不捕获
_KEYSYM_MAP = {
    "Return": "回车", "Tab": "Tab", "space": "空格", "BackSpace": "退格",
    "Delete": "删除", "Escape": "Esc", "Up": "上", "Down": "下",
    "Left": "左", "Right": "右", "Home": "Home", "End": "End",
    "Prior": "上翻页", "Next": "下翻页",
}


def keysym_to_name(ks):
    """tkinter keysym → 脚本键名；不认识的（修饰键等）返回 None。"""
    if ks in _KEYSYM_MAP:
        return _KEYSYM_MAP[ks]
    if ks.startswith("KP_") and ks[3:].isdigit():
        return "小键盘" + ks[3:]
    if len(ks) == 1 and ks.isalnum():
        return ks
    if len(ks) > 1 and ks[0] == "F" and ks[1:].isdigit():
        return ks      # F1 ~ F12
    return None


def _num(value, default=None):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def pick_position(parent, hide=()):
    """全屏半透明取坐标：先把 hide 里的窗口藏起来（避免挡住目标位置），
    移动鼠标实时显示坐标，单击取位，Esc 取消；结束时恢复窗口。"""
    result = {"pos": None}
    hidden = []
    for w in hide:
        try:
            if w.winfo_viewable():
                w.withdraw()
                hidden.append(w)
        except tk.TclError:
            pass
    ov = tk.Toplevel(parent)
    ov.overrideredirect(True)
    ov.geometry(f"{ov.winfo_screenwidth()}x{ov.winfo_screenheight()}+0+0")
    ov.attributes("-topmost", True)
    ov.attributes("-alpha", 0.25)
    ov.configure(bg="#0b2545", cursor="crosshair")
    tk.Label(ov, text="移动鼠标到目标位置，单击选取；按 Esc 取消",
             font=("微软雅黑", 15, "bold"), fg="white", bg="#000000",
             padx=24, pady=10).place(relx=0.5, rely=0.04, anchor="center")
    pos_lbl = tk.Label(ov, text="X: 0   Y: 0", font=("Consolas", 20, "bold"),
                       fg="#FFD54F", bg="#000000", padx=24, pady=6)
    pos_lbl.place(relx=0.5, rely=0.12, anchor="center")

    def on_move(e):
        pos_lbl.config(text=f"X: {e.x_root}   Y: {e.y_root}")

    def on_click(e):
        result["pos"] = (e.x_root, e.y_root)
        ov.destroy()

    ov.bind("<Motion>", on_move)
    ov.bind("<Button-1>", on_click)
    ov.bind("<Escape>", lambda e: ov.destroy())
    ov.focus_force()
    try:
        ov.grab_set()
        parent.wait_window(ov)
    finally:
        for w in hidden:
            try:
                w.deiconify()
            except tk.TclError:
                pass
    return result["pos"]


def _make_dialog(parent, title, tip):
    """通用模态对话框骨架，返回 (dlg, body_frame, btn_row)。
    调用方加完控件后用 ScriptEditor._show_dialog 居中弹出。"""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.resizable(False, False)
    dlg.transient(parent.winfo_toplevel())
    dlg.grab_set()
    tk.Label(dlg, text="ⓘ " + tip, fg="#666666",
             font=("微软雅黑", 9)).pack(anchor="w", padx=16, pady=(14, 4))
    body = tk.Frame(dlg)
    body.pack(fill="both", expand=True, padx=16)
    btn_row = tk.Frame(dlg)
    btn_row.pack(fill="x", pady=12)
    return dlg, body, btn_row


def _mods_grid(parent, start_row=0):
    """"同时按下键盘" 4 行 2 列复选框（照参考软件布局），返回 {名称: StringVar}。"""
    grid = tk.Frame(parent)
    grid.pack(side="left", padx=8)
    mod_vars = {}
    for r, pair in enumerate([("左Ctrl", "右Ctrl"), ("左Shift", "右Shift"),
                              ("左Alt", "右Alt"), ("左Win", "右Win")]):
        for c, name in enumerate(pair):
            v = tk.StringVar(value="0")
            ttk.Checkbutton(grid, text=name, variable=v,
                            onvalue="1", offvalue="0").grid(
                row=r, column=c, sticky="w", padx=8, pady=1)
            mod_vars[name] = v
    return grid, mod_vars


def _mods_selected(mod_vars):
    return [MOD_TO_NAME[n] for n in MOD_CHOICES if mod_vars[n].get() == "1"]


class ScriptEditor(tk.Toplevel):
    """脚本编辑窗口。on_saved(path) 在保存后回调主界面。"""

    def __init__(self, master, on_saved=None, source_path=None, scripts_dir=None):
        super().__init__(master)
        self.title("脚本编辑 - 鼠标脚本工具 by 西塔 | ptyo7o2")
        self.geometry("920x580")
        self.minsize(820, 500)

        self.on_saved = on_saved
        self.source_path = source_path
        self.scripts_dir = scripts_dir
        self.actions = []      # 编辑器动作 dict 列表
        self.running = False
        self.stop_flag = threading.Event()

        self._build_left()
        self._build_right()
        if source_path:
            self._load_source(source_path)

    # ---------- 界面 ----------
    def _build_left(self):
        left = tk.Frame(self, width=210)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        left.pack_propagate(False)
        canvas = tk.Canvas(left, highlightthickness=0, width=196)
        sb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw", width=190)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for group_name, items in OP_GROUPS:
            tk.Label(inner, text=group_name, fg="#3B82F6",
                     font=("微软雅黑", 9, "bold")).pack(anchor="w", pady=(8, 2))
            for name, kind, button, action in items:
                row = tk.Frame(inner)
                row.pack(fill="x", pady=1)
                icon = "🖱" if kind in ("move", "wait", "click") else "⌨"
                tk.Label(row, text=f"{icon} {name}",
                         font=("微软雅黑", 9)).pack(side="left")
                ttk.Button(row, text="添加", width=5,
                           command=lambda k=kind, b=button, a=action:
                           self._add_action(k, b, a)).pack(side="right")

    def _build_right(self):
        right = tk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        top = tk.Frame(right)
        top.pack(fill="x")
        self.name_var = tk.StringVar(value=self._default_name())
        ttk.Entry(top, textvariable=self.name_var, font=("微软雅黑", 10)).pack(
            side="left", fill="x", expand=True, ipady=3)
        ttk.Button(top, text="保存鼠标宏", style="Blue.TButton",
                   command=self.on_save).pack(side="left", padx=(8, 0))

        mid = tk.Frame(right)
        mid.pack(fill="x", pady=(8, 4))
        self.count_var = tk.StringVar(value="当前动作数: 0")
        tk.Label(mid, textvariable=self.count_var,
                 font=("微软雅黑", 9)).pack(side="left")
        ttk.Button(mid, text="🗑 清空", command=self.on_clear).pack(side="right")

        cols = ("no", "act", "param", "copy", "del")
        self.tree = ttk.Treeview(right, columns=cols, show="headings",
                                 selectmode="none", height=15)
        for col, text, width, anchor in (("no", "序号", 50, "center"),
                                         ("act", "动作", 150, "w"),
                                         ("param", "参数", 350, "w"),
                                         ("copy", "复制", 50, "center"),
                                         ("del", "删除", 50, "center")):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col == "param"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self._on_table_click)

        bottom = tk.Frame(right)
        bottom.pack(fill="x", pady=(8, 0))
        self.status_var = tk.StringVar(value="点左侧「添加」逐步做脚本；保存后回主界面勾选运行")
        tk.Label(bottom, textvariable=self.status_var, fg="#666666",
                 font=("微软雅黑", 9)).pack(side="left")
        self.run_btn = ttk.Button(bottom, text="执行脚本", style="Blue.TButton",
                                  command=self.on_run)
        self.run_btn.pack(side="right")

    def _default_name(self):
        base = "鼠标宏-" + time.strftime("%Y%m%d%H%M%S")
        if self.source_path:
            base = os.path.splitext(os.path.basename(self.source_path))[0]
        return base

    def _show_dialog(self, dlg):
        """屏幕居中弹出模态对话框并等待结果。"""
        dlg.update_idletasks()
        w = max(dlg.winfo_reqwidth(), 1)
        h = max(dlg.winfo_reqheight(), 1)
        x = (dlg.winfo_screenwidth() - w) // 2
        y = (dlg.winfo_screenheight() - h) // 2
        dlg.geometry(f"+{x}+{y}")
        self.wait_window(dlg)
        return dlg.result

    # ---------- 添加动作 ----------
    def _add_action(self, kind, button, action):
        if kind == "move":
            dlg = self._dialog_move()
        elif kind == "wait":
            dlg = self._dialog_wait()
        elif kind == "click":
            dlg = self._dialog_click(button, action)
        elif kind == "keypress":
            dlg = self._dialog_keypress()
        else:
            dlg = self._dialog_type()
        if dlg is not None:
            self.actions.append(dlg)
            self._refresh()

    def _dialog_move(self):
        dlg, body, btn_row = _make_dialog(self, "鼠标移动", "将鼠标移动到指定位置")
        row = tk.Frame(body)
        row.pack(fill="x", pady=6)
        tk.Label(row, text="移动到坐标  X").pack(side="left")
        x_var, y_var = tk.StringVar(), tk.StringVar()
        ttk.Entry(row, textvariable=x_var, width=8).pack(side="left", padx=6)
        tk.Label(row, text="Y").pack(side="left")
        ttk.Entry(row, textvariable=y_var, width=8).pack(side="left", padx=6)

        def do_pick():
            # 选取期间隐藏对话框、编辑器与主窗口，避免挡住要选的位置
            pos = pick_position(dlg, hide=(dlg, self, self.master))
            dlg.grab_set()   # 选完恢复对话框的模态
            if pos:
                x_var.set(str(pos[0]))
                y_var.set(str(pos[1]))

        ttk.Button(row, text="选取坐标", command=do_pick).pack(side="left", padx=6)
        row2 = tk.Frame(body)
        row2.pack(fill="x", pady=6)
        delay = tk.StringVar(value="30")
        ttk.Spinbox(row2, from_=0, to=600000, textvariable=delay, width=7).pack(side="left")
        tk.Label(row2, text=" 毫秒后执行下一个动作; (1000毫秒等于1秒)").pack(side="left")

        def on_ok():
            x, y = _num(x_var.get()), _num(y_var.get())
            if x is None or y is None:
                messagebox.showwarning("鼠标移动", "请填写 X、Y 坐标（可用「选取坐标」自动填入）", parent=dlg)
                return
            d = _num(delay.get(), 30)
            dlg.result = {"kind": "move", "x": x, "y": y, "delay": max(0, d)}
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btn_row, text="确定", style="Blue.TButton",
                   command=on_ok).pack(side="right", padx=6)
        return self._show_dialog(dlg)

    def _dialog_wait(self):
        dlg, body, btn_row = _make_dialog(
            self, "等待时间", "指定一个动作执行之后等待多久再执行下一个动作")
        row = tk.Frame(body)
        row.pack(fill="x", pady=10)
        ms = tk.StringVar(value="200")
        ttk.Spinbox(row, from_=0, to=600000, textvariable=ms, width=8).pack(side="left")
        tk.Label(row, text=" 毫秒后执行下一个动作; (1000毫秒等于1秒)").pack(side="left")

        def on_ok():
            n = _num(ms.get(), 0)
            dlg.result = {"kind": "wait", "ms": max(0, n)}
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btn_row, text="确定", style="Blue.TButton",
                   command=on_ok).pack(side="right", padx=6)
        return self._show_dialog(dlg)

    def _dialog_click(self, button, action):
        dlg, body, btn_row = _make_dialog(self, "鼠标点击", "点击鼠标所在位置")
        row = tk.Frame(body)
        row.pack(fill="x", pady=6)
        tk.Label(row, text="鼠标按键").pack(side="left")
        b_var = tk.StringVar(value=BUTTON_CN[button])
        ttk.Combobox(row, textvariable=b_var, width=10, state="readonly",
                     values=list(BUTTONS)).pack(side="left", padx=6)
        tk.Label(row, text="  鼠标按键").pack(side="left")
        a_var = tk.StringVar(value=ACTION_CN[action])
        ttk.Combobox(row, textvariable=a_var, width=14, state="readonly",
                     values=list(ACTION_CN.values())).pack(side="left", padx=6)

        row2 = tk.Frame(body)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="同时按下键盘").pack(side="left")
        _, mod_vars = _mods_grid(row2)

        row3 = tk.Frame(body)
        row3.pack(fill="x", pady=6)
        tk.Label(row3, text="执行次数:").pack(side="left")
        times = tk.StringVar(value="1")
        ttk.Spinbox(row3, from_=0, to=99, textvariable=times, width=5).pack(side="left", padx=4)
        tk.Label(row3, text="(0~99，默认一次)").pack(side="left")

        row4 = tk.Frame(body)
        row4.pack(fill="x", pady=6)
        tk.Label(row4, text="延迟").pack(side="left")
        delay = tk.StringVar(value="30")
        ttk.Spinbox(row4, from_=0, to=600000, textvariable=delay, width=7).pack(side="left")
        tk.Label(row4, text=" 毫秒后执行下一个动作; (1000毫秒等于1秒)").pack(side="left")

        def on_ok():
            dlg.result = {"kind": "click", "button": BUTTONS[b_var.get()],
                          "action": ACTION_BY_CN[a_var.get()],
                          "mods": _mods_selected(mod_vars),
                          "times": max(0, _num(times.get(), 1)),
                          "delay": max(0, _num(delay.get(), 30))}
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btn_row, text="确定", style="Blue.TButton",
                   command=on_ok).pack(side="right", padx=6)
        return self._show_dialog(dlg)

    def _dialog_keypress(self):
        dlg, body, btn_row = _make_dialog(
            self, "键盘点击", "模拟键盘单击、按住、抬起等点击动作")
        row1 = tk.Frame(body)
        row1.pack(fill="x", pady=6)
        tk.Label(row1, text="键盘按键").pack(side="left")
        key_var = tk.StringVar(value=_KEY_PLACEHOLDER)
        key_entry = ttk.Entry(row1, textvariable=key_var, width=16, justify="center",
                              font=("微软雅黑", 10))
        key_entry.pack(side="left", padx=6, ipady=2)
        tk.Label(row1, text="  键盘动作").pack(side="left")
        a_var = tk.StringVar(value="单击(按下+松开)")
        ttk.Combobox(row1, textvariable=a_var, width=14, state="readonly",
                     values=list(ACTION_CN.values())).pack(side="left", padx=6)

        row2 = tk.Frame(body)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="同时按下键盘").pack(side="left")
        _, mod_vars = _mods_grid(row2)

        row3 = tk.Frame(body)
        row3.pack(fill="x", pady=6)
        tk.Label(row3, text="执行次数:").pack(side="left")
        times = tk.StringVar(value="1")
        ttk.Spinbox(row3, from_=0, to=99, textvariable=times, width=5).pack(side="left", padx=4)
        tk.Label(row3, text="(0~99，默认一次)").pack(side="left")

        row4 = tk.Frame(body)
        row4.pack(fill="x", pady=6)
        tk.Label(row4, text="延迟").pack(side="left")
        delay = tk.StringVar(value="30")
        ttk.Spinbox(row4, from_=0, to=600000, textvariable=delay, width=7).pack(side="left")
        tk.Label(row4, text=" 毫秒后执行下一个动作; (1000毫秒等于1秒)").pack(side="left")

        def on_key(e):
            name = keysym_to_name(e.keysym)
            if name:
                key_entry.config(foreground="black")
                key_var.set(name)
            return "break"

        def on_focus_in(e):
            if key_var.get() == _KEY_PLACEHOLDER:
                key_var.set("")

        key_entry.bind("<KeyPress>", on_key)
        key_entry.bind("<FocusIn>", on_focus_in)

        def on_ok():
            key = key_var.get().strip()
            if not key or key == _KEY_PLACEHOLDER:
                messagebox.showwarning("键盘点击", "请先点进「键盘按键」框，直接按下一个键", parent=dlg)
                return
            dlg.result = {"kind": "keypress", "key": key,
                          "action": ACTION_BY_CN[a_var.get()], "mods": _mods_selected(mod_vars),
                          "times": max(0, _num(times.get(), 1)),
                          "delay": max(0, _num(delay.get(), 30))}
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btn_row, text="确定", style="Blue.TButton",
                   command=on_ok).pack(side="right", padx=6)
        return self._show_dialog(dlg)

    def _dialog_type(self):
        dlg, body, btn_row = _make_dialog(self, "输入文字", "把一串文字输入到当前光标所在位置（支持中文）")
        row = tk.Frame(body)
        row.pack(fill="x", pady=6)
        tk.Label(row, text="文字内容").pack(side="left")
        text_var = tk.StringVar()
        ttk.Entry(row, textvariable=text_var, width=36,
                  font=("微软雅黑", 10)).pack(side="left", padx=6, ipady=2)

        row3 = tk.Frame(body)
        row3.pack(fill="x", pady=6)
        tk.Label(row3, text="执行次数:").pack(side="left")
        times = tk.StringVar(value="1")
        ttk.Spinbox(row3, from_=0, to=99, textvariable=times, width=5).pack(side="left", padx=4)
        tk.Label(row3, text="(0~99，默认一次)").pack(side="left")

        row4 = tk.Frame(body)
        row4.pack(fill="x", pady=6)
        tk.Label(row4, text="延迟").pack(side="left")
        delay = tk.StringVar(value="30")
        ttk.Spinbox(row4, from_=0, to=600000, textvariable=delay, width=7).pack(side="left")
        tk.Label(row4, text=" 毫秒后执行下一个动作; (1000毫秒等于1秒)").pack(side="left")

        def on_ok():
            text = text_var.get().strip()
            if not text:
                messagebox.showwarning("输入文字", "请填写要输入的文字内容", parent=dlg)
                return
            dlg.result = {"kind": "type", "text": text,
                          "times": max(0, _num(times.get(), 1)),
                          "delay": max(0, _num(delay.get(), 30))}
            dlg.destroy()

        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=6)
        ttk.Button(btn_row, text="确定", style="Blue.TButton",
                   command=on_ok).pack(side="right", padx=6)
        return self._show_dialog(dlg)

    # ---------- 表格 ----------
    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for i, a in enumerate(self.actions, 1):
            self.tree.insert("", "end", iid=str(i - 1),
                             values=(i, *self._display(a), "📄", "🗑"))
        self.count_var.set(f"当前动作数: {len(self.actions)}")

    @staticmethod
    def _display(a):
        kind = a["kind"]
        if kind == "move":
            return "鼠标移动到", f"X:{a['x']}, Y:{a['y']}  延迟{a['delay']}毫秒"
        if kind == "wait":
            return "等待", f"{a['ms']} 毫秒"
        if kind == "mod":
            return f"键盘{MOD_CN[a['name']]}", "按下" if a["phase"] == "down" else "松开"
        if kind == "keypress":
            extra = ""
            if a["mods"]:
                extra = " 同时按下 " + "、".join(MOD_CN[m] for m in a["mods"])
            return (f"键盘[{a['key']}]{_KEYPRESS_CN[a['action']]}",
                    f"执行{a['times']}次{extra}  延迟{a['delay']}毫秒")
        if kind == "click":
            extra = ""
            if a["mods"]:
                extra = " 同时按下 " + "、".join(MOD_CN[m] for m in a["mods"])
            return (f"{BUTTON_CN[a['button']]}{ {'click': '点击', 'down': '按下', 'up': '松开', 'double': '双击'}[a['action']] }",
                    f"执行{a['times']}次{extra}  延迟{a['delay']}毫秒")
        if kind == "type":
            return "输入文字", f"{a['text']}  (执行{a['times']}次, 延迟{a['delay']}毫秒)"
        return str(a), ""

    def _on_table_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if col == "#5":     # 🗑 删除该动作
            self.actions.pop(int(row))
            self._refresh()
        elif col == "#4":   # 📄 复制该动作，追加到列表末尾
            self.actions.append(dict(self.actions[int(row)]))
            self._refresh()
            self.status_var.set(f"已复制第 {int(row) + 1} 步到列表末尾")

    def on_clear(self):
        if self.actions and messagebox.askyesno("脚本编辑", "确定清空全部动作？"):
            self.actions.clear()
            self._refresh()

    # ---------- 保存 ----------
    def on_save(self):
        if not self.actions:
            messagebox.showinfo("脚本编辑", "请先在左侧点「添加」加入动作")
            return
        name = "".join(c for c in self.name_var.get().strip() if c not in '\\/:*?"<>|')
        if not name:
            messagebox.showwarning("脚本编辑", "请填写脚本名称")
            return
        # 编辑已有脚本且未改名 → 覆盖原文件；否则存到"脚本"文件夹
        if self.source_path and name == self._default_name():
            path = self.source_path
        else:
            os.makedirs(self.scripts_dir, exist_ok=True)
            path = os.path.join(self.scripts_dir, name + ".txt")
        text = scriptfmt.serialize_editor_actions(self.actions)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            messagebox.showerror("脚本编辑", f"保存失败：{e}")
            return
        self.source_path = path
        self.status_var.set(f"已保存：{path}")
        if self.on_saved:
            self.on_saved(path)
        messagebox.showinfo("脚本编辑", f"已保存：{os.path.basename(path)}\n"
                                        "回主界面勾选后按 F10 运行")

    # ---------- 执行 ----------
    def on_run(self):
        if self.running:                    # 执行中再点 = 停止
            self.stop_flag.set()
            self.status_var.set("正在停止…")
            return
        if not self.actions:
            messagebox.showinfo("脚本编辑", "请先添加动作")
            return
        if not messagebox.askyesno(
                "执行脚本",
                f"将按当前动作执行一遍（共 {len(self.actions)} 步）。\n"
                "点「是」后请立即把光标切到目标输入框；\n"
                "执行中再点一次本按钮可随时停止。"):
            return
        text = scriptfmt.serialize_editor_actions(self.actions)
        parsed, errors = scriptfmt.parse(text)
        if errors:
            messagebox.showwarning("脚本编辑", "部分动作无法识别，已跳过")
        self.stop_flag.clear()
        self.running = True
        self.run_btn.configure(text="⏹ 停止执行")
        self.status_var.set("执行中… 3 秒后开始，请切到目标窗口")
        threading.Thread(target=self._worker, args=(parsed,), daemon=True).start()

    def _worker(self, parsed):
        msg = "执行完成"
        try:
            time.sleep(3)   # 给用户切窗口的时间
            if self.stop_flag.is_set():
                msg = "已停止"
            else:
                msg = "执行完成" if sim.exec_actions(parsed, self.stop_flag) else "已停止"
        except Exception as e:   # 输入模拟异常不让线程静默死掉
            msg = f"执行出错: {e}"
        finally:
            self.after(0, self._run_done, msg)

    def _run_done(self, msg):
        self.running = False
        self.run_btn.configure(text="执行脚本")
        self.run_btn.state(["!disabled"])
        self.status_var.set(msg)

    # ---------- 载入已有脚本 ----------
    def _load_source(self, path):
        try:
            raw = scriptfmt.read_text(path)
        except OSError:
            return
        parsed, _ = scriptfmt.parse(raw)
        actions = scriptfmt.to_editor_actions(parsed)
        if actions is None:
            messagebox.showinfo(
                "脚本编辑", "该脚本包含键盘编码动作（qfwjb 录制的小键盘等），"
                "编辑器暂不支持显示，将用记事本打开。")
            os.startfile(path)
            self.destroy()
            return
        self.actions = actions
        self._refresh()
