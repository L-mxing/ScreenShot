# -*- coding: utf-8 -*-
"""
screenshot_gui.py
截图工具 GUI —— 直接调用同目录下的 screenshot_backend.capture_region
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 保证能导入同目录下的 screenshot_backend 模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from screenshot_backend import capture_region, transform_pos


class ScreenshotApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("截图工具")
        self.root.resizable(False, False)

        # ---------- 状态变量 ----------
        self.var_x1 = tk.StringVar(value="1200")
        self.var_y1 = tk.StringVar(value="878")
        self.var_x2 = tk.StringVar(value="1270")
        self.var_y2 = tk.StringVar(value="949")
        self.var_path = tk.StringVar(
            value=os.path.join("screenshots", "SC_04_start_btn.png")
        )
        self.var_size = tk.StringVar(value="区域尺寸：--")
        self.var_status = tk.StringVar(value="就绪")

        # 坐标变化时实时刷新尺寸提示
        for v in (self.var_x1, self.var_y1, self.var_x2, self.var_y2):
            v.trace_add("write", lambda *_: self._update_size())

        self._build_ui()
        self._update_size()
        self._center()

    # ================= 界面构建 =================
    def _build_ui(self):
        pad = dict(padx=6, pady=4)
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        # ---------- 截图区域 ----------
        area = ttk.LabelFrame(main, text="截图区域（屏幕坐标 / 像素）", padding=10)
        area.grid(row=0, column=0, sticky="ew")

        ttk.Label(area, text="左上角  X1").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(area, textvariable=self.var_x1, width=9).grid(row=0, column=1, **pad)
        ttk.Label(area, text="Y1").grid(row=0, column=2, sticky="e", **pad)
        ttk.Entry(area, textvariable=self.var_y1, width=9).grid(row=0, column=3, **pad)

        ttk.Label(area, text="右下角  X2").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(area, textvariable=self.var_x2, width=9).grid(row=1, column=1, **pad)
        ttk.Label(area, text="Y2").grid(row=1, column=2, sticky="e", **pad)
        ttk.Entry(area, textvariable=self.var_y2, width=9).grid(row=1, column=3, **pad)

        btns = ttk.Frame(area)
        btns.grid(row=0, column=4, rowspan=2, padx=(12, 0))
        ttk.Button(btns, text="拾取区域", command=self._pick_region, width=10).grid(
            row=0, column=0, pady=2
        )
        ttk.Button(btns, text="全屏", command=self._fill_screen, width=10).grid(
            row=1, column=0, pady=2
        )

        ttk.Label(
            area, textvariable=self.var_size, foreground="#555555"
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        # ---------- 保存路径 ----------
        pathbox = ttk.LabelFrame(main, text="保存路径", padding=10)
        pathbox.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        pathbox.columnconfigure(0, weight=1)

        ttk.Entry(pathbox, textvariable=self.var_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(pathbox, text="浏览…", command=self._browse, width=8).grid(
            row=0, column=1
        )

        # ---------- 操作按钮 ----------
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)

        ttk.Button(actions, text="截  图", command=self._on_capture).grid(
            row=0, column=0, sticky="ew", ipady=4
        )
        ttk.Button(actions, text="清空日志", command=self._clear_log).grid(
            row=0, column=1, padx=(6, 0)
        )

        # ---------- 日志 ----------
        logbox = ttk.LabelFrame(main, text="日志", padding=6)
        logbox.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        logbox.columnconfigure(0, weight=1)

        self.txt_log = tk.Text(
            logbox, height=7, width=54, state="disabled", wrap="word"
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(logbox, orient="vertical", command=self.txt_log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb.set)

        ttk.Label(
            main, textvariable=self.var_status, foreground="#0a7a4a"
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

    # ================= 内部工具 =================
    def _center(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{max((sh - h) // 3, 0)}")

    def _log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _read_coords(self):
        """读取并校验坐标，返回 (x1, y1, x2, y2)；失败抛 ValueError。"""
        return (
            int(float(self.var_x1.get().strip())),
            int(float(self.var_y1.get().strip())),
            int(float(self.var_x2.get().strip())),
            int(float(self.var_y2.get().strip())),
        )

    def _update_size(self):
        """实时显示 region 的宽高（复用后端的 transform_pos）。"""
        try:
            x1, y1, x2, y2 = self._read_coords()
        except ValueError:
            self.var_size.set("区域尺寸：-- （坐标需为数字）")
            return

        region = transform_pos(x1, y1, x2, y2)
        self.var_size.set(
            f"区域尺寸：{region['width']} × {region['height']} px"
            f"　(left={region['left']}, top={region['top']})"
        )

    # ================= 事件处理 =================
    def _browse(self):
        current = self.var_path.get().strip()
        if current:
            init_dir = os.path.dirname(os.path.abspath(current))
            init_file = os.path.basename(current)
        else:
            init_dir, init_file = _HERE, "screenshot.png"

        path = filedialog.asksaveasfilename(
            title="选择保存位置",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
            initialdir=init_dir,
            initialfile=init_file,
        )
        if path:
            self.var_path.set(path)

    def _fill_screen(self):
        self.var_x1.set("0")
        self.var_y1.set("0")
        self.var_x2.set(str(self.root.winfo_screenwidth()))
        self.var_y2.set(str(self.root.winfo_screenheight()))

    def _on_capture(self):
        # 1) 参数校验
        try:
            x1, y1, x2, y2 = self._read_coords()
        except ValueError:
            messagebox.showerror("参数错误", "坐标必须是数字。")
            return

        path = self.var_path.get().strip()
        if not path:
            messagebox.showerror("参数错误", "请填写保存路径。")
            return

        # 2) 调用后端
        self.var_status.set("正在截图…")
        self.root.update_idletasks()

        try:
            saved = capture_region(x1, y1, x2, y2, path)
        except Exception as exc:                      # noqa: BLE001
            self.var_status.set("截图失败")
            self._log(f"✗ 截图失败：{exc}")
            messagebox.showerror("截图失败", str(exc))
            return

        # 3) 成功反馈
        region = transform_pos(x1, y1, x2, y2)
        self.var_status.set(f"完成　{region['width']}×{region['height']} px")
        self._log(f"✓ 已保存：{saved}")

    # ---------- 屏幕拖拽拾取区域 ----------
    def _pick_region(self):
        self.root.withdraw()
        self.root.after(200, self._create_overlay)

    def _create_overlay(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.geometry(f"{sw}x{sh}+0+0")
        ov.attributes("-topmost", True)
        try:
            ov.attributes("-alpha", 0.30)
        except tk.TclError:
            pass
        ov.configure(bg="black")

        canvas = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        state = {"sx": 0, "sy": 0, "rect": None, "done": False}

        def to_canvas(xr, yr):
            return xr - canvas.winfo_rootx(), yr - canvas.winfo_rooty()

        def on_press(e):
            state["sx"], state["sy"] = e.x_root, e.y_root
            cx, cy = to_canvas(e.x_root, e.y_root)
            state["rect"] = canvas.create_rectangle(
                cx, cy, cx, cy, outline="#ff3b30", width=2
            )

        def on_drag(e):
            if state["rect"] is None:
                return
            cx, cy = to_canvas(state["sx"], state["sy"])
            ex, ey = to_canvas(e.x_root, e.y_root)
            canvas.coords(state["rect"], cx, cy, ex, ey)

        def on_release(e):
            if state["done"]:
                return
            state["done"] = True

            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root
            close()

            if abs(x2 - x1) < 2 or abs(y2 - y1) < 2:
                self._log("已取消区域拾取（拖动范围过小）。")
                return

            self.var_x1.set(str(min(x1, x2)))
            self.var_y1.set(str(min(y1, y2)))
            self.var_x2.set(str(max(x1, x2)))
            self.var_y2.set(str(max(y1, y2)))
            self._log(f"已拾取区域：({x1}, {y1}) → ({x2}, {y2})")

        def close():
            try:
                ov.grab_release()
            except tk.TclError:
                pass
            ov.destroy()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        ov.bind("<Escape>", lambda e: close())

        canvas.focus_set()
        ov.focus_force()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")      # Windows 下更美观；其他平台自动回退
    except tk.TclError:
        pass
    ScreenshotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()