# -*- coding: utf-8 -*-
"""卡密验证客户端。

服务端：cardserver（HTTP + HMAC-SHA256 签名，响应带 X-Sig 头）。
流程：
  1. 本地有已激活缓存 → 联网 /api/check 校验，更新到期时间
  2. 服务端不可达 → 缓存未过期时允许短时离线使用
  3. 无缓存或校验不过 → 弹出激活窗口，调 /api/verify 首次激活（绑定机器码）
机器码：Windows 注册表 MachineGuid。
"""

import hashlib
import hmac
import json
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
import urllib.error
import urllib.request

try:
    import winreg
except ImportError:  # 非 Windows 环境（开发用）
    winreg = None

SERVER = "http://82.157.64.196:8848"
# 客户端校验响应签名用，必须与服务端 config.json 的 hmac_secret 一致
SECRET = "fcd83908ed4547412b6089f9044bef931de3cfe64fa170111bcec7c92accb8f4"


def machine_id():
    """Windows 取注册表 MachineGuid；失败时回退主机名+用户目录哈希。"""
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography") as k:
                guid, _ = winreg.QueryValueEx(k, "MachineGuid")
            return "win-" + guid.replace("-", "")
        except OSError:
            pass
    raw = os.environ.get("COMPUTERNAME", "unknown") + os.path.expanduser("~")
    return "h-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _post(path, payload):
    """POST JSON 并校验 X-Sig 签名，返回 dict。签名不符抛 RuntimeError。"""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(SERVER + path, data=body,
                                 headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=10)
    raw = resp.read()
    calc = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, resp.headers.get("X-Sig", "")):
        raise RuntimeError("服务器签名校验失败")
    return json.loads(raw)


def _server_error(exc):
    """从 HTTPError 中提取服务端 error 文案，取不到返回 None。"""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            return json.loads(exc.read()).get("error")
        except Exception:
            return None
    return None


class License:
    """许可证缓存与校验。"""

    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.mid = machine_id()
        self.offline = False
        self.key = None

    def _load(self):
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("machine_id") == self.mid and cache.get("key"):
                return cache
        except (OSError, ValueError):
            pass
        return None

    def _save(self, key, expire_at):
        self.key = key
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump({"key": key, "machine_id": self.mid,
                       "expire_at": expire_at}, f, ensure_ascii=False)

    def check_cached(self):
        """有缓存时联网复检。返回 (ok, reason)：
        ok=True 已放行；ok=False 需要重新激活。"""
        cache = self._load()
        if not cache:
            return False, "未激活"
        key = cache["key"]
        try:
            result = _post("/api/check", {"key": key, "machine_id": self.mid})
        except RuntimeError as e:      # 签名不符等：严格拒绝，不走离线
            return False, str(e)
        except urllib.error.HTTPError as e:
            server_msg = _server_error(e)
            return False, server_msg or "卡密校验未通过"
        except (urllib.error.URLError, OSError):
            # 离线容错：服务端不可达且缓存未过期 → 放行
            if cache.get("expire_at", 0) > time.time():
                self.offline = True
                self.key = key
                return True, "离线模式"
            return False, "无法连接验证服务器"
        if result.get("ok"):
            expire_at = int(result.get("expire_at") or cache.get("expire_at", 0))
            if expire_at > time.time():
                self._save(key, expire_at)
                return True, "已激活"
            return False, "卡密已过期"
        return False, result.get("error") or "卡密校验未通过"

    def activate(self, key):
        """首次激活。返回 (ok, message)。"""
        key = key.strip()
        if not key:
            return False, "请输入卡密"
        try:
            result = _post("/api/verify", {"key": key, "machine_id": self.mid})
        except urllib.error.HTTPError as e:
            return False, _server_error(e) or "激活失败，请稍后重试"
        except RuntimeError as e:
            return False, str(e)
        except (urllib.error.URLError, OSError):
            return False, "无法连接验证服务器，请检查网络后重试"
        if result.get("ok"):
            expire_at = int(result.get("expire_at") or time.time() + 86400)
            self._save(key, expire_at)
            return True, "激活成功"
        return False, result.get("error") or "卡密无效"


def gate(root, cache_path):
    """主程序启动前的验证门。返回 True 放行进入主界面。"""
    lic = License(cache_path)
    ok, reason = lic.check_cached()
    if ok:
        if lic.offline:
            messagebox.showinfo(
                "鼠标脚本工具", "当前处于离线模式（验证服务器暂时不可达），"
                "本次允许使用；下次联网时会自动恢复正常校验。")
        return True
    return _activate_dialog(root, lic)


def _activate_dialog(root, lic):
    """阻塞式激活窗口。激活成功返回 True。"""
    result = {"ok": False}

    dlg = tk.Toplevel(root)
    dlg.title("激活 - 鼠标脚本工具 by 西塔 | ptyo7o2")
    dlg.geometry("440x220")
    dlg.resizable(False, False)
    dlg.grab_set()

    tk.Label(dlg, text="本软件需要卡密激活使用",
             font=("微软雅黑", 11, "bold")).pack(pady=(18, 2))
    tk.Label(dlg, text="每张卡密绑定一台电脑，请输入收到的卡密：",
             font=("微软雅黑", 9)).pack()
    var = tk.StringVar()
    entry = ttk.Entry(dlg, textvariable=var, width=26,
                      font=("Consolas", 12), justify="center")
    entry.pack(pady=10)
    entry.focus_set()
    msg = tk.StringVar(value="")
    tk.Label(dlg, textvariable=msg, fg="#E53935",
             font=("微软雅黑", 9)).pack()

    def do_activate():
        btn.state(["disabled"])
        msg.set("正在验证，请稍候…")
        dlg.update()
        ok, message = lic.activate(var.get())
        if ok:
            result["ok"] = True
            dlg.destroy()
        else:
            msg.set(message)
            btn.state(["!disabled"])

    def on_close():
        dlg.destroy()

    btn_row = tk.Frame(dlg)
    btn_row.pack(pady=8)
    btn = ttk.Button(btn_row, text="激活", style="Blue.TButton", command=do_activate)
    btn.pack(side="left", padx=6)
    entry.bind("<Return>", lambda e: do_activate())
    ttk.Button(btn_row, text="取消", command=on_close).pack(side="left", padx=6)

    root.wait_window(dlg)
    return result["ok"]
