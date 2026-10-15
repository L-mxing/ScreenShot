# -*- coding: utf-8 -*-
"""截图工具（界面层）—— 启动方式：python text.py

这个文件只管界面：画控件、收输入、把结果写进日志区。
真正的活都在同目录的几个模块里 —— 改行为改那边，改外观改这里：

    screenshot_backend.py   截图本体：mss 抓帧 + 存成 PNG
    screenshot_core.py      纯逻辑：保存路径规则、文件名规则、坐标解析
    screenshot_utils.py     图像工具：读模板图、抓整屏帧

四种用法：
    1. 手填坐标 → 「截图」按钮
    2. 「全屏」按钮（或坐标留空）→ 截整个屏幕
    3. 「拾取区域」→ 在屏幕上拖一个矩形，坐标自动填回输入框
    4. 「模板匹配」→ 拿一张小图去屏幕上找它在哪，打印匹配分数（调试用）

⚠️ 窗口高度（geometry 里的 590）是照着实际内容量出来的。
   往里加控件前先确认总高还放得下，否则最底下的日志区和状态栏会被裁掉。
"""

import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import cv2

# 保证能导入同目录下的 screenshot_backend 模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from screenshot_backend import capture_region, transform_pos

# 复用同目录下的逻辑层与图像工具层：保存路径规则、模板读取、抓帧都在那边。
# 这里只做界面 —— 避免同一份代码在两处各养一个副本（改一处还得记得改另一处）。
import screenshot_core as core
import screenshot_utils as utils


