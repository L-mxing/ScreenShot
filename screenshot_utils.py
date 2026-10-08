"""截图工具的**图像工具层** —— 只保留本项目（截图工具）真正调用到的部分。

现在有这些东西：
  1. `_sct`：mss 截图实例（全局复用）
  2. `grab_screen()`：抓一帧屏幕，返回 BGR 图 + 显示器信息
  3. `_load_template()`：读模板图片（带缓存 + 文件修改时间校验）
  4. `save_image()`：把图像写成本地文件（中文路径安全）
  5. `copy_image_to_clipboard()`：把图像放进 Windows 剪贴板

它们服务于 `screenshot_ui.py` 的两条路径：
  · 「模板匹配诊断」：`_load_template()` 读模板 → `_sct` 抓帧 → cv2.matchTemplate 算分数
  · 「快捷截图」：`grab_screen()` 冻结画面 → 选区 → `save_image()` / `copy_image_to_clipboard()`

—— 为什么只剩这么点 ——
这个文件原本与隔壁「Hokage OL automation script」项目共用，是一份 950 行的公共库
（模板定位、鼠标点击、自动战斗/倍速一整套游戏自动化工具）。2026-09-30 按"只留本项目
真正调用的部分"精简，因此**两份副本自今日起不再相同**。隔壁那份仍完整保留在原处：
    D:\\PythonProject\\ProjectVault\\Hokage OL automation script\\screenshot_utils.py
本目录 `.workbuddy/backup/` 下另存了一份原版快照（950 行，md5 与精简前一致）。
以后本项目若又要用 locate_on_screen / click_pos / wait_image / auto_battle_with_speed
这类被删掉的接口，从上面两个位置取回即可。

依赖：mss（截图）+ numpy（存数组）+ opencv(cv2)（解码/编码图片）+ ctypes（剪贴板）。
"""

import ctypes
import os
import struct
import sys

import cv2
import numpy as np
import mss

# ============================================================ 一、截图实例与模板读取
# mss 全局单例，复用避免反复初始化开销。
# ⚠️ `screenshot_ui.py` 直接访问它来取主屏尺寸并抓帧（`utils._sct.monitors[1]`），
#    所以名字和"它是模块级变量"这两点都别改。
_sct = mss.MSS()

# 模板缓存：key = 图片路径，value = (图像数组, 该文件的修改时间)。
# 存 mtime 是为了开发期替换模板 PNG 后能自动重新加载，不必重启程序。
_template_cache: dict[str, tuple[np.ndarray, float]] = {}


def _load_template(image_path: str) -> np.ndarray:
    """读取模板图片（带缓存 + mtime 校验），返回灰度单通道数组。

    用 np.fromfile 读字节再交给 cv2.imdecode 解码，而不是直接 cv2.imread ——
    前者能正确处理含中文的路径（Windows 上 cv2.imread 遇到中文路径会静默返回 None）。

    :param image_path: 模板图片路径
    :return: 灰度模板图像（2 维 numpy 数组）
    :raises FileNotFoundError: 文件不存在或图片解码失败
    """
    mtime = os.path.getmtime(image_path)
    if image_path not in _template_cache or mtime != _template_cache[image_path][1]:
        data = np.fromfile(image_path, dtype=np.uint8)
        template = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"模板图片加载失败: {image_path}")
        _template_cache[image_path] = (template, mtime)
    return _template_cache[image_path][0]


# ============================================================ 二、抓帧
def grab_screen(monitor=None):
    """抓一帧屏幕，返回 (BGR 三通道图像, 该显示器的信息 dict)。

    :param monitor: mss 的显示器信息（如 `_sct.monitors[1]`）；不传就抓主显示器
    :return: (numpy 数组 HxWx3，显示器 dict 含 left/top/width/height)
    """
    mon = monitor if monitor is not None else _sct.monitors[1]
    frame = np.array(_sct.grab(mon))[:, :, :3]      # mss 输出 BGRA，丢掉 alpha 通道
    return frame, mon


