"""交互式区域选区（QQ 截图那种）—— 全屏遮罩 + 鼠标拖拽 + 实时预览。

—— 交互流程 ——
    1. 冻结当前屏幕画面（先截图，再显示遮罩），所以选区过程中画面是静止的，
       不会因为鼠标划过而变来变去。
    2. 全屏铺一张半透明遮罩：鼠标所在处显示"拖动选择区域，Esc 取消"。
    3. 按住左键拖拽 → 选区内恢复成清晰原图，选区外压暗，实时显示 "宽 × 高"。
    4. 松开左键 → 选区右下角弹出工具条「保存 / 复制 / 取消」。
       · 保存 = 写成本地图片文件（路径规则由 core 决定）
       · 复制 = 放进剪贴板
       · 取消 / Esc / 右键 = 放弃
    5. 也可以直接按 Enter（=保存）或 Ctrl+C（=复制）。

—— 为什么不用 PIL ——
tkinter 8.6 的 PhotoImage 原生支持 PNG 字节，所以直接把 cv2 编码出的 PNG 喂给
它就行，不需要额外装 Pillow（实测 1920x1080 编码约 33ms）。

—— 关于可测试性 ——
鼠标事件的三个回调都只做一件事：把坐标转交给 _press / _drag / _release。
真正的逻辑全在这三个"收坐标"的方法里，于是测试可以不开鼠标、直接喂坐标验证。

只依赖标准库 tkinter + 已装好的 cv2。
"""

import tkinter as tk
from dataclasses import dataclass

import cv2

# 选区外遮罩的网点密度。tkinter 的 Canvas 不支持半透明，只能用"黑色 + 网点"来伪装，
# gray50 = 50% 网点，看起来正好是"压暗一层"。gray25 太黑，gray75 太亮。
DIM_STIPPLE = "gray50"
BORDER_COLOR = "#00a8ff"
LABEL_BG = "#000000"
LABEL_FG = "#ffffff"

MIN_SIZE = 4        # 边长小于它就算"点了一下"，不当作选区

TOOLBAR_BG = "#2b2b2b"
BTN_PRIMARY = "#3c8ce7"
BTN_NORMAL = "#4a4a4a"


@dataclass
class Selection:
    """用户选定的区域（坐标相对**冻结帧**的左上角，不是屏幕绝对坐标）。"""

    left: int
    top: int
    width: int
    height: int
    action: str = "save"        # "save" 保存 / "copy" 复制

    def crop(self, image):
        """从冻结帧里切出这块区域。"""
        return image[self.top:self.top + self.height, self.left:self.left + self.width]


