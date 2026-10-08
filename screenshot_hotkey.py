"""全局快捷键（Windows 专用）—— 窗口没有焦点时也能收到按键。

—— 为什么要单独一个文件 ——
tkinter 只能在**自己的窗口有焦点**时收到按键，所以想按快捷键唤醒截图，必须用系统
接口。常见做法是装第三方库（keyboard / pynput / pywin32），但 Windows 自带的
`RegisterHotKey` 用 ctypes 就能调 —— 于是这个功能**不需要新增任何第三方依赖**。

—— 怎么工作 ——
RegisterHotKey(hWnd=None) 把热键挂在**调用它的那个线程**的消息队列上，所以这里专门
起一条后台线程，在里面注册 + 跑自己的消息循环 GetMessageW。主线程（tkinter）完全
不受影响。

回调发生在**后台线程**里。tkinter 不是线程安全的，所以这里绝不去碰界面 ——
调用方（screenshot_ui.py）只是往 queue 里丢个记号，由 tkinter 主线程定时取走再处理。

依赖：仅标准库（ctypes / threading）。
"""

import ctypes
import sys
import threading
from ctypes import wintypes

import screenshot_core as core

# 本模块只做 Windows：其它平台上 RegisterHotKey 根本不存在
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ⚠️ 所有返回值是"句柄/指针/字节数"的接口都必须显式声明原型。
    #    ctypes 默认把返回值当 32 位 int，而 Win64 上句柄是 64 位 —— 不声明就会被
    #    截断成野指针（实测：GlobalLock 返回 0，memmove 直接触发访问违例崩掉进程）。
    #    本模块目前虽然只用整数参数，但保持"凡涉及系统调用就写死原型"的习惯。
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                       wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int          # 可能返回 -1（出错）
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
else:
    _user32 = _kernel32 = None

# ---- Win32 常量 ----
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# 按住不放时只触发一次。没有它的话，用户按着快捷键稍久一点就会连开好几个选区窗口。
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

HOTKEY_ID = 1              # 本进程只用这一个热键，固定 id