# ============================================================ 三、保存成文件
# 允许写出的扩展名；不在名单里就按 .png 写
WRITABLE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")


def save_image(image_bgr, output_path):
    """把 BGR 图像写成图片文件（自动建目录；中文路径安全）。返回最终写入的绝对路径。

    为什么不用 `cv2.imwrite`：它在 Windows 上遇到含中文的路径会**静默失败** ——
    不抛异常、只返回 False，文件根本没写出来，排查起来极其费劲。这里先把图编成内存
    里的图片字节，再用 Python 自己的文件对象写盘，路径交给 Python 处理，稳。

    :param image_bgr: BGR 三通道图像
    :param output_path: 目标路径（扩展名决定格式）
    :return: 实际写入的绝对路径（若原路径没有可用扩展名，会自动补 `.png`）
    :raises ValueError: 编码失败
    """
    output_path = os.path.abspath(output_path)
    ext = os.path.splitext(output_path)[1].lower()
    if ext not in WRITABLE_EXTENSIONS:
        ext = ".png"
        output_path += ".png"

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    ok, buf = cv2.imencode(ext, image_bgr)
    if not ok:
        raise ValueError(f"图片编码失败（格式 {ext}），请换一种扩展名。")
    with open(output_path, "wb") as f:
        f.write(buf.tobytes())
    return output_path


# ============================================================ 四、复制到剪贴板
# Windows 剪贴板放图片用的是 CF_DIB 格式：一张"裸 BMP"—— 只有信息头、没有 14 字节的
# 文件头，像素自下而上排列，且每一行的字节数要补齐到 4 的倍数。
_CF_DIB = 8
_GMEM_MOVEABLE = 0x0002
_BITMAPINFOHEADER_SIZE = 40


def _bgr_to_dib(image_bgr):
    """把 BGR 图打包成 Windows 剪贴板要的 DIB 字节串。"""
    height, width = image_bgr.shape[:2]
    row_bytes = width * 3
    stride = row_bytes + (4 - row_bytes % 4) % 4        # 每行 4 字节对齐
    bits = np.zeros((height, stride), dtype=np.uint8)
    bits[:, :row_bytes] = image_bgr[::-1].reshape(height, row_bytes)   # 自下而上
    header = struct.pack("<IiiHHIIiiII", _BITMAPINFOHEADER_SIZE, width, height,
                         1, 24, 0, bits.size, 0, 0, 0, 0)
    return header + bits.tobytes()


def copy_image_to_clipboard(image_bgr):
    """把 BGR 图放进 Windows 剪贴板（CF_DIB），之后可在别的程序里 Ctrl+V 直接粘贴。

    :param image_bgr: BGR 三通道图像
    :raises RuntimeError: 非 Windows，或剪贴板被别的程序占用打不开
    """
    if sys.platform != "win32":
        raise RuntimeError("复制到剪贴板目前只支持 Windows。")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # ⚠️ 句柄在 64 位系统上是指针宽度。不声明原型的话 ctypes 会按 32 位 int 处理返回值，
    #    把 64 位句柄截断成野指针 —— 实测后果是 GlobalLock 返回 0、memmove 直接触发
    #    访问违例把整个进程干掉。凡是返回句柄的系统调用，原型必须写死。
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    dib = _bgr_to_dib(image_bgr)

    if not user32.OpenClipboard(None):
        raise RuntimeError("打不开剪贴板（可能被其它程序占用），请稍后重试。")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(dib))
        if not handle:
            raise RuntimeError("分配剪贴板内存失败。")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise RuntimeError("锁定剪贴板内存失败。")
        ctypes.memmove(ptr, dib, len(dib))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(_CF_DIB, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("写入剪贴板失败。")
        # 写入成功后这块内存所有权归系统，不能再 GlobalFree，否则剪贴板内容会损坏
    finally:
        user32.CloseClipboard()