class RegionSelector:
    """全屏选区遮罩。

    :param root: 主窗口（Toplevel 的父窗口）
    :param image_bgr: 已经冻结好的一帧画面（BGR 三通道）
    :param monitor: 这帧画面对应的显示器信息 dict（mss 的 monitors[n]）
    """

    def __init__(self, root, image_bgr, monitor):
        self.result = None
        self._root = root
        self._image = image_bgr
        self._monitor = monitor
        self._w = int(monitor["width"])
        self._h = int(monitor["height"])

        # 拖拽状态：起点 / 当前点 / 是否正在拖
        self._start = None
        self._current = None
        self._dragging = False
        self._crosshair_visible = True
        self._toolbar = None

        self._build()

    # ================================================================ 搭建界面
    def _build(self):
        win = tk.Toplevel(self._root)
        self.window = win
        win.withdraw()                      # 先藏起来，等 show() 再亮
        win.overrideredirect(True)          # 去掉标题栏，铺满整屏
        win.geometry(f"{self._w}x{self._h}+{int(self._monitor['left'])}+{int(self._monitor['top'])}")
        win.attributes("-topmost", True)
        win.configure(bg="black")

        canvas = tk.Canvas(win, width=self._w, height=self._h, bd=0,
                           highlightthickness=0, cursor="crosshair", bg="black")
        canvas.pack(fill="both", expand=True)
        self.canvas = canvas

        # 1) 冻结的那一帧，铺在最底下
        ok, buf = cv2.imencode(".png", self._image)
        if not ok:
            raise ValueError("冻结画面编码失败，无法显示选区遮罩。")
        self._photo = tk.PhotoImage(data=buf.tobytes())      # 必须留引用，否则被回收变白屏
        canvas.create_image(0, 0, anchor="nw", image=self._photo)

        # 2) 选区外的四块压暗遮罩（上 / 下 / 左 / 右）
        self._dims = [canvas.create_rectangle(0, 0, 0, 0, fill="black",
                                              stipple=DIM_STIPPLE, outline="")
                      for _ in range(4)]

        # 3) 选区边框 + 尺寸标签
        self._sel_box = canvas.create_rectangle(0, 0, 0, 0, outline=BORDER_COLOR,
                                                width=2, state="hidden")
        self._label_bg = canvas.create_rectangle(0, 0, 0, 0, fill=LABEL_BG,
                                                 outline="", state="hidden")
        self._label = canvas.create_text(0, 0, text="", fill=LABEL_FG,
                                         font=("", 10), anchor="nw", state="hidden")

        # 4) 十字辅助线
        self._cross_h = canvas.create_line(0, 0, 0, 0, fill=BORDER_COLOR, dash=(4, 4))
        self._cross_v = canvas.create_line(0, 0, 0, 0, fill=BORDER_COLOR, dash=(4, 4))

        # 5) 中心提示
        self._hint = canvas.create_text(self._w // 2, 44, text="按住左键拖动选择区域　·　Esc 取消",
                                        fill=LABEL_FG, font=("", 12))

        # ---- 事件绑定：回调只负责"转发坐标"，逻辑在 _press/_drag/_release ----
        canvas.bind("<Button-1>", lambda e: self._press(e.x, e.y))
        canvas.bind("<B1-Motion>", lambda e: self._drag(e.x, e.y))
        canvas.bind("<ButtonRelease-1>", lambda e: self._release(e.x, e.y))
        canvas.bind("<Motion>", lambda e: self._move(e.x, e.y))
        canvas.bind("<Button-3>", lambda e: self.cancel())        # 右键放弃

        win.bind("<Escape>", lambda e: self.cancel())
        win.bind("<Return>", lambda e: self.confirm("save"))
        win.bind("<Control-c>", lambda e: self.confirm("copy"))
        win.bind("<Control-C>", lambda e: self.confirm("copy"))

    # ================================================================ 对外入口
    def show(self):
        """显示遮罩并阻塞，直到用户确定或取消。返回 Selection，取消时返回 None。"""
        self.window.deiconify()
        self.window.lift()
        self.window.attributes("-topmost", True)
        self.window.focus_force()
        self.window.grab_set()                  # 独占输入，避免误触到底下窗口
        self.window.after(30, self.window.focus_force)   # 有些窗口管理器要等一下才给焦点
        self.window.wait_window()
        return self.result

    def confirm(self, action):
        """确定：把当前选区记下来并关闭。没有有效选区时什么都不做。"""
        if not self.has_selection():
            return
        x1, y1, x2, y2 = self._rect()
        self.result = Selection(x1, y1, x2 - x1, y2 - y1, action)
        self._close()

    def cancel(self):
        """取消：不返回任何结果，直接关闭。"""
        self.result = None
        self._close()

    # ================================================================ 拖拽逻辑
    def _press(self, x, y):
        """按下左键：清掉上一次的工具条与选区，重新开始画。"""
        self._hide_toolbar()
        self._start = (x, y)
        self._current = (x, y)
        self._dragging = True
        self._crosshair_visible = False
        self.canvas.itemconfigure(self._cross_h, state="hidden")
        self.canvas.itemconfigure(self._cross_v, state="hidden")
        self.canvas.itemconfigure(self._hint, state="hidden")
        self._redraw()

    def _drag(self, x, y):
        """拖拽中：更新终点，实时重画。"""
        if not self._dragging:
            return
        self._current = (x, y)
        self._redraw()

    def _release(self, x, y):
        """松开左键：选区够大就弹工具条，太小（只是点了一下）就复位。"""
        if not self._dragging:
            return
        self._dragging = False
        self._current = (x, y)
        self._redraw()
        if self.has_selection():
            self._show_toolbar()
        else:
            self._reset()

    def _move(self, x, y):
        """移动鼠标：十字线跟着走（选区定稿后就不再显示）。"""
        if not self._crosshair_visible:
            return
        self.canvas.coords(self._cross_h, 0, y, self._w, y)
        self.canvas.coords(self._cross_v, x, 0, x, self._h)

    # ================================================================ 内部工具
    def _rect(self):
        """把"起点 + 终点"整理成左上/右下（往回拖也不会得到负宽高）。"""
        if not self._start or not self._current:
            return 0, 0, 0, 0
        x1, y1 = self._start
        x2, y2 = self._current
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def has_selection(self):
        """当前是否有一块足够大的有效选区。"""
        x1, y1, x2, y2 = self._rect()
        return (x2 - x1) >= MIN_SIZE and (y2 - y1) >= MIN_SIZE

    def _reset(self):
        """回到"还没开始选"的状态。"""
        self._start = self._current = None
        self._crosshair_visible = True
        self.canvas.itemconfigure(self._sel_box, state="hidden")
        self.canvas.itemconfigure(self._label, state="hidden")
        self.canvas.itemconfigure(self._label_bg, state="hidden")
        self.canvas.itemconfigure(self._cross_h, state="normal")
        self.canvas.itemconfigure(self._cross_v, state="normal")
        self.canvas.itemconfigure(self._hint, state="normal")
        for item in self._dims:
            self.canvas.coords(item, 0, 0, 0, 0)

    def _redraw(self):
        """按当前选区重画：边框、四块遮罩、尺寸标签。"""
        x1, y1, x2, y2 = self._rect()
        if (x2 - x1) <= 0 or (y2 - y1) <= 0:
            return

        self.canvas.coords(self._sel_box, x1, y1, x2, y2)
        self.canvas.itemconfigure(self._sel_box, state="normal")

        # 上、下、左、右四块压暗区，中间留出清晰的选区
        self.canvas.coords(self._dims[0], 0, 0, self._w, y1)
        self.canvas.coords(self._dims[1], 0, y2, self._w, self._h)
        self.canvas.coords(self._dims[2], 0, y1, x1, y2)
        self.canvas.coords(self._dims[3], x2, y1, self._w, y2)

        self._place_label(f"{x2 - x1} × {y2 - y1}", x1, y1)

    def _place_label(self, text, x1, y1):
        """把尺寸标签放在选区左上角外侧；顶到屏幕边上时改放内侧。"""
        self.canvas.itemconfigure(self._label, text=text, state="normal")
        lx, ly = x1, y1 - 24
        if ly < 4:                       # 贴着屏幕顶边 -> 挪到选区内侧
            lx, ly = x1 + 4, y1 + 4
        self.canvas.coords(self._label, lx, ly)
        box = self.canvas.bbox(self._label)      # 文字排好版才能量出真实尺寸
        if box:
            self.canvas.coords(self._label_bg, box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2)
            self.canvas.itemconfigure(self._label_bg, state="normal")
            self.canvas.tag_raise(self._label_bg)      # 背景要压在文字下面
            self.canvas.tag_raise(self._label)

    def _show_toolbar(self):
        """在选区右下角弹出「保存 / 复制 / 取消」。"""
        self._hide_toolbar()
        x1, y1, x2, y2 = self._rect()

        bar = tk.Frame(self.window, bg=TOOLBAR_BG, bd=0)
        self._toolbar = bar

        def add_button(text, command, color):
            btn = tk.Button(bar, text=text, command=command, bg=color, fg="white",
                            activebackground=color, activeforeground="white",
                            relief="flat", bd=0, padx=14, pady=5,
                            cursor="hand2", font=("", 10))
            btn.pack(side="left", padx=3, pady=3)
            return btn

        add_button("保存", lambda: self.confirm("save"), BTN_PRIMARY)
        add_button("复制", lambda: self.confirm("copy"), BTN_NORMAL)
        add_button("取消", self.cancel, BTN_NORMAL)

        bar.update_idletasks()
        bw, bh = bar.winfo_reqwidth(), bar.winfo_reqheight()
        px, py = x2 - bw, y2 + 6                       # 默认贴在选区右下外侧
        if py + bh > self._h:                          # 下面放不下 -> 改放选区上方
            py = y1 - bh - 6
        if px < 0:
            px = 0
        if px + bw > self._w:
            px = max(0, self._w - bw)
        if py < 0:
            py = min(self._h - bh, y2 - bh - 6)
        bar.place(x=px, y=py)

    def _hide_toolbar(self):
        if self._toolbar is not None:
            self._toolbar.destroy()
            self._toolbar = None

    def _close(self):
        self._hide_toolbar()
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()


def select_region(root, image_bgr, monitor):
    """一次性用法：显示选区遮罩，返回 Selection 或 None（取消）。

    :param root: 主窗口
    :param image_bgr: 冻结好的一帧画面
    :param monitor: 这帧画面对应的显示器信息 dict
    """
    return RegionSelector(root, image_bgr, monitor).show()