# core 给的规范修饰键名 -> Win32 标志位
MOD_FLAGS = {
    "ctrl": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

# 除单个字母/数字外的具名键 -> 虚拟键码
NAMED_VK = {
    "esc": 0x1B, "space": 0x20, "tab": 0x09, "enter": 0x0D, "backspace": 0x08,
    "delete": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
}

# 注册失败的常见错误码 -> 人话
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_ERROR_HINTS = {
    ERROR_HOTKEY_ALREADY_REGISTERED:
        "这个组合已经被别的程序占用了，换一个试试（比如 Ctrl+Alt+B）。",
    1400: "快捷键参数无效，检查一下主键是不是允许的键。",
}


class HotkeyError(RuntimeError):
    """注册快捷键失败（格式错、被占用、或不在 Windows 上）。

    `code` 是 RegisterHotKey 失败时系统给的错误码。**1409（ERROR_HOTKEY_ALREADY_REGISTERED）
    表示这个组合已经被别的程序占用了** —— 调用方可以据此决定"要不要换个键再试一次"，
    而不是一律当成失败。见 `ERROR_HOTKEY_ALREADY_REGISTERED`。
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def vk_of(key):
    """把 core 规范化后的主键名转成 Win32 虚拟键码。

    :param key: 已小写的主键名，如 "a" / "5" / "f9" / "esc"
    :return: 虚拟键码整数
    :raises ValueError: 不认识的主键
    """
    if len(key) == 1 and key.isalnum():
        # 字母 A-Z 的码就是 0x41-0x5A，数字 0-9 是 0x30-0x39，刚好等于 ASCII 大写
        return ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return 0x70 + int(key[1:]) - 1          # F1 = 0x70
    if key in NAMED_VK:
        return NAMED_VK[key]
    raise ValueError(f"不认识的主键「{key}」")


class HotkeyListener:
    """注册单个全局快捷键；按一下调一次 callback（在后台线程里）。

    用法：
        listener = HotkeyListener(on_press)
        listener.start("Ctrl+Alt+A")     # 失败会抛 HotkeyError
        ...
        listener.stop()
    """

    def __init__(self, callback):
        self._callback = callback
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self._error = None
        self._error_code = None
        self._hotkey_text = ""

    # ---------------------------------------------------------------- 对外属性
    @property
    def is_active(self):
        """当前是否已成功注册（线程活着且没在退出中）。"""
        return self._thread is not None and self._thread.is_alive()

    @property
    def hotkey_text(self):
        """当前生效的快捷键文本；未注册时是空串。"""
        return self._hotkey_text

    # ---------------------------------------------------------------- 注册 / 注销
    def start(self, hotkey_text):
        """注册快捷键（会先注销上一个）。

        :param hotkey_text: 如 "Ctrl+Alt+A"
        :raises ValueError: 文本格式不对（由 core.parse_hotkey 抛出）
        :raises HotkeyError: 不在 Windows 上，或组合被占用导致注册失败
        """
        self.stop()

        if not IS_WINDOWS:
            raise HotkeyError("全局快捷键目前只支持 Windows。")

        mods, key = core.parse_hotkey(hotkey_text)      # 可能 ValueError
        flags = MOD_NOREPEAT
        for name in mods:
            flags |= MOD_FLAGS[name]
        vk = vk_of(key)

        self._ready.clear()
        self._error = None
        self._error_code = None
        self._hotkey_text = ""
        self._thread = threading.Thread(target=self._run, args=(flags, vk),
                                        name="hotkey-listener", daemon=True)
        self._thread.start()

        # 等注册结果：注册失败必须让调用方当场知道（而不是静默变成"快捷键没反应"）
        if not self._ready.wait(timeout=3.0):
            self._thread = None
            self._thread_id = None
            raise HotkeyError("全局快捷键注册超时，系统未响应，建议更换快捷键或重试。")
        if self._error:
            self._thread = None
            self._thread_id = None
            raise HotkeyError(self._error, code=self._error_code)

        self._hotkey_text = core.format_hotkey(mods, key)

    def stop(self):
        """注销快捷键并结束后台线程；没在跑时是安全的空操作。"""
        thread, thread_id = self._thread, self._thread_id
        if thread is None:
            return
        if thread_id:
            # 往后台线程的消息队列里塞一条 WM_QUIT，GetMessageW 返回 0，循环自然退出
            _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None
        self._hotkey_text = ""

    # ---------------------------------------------------------------- 后台线程
    def _run(self, flags, vk):
        """后台线程主体：注册 → 消息循环 → 注销。"""
        self._thread_id = _kernel32.GetCurrentThreadId()

        if not _user32.RegisterHotKey(None, HOTKEY_ID, flags, vk):
            code = ctypes.get_last_error()
            hint = _ERROR_HINTS.get(code, "可能被其它程序占用了，换一个组合试试。")
            self._error_code = code
            self._error = f"注册快捷键失败（错误码 {code}）：{hint}"
            self._ready.set()
            return

        self._ready.set()
        msg = wintypes.MSG()
        try:
            while True:
                result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result in (0, -1):       # 0 = 收到 WM_QUIT；-1 = 出错，都收工
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        self._callback()
                    except Exception:
                        # 回调是用户代码。它炸了不该把消息循环带走，否则快捷键从此失灵
                        # 而且再也不会有人知道。吞掉异常，让监听继续活着。
                        pass
        finally:
            _user32.UnregisterHotKey(None, HOTKEY_ID)


# ============================================================ 自检（python screenshot_hotkey.py）
def _self_check():
    """注册 Ctrl+Alt+F9 → 用 keybd_event 模拟按键 → 验证回调触发 → 注销 → 验证不再触发。

    这是本模块唯一能脱离人手自动验证的方式：真的走了一遍系统的热键注册与消息派发。
    """
    import time

    if not IS_WINDOWS:
        print("非 Windows，跳过。")
        return

    fired = []
    listener = HotkeyListener(lambda: fired.append(time.perf_counter()))
    listener.start("Ctrl+Alt+F9")
    print(f"注册成功：{listener.hotkey_text}")

    KEYUP = 0x0002
    keys = (0x11, 0x12, 0x78)          # Ctrl, Alt, F9
    for vk in keys:
        _user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(keys):
        _user32.keybd_event(vk, 0, KEYUP, 0)
    time.sleep(0.4)
    print(f"模拟按键后回调触发：{len(fired)} 次 -> {'✅ 通过' if len(fired) == 1 else '❌ 异常'}")

    listener.stop()
    before = len(fired)
    for vk in keys:
        _user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(keys):
        _user32.keybd_event(vk, 0, KEYUP, 0)
    time.sleep(0.3)
    print(f"注销后再按：新增 {len(fired) - before} 次 -> "
          f"{'✅ 已彻底注销' if len(fired) == before else '❌ 仍在触发'}")

    # 格式错误的输入应当抛 ValueError，被占用/非法组合应当抛 HotkeyError
    for bad in ("", "Ctrl+", "Ctrl+A+B", "Ctrl+Foo", "A", "Ctrl+Alt+A"):
        try:
            core.parse_hotkey(bad)
            print(f"  parse_hotkey({bad!r}) -> 通过校验")
        except ValueError as e:
            print(f"  parse_hotkey({bad!r}) -> ValueError: {e}")


if __name__ == "__main__":
    _self_check()
