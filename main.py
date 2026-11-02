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
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import scriptfmt
import sim
import license_client
import editor

APP_TITLE = "鼠标脚本工具"
# 水印：标题栏与激活窗口统一带作者标识
APP_TITLE_LABELED = "鼠标脚本工具 by 西塔 | ptyo7o2"
ABOUT_TEXT = "鼠标脚本工具 v2.3\n\n作者：西塔\n联系方式：ptyo7o2\n\n热键：F9 编辑脚本 | F10 运行/停止\n快速连按 3 次 Esc 强制退出软件"

# 程序目录：打包成 exe 后取 exe 所在目录，脚本状态下取 py 文件目录
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SCRIPTS_DIR = os.path.join(BASE_DIR, "脚本")

COLOR_KEYS = ("black", "red", "green", "blue")
COLOR_FG = {"black": "#333333", "red": "#E53935", "green": "#0B8A3C", "blue": "#1565C0"}
COLOR_NAMES = {"black": "默认黑", "red": "红色", "green": "绿色", "blue": "蓝色"}


def _topmost_off(w):
    """取消窗口置顶（窗口可能已关闭，静默忽略）。"""
    try:
        if w.winfo_exists():
            w.attributes("-topmost", False)
    except tk.TclError:
        pass





class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE_LABELED)
        root.geometry("860x520")
        root.minsize(720, 420)

        self.items = []          # 每项: dict(path, name, color, checked)
        self.events = queue.Queue()
        self.stop_flag = threading.Event()
        self.running = False
        self.play_count = tk.StringVar(value="1")
        self.count_mode = tk.StringVar(value="自定义次数")
        self.icon_name = None       # 用户自定义图标文件名（appicon.ico/png）
        self._icon_img = None       # PhotoImage 引用防垃圾回收
        self._hud = None            # 运行中右下角提醒浮窗
        self.hud_round = None       # 浮窗上的轮次文字

        self._build_style()
        self._build_ui()
        self._load_config()
        self._apply_icon()
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
        style.configure("Treeview", font=("微软雅黑", 9), rowheight=32)
        style.configure("Treeview.Heading", font=("微软雅黑", 9, "bold"))
        self.root.option_add("*Font", ("微软雅黑", 9))

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        top.pack(fill="x")
        ttk.Button(top, text="📥 导入", style="Blue.TButton",
                   command=self.on_import).pack(side="left")
        ttk.Button(top, text="🖼 换图标",
                   command=self.on_change_icon).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="🗑 清空", command=self.on_clear).pack(side="right")

        columns = ("chk", "name", "path", "ops")
        top_master = ttk.Frame(self.root, padding=(8, 0))
        self.tree = ttk.Treeview(top_master, columns=columns, show="headings",
                                 selectmode="none")
        headings = [("chk", "选择", 58, "center"), ("name", "脚本名称", 220, "w"),
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
        self.menu.add_command(label="✏ 重命名", command=lambda: self.rename_item(self._menu_index))
        self.menu.add_command(label="📂 打开所在文件夹", command=lambda: self.open_folder(self._menu_index))
        self.menu.add_separator()
        self.menu.add_command(label="↑ 上移", command=lambda: self.move_item(self._menu_index, -1))
        self.menu.add_command(label="↓ 下移", command=lambda: self.move_item(self._menu_index, 1))
        self.menu.add_separator()
        self.menu.add_command(label="🗑 从列表移除", command=lambda: self.remove_item(self._menu_index))
        self.menu.add_separator()
        self.menu.add_command(label="关于", command=lambda: messagebox.showinfo(APP_TITLE_LABELED, ABOUT_TEXT))

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
        self.tree.bind("<Button-3>", self._on_right_click)

    # ---------- 列表 ----------
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, it in enumerate(self.items):
            self.tree.insert("", "end", iid=str(i), values=(
                "✅" if it["checked"] else "⬜",
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

    # ---------- 自定义图标 ----------
    def on_change_icon(self):
        """用户自己选择 .ico/.png 图标文件，复制到程序目录并立即生效。"""
        p = filedialog.askopenfilename(
            parent=self.root, title="选择图标文件（.ico 或 .png）",
            filetypes=[("图标文件", "*.ico *.png"), ("所有文件", "*.*")])
        if not p:
            return
        ext = os.path.splitext(p)[1].lower()
        if ext not in (".ico", ".png"):
            messagebox.showwarning(APP_TITLE, "请选择 .ico 或 .png 格式的图标文件")
            return
        target = os.path.join(BASE_DIR, "appicon" + ext)
        try:
            shutil.copyfile(p, target)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"保存图标失败：{e}")
            return
        other = "appicon.ico" if ext == ".png" else "appicon.png"
        try:
            os.remove(os.path.join(BASE_DIR, other))
        except OSError:
            pass
        self.icon_name = "appicon" + ext
        self._apply_icon()
        self._save_config()
        self._set_status("图标已更换。想恢复默认：删除程序目录下的 appicon 文件后重启软件")

    def _all_toplevels(self):
        """主窗口 + 所有已打开的 Toplevel（编辑器、弹框等）。"""
        wins = [self.root]

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Toplevel):
                    wins.append(c)
                walk(c)
        walk(self.root)
        return wins

    def _apply_icon(self):
        """把用户自定义图标应用到全部窗口（ico 用 iconbitmap，png 用 iconphoto）。"""
        if not self.icon_name:
            return
        path = os.path.join(BASE_DIR, self.icon_name)
        if not os.path.exists(path):
            return
        try:
            if self.icon_name.lower().endswith(".ico"):
                for w in self._all_toplevels():
                    try:
                        w.iconbitmap(path)
                    except tk.TclError:
                        pass
            else:
                img = tk.PhotoImage(file=path)
                self._icon_img = img       # 防垃圾回收
                for w in self._all_toplevels():
                    try:
                        w.iconphoto(False, img)
                    except tk.TclError:
                        pass
        except tk.TclError:
            pass

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
        """右键「编辑脚本」：优先用脚本编辑窗口打开（编辑保存直接覆盖原文件）。"""
        if not (0 <= index < len(self.items)):
            return
        ed = editor.ScriptEditor(self.root, on_saved=self._on_editor_saved,
                                 source_path=self.items[index]["path"],
                                 scripts_dir=SCRIPTS_DIR)
        self._apply_icon()   # 编辑器是新建 Toplevel，补设自定义图标

    def rename_item(self, index):
        """重命名：列表显示与磁盘文件一起改。"""
        if not (0 <= index < len(self.items)):
            return
        it = self.items[index]
        new = simpledialog.askstring("重命名", "新的脚本名称：",
                                     initialvalue=it["name"], parent=self.root)
        if not new or not new.strip():
            return
        new_name = "".join(c for c in new.strip() if c not in '\\/:*?"<>|')
        ext = os.path.splitext(it["path"])[1] or ".txt"
        new_path = os.path.join(os.path.dirname(it["path"]), new_name + ext)
        if new_path == it["path"]:
            return
        if os.path.exists(new_path):
            messagebox.showwarning("重命名", "同名脚本已存在，请换一个名字")
            return
        try:
            os.rename(it["path"], new_path)
        except OSError as e:
            messagebox.showerror("重命名", f"重命名失败：{e}")
            return
        it["path"] = new_path
        it["name"] = new_name
        self._refresh_tree()
        self._save_config()
        self._set_status(f"已重命名为「{new_name}」")

    def open_folder(self, index):
        if 0 <= index < len(self.items):
            os.startfile(os.path.dirname(self.items[index]["path"]))

    def on_new_script(self):
        """F9 /「创建鼠标宏」：打开脚本编辑窗口（点添加、弹框填参数做脚本）。"""
        ed = editor.ScriptEditor(self.root, on_saved=self._on_editor_saved,
                                 scripts_dir=SCRIPTS_DIR)
        self._apply_icon()   # 编辑器是新建 Toplevel，补设自定义图标

    def _on_editor_saved(self, path):
        """编辑器保存后刷新主界面列表：已有则更新名称，否则新增。"""
        path = os.path.normpath(path)
        for it in self.items:
            if it["path"] == path:
                it["name"] = os.path.splitext(os.path.basename(path))[0]
                break
        else:
            self.items.append({"path": path,
                               "name": os.path.splitext(os.path.basename(path))[0],
                               "color": "black", "checked": True})
        self._refresh_tree()
        self._save_config()

    # ---------- 运行 ----------
    def on_run(self):
        try:
            self._on_run_inner()
        except Exception as e:      # 兜底：任何异常都可见，绝不静默"没反应"
            self._flash_main()
            self._set_status(f"运行出错：{e}")
            try:
                messagebox.showerror(APP_TITLE, f"运行出错：{e}", parent=self.root)
            except tk.TclError:
                pass

    def _on_run_inner(self):
        if self.running:
            self._flash_main()
            self._set_status("已在运行中 — 再按一次 F10 停止")
            return
        checked = [it for it in self.items if it["checked"]]
        if not checked:
            # 先把主界面弹到最前再提示，否则在别的窗口按 F10 时
            # 提示会被压在后台，看起来像"没反应"
            self._flash_main()
            self._set_status("未运行：请先勾选脚本前的 ✅")
            messagebox.showinfo(APP_TITLE, "请先勾选要运行的脚本", parent=self.root)
            return
        if self.count_mode.get() == "无限循环":
            count = None
        else:
            try:
                count = max(1, int(self.play_count.get()))
            except ValueError:
                self._flash_main()
                self._set_status("未运行：回放次数请填数字")
                messagebox.showwarning(APP_TITLE, "回放次数请填数字", parent=self.root)
                return

        scripts = []
        for it in checked:
            raw = scriptfmt.read_text(it["path"])
            actions, errors = scriptfmt.parse(raw)
            scripts.append((it["name"], actions, errors))

        self.stop_flag.clear()
        self.running = True
        self.run_btn.configure(text="⏹ 停止(F10)")
        self._set_status(f"开始运行：{len(checked)} 个脚本…")
        try:
            self._create_hud()      # 浮窗只是提醒，失败不影响运行
        except Exception:
            self._hud = None
        threading.Thread(target=self._worker, args=(scripts, count), daemon=True).start()

    # ---------- 运行浮窗与完成提醒 ----------
    def _create_hud(self):
        """运行中在屏幕右下角显示置顶小浮窗，提醒停止方式。"""
        self._destroy_hud()
        hud = tk.Toplevel(self.root)
        hud.overrideredirect(True)
        hud.attributes("-topmost", True)
        hud.configure(bg="#1F2937")
        tk.Label(hud, text="● 运行中", font=("微软雅黑", 11, "bold"),
                 fg="#4ADE80", bg="#1F2937").pack(padx=18, pady=(10, 2))
        self.hud_round = tk.StringVar(value="即将开始…")
        tk.Label(hud, textvariable=self.hud_round, font=("微软雅黑", 9),
                 fg="#E5E7EB", bg="#1F2937").pack(padx=18)
        tk.Label(hud, text="F10 = 停止   |   连按3次 Esc = 强制退出",
                 font=("微软雅黑", 9), fg="#FBBF24", bg="#1F2937").pack(padx=18, pady=(4, 10))
        hud.update_idletasks()
        w, h = hud.winfo_reqwidth(), hud.winfo_reqheight()
        sw, sh = hud.winfo_screenwidth(), hud.winfo_screenheight()
        hud.geometry(f"+{sw - w - 24}+{sh - h - 80}")
        self._hud = hud

    def _destroy_hud(self):
        hud = getattr(self, "_hud", None)
        if hud is not None:
            try:
                hud.destroy()
            except tk.TclError:
                pass
        self._hud = None

    def _flash_main(self):
        """主界面弹出并置顶约 2 秒，提醒运行结束/停止成功。"""
        r = self.root
        try:
            if r.state() == "iconic":
                r.deiconify()
            r.deiconify()
            r.lift()
            r.focus_force()
            r.attributes("-topmost", True)
            r.after(2000, lambda: _topmost_off(r))
        except tk.TclError:
            pass

    def _worker(self, scripts, count):
        stop = self.stop_flag
        self.events.put(("status", "运行中… 再按一次 F10 停止"))
        total = 0
        try:
            round_no = 0
            while True:
                round_no += 1
                for name, actions, errors in scripts:
                    if stop.is_set():
                        return
                    if not sim.exec_actions(actions, stop):
                        return
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

    def on_stop(self):
        if self.running:
            self.stop_flag.set()
            self._set_status("正在停止…")

    def _force_exit(self):
        """Esc 快速三连：强制退出整个软件，运行中的脚本一并终止。"""
        self.stop_flag.set()
        try:
            self.root.destroy()
        finally:
            os._exit(0)

    # ---------- 配置 ----------
    def _load_config(self):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            self.items = cfg.get("items", [])
            self.count_mode.set(cfg.get("count_mode", "自定义次数"))
            self.play_count.set(str(cfg.get("play_count", 1)))
            if cfg.get("icon"):
                self.icon_name = cfg["icon"]
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def _save_config(self):
        cfg = {"items": self.items,
               "count_mode": self.count_mode.get(),
               "play_count": self.play_count.get(),
               "icon": self.icon_name}
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
                        if self.running:
                            self.on_stop()
                        else:
                            self.on_run()
                    elif payload == "esc_exit":
                        self._force_exit()
                elif kind == "status":
                    self._set_status(payload)
                    hud = getattr(self, "_hud", None)
                    if hud is not None and hud.winfo_exists():
                        try:
                            self.hud_round.set(payload)
                        except tk.TclError:
                            pass
                elif kind == "done":
                    self.running = False
                    self._destroy_hud()
                    self.run_btn.state(["!disabled"])
                    self.run_btn.configure(text="运行鼠标宏(F10)")
                    self._flash_main()
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
    # DPI 感知：高缩放屏幕（125%/150%）下让遮罩真正全屏、坐标不虚拟化
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    root = tk.Tk()
    root.withdraw()
    if not license_client.gate(root, os.path.join(BASE_DIR, "license.json")):
        root.destroy()
        return
    root.deiconify()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
