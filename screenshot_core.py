# -*- coding: utf-8 -*-
"""截图工具的**逻辑层** —— 不依赖 tkinter，可脱离界面单独测试。

`screenshot_ui.py` 只管控件、布局和显示；这里放四件事：
  1. 截图后端的加载（同目录的 `screenshot_backend.py`）
  2. 文件名与保存路径的规则（时间戳命名、补扩展名、撞车让位、展开 ~）
  3. 坐标输入的解析（四个全空 = 全屏）
  4. 快捷键文本的解析与规范化（"Ctrl+Alt+A" → 修饰键集合 + 主键名）

第 4 项只做**文本层面**的规范化，不碰任何操作系统接口 —— 把 "ctrl"/"Ctrl"/"CTRL"
统一成同一个名字，是纯字符串活。真正的平台映射（名字 → Win32 虚拟键码）在
`screenshot_hotkey.py` 里，那是另一层的事。

只依赖标准库。改规则时改这个文件，改界面时改 `screenshot_ui.py`。
"""

import os
from importlib import util as _importlib_util

# 本目录（`screenshot_backend.py` 也在这里）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_PATH = os.path.join(BASE_DIR, "screenshot_backend.py")

# 允许的图片扩展名；不在名单里就补 .png（避免造出 shot.b / shot. 这种名不副实的文件）
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")

_capture_region = None


# ============================================================ 一、后端加载与截图执行
def ensure_backend():
    """加载同目录的 `screenshot_backend.py`，返回其中的 capture_region（只加载一次）。

    用绝对路径加载，所以从任意工作目录启动都能跑。
    注意：spec_from_file_location() 对不存在的文件也会返回 spec（实测 spec 与 loader
    均非 None），因此必须自己先判断文件是否存在 —— 真正的报错点在 exec_module() 那一行。
    """
    global _capture_region
    if _capture_region is not None:
        return _capture_region

    if not os.path.exists(BACKEND_PATH):
        raise SystemExit(f"找不到截图模块：{BACKEND_PATH}（请确认它和本文件在同一目录）")

    spec = _importlib_util.spec_from_file_location("screenshot_func", BACKEND_PATH)
    module = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _capture_region = module.capture_region
    return _capture_region


def capture_region(x1, y1, x2, y2, output_path):
    """薄转发到后端真正的 capture_region（首次调用时才加载后端）。"""
    return ensure_backend()(x1, y1, x2, y2, output_path)


# ============================================================ 二、文件名与路径规则
def generate_default_filename(now=None):
    """默认截图文件名，格式为 screenshot.png。

    这里保持固定命名，后续重复截图由 dedupe_path() 负责自动加 _1 / _2 等后缀。
    """
    return "screenshot.png"


def dedupe_path(path):
    """若该文件已存在，就在扩展名前加 _1 / _2 / _3 …（只用于自动生成的名字）。

    默认命名是 `Clipboard_Screenshot.png`，第一次冲突就变成 `Clipboard_Screenshot_1.png`。
    """
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 1
    while os.path.exists(f"{stem}_{index}{ext}"):
        index += 1
    return f"{stem}_{index}{ext}"


def is_auto_name(file_name, auto_name):
    """判断这个名字是「自动生成的」还是「用户手输的」。

    手输的同名覆盖是用户的意图，调用方不该替他让位。
    """
    stripped = file_name.strip()
    return (not stripped) or (stripped == auto_name)


def should_advance_auto_name(current, auto_name):
    """截图成功后，文件名是否该前进到下一个时间戳。

    当前值仍是「上一次自动生成的名字」或为空 -> 该前进；
    用户手输过 -> 不动（他可能就是要覆盖同名文件）。
    """
    return is_auto_name(current, auto_name)


def build_output_path(output_dir, file_name, auto_name=""):
    """算出最终写到哪个文件。规则：

    - `output_dir` 为空 -> ValueError
    - `output_dir` 里的 `~` 会展开
    - `file_name` 留空 -> 用 generate_default_filename() 自动命名
    - 结尾的点不算扩展名；扩展名不在白名单 -> 补 `.png`
    - 自动名（见 is_auto_name）撞车 -> dedupe_path() 让位成 `_2`/`_3`
    - 手输名撞车 -> 原样返回（尊重用户主动覆盖）
    """
    output_dir = os.path.expanduser(output_dir.strip())
    if not output_dir:
        raise ValueError("保存目录不能为空。")

    auto_named = is_auto_name(file_name, auto_name)
    name = file_name.strip().rstrip(".")
    if not name:
        # 留空 = 自动命名（全屏和区域行为一致）
        name = generate_default_filename()
        auto_named = True

    if os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
        name += ".png"

    path = os.path.join(output_dir, name)
    return dedupe_path(path) if auto_named else path


