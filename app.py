import os
import sys
import tkinter as tk
from fileinput import close
from tkinter import ttk, filedialog, messagebox

# 保证能导入同目录下的 screenshot_backend 模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from screenshot_backend import transform_pos, capture_region


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
            value=os.path.join("screenshots", "board.png")
        )
        self.var_size = tk.StringVar(value="区域尺寸：--")
        self.var_status = tk.StringVar(value="就绪")

        # 坐标变化时实时刷新尺寸提示
        for v in (self.var_x1, self.var_y1, self.var_x2, self.var_y2):
            v.trace_add("write", lambda *_: self._update_size())

        self._build_ui()
        self._update_size()
        self._center()

    def _build_ui(self):
        """界面构建"""

        # 主框架
        pad = dict(padx=6, pady=4)
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        # ============= 截图区域 ==============================================
        area = ttk.LabelFrame(main, text="截图区域（屏幕坐标）", padding=10)
        area.grid(row=0, column=0, sticky="ew")

        # 坐标填写区域
        ttk.Label(area, text="左上角  X1").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(area, textvariable=self.var_x1, width=9).grid(row=0, column=1, **pad)
        ttk.Label(area, text="Y1").grid(row=0, column=2, sticky="e", **pad)
        ttk.Entry(area, textvariable=self.var_y1, width=9).grid(row=0, column=3, **pad)

        ttk.Label(area, text="右下角  X2").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(area, textvariable=self.var_x2, width=9).grid(row=1, column=1, **pad)
        ttk.Label(area, text="Y2").grid(row=1, column=2, sticky="e", **pad)
        ttk.Entry(area, textvariable=self.var_y2, width=9).grid(row=1, column=3, **pad)

        # 右侧  "拾取区域" "全屏"
        btns = ttk.Frame(area)
        btns.grid(row=0, column=4, rowspan=2, padx=(12, 0))
        ttk.Button(btns, text="拾取区域", command=self._pick_region, width=10).grid(row=0, column=0, pady=2)
        ttk.Button(btns, text="全屏", command=self._fill_screen, width=10).grid(row=1, column=0, pady=2)

        # 字典格式坐标显示
        ttk.Label(
            area, textvariable=self.var_size, foreground="#555555"
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        # =================================================================

        # ============== 保存路径 ==========================================
        pathbox = ttk.LabelFrame(main, text="保存路径", padding=10)
        pathbox.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        pathbox.columnconfigure(0, weight=1)

        # 路径输入框
        ttk.Entry(pathbox, textvariable=self.var_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )

        # 浏览路径按钮
        ttk.Button(pathbox, text="浏览", command=self._browse, width=8).grid(row=0, column=1)
        # ==================================================================

        # --------------------- 操作按钮 -----------------------------------
        actions = ttk.Frame(main)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)

        ttk.Button(actions, text="截 图",command=self._on_capture).grid(
            row=0, column=0, sticky="ew",
        )
        ttk.Button(actions, text="清空日志",command=self._clear_log).grid(
            row=0, column=1, padx=(6, 0)
        )

        # ------------------------------------------------------------------

        # ------------- 日志 ------------------------------------------------
        logbox = ttk.LabelFrame(main, text="日志", padding=6)
        logbox.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        logbox.columnconfigure(0, weight=1)

        # 文本框
        self.txt_log = tk.Text(
            logbox, height=7, width=54, state="disabled", wrap="word"
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")

        # 滚动条
        sb = ttk.Scrollbar(logbox, orient="vertical",command=self.txt_log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb.set)

        # 状态标签
        ttk.Label(
            main, textvariable=self.var_status, foreground="#0a7a4a"
        ).grid(row=4, column=0, sticky="w", pady=(8, 0))

    # ========== 内部工具 ==================
    def _center(self):
        """把主窗口摆到屏幕水平居中、垂直偏上（上方留 1/3）的位置。"""
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{max((sh - h) // 3, 0)}")

    # ================ 日志状态更新 ================
    def _log(self, msg: str):
        """向只读日志框追加一行文本。

            Text 处于 disabled 状态时程序也无法写入，因此这里先临时切到
            normal 写入，再切回 disabled 保持只读。

            参数：
                msg: 要追加的日志内容，无需自带换行（函数会自动补 "\\n"）

            返回：
                无
        """
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        """清空只读日志框的全部内容。"""
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    # -----------区域尺寸标签--------------
    def _read_coords(self):
        """读取并校验四个坐标输入框。

        从 var_x1/var_y1/var_x2/var_y2 取值，去掉首尾空格后转成整数。
        允许输入小数，会朝零截断（如 "3.9" -> 3）。

        返回:
            tuple[int, int, int, int]: (x1, y1, x2, y2)

        异常:
            ValueError: 任一输入为空或不是数字时抛出。
        """
        return (
            int(float(self.var_x1.get().strip())),
            int(float(self.var_y1.get().strip())),
            int(float(self.var_x2.get().strip())),
            int(float(self.var_y2.get().strip())),
        )

    def _update_size(self):
        """实时显示 region 的宽高（复用后端的 transform_pos）"""
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

    # ---------------------------------------------------------

    # ============== 事件处理 ===========================
    def _browse(self):
        """打开系统“另存为”对话框，让用户选择保存路径。

            对话框的初始目录/文件名优先取自 var_path 当前值：
                - 非空：拆成 dirname + basename 作为 initialdir / initialfile
                - 为空：回退到脚本所在目录 _HERE + "screenshot.png"

            用户确认后把选中的路径写回 var_path；取消则不做任何改动。
            注意：本方法只负责“选路径”，不负责真正创建或保存文件。

            :return: None
        """
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
        """将截图区域设为全屏范围。

            把 var_x1/var_y1 置为 "0"，var_x2/var_y2 置为屏幕分辨率，
            从而让区域覆盖整块主屏。设置后由 trace_add 触发 _update_size
            自动刷新尺寸提示。

            :return: None
        """
        self.var_x1.set("0")
        self.var_y1.set("0")
        self.var_x2.set(str(self.root.winfo_screenwidth()))
        self.var_y2.set(str(self.root.winfo_screenheight()))

    def _on_capture(self):
        """处理截图按钮的点击事件。

            依次完成：读取并校验坐标输入、校验保存路径、更新状态提示、
            调用 capture_region 执行截图并保存，最后根据结果显示成功或失败信息。
            任一环节出错都会通过 messagebox 弹窗提示并提前返回，同时把结果写入日志。

            :return: None
        """
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

        self.var_status.set("正在截图...")
        self.root.update_idletasks()

        # 2) 调用后端
        try:
            saved = capture_region(x1, y1, x2, y2, path)
        except Exception as exc:
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
        """ 进入“拾取区域”模式。

            先隐藏主窗口，延迟 200ms 再创建全屏遮罩：

            - withdraw() 是异步的，窗口真正从屏幕消失需要一点时间；
            - 若立刻创建遮罩，可能把还没消失的主窗口一起截进去；
            - after 不阻塞主线程，200ms 内事件循环正常处理窗口隐藏。
        """
        self.root.withdraw()
        self.root.after(200, self._create_overlay)


    def _create_overlay(self):
        sw=self.root.winfo_screenwidth()
        sh=self.root.winfo_screenheight()

        ov=tk.Toplevel(self.root)
        ov.overrideredirect(True)#去掉标题栏和边框
        ov.geometry(f"{sw}x{sh}+0+0")#铺满屏幕
        ov.attributes("-topmost", True)# 置顶
        try:
            ov.attributes("-alpha",0.30)#不透明度30%
        except tk.TclError:
            pass
        ov.configure(bg="black")#黑色蒙版

        canvas = tk.Canvas(ov, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        state = {"sx": 0, "sy": 0, "rect": None, "done": False}

        def to_canvas(xr,yr):
            """
                把屏幕坐标 (xr, yr) 转成 canvas 内部坐标。

                - canvas 有自己的坐标系，原点在画布左上角；
                - winfo_rootx/y 给出画布左上角在屏幕上的位置，
                两者相减即得画布内部坐标。

                :param xr: 屏幕坐标的 x（相对屏幕左上角）
                :param yr: 屏幕坐标的 y（相对屏幕左上角）
                :return: canvas 内部坐标 (x, y)
            """
            return xr-canvas.winfo_rootx(), yr-canvas.winfo_rooty()

        def on_press(e):
            """鼠标按下：记录起点，并在画布上创建 0 大小的初始矩形。

            - 起点用 e.x_root/e.y_root（屏幕坐标），供最终算区域用；
            - 画图需画布坐标，故用 to_canvas 转换；
            - 矩形初始四角重合，拖动时由 on_drag 更新右下角。
            """
            state["sx"], state["sy"] = e.x_root, e.y_root  # 起点（屏幕坐标）
            cx, cy = to_canvas(e.x_root, e.y_root)  # 转画布坐标
            state["rect"] = canvas.create_rectangle(
                cx, cy, cx, cy, outline="#ff3b30", width=2  # 0 大小，待拖动放大
            )

        def on_drag(e: tk.Event):
            """鼠标拖动回调：把选框矩形更新为“起点 → 当前鼠标位置”。

            左上角固定在按下时的起点 (sx, sy)，右下角跟随鼠标实时移动，
            从而拖出可缩放的选择框。

            :param e: 鼠标拖动事件，提供 e.x_root / e.y_root（屏幕坐标）
            """
            if state["rect"] is None:
                return
            cx, cy = to_canvas(state["sx"], state["sy"])
            ex, ey = to_canvas(e.x_root, e.y_root)
            canvas.coords(state["rect"], cx, cy, ex, ey)#更新矩形

        def on_release(e: tk.Event):
            """鼠标松开回调：校验选区、写回坐标并关闭遮罩。"""
            if state["done"]:
                return
            state["done"] = True

            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root

            # 拖动范围过小 → 视为取消
            if abs(x2 - x1) < 2 or abs(y2 - y1) < 2:
                self._log("已取消区域拾取（拖动范围过小）。")
                close()
                return

            # 规范化坐标（支持任意方向拖拽）
            nx1, nx2 = min(x1, x2), max(x1, x2)
            ny1, ny2 = min(y1, y2), max(y1, y2)

            # 写回四个变量
            self.var_x1.set(str(nx1))
            self.var_y1.set(str(ny1))
            self.var_x2.set(str(nx2))
            self.var_y2.set(str(ny2))

            # 日志用规范化后的坐标，和实际区域一致
            self._log(f"已拾取区域：({nx1}, {ny1}) → ({nx2}, {ny2})")

            # 最后再关遮罩、恢复主窗口
            close()

        def close():
            """结束区域拾取：释放 grab、销毁遮罩、恢复并置顶主窗口。

            无论用户是正常选完区域，还是按 Esc / 拖动过小取消，最终都会调用它。
            收尾后主窗口重新显示、位于最前，并拿回键盘焦点。
            """
            # 若遮罩曾 grab_set 独占输入，这里必须释放；
            # 未设置过或已释放时会抛 TclError，忽略即可
            try:
                ov.grab_release()
            except tk.TclError:
                pass

            ov.destroy()  # 销毁遮罩，屏幕上的半透明层消失
            self.root.deiconify()  # 恢复此前 withdraw() 隐藏的主窗口
            self.root.lift()  # 提到同层窗口最前，避免被其他程序压住
            self.root.focus_force()  # 强制拿回键盘焦点，恢复后可直接操作

        # ---- 鼠标事件：按下 → 拖动 → 松开 ----
        canvas.bind("<ButtonPress-1>", on_press)  # 左键按下：记起点、创建初始矩形
        canvas.bind("<B1-Motion>", on_drag)  # 按住左键拖动：实时更新矩形四角
        canvas.bind("<ButtonRelease-1>", on_release)  # 左键松开：算区域、写回坐标、收尾

        # ---- 键盘取消：按 Esc 直接结束拾取 ----
        # lambda 用来丢弃事件参数 e，close() 本身不需要它
        ov.bind("<Escape>", lambda e: close())

        # ---- 抢焦点：确保键盘事件（Esc）能被接收到 ----
        # overrideredirect(True) 的无边框窗口默认拿不到焦点，
        # 单靠 focus_set 常不生效，故再用 focus_force 强制抢一次
        canvas.focus_set()  # 请求把焦点给 canvas
        ov.focus_force()  # 强制窗口拿到键盘焦点

def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    ScreenshotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
