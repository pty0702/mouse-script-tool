# -*- coding: utf-8 -*-
"""鼠标脚本工具 —— 主程序。

界面沿用"全方位鼠标连点器(360专版)"主列表页：
  导入 / 清空 / 脚本列表（名称、路径、操作）/ 回放次数 / F9 新建 / F10 运行
特色功能：
  - 脚本为纯文本（记事本、Word 里改好另存 .txt 即可），同时兼容 .qfwjb 录制格式
  - 脚本名称可改颜色：红=账号、绿=密码，颜色保存在配置里
  - 双击脚本名：把该脚本"输入"的内容复制到剪贴板
  - 勾选脚本按 F10：把内容自动打字到当前光标所在的输入框
"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import scriptfmt
import sim

APP_TITLE = "鼠标脚本工具"

# 程序目录：打包成 exe 后取 exe 所在目录，脚本状态下取 py 文件目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SCRIPTS_DIR = os.path.join(BASE_DIR, "脚本")

COLOR_KEYS = ("black", "red", "green")
COLOR_FG = {"black": "#333333", "red": "#E53935", "green": "#0B8A3C"}
COLOR_NAMES = {"black": "默认黑", "red": "红色(账号)", "green": "绿色(密码)"}

TEMPLATE = """\
# 鼠标脚本模板 —— 在下面写指令，保存后回到软件点"导入"
# 可用指令（# 开头是注释，空行忽略）：
#   移到 134,87     鼠标移动到坐标
#   左键点击        单击左键（另有 右键点击 / 左键双击）
#   等待 200        等 200 毫秒
#   输入 你的账号    输入一串文字（支持中文）
# 用法：运行前先把光标点进目标输入框，再按 F10
输入 """

COL_TPL = """\
# {name} —— 鼠标脚本模板，改好保存后回软件点"导入"
# 可用指令：移到 x,y / 左键点击 / 右键点击 / 左键双击 / 等待 毫秒 / 输入 文字
输入 """


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("860x520")
        root.minsize(720, 420)

        self.items = []          # 每项: dict(path, name, color, checked)
        self.events = queue.Queue()
        self.stop_flag = threading.Event()
        self.running = False
        self.play_count = tk.StringVar(value="1")
        self.count_mode = tk.StringVar(value="自定义次数")

        self._build_style()
        self._build_ui()
        self._load_config()
        self._refresh_tree()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        sim.start_hotkeys(self.events)
        self.root.after(80, self._poll_events)

    # ---------- 界面 ----------
    def _build_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Blue.TButton", foreground="white", background="#3B82F6",
                        font=("微软雅黑", 10), padding=(14, 6))
        style.map("Blue.TButton",
                  background=[("disabled", "#93B8F5"), ("active", "#2F6FE0")])
        style.configure("Treeview", font=("微软雅黑", 9), rowheight=28)
        style.configure("Treeview.Heading", font=("微软雅黑", 9, "bold"))
        self.root.option_add("*Font", ("微软雅黑", 9))

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        ttk.Button(top, text="📥 导入", style="Blue.TButton",
                   command=self.on_import).pack(side="left")
        ttk.Button(top, text="🗑 清空", command=self.on_clear).pack(side="right")

        columns = ("chk", "name", "path", "ops")
        top_master = ttk.Frame(self.root, padding=(8, 0))
        self.tree = ttk.Treeview(top_master, columns=columns, show="headings",
                                 selectmode="none")
        headings = [("chk", "☑", 50, "center"), ("name", "脚本名称", 220, "w"),
                    ("path", "文件路径", 340, "w"), ("ops", "操作", 170, "center")]
        for col, text, width, anchor in headings:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "path"))
        vsb = ttk.Scrollbar(top_master, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        top_master.pack(fill="both", expand=True)

        for key in COLOR_KEYS:
            self.tree.tag_configure(key, foreground=COLOR_FG[key])

        self.menu = tk.Menu(self.root, tearoff=0)
        color_menu = tk.Menu(self.menu, tearoff=0)
        for key in COLOR_KEYS:
            color_menu.add_command(label=COLOR_NAMES[key],
                                   command=lambda k=key: self.set_color(self._menu_index, k))
        self.menu.add_cascade(label="颜色", menu=color_menu)
        self.menu.add_command(label="⚙ 编辑脚本", command=lambda: self.edit_script(self._menu_index))
        self.menu.add_command(label="📂 打开所在文件夹", command=lambda: self.open_folder(self._menu_index))
        self.menu.add_command(label="📄 复制内容到剪贴板", command=lambda: self.copy_item(self._menu_index))
        self.menu.add_separator()
        self.menu.add_command(label="↑ 上移", command=lambda: self.move_item(self._menu_index, -1))
        self.menu.add_command(label="↓ 下移", command=lambda: self.move_item(self._menu_index, 1))
        self.menu.add_separator()
        self.menu.add_command(label="🗑 从列表移除", command=lambda: self.remove_item(self._menu_index))

        bottom = ttk.Frame(self.root, padding=(8, 4, 8, 8))
        bottom.pack(fill="x", side="bottom")
        ttk.Label(bottom, text="回放次数：").pack(side="left")
        self.mode_box = ttk.Combobox(bottom, textvariable=self.count_mode, width=12,
                                     values=("自定义次数", "无限循环"), state="readonly")
        self.mode_box.pack(side="left")
        self.mode_box.bind("<<ComboboxSelected>>", lambda e: self._save_config())
        spin = ttk.Spinbox(bottom, from_=1, to=9999, width=5, textvariable=self.play_count)
        spin.pack(side="left", padx=6)
        ttk.Label(bottom, text="次").pack(side="left")
        self.status_text = tk.StringVar(
            value="就绪 — 先把光标点进目标输入框，再按 F10")
        ttk.Label(bottom, textvariable=self.status_text,
                  foreground="#666666").pack(side="left", padx=16)
        ttk.Button(bottom, text="创建鼠标宏(F9)", style="Blue.TButton",
                   command=self.on_new_script).pack(side="right")
        self.run_btn = ttk.Button(bottom, text="运行鼠标宏(F10)", style="Blue.TButton",
                                  command=self.on_run)
        self.run_btn.pack(side="right", padx=(0, 10))

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

    # ---------- 列表 ----------
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            self.tree.insert("", "end", iid=str(i), values=(
                "☑" if it["checked"] else "☐",
                it["name"], it["path"], "⚙   🗑   📂   📄"),
                tags=(it["color"],))

    def _on_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if col == "#1":                       # 勾选框
            idx = int(row)
            self.items[idx]["checked"] = not self.items[idx]["checked"]
            self._refresh_tree()
            self._save_config()
        elif col == "#4":                     # 操作列 → 弹菜单
            self._show_menu(int(row), event)

    def _on_double_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.copy_item(int(row))

    def _on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self._show_menu(int(row), event)

    def _show_menu(self, index, event):
        self._menu_index = index
        self.menu.tk_popup(event.x_root, event.y_root)

    # ---------- 动作 ----------
    def on_import(self):
        paths = filedialog.askopenfilenames(
            title="选择脚本文件（可多选）",
            filetypes=[("脚本文件", "*.txt *.qfwjb"), ("所有文件", "*.*")])
        if not paths:
            return
        existing = {it["path"] for it in self.items}
        for p in paths:
            p = os.path.normpath(p)
            if p not in existing:
                self.items.append({"path": p,
                                   "name": os.path.splitext(os.path.basename(p))[0],
                                   "color": "black", "checked": True})
        self._refresh_tree()
        self._save_config()

    def on_clear(self):
        if self.items and messagebox.askyesno(APP_TITLE, "确定清空脚本列表？（不删除文件）"):
            self.items.clear()
            self._refresh_tree()
            self._save_config()

    def remove_item(self, index):
        if 0 <= index < len(self.items):
            self.items.pop(index)
            self._refresh_tree()
            self._save_config()

    def move_item(self, index, delta):
        j = index + delta
        if 0 <= index < len(self.items) and 0 <= j < len(self.items):
            self.items[index], self.items[j] = self.items[j], self.items[index]
            self._refresh_tree()
            self._save_config()

    def set_color(self, index, key):
        if 0 <= index < len(self.items):
            self.items[index]["color"] = key
            self._refresh_tree()
            self._save_config()

    def edit_script(self, index):
        if 0 <= index < len(self.items):
            os.startfile(self.items[index]["path"])

    def open_folder(self, index):
        if 0 <= index < len(self.items):
            os.startfile(os.path.dirname(self.items[index]["path"]))

    def copy_item(self, index):
        """双击/右键复制：把该脚本"输入"的内容放进剪贴板。"""
        if not (0 <= index < len(self.items)):
            return
        it = self.items[index]
        raw = scriptfmt.read_text(it["path"])
        actions, _ = scriptfmt.parse(raw)
        text = scriptfmt.extract_copy_text(actions, raw)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status(f"已复制「{it['name']}」的内容到剪贴板（{len(text)} 字）— 去 Ctrl+V 粘贴")

    def on_new_script(self):
        os.makedirs(SCRIPTS_DIR, exist_ok=True)
        path = os.path.join(SCRIPTS_DIR, f"新脚本-{time.strftime('%Y%m%d%H%M%S')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(COL_TPL.format(name=os.path.basename(path)))
        os.startfile(path)   # 默认文本编辑器打开
        self._set_status("已新建脚本模板并打开编辑器，改完保存后点「导入」")

    # ---------- 运行 ----------
    def on_run(self):
        if self.running:
            return
        checked = [it for it in self.items if it["checked"]]
        if not checked:
            messagebox.showinfo(APP_TITLE, "请先勾选要运行的脚本")
            return
        if self.count_mode.get() == "无限循环":
            count = None
        else:
            try:
                count = max(1, int(self.play_count.get()))
            except ValueError:
                messagebox.showwarning(APP_TITLE, "回放次数请填数字")
                return

        scripts = []
        for it in checked:
            raw = scriptfmt.read_text(it["path"])
            actions, errors = scriptfmt.parse(raw)
            scripts.append((it["name"], actions, errors))

        self.stop_flag.clear()
        self.running = True
        self.run_btn.state(["disabled"])
        threading.Thread(target=self._worker, args=(scripts, count), daemon=True).start()

    def _worker(self, scripts, count):
        stop = self.stop_flag
        self.events.put(("status", "运行中… 按 F11 可随时停止"))
        total = 0
        try:
            round_no = 0
            while True:
                round_no += 1
                for name, actions, errors in scripts:
                    if stop.is_set():
                        return
                    for act in actions:
                        if stop.is_set():
                            return
                        self._exec(act, stop)
                    if errors:
                        self.events.put(("status", f"「{name}」有 {len(errors)} 行未识别被跳过"))
                    total += 1
                self.events.put(("status", f"已完成第 {round_no} 轮（共处理 {total} 个脚本）"))
                if count is None:
                    time.sleep(0.3)
                    continue
                if round_no >= count:
                    break
        finally:
            self.events.put(("done", "已停止" if stop.is_set() else "运行完成"))

    def _exec(self, act, stop):
        kind = act[0]
        if kind == "move":
            sim.move_to(act[1], act[2])
        elif kind == "click":
            for _ in range(act[2]):
                if stop.is_set():
                    return
                sim.click(act[1])
        elif kind == "down":
            sim.mouse_down(act[1])
        elif kind == "up":
            sim.mouse_up(act[1])
        elif kind == "key":
            (sim.key_down if act[2] == "down" else sim.key_up)(act[1])
        elif kind == "wait":
            end = time.time() + act[1] / 1000.0
            while time.time() < end and not stop.is_set():
                time.sleep(0.02)
        elif kind == "type":
            sim.type_text(act[1])

    def on_stop(self):
        if self.running:
            self.stop_flag.set()
            self._set_status("正在停止…")

    # ---------- 配置 ----------
    def _load_config(self):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            self.items = cfg.get("items", [])
            self.count_mode.set(cfg.get("count_mode", "自定义次数"))
            self.play_count.set(str(cfg.get("play_count", 1)))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def _save_config(self):
        cfg = {"items": self.items,
               "count_mode": self.count_mode.get(),
               "play_count": self.play_count.get()}
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------- 事件循环 ----------
    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "hotkey":
                    if payload == "f9":
                        self.on_new_script()
                    elif payload == "f10":
                        self.on_run()
                    elif payload == "f11":
                        self.on_stop()
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "done":
                    self.running = False
                    self.run_btn.state(["!disabled"])
                    self._set_status(payload + " — 就绪")
        except queue.Empty:
            pass
        self.root.after(80, self._poll_events)

    def _set_status(self, text):
        self.status_text.set(text)

    def _on_close(self):
        self._save_config()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