class ScreenshotApp:
    """截图工具主窗口。

    界面从上到下分 6 行：截图区域 / 保存设置 / 操作按钮 / 模板匹配 / 日志 / 状态栏。
    窗口尺寸在 __init__ 里定死（不可缩放），所以每加一块控件都要回头确认还装得下。
    """

    def __init__(self, root: tk.Tk):
        """建根窗口 → 准备状态变量 → 搭界面 → 首次刷新尺寸提示 → 居中。

        顺序有讲究：先有状态变量，_build_ui() 里的 Entry 才绑得上；
        _update_size() 要排在 _build_ui() 之后，它依赖界面已经建好。
        """
        self.root = root
        self.root.title("截图工具")
        self.root.geometry("340x590")
        self.root.resizable(False, False)

        # ---------- 状态变量 ----------
        self.var_x1 = tk.StringVar(value="")
        self.var_y1 = tk.StringVar(value="")
        self.var_x2 = tk.StringVar(value="")
        self.var_y2 = tk.StringVar(value="")
        # 保存设置：目录和文件名分开填，截图时才拼成完整路径
        self.var_dir = tk.StringVar(value=os.path.join(_HERE, "screenshots"))
        # 记住「上一次自动生成的文件名」：用户手改过就不再自动覆盖他的输入
        self._auto_name = core.generate_default_filename()
        self.var_name = tk.StringVar(value=self._auto_name)
        self.var_size = tk.StringVar(value="区域尺寸：--")
        self.var_status = tk.StringVar(value="就绪")
        self.var_topmost = tk.BooleanVar(value=False)

        # 坐标变化时实时刷新尺寸提示
        for v in (self.var_x1, self.var_y1, self.var_x2, self.var_y2):
            v.trace_add("write", lambda *_: self._update_size())

        self._build_ui()
        self._update_size()
        self._center()

    # ================= 界面构建 =================
    def _build_ui(self):
        """搭出整窗界面（纵向 6 行，布局见类 docstring）。

        行号是手写的，往中间插新区块时要连带改掉后面所有区块的 row 值。
        """
        pad = dict(padx=6, pady=4)
        main_w = ttk.Frame(self.root, padding=12)
        main_w.grid(row=0, column=0)

        # ---------- 截图区域 ----------
        area = ttk.LabelFrame(main_w, text="截图区域（屏幕坐标 / 像素）", padding=10)
        area.grid(row=0, column=0, sticky="ew")

        # 坐标输入框统一校验：最多 4 位数字（0–9999），可清空
        coord_vcmd = (self.root.register(self._validate_coord), "%P")

        def coord_entry(var):
            """造一个坐标输入框：固定宽度、输入校验、绑好对应变量。"""
            return ttk.Entry(
                area, textvariable=var, width=5,
                validate="key", validatecommand=coord_vcmd,
            )

        # 四个框按「左上 X1 → Y1 → 右下 X2 → Y2」串成一条链，给方向键跳转用
        e_x1, e_y1 = coord_entry(self.var_x1), coord_entry(self.var_y1)
        e_x2, e_y2 = coord_entry(self.var_x2), coord_entry(self.var_y2)

        ttk.Label(area, text="左上角  X1").grid(row=0, column=0, sticky="w", **pad)
        e_x1.grid(row=0, column=1, **pad)
        ttk.Label(area, text="Y1").grid(row=0, column=2, sticky="e", **pad)
        e_y1.grid(row=0, column=3, **pad)

        ttk.Label(area, text="右下角  X2").grid(row=1, column=0, sticky="w", **pad)
        e_x2.grid(row=1, column=1, **pad)
        ttk.Label(area, text="Y2").grid(row=1, column=2, sticky="e", **pad)
        e_y2.grid(row=1, column=3, **pad)

        self._bind_coord_navigation((e_x1, e_y1, e_x2, e_y2))

        btns = ttk.Frame(area)
        btns.grid(row=0, column=4, rowspan=2, padx=(6, 0))
        ttk.Button(btns, text="拾取区域", command=self._pick_region, width=8).grid(
            row=0, column=0, pady=2
        )
        ttk.Button(btns, text="全屏", command=self._fill_screen, width=8).grid(
            row=1, column=0, pady=2
        )

        # ---------- 尺寸提示 ----------
        # 用「容器 + 关闭尺寸传播」把提示框住：
        # 容器宽度交给 grid 按列宽分配（sticky="ew"），自己不参与宽度计算，
        # 所以 var_size 文本再长，也只在容器内部被裁掉，
        # 不会往上撑宽列宽 → area → main_w，整体布局与窗口尺寸保持不动。
        size_wrap = ttk.Frame(area)
        size_wrap.grid(row=2, column=0, columnspan=5, sticky="ew", padx=6, pady=(8, 0))

        size_lbl = ttk.Label(
            size_wrap, textvariable=self.var_size, foreground="#555555", anchor="w"
        )
        size_lbl.pack(fill="both", expand=True)

        # 先量出单行文字需要的高度，再把容器高度钉死、关掉传播
        size_wrap.update_idletasks()
        size_wrap.configure(height=size_lbl.winfo_reqheight())
        size_wrap.pack_propagate(False)   # 容器内用的是 pack，必须关 pack 的传播

        # ---------- 保存设置 ----------
        # 目录和文件名各占一行：标签在左、控件在右，比上下堆叠省一半高度。
        # column 1 必须给 weight，Entry 才会跟着窗口横向拉伸。
        pathbox = ttk.LabelFrame(main_w, text="保存", padding=10)
        pathbox.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        pathbox.columnconfigure(1, weight=1)

        ttk.Label(pathbox, text="保存目录").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(pathbox, textvariable=self.var_dir).grid(
            row=0, column=1, sticky="ew", padx=6, pady=(0, 4)
        )
        ttk.Button(pathbox, text="选择目录", command=self._choose_dir, width=8).grid(
            row=0, column=2, pady=(0, 4)
        )

        ttk.Label(pathbox, text="文件名").grid(row=1, column=0, sticky="w")
        ttk.Entry(pathbox, textvariable=self.var_name).grid(
            row=1, column=1, sticky="ew", padx=6
        )
        ttk.Label(pathbox, text="默认 .png", foreground="#888888").grid(
            row=1, column=2, sticky="w"
        )

        # ---------- 操作按钮 ----------
        actions = ttk.Frame(main_w)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))


        ttk.Button(actions, text="截  图", command=self._on_capture, width=16).grid(
            row=0, column=0, sticky="w", ipady=4, padx=(10, 6)
        )
        ttk.Button(actions, text="打开目录", command=self._open_output_dir, width=9).grid(
            row=0, column=1, padx=3
        )
        ttk.Button(actions, text="清空日志", command=self._clear_log, width=9).grid(
            row=0, column=2, padx=3
        )

        # ---------- 模板匹配 ----------
        tplbox = ttk.LabelFrame(main_w, text="模板匹配", padding=10)
        tplbox.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tplbox.columnconfigure(0, weight=1)

        self.var_template = tk.StringVar(
            value=os.path.join(_HERE, "image", "game_ui_snapshots", "auto_disable.png")
        )
        ttk.Entry(tplbox, textvariable=self.var_template).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(tplbox, text="选择模板", command=self._choose_template, width=8).grid(
            row=0, column=1
        )
        ttk.Button(tplbox, text="查看匹配分数", command=self._check_match).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0)
        )

        # ---------- 日志 ----------
        logbox = ttk.LabelFrame(main_w, text="日志", padding=6)
        logbox.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        logbox.columnconfigure(0, weight=1)

        self.txt_log = tk.Text(
            logbox, height=7, width=38, state="disabled", wrap="word"
        )
        self.txt_log.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(logbox, orient="vertical", command=self.txt_log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb.set)

        # 状态栏和「窗口置顶」挤同一行 —— 底下的空间已经用满，没地方再开一行了
        status_row = ttk.Frame(main_w)
        status_row.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        status_row.columnconfigure(0, weight=1)

        ttk.Label(
            status_row, textvariable=self.var_status, foreground="#0a7a4a"
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            status_row, text="窗口置顶", variable=self.var_topmost,
            command=self._toggle_topmost,
        ).grid(row=0, column=1, sticky="e")

    # ================= 内部工具 =================
    def _center(self):
        """把窗口摆到屏幕偏上的位置：水平居中，垂直大约在上三分之一处。"""
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"+{(sw - w) // 2}+{max((sh - h) // 3, 0)}")

    def _log(self, msg: str):
        """往日志区写一行，行首带时间戳（方便对照每次操作发生的时刻）。"""
        stamp = datetime.now().strftime("[%H:%M:%S]")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{stamp} {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _clear_log(self):
        """清空日志区。

        Text 平时是 disabled（防止用户误敲），所以改内容前后要自己开关一遍。
        """
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _toggle_topmost(self):
        """切换窗口置顶（截图时常用：把工具钉在最前面，免得被别的窗口盖住）。"""
        try:
            self.root.attributes("-topmost", self.var_topmost.get())
            self._log(f"窗口置顶已{'开启' if self.var_topmost.get() else '关闭'}")
        except tk.TclError as exc:
            self._log(f"✗ 置顶设置失败：{exc}")

    def _validate_coord(self, proposed: str) -> bool:
        """Entry 输入校验：允许清空，或最多 4 位半角数字（0–9999）。

        返回 False 时 Tk 直接拒绝这次输入（键盘输入和粘贴都拦）。
        注意：本函数绝不能抛异常，否则 Tk 会永久关闭该控件的校验。
        """
        return proposed == "" or (
            proposed.isascii() and proposed.isdigit() and len(proposed) <= 4
        )

    def _bind_coord_navigation(self, entries):
        """让方向键能在四个坐标框之间跳。

        - ↓ / ↑：直接跳下一个 / 上一个（单行输入框里上下键本来就没别的用途）
        - → / ←：只有光标已在末尾 / 开头时才跳，否则留给它正常移动光标 ——
          不这样做的话，填完 1234 想按 ← 退回去改一位都做不到
        首尾相接成一个环。

        :param entries: 按跳转顺序排好的输入框 (X1, Y1, X2, Y2)
        """
        count = len(entries)

        def jump(index):
            """焦点跳到第 index 个框（越界就绕回来），并全选内容方便直接覆盖。"""
            target = entries[index % count]
            target.focus_set()
            target.selection_range(0, "end")
            return "break"          # 返回 break 才会吃掉这次按键的默认行为

        for i, entry in enumerate(entries):
            entry.bind("<Down>", lambda _e, i=i: jump(i + 1))
            entry.bind("<Up>", lambda _e, i=i: jump(i - 1))
            entry.bind("<Right>", lambda e, i=i: jump(i + 1)
                       if int(e.widget.index("insert")) >= len(e.widget.get()) else None)
            entry.bind("<Left>", lambda e, i=i: jump(i - 1)
                       if int(e.widget.index("insert")) <= 0 else None)

    def _read_coords(self, allow_empty=False):
        """读取并校验坐标。

        - allow_empty=False：任意一项为空 → ValueError（提交时用）
        - allow_empty=True ：任意一项为空 → 返回 None（实时预览用）

        合法时返回 (x1, y1, x2, y2)，否则抛 ValueError。
        """
        vars_ = (self.var_x1, self.var_y1, self.var_x2, self.var_y2)
        raw = [v.get().strip() for v in vars_]

        if any(s == "" for s in raw):
            if allow_empty:
                return None
            raise ValueError("坐标不能为空")

        try:
            return tuple(int(float(s)) for s in raw)
        except (ValueError, OverflowError):   # inf / nan 抛的是 OverflowError
            raise ValueError("坐标需为数字") from None

    def _update_size(self):
        """实时显示 region 的宽高（复用后端的 transform_pos）。"""
        try:
            coords = self._read_coords(allow_empty=True)
        except ValueError as e:
            self.var_size.set(f"区域：-- （{e}）")
            return

        if coords is None:
            self.var_size.set("区域：-- （请输入坐标）")
            return

        x1, y1, x2, y2 = coords
        region = transform_pos(x1, y1, x2, y2)
        self.var_size.set(
            f"区域：{region['width']}×{region['height']} px "
            f"(left={region['left']}, top={region['top']})"
        )

    # ================= 事件处理 =================
    def _choose_dir(self):
        """选择保存目录（只改目录，文件名那边不动）。"""
        current = os.path.expanduser(self.var_dir.get().strip())
        init_dir = current if os.path.isdir(current) else _HERE
        chosen = filedialog.askdirectory(title="选择保存目录", initialdir=init_dir)
        if chosen:
            self.var_dir.set(chosen)

    def _choose_template(self):
        """选择模板图片。"""
        path = filedialog.askopenfilename(
            title="选择模板图片",
            initialdir=_HERE,
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            self.var_template.set(path)

    def _check_match(self):
        """算模板在「全屏」和「当前坐标区域」里的最高匹配分（诊断用）。"""
        tpl_path = self.var_template.get().strip()
        if not tpl_path:
            messagebox.showerror("模板未指定", "请先选择或填写模板路径。")
            return

        try:
            tpl = utils._load_template(tpl_path)
        except Exception as exc:                      # noqa: BLE001
            self._log(f"✗ 模板加载失败：{exc}")
            messagebox.showerror("模板加载失败", str(exc))
            return

        try:
            # 抓一帧再转灰度：模板本身是灰度图，两边通道数必须一致
            frame_bgr, _monitor = utils.grab_screen()
            frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

            # ① 全屏匹配
            result = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
            _, best, _, loc = cv2.minMaxLoc(result)
            self._log(f"全屏最高分：{best:.3f} @ {loc}")

            # ② 区域匹配：复用上面的坐标输入框，全空就跳过
            try:
                coords = self._read_coords(allow_empty=True)
            except ValueError as e:
                coords = None
                self._log(f"坐标无效，跳过区域内匹配（{e}）")

            if coords is None:
                self._log("未指定区域坐标，跳过区域内匹配")
            else:
                region = transform_pos(*coords)       # 顺序填反了也能归一化
                if region["width"] <= 0 or region["height"] <= 0:
                    raise ValueError("区域宽高必须大于 0。")
                left, top = region["left"], region["top"]
                sub = frame[top:top + region["height"], left:left + region["width"]]
                if sub.size == 0:
                    raise ValueError("指定区域超出屏幕范围或为空。")

                result2 = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
                _, best2, _, loc2 = cv2.minMaxLoc(result2)
                self._log(f"区域最高分：{best2:.3f} → 绝对位置 "
                          f"({loc2[0] + left}, {loc2[1] + top})")
                self._log(f"阈值 0.8：{'通过' if best2 >= 0.8 else '不通过'}"
                          f"　阈值 0.7：{'通过' if best2 >= 0.7 else '不通过'}")

            self.var_status.set(f"匹配完成：{os.path.basename(tpl_path)}")
        except Exception as exc:                      # noqa: BLE001
            self.var_status.set("匹配失败")
            self._log(f"✗ 匹配失败：{exc}")
            messagebox.showerror("匹配失败", str(exc))

    def _open_output_dir(self):
        """在文件管理器里打开保存目录，方便查看刚存下的图。"""
        path = os.path.expanduser(self.var_dir.get().strip())
        if not path:
            messagebox.showerror("参数错误", "保存目录为空，请先填写或选择。")
            return
        if not os.path.isdir(path):
            messagebox.showerror("目录不存在", f"找不到这个目录：\n{path}")
            return
        try:
            os.startfile(path)                      # Windows：叫起资源管理器
        except AttributeError:                      # 非 Windows 的兜底
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))

    def _advance_auto_name(self):
        """截图成功后推进自动文件名（用户手输过的名字不动）。"""
        if core.should_advance_auto_name(self.var_name.get(), self._auto_name):
            self._auto_name = core.generate_default_filename()
            self.var_name.set(self._auto_name)

    def _fill_screen(self):
        """「全屏」按钮：把四个坐标填成整块屏幕（0,0 → 屏幕宽,屏幕高）。"""
        self.var_x1.set("0")
        self.var_y1.set("0")
        self.var_x2.set(str(self.root.winfo_screenwidth()))
        self.var_y2.set(str(self.root.winfo_screenheight()))

    def _on_capture(self):
        """「截图」按钮：校验输入 → 拼保存路径 → 调后端抓图 → 反馈结果。

        界面层是错误处理的最后一站，所以这里不往上抛异常：
        每一步失败都弹一句人话，并把细节写进日志区。
        """
        # 1) 参数校验
        try:
            x1, y1, x2, y2 = self._read_coords()
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return

        # 2) 拼出保存路径（目录 + 文件名；文件名留空则自动命名）
        try:
            path = core.build_output_path(
                self.var_dir.get(), self.var_name.get(), self._auto_name
            )
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return

        # 3) 调用后端
        self.var_status.set("正在截图…")
        self.root.update_idletasks()

        try:
            saved = capture_region(x1, y1, x2, y2, path)
        except Exception as exc:                      # noqa: BLE001
            self.var_status.set("截图失败")
            self._log(f"✗ 截图失败：{exc}")
            messagebox.showerror("截图失败", str(exc))
            return

        # 4) 成功反馈（先推进自动名，免得连点两次覆盖上一张）
        self._advance_auto_name()
        region = transform_pos(x1, y1, x2, y2)
        self.var_status.set(f"完成　{region['width']}×{region['height']} px")
        self._log(f"✓ 已保存：{saved}")

    # ---------- 屏幕拖拽拾取区域 ----------
    def _pick_region(self):
        """「拾取区域」按钮：先把自己藏起来，再铺遮罩让用户拖框。

        延迟 200ms 是为了等窗口真的从屏幕上消失 ——
        不等的话，遮罩背景里会残留自己的窗口。
        """
        self.root.withdraw()
        self.root.after(200, self._create_overlay)

    def _create_overlay(self):
        """铺一层半透明全屏遮罩，让用户拖出一个矩形。

        拖完把结果写回四个坐标框（自动取左上/右下，往哪个方向拖都对）；
        按 Esc、或拖得比 2px 还小，都算取消，什么都不改。
        """
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

        # 一次拖拽的全部状态：起点 (sx, sy)、画布上的矩形 id、是否已经收尾
        state = {"sx": 0, "sy": 0, "rect": None, "done": False}

        def to_canvas(xr, yr):
            """屏幕绝对坐标 → 画布内坐标。

            画布铺满整屏时两者通常相等，但多显示器 / 窗口有偏移时会有差别，
            所以老老实实换算一次。
            """
            return xr - canvas.winfo_rootx(), yr - canvas.winfo_rooty()

        def on_press(e):
            """按下鼠标：记下起点，并在光标处画出一个零尺寸的矩形。"""
            state["sx"], state["sy"] = e.x_root, e.y_root
            cx, cy = to_canvas(e.x_root, e.y_root)
            state["rect"] = canvas.create_rectangle(
                cx, cy, cx, cy, outline="#ff3b30", width=2
            )

        def on_drag(e):
            """拖动中：让矩形的一个角跟着光标跑。"""
            if state["rect"] is None:
                return
            cx, cy = to_canvas(state["sx"], state["sy"])
            ex, ey = to_canvas(e.x_root, e.y_root)
            canvas.coords(state["rect"], cx, cy, ex, ey)

        def on_release(e):
            """松开鼠标：收掉遮罩，把拖出的矩形写回四个坐标框。"""
            if state["done"]:
                return
            state["done"] = True

            x1, y1 = state["sx"], state["sy"]
            x2, y2 = e.x_root, e.y_root
            close()

            if abs(x2 - x1) < 2 or abs(y2 - y1) < 2:
                self._log("已取消区域拾取（拖动范围过小）。")
                return

            # 反着拖（从右下往左上）也要得到同一个矩形，所以统一取 min/max
            self.var_x1.set(str(min(x1, x2)))
            self.var_y1.set(str(min(y1, y2)))
            self.var_x2.set(str(max(x1, x2)))
            self.var_y2.set(str(max(y1, y2)))
            self._log(f"已拾取区域：({x1}, {y1}) → ({x2}, {y2})")

        def close():
            """收掉遮罩、把主窗口放回来（正常拖完和按 Esc 都走这里）。"""
            try:
                ov.grab_release()     # 没抓过 grab 时释放会报错，忽略即可
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
    """程序入口：建根窗口 → 套用 Windows 主题 → 进事件循环。"""
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")      # Windows 下更美观；其他平台自动回退
    except tk.TclError:
        pass
    ScreenshotApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()