# ============================================================ 三、坐标输入解析
def parse_coordinates(x1_text, y1_text, x2_text, y2_text):
    """把四个输入框的文本解析成 (x1, y1, x2, y2)。

    四个全空 -> 返回 None，表示「截全屏」（屏幕尺寸由界面层提供，逻辑层不碰屏幕）。
    只填了一部分、或不是整数 -> ValueError。
    """
    texts = (x1_text, y1_text, x2_text, y2_text)
    if not any(t.strip() for t in texts):
        return None
    try:
        return tuple(int(t.strip()) for t in texts)
    except (TypeError, ValueError):
        raise ValueError("请输入完整且有效的坐标，或全部留空以截取全屏。")


# ============================================================ 四、快捷键文本解析
DEFAULT_HOTKEY = "Ctrl+Alt+A"

# 默认键被别的程序占用时，按顺序往下试这几个。
# 为什么需要：Ctrl+Alt+A 是 QQ / 微信 / 360 等一大堆软件的截图键，国内机器上很容易被占；
# 被占了注册就会失败，用户按下去毫无反应（界面还显示"已启用"，最难查）。
# ⚠️ 只用 Ctrl+Alt 系列，**刻意避开 Ctrl+Shift** —— 后者是中文输入法（搜狗等）切换输入法的
#    地盘，很容易被输入法先一步吃掉，表现为"注册成功但按了不响"。
# ⚠️ 只在**启动时**自动换；用户在输入框里亲手点「应用」，失败了就该照实报错、不偷偷换。
HOTKEY_FALLBACKS = ("Ctrl+Alt+A", "Ctrl+Alt+S", "Ctrl+Alt+D", "Ctrl+Alt+Q", "Ctrl+Alt+F9")

# 修饰键的规范名与书写顺序（显示时按这个顺序拼，例如 Ctrl+Alt+A 而不是 Alt+Ctrl+A）
HOTKEY_MODIFIERS = ("ctrl", "alt", "shift", "win")

# 各种叫法都归一到规范名：用户写 Ctrl / control / ctl 都是同一个键
_MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "alt": "alt", "menu": "alt",
    "shift": "shift",
    "win": "win", "windows": "win", "super": "win", "meta": "win",
}

# 除单个字母/数字外，允许作为主键的名字。
# ⚠️ 这里只收"位置固定"的键。像 - = [ ] ; ' , . / \ ` 这些键的键码随键盘布局变化
#    （同一个键位在美式键盘和德语键盘上不是同一个码），所以一律不收，免得在别人的
#    电脑上注册出个风马牛不相及的键。
NAMED_KEYS = frozenset({
    "esc", "space", "tab", "enter", "backspace", "delete", "insert",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
}) | {f"f{i}" for i in range(1, 25)}

_MODIFIER_LABEL = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


def parse_hotkey(text):
    """把快捷键文本（如 "Ctrl+Alt+A"）解析成 (修饰键集合, 主键名)。

    规范化规则：大小写不敏感、忽略多余空格、"control" 等同 "ctrl"。
    返回的修饰键集合元素只会是 "ctrl"/"alt"/"shift"/"win" 之一；主键名一律小写。

    :param text: 用户输入的快捷键文本
    :return: (frozenset 修饰键, str 主键名)，例如 (frozenset({"ctrl","alt"}), "a")
    :raises ValueError: 文本为空、没有主键、有多个主键、主键不认识、或缺少修饰键
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("快捷键不能为空。")

    parts = [p.strip().lower() for p in raw.split("+") if p.strip()]
    if not parts:
        raise ValueError("快捷键格式不对，示例：Ctrl+Alt+A")

    mods, keys = set(), []
    for part in parts:
        if part in _MODIFIER_ALIASES:
            mods.add(_MODIFIER_ALIASES[part])
        else:
            keys.append(part)

    if len(keys) != 1:
        raise ValueError(
            f"快捷键必须正好有一个主键，现在识别出 {len(keys)} 个："
            f"{'+'.join(keys) if keys else '（没有）'}。示例：Ctrl+Alt+A")

    key = keys[0]
    is_plain = len(key) == 1 and key.isalnum()
    if not is_plain and key not in NAMED_KEYS:
        raise ValueError(f"不认识的主键「{key}」。可用：A-Z、0-9、F1-F24，"
                         f"以及 {', '.join(sorted(NAMED_KEYS))}。")

    if not mods:
        # 不留修饰键的话，注册上就会把用户正常打字的这个键吞掉（按 A 就触发截图）
        raise ValueError("至少需要一个修饰键（Ctrl / Alt / Shift / Win），"
                         "否则会和正常打字冲突。示例：Ctrl+Alt+A")

    return frozenset(mods), key


def _display_key(key):
    """把主键名写成给人看的样子：a -> A、f9 -> F9、esc -> Esc。"""
    if key.startswith("f") and key[1:].isdigit():
        return key.upper()
    return key.upper() if len(key) == 1 else key.capitalize()


def format_hotkey(mods, key):
    """把 (修饰键集合, 主键名) 拼回给人看的文本，顺序固定为 Ctrl→Alt→Shift→Win。

    :return: 例如 "Ctrl+Alt+A"
    """
    ordered = [m for m in HOTKEY_MODIFIERS if m in mods]
    return "+".join([_MODIFIER_LABEL[m] for m in ordered] + [_display_key(key)])
