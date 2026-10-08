# -*- coding: utf-8 -*-
"""截图工具的**界面层**（tkinter）。

只管三件事：控件与布局、收集用户输入、把结果显示出来。
所有规则都在 `screenshot_ui_core.py` 里（命名、路径、坐标解析、后端加载、快捷键解析）——
要改行为改那边，要改外观改这里。

三种截图方式：
  1. 手填坐标 / 留空全屏  → 「截图」按钮
  2. 全局快捷键唤醒       → 默认 Ctrl+Alt+A，窗口没焦点时也能触发
  3. 拖拽选区（QQ 那种）  → 快捷键或「立即选区截图」按钮，鼠标拉一块矩形

第 2、3 项的背后：`screenshot_hotkey.py` 负责注册系统级热键（纯 ctypes），
`screenshot_overlay.py` 负责全屏遮罩与拖拽交互（tkinter）。

启动方式不变：`python screenshot_ui.py`
"""

import os
import queue
import sys
import traceback
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

# 把脚本所在目录放进 sys.path：这样无论从哪个工作目录启动，都能 import 同目录的逻辑层。
# （拆成两个模块后，普通 import 需要这一句；实测缺它时从别处启动会 ModuleNotFoundError）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import screenshot_core as core  # noqa: E402  （必须在 sys.path 处理之后）
import cv2
import screenshot_hotkey as hotkey
import screenshot_overlay as overlay
import screenshot_utils as utils

# 启动即检查后端是否就位：缺「screenshot_backend.py」时立刻报错，而不是等到第一次截图才发现
core.ensure_backend()


class ScreenshotApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("截图工具")
        self.geometry("280x580")
        self.resizable(False, True)

        self.output_dir_var = tk.StringVar(value=os.path.join(_HERE, "screenshots"))
        # 记住「上一次自动生成的文件名」：用户手改过就不再自动覆盖他的输入
        self._auto_name = core.generate_default_filename()
        self.filename_var = tk.StringVar(value=self._auto_name)
        self.status_var = tk.StringVar(value="准备就绪")
        self.topmost_var = tk.BooleanVar(value=False)

        # ---- 快捷截图相关状态 ----
        self.hotkey_var = tk.StringVar(value=core.DEFAULT_HOTKEY)
        self.hotkey_status_var = tk.StringVar(value="未启用")
        # 热键回调发生在后台线程，而 tkinter 不是线程安全的 —— 所以回调只往这个队列
        # 丢个记号，由主线程定时取走再处理（见 _poll_hotkey_queue）。
        self._hotkey_events = queue.Queue()
        # 关键修复：热键回调在后台线程里以无参形式调用，因此必须包装成 "放入一个事件标记"，
        # 不能直接传 queue.put，因为它要求一个 item 参数。
        self._hotkey = hotkey.HotkeyListener(lambda: self._hotkey_events.put("hotkey"))
        self._selecting = False          # 选区进行中，防止重复触发叠出多个遮罩
        self._was_visible = True         # 触发选区前主窗口是不是可见的

        self._build_ui()

        # 启动时自动注册一次默认快捷键。失败也不拦着窗口打开，只在界面上提示
        self._apply_hotkey(silent=True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_hotkey_queue()

    # ---------------------------------------------------------------- 界面搭建
    def _build_ui(self):
        # 视觉样式：保持原有功能不变，只增强外观层、对比度和交互反馈。
        self.configure(bg='#eef2ff')
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        style.configure('.', font=('Microsoft YaHei', 10), background='#eef2ff', foreground='#1f2937')
        style.configure('TFrame', background='#eef2ff')
        style.configure('TLabel', background='#eef2ff', foreground='#334155')
        style.configure('TLabelframe', background='#ffffff', borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background='#ffffff', foreground='#1f2937', font=('Microsoft YaHei', 10, 'bold'))
        style.configure('TEntry', fieldbackground='#ffffff', foreground='#0f172a', padding=6, borderwidth=1)
        style.configure('TCheckbutton', background='#eef2ff', foreground='#1f2937')
        style.configure('TButton', background='#e2e8f0', foreground='#1f2937', padding=8, borderwidth=0)
        style.map('TButton', background=[('active', '#dfe7f5'), ('pressed', '#d2deef')], foreground=[('active', '#1f2937'), ('pressed', '#1f2937')])
        style.configure('Accent.TButton', background='#4f46e5', foreground='#ffffff', padding=(14, 9), borderwidth=0, relief='flat', font=('Microsoft YaHei', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#4338ca'), ('pressed', '#3730a3')], foreground=[('active', '#ffffff'), ('pressed', '#ffffff')])
        style.configure('Secondary.TButton', background='#e2e8f0', foreground='#1f2937', padding=(10, 8), borderwidth=0)
        style.map('Secondary.TButton', background=[('active', '#dbe4f0'), ('pressed', '#cbd5e1')], foreground=[('active', '#1f2937'), ('pressed', '#1f2937')])

        self.geometry('320x620')
        main = ttk.Frame(self, padding=12)
        main.pack(fill='both', expand=True)

        # ---------- 区域选择 ----------
        region_frame = ttk.LabelFrame(main, text='截取区域（留空为全屏）')
        region_frame.pack(fill='x', pady=(0, 6))

        ttk.Label(region_frame, text='X1').grid(row=0, column=0, sticky='w', padx=(6, 0))
        ttk.Label(region_frame, text='Y1').grid(row=0, column=1, sticky='w', padx=(6, 0))
        ttk.Label(region_frame, text='X2').grid(row=0, column=2, sticky='w', padx=(6, 0))
        ttk.Label(region_frame, text='Y2').grid(row=0, column=3, sticky='w', padx=(6, 0))

        self.x1_entry = ttk.Entry(region_frame, width=6)
        self.y1_entry = ttk.Entry(region_frame, width=6)
        self.x2_entry = ttk.Entry(region_frame, width=6)
        self.y2_entry = ttk.Entry(region_frame, width=6)

        self.x1_entry.grid(row=1, column=0, padx=(6, 4), pady=(4, 6), sticky='ew')
        self.y1_entry.grid(row=1, column=1, padx=4, pady=(4, 6), sticky='ew')
        self.x2_entry.grid(row=1, column=2, padx=4, pady=(4, 6), sticky='ew')
        self.y2_entry.grid(row=1, column=3, padx=(4, 6), pady=(4, 6), sticky='ew')
        for column_index in (0, 1, 2, 3):
            region_frame.grid_columnconfigure(column_index, weight=1)

        # ---------- 保存设置 ----------
        save_frame = ttk.LabelFrame(main, text='保存')
        save_frame.pack(fill='x', pady=(0, 8))

        ttk.Label(save_frame, text='保存目录').grid(row=0, column=0, sticky='w', pady=(6, 4))
        self.output_dir_entry = ttk.Entry(save_frame, textvariable=self.output_dir_var)
        self.output_dir_entry.grid(row=0, column=1, sticky='ew', padx=(6, 4), pady=(6, 4))
        ttk.Button(save_frame, text='选择目录', style='Secondary.TButton', command=self.choose_output_dir).grid(row=0, column=2, padx=(4, 0), pady=(6, 4))

        ttk.Label(save_frame, text='文件名').grid(row=1, column=0, sticky='w', pady=(0, 6))
        self.filename_entry = ttk.Entry(save_frame, textvariable=self.filename_var)
        self.filename_entry.grid(row=1, column=1, sticky='ew', padx=(6, 4), pady=(0, 6))
        ttk.Label(save_frame, text='(默认 .png)', foreground='#64748b').grid(row=1, column=2, sticky='w')

        save_frame.grid_columnconfigure(1, weight=1)

        # 大按钮区
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill='x', pady=(0, 8))
        ttk.Button(btn_frame, text='截图', style='Accent.TButton', command=self.take_screenshot).pack(side='left', fill='x', expand=True, padx=(0, 6))
        ttk.Button(btn_frame, text='打开目录', style='Secondary.TButton', command=lambda: os.startfile(self.output_dir_var.get())).pack(side='left')

        # ---------- 模板匹配诊断 ----------
        tpl_frame = ttk.LabelFrame(main, text='模板匹配诊断')
        tpl_frame.pack(fill='x', pady=(0, 8))

        self.template_var = tk.StringVar(value=os.path.join(_HERE, 'image', 'game_ui_snapshots', 'auto_disable.png'))
        self.template_entry = ttk.Entry(tpl_frame, textvariable=self.template_var)
        self.template_entry.grid(row=0, column=0, sticky='ew', padx=(6, 4), pady=6)
        ttk.Button(tpl_frame, text='选择模板', style='Secondary.TButton', command=self.choose_template).grid(row=0, column=1, padx=(4, 0), pady=6)
        ttk.Button(tpl_frame, text='查看匹配分数', style='Secondary.TButton', command=self.check_match).grid(row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(0, 6))
        tpl_frame.grid_columnconfigure(0, weight=1)

        # ---------- 快捷截图 ----------
        hot_frame = ttk.LabelFrame(main, text='快捷截图（拖拽选区）')
        hot_frame.pack(fill='x', pady=(0, 8))

        ttk.Label(hot_frame, text='快捷键').grid(row=0, column=0, sticky='w', padx=(6, 4), pady=(6, 4))
        self.hotkey_entry = ttk.Entry(hot_frame, textvariable=self.hotkey_var)
        self.hotkey_entry.grid(row=0, column=1, sticky='ew', pady=(6, 4))
        ttk.Button(hot_frame, text='应用', style='Secondary.TButton', command=self._apply_hotkey).grid(row=0, column=2, padx=(4, 6), pady=(6, 4))

        ttk.Button(hot_frame, text='立即选区截图', style='Secondary.TButton', command=self.start_region_capture).grid(
            row=1, column=0, columnspan=3, sticky='ew', padx=6, pady=(0, 4))

        self.hotkey_label = ttk.Label(hot_frame, textvariable=self.hotkey_status_var,
                                      foreground='#64748b', wraplength=248, justify='left')
        self.hotkey_label.grid(row=2, column=0, columnspan=3, sticky='w', padx=6, pady=(0, 6))
        hot_frame.grid_columnconfigure(1, weight=1)

        # ---------- 选项与状态 ----------
        opt_frame = ttk.Frame(main)
        opt_frame.pack(fill='x', pady=(0, 8))
        ttk.Checkbutton(opt_frame, text='窗口置顶', variable=self.topmost_var, command=self.toggle_topmost).pack(side='left')
        ttk.Label(opt_frame, textvariable=self.status_var, foreground='#2563eb').pack(side='right')

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(main, text='输出日志')
        log_frame.pack(fill='both', expand=True)
        self.log_text = scrolledtext.ScrolledText(log_frame, state='disabled', wrap=tk.WORD, bg='#f8fafc', fg='#334155', insertbackground='#334155')
        self.log_text.pack(fill='both', expand=True, padx=8, pady=(8, 4))
        clear_btn = ttk.Button(log_frame, text='清空日志', style='Secondary.TButton', command=self.clear_log)
        clear_btn.pack(anchor='e', padx=8, pady=(0, 8))

        # 快捷键
        self.bind('<Return>', lambda _event: self.take_screenshot())

    # ---------------------------------------------------------------- 界面交互
    def toggle_topmost(self):
        try:
            self.attributes("-topmost", self.topmost_var.get())
            self.log(f"窗口置顶已{'开启' if self.topmost_var.get() else '关闭'}")
        except Exception as exc:
            self.log(f"置顶设置失败：{exc}")

    def log(self, message):
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"{timestamp} {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self.log("日志已清空")

    def choose_output_dir(self):
        directory = filedialog.askdirectory(initialdir=self.output_dir_var.get() or _HERE)
        if directory:
            self.output_dir_var.set(directory)

    def choose_template(self):
        path = filedialog.askopenfilename(initialdir=_HERE, filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*")])
        if path:
            self.template_var.set(path)

    def check_match(self):
        """计算并显示模板在全屏与指定区域内的匹配最高分（调试用）。"""
        tpl_path = self.template_var.get().strip()
        if not tpl_path:
            messagebox.showerror("模板未指定", "请先选择或填写模板路径。")
            return
        try:
            tpl = utils._load_template(tpl_path)
        except Exception as exc:
            self.log(f"模板加载失败：{exc}")
            messagebox.showerror("模板加载失败", str(exc))
            return
        try:
            # 抓取主屏幕一帧再转灰度（模板本身是灰度，两边通道数必须一致）
            frame_bgr, _monitor = utils.grab_screen()
            frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

            # 全屏匹配
            res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            self.log(f"全屏最高分: {max_val:.3f} @ {max_loc}")

            # 区域匹配：复用界面上的四个坐标输入框（若全空表示未设置）
            region = core.parse_coordinates(
                self.x1_entry.get(), self.y1_entry.get(), self.x2_entry.get(), self.y2_entry.get()
            )
            if region is None:
                self.log("未指定区域坐标，跳过区域内匹配（可在上方填写 X1/Y1/X2/Y2）")
            else:
                x1, y1, x2, y2 = region
                if x2 <= x1 or y2 <= y1:
                    raise ValueError("区域坐标不合法：X2 必须大于 X1，Y2 必须大于 Y1。")
                sub = frame[y1:y2, x1:x2]
                if sub.size == 0:
                    raise ValueError("指定区域超出屏幕范围或为空。")
                res2 = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
                _, max2, _, loc2 = cv2.minMaxLoc(res2)
                abs_pos = (loc2[0] + x1, loc2[1] + y1)
                self.log(f"region 内最高分: {max2:.3f} -> 绝对位置 {abs_pos}")
                self.log(f"阈值0.8: {'通过' if max2 >= 0.8 else '不通过'} | 阈值0.7: {'通过' if max2 >= 0.7 else '不通过'}")

            self.status_var.set(f"模板匹配完成：{os.path.basename(tpl_path)}")
        except Exception as exc:
            self.log(f"匹配失败：{exc}")
            self.log("详细错误（排查用）：\n" + traceback.format_exc())
            messagebox.showerror("匹配失败", str(exc))

    # ---------------------------------------------------------------- 全局快捷键
    def _set_hotkey_status(self, text, ok=True):
        """更新快捷键那行小字（正常灰、出错红）。"""
        self.hotkey_status_var.set(text)
        self.hotkey_label.configure(foreground='#666666' if ok else '#cc0000')

    def _apply_hotkey(self, silent=False):
        """把输入框里的快捷键注册成全局热键。

        :param silent: True 时失败只写到日志和状态行，不弹窗（启动自检用）。
            启动时如果默认键被别的程序占用，会自动往下试 `core.HOTKEY_FALLBACKS`
            里的备选，并把换成的那个写回输入框 —— 免得用户对着一个"看着已启用、
            按了却没反应"的假状态发呆（Ctrl+Alt+A 在国内机器上很容易被 QQ/微信/360 占掉）。
        """
        text = self.hotkey_var.get().strip()
        # 候选顺序：启动时（silent）允许自动退让；用户手点「应用」时只认他输入的那一个
        candidates = [text]
        if silent:
            candidates += [k for k in core.HOTKEY_FALLBACKS if k.lower() != text.lower()]

        last_error = None
        for candidate in candidates:
            try:
                self._hotkey.start(candidate)
            except ValueError as exc:
                # 文本本身不合法（少修饰键、主键不认识…），换哪个键都一样，直接报
                last_error = exc
                break
            except hotkey.HotkeyError as exc:
                last_error = exc
                # 只有"被别的程序占用"才值得退让；其它错误码换键也白搭
                if exc.code != hotkey.ERROR_HOTKEY_ALREADY_REGISTERED:
                    break
                continue

            if candidate != text:
                self.hotkey_var.set(candidate)
                self.log(f"快捷键 {text} 已被其它程序占用，自动改用 {candidate}")
            self._set_hotkey_status(f"已启用：{self._hotkey.hotkey_text}（窗口没有焦点时也生效）")
            self.log(f"全局快捷键已启用：{self._hotkey.hotkey_text}")
            return True

        self._set_hotkey_status(f"未启用：{last_error}", ok=False)
        self.log(f"快捷键设置失败：{last_error}")
        if not silent:
            messagebox.showerror("快捷键设置失败", str(last_error))
        return False

    def _poll_hotkey_queue(self):
        """主线程定时取走热键线程丢进队列的记号，再真正去开选区。

        为什么绕这一圈：回调运行在后台线程里，而 tkinter 只允许主线程碰。直接跨线程
        调界面轻则报错、重则随机崩溃，所以用队列做交接。

        ⚠️ 整轮循环必须包在 try 里，`self.after(...)` 放在 finally：只要有一轮抛了异常
        没人接住，这串 after 链就断了 —— 之后热键**永远失灵**，而界面还显示"已启用"。
        这是最难查的一类故障，宁可把异常吞掉记进日志，也不能让它把轮询带走。
        """
        try:
            while True:
                self._hotkey_events.get_nowait()
                try:
                    self.start_region_capture()
                except Exception as exc:
                    self._selecting = False      # 别让一次失败把后续按键全挡掉
                    self.log(f"响应快捷键时出错：{exc}")
                    self.log("详细错误（排查用）：\n" + traceback.format_exc())
        except queue.Empty:
            pass
        finally:
            self.after(60, self._poll_hotkey_queue)

    # ---------------------------------------------------------------- 拖拽选区截图
    def start_region_capture(self):
        """触发一次拖拽选区截图（快捷键或按钮都会走到这里）。"""
        if self._selecting:
            self.log("上一次选区还没结束，本次触发忽略")
            return

        self._selecting = True
        try:
            # 先记一笔。这行是判断"快捷键到底有没有送达"最直接的证据：
            # 日志里没有它 = 按键根本没到程序；有它但没后续 = 卡在冻结画面或开遮罩
            self.log("收到快捷键，正在冻结画面…")

            # 把自己的窗口藏起来，否则会被截进画面
            self._was_visible = bool(self.winfo_viewable())
            if self._was_visible:
                self.withdraw()
                # 给窗口管理器一点时间真正把窗口抹掉，不然刚抓到的帧里还有它
                self.after(220, self._do_region_capture)
            else:
                self.after(10, self._do_region_capture)
        except Exception:
            # 排期都失败了，必须把闸放开，否则后续每一次按键都会被上面那句
            # "if self._selecting: return" 挡掉 —— 表现就是快捷键彻底失灵且毫无提示
            self._selecting = False
            raise

    def _do_region_capture(self):
        """冻结画面 → 显示选区遮罩 → 按用户选择保存或复制。"""
        try:
            frame, monitor = utils.grab_screen()
            self.log(f"已冻结画面 {monitor['width']}x{monitor['height']}，等待拖拽选区…")

            selection = overlay.select_region(self, frame, monitor)
            if selection is None:
                self.status_var.set("已取消选区截图")
                self.log("选区截图已取消")
                return

            cropped = selection.crop(frame)
            size_text = f"{selection.width}x{selection.height}"

            if selection.action == "copy":
                utils.copy_image_to_clipboard(cropped)
                self.status_var.set(f"已复制到剪贴板：{size_text}")
                self.log(f"已复制到剪贴板：{size_text}（可直接 Ctrl+V 粘贴）")
            else:
                output_path = core.build_output_path(
                    self.output_dir_var.get(), self.filename_var.get(), self._auto_name)
                saved_path = utils.save_image(cropped, output_path)
                self._advance_auto_name()       # 与「截图」按钮一致：成功后推进自动文件名
                self.status_var.set(f"截图已保存：{os.path.basename(saved_path)}")
                self.log(f"选区截图已保存：{saved_path}（{size_text}）")
        except ValueError as exc:
            self.status_var.set(f"参数错误：{exc}")
            self.log(f"参数错误：{exc}")
            messagebox.showerror("参数错误", str(exc))
        except Exception as exc:
            self.status_var.set(f"选区截图失败：{exc}")
            self.log(f"选区截图失败：{exc}")
            self.log("详细错误（排查用）：\n" + traceback.format_exc())
            messagebox.showerror("选区截图失败", str(exc))
        finally:
            self._selecting = False
            if self._was_visible:
                self.deiconify()
                self.lift()

    def on_close(self):
        """关窗口前先注销全局快捷键，免得留一个按了没反应、还占着组合的热键。"""
        self._hotkey.stop()
        self.destroy()

    def _advance_auto_name(self):
        """截图成功后推进自动文件名（用户手输过的名字不动）。"""
        if core.should_advance_auto_name(self.filename_var.get(), self._auto_name):
            self._auto_name = core.generate_default_filename()
            self.filename_var.set(self._auto_name)

    # ---------------------------------------------------------------- 主流程（只做编排）
    def take_screenshot(self):
        try:
            region = core.parse_coordinates(
                self.x1_entry.get(),
                self.y1_entry.get(),
                self.x2_entry.get(),
                self.y2_entry.get(),
            )
            if region is None:
                # 四个坐标全空 -> 全屏（屏幕尺寸只有界面层知道，所以在这里取）
                x1, y1 = 0, 0
                x2, y2 = self.winfo_screenwidth(), self.winfo_screenheight()
                self.log(f"开始截图：全屏 ({x1}, {y1}) -> ({x2}, {y2})")
            else:
                x1, y1, x2, y2 = region
                self.log(f"开始截图：区域 ({x1}, {y1}) -> ({x2}, {y2})")

            output_path = core.build_output_path(
                self.output_dir_var.get(),
                self.filename_var.get(),
                self._auto_name,
            )
            saved_path = core.capture_region(x1, y1, x2, y2, output_path)

            # 关键：截图成功后推进文件名，否则连点两次会静默覆盖上一张
            self._advance_auto_name()

            # 状态栏只有 300px 宽，放完整路径会被裁掉右半段（文件名正好在那），所以只显示文件名
            self.status_var.set(f"截图已保存：{os.path.basename(saved_path)}")
            self.log(f"截图成功：{saved_path}")
        except ValueError as exc:
            self.status_var.set(f"参数错误：{exc}")
            self.log(f"参数错误：{exc}")
            messagebox.showerror("参数错误", str(exc))
        except Exception as exc:
            self.status_var.set(f"截图失败：{exc}")
            self.log(f"截图失败：{exc}")
            # 弹窗只给一行短消息，完整堆栈写进日志区（可滚动），方便排查
            self.log("详细错误（排查用）：\n" + traceback.format_exc())
            messagebox.showerror("截图失败", str(exc))


def main():
    app = ScreenshotApp()
    app.mainloop()


if __name__ == "__main__":
    main()
