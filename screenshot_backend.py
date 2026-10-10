
import os

import mss
import mss.tools


def transform_pos(x_1, y_1, x_2, y_2):
    """将任意两个对角坐标整理成规范的矩形区域字典。

        无论传入的 (x_1, y_1) 和 (x_2, y_2) 哪个在左上、哪个在右下，
        都统一转换为 mss 等库所需的 {left, top, width, height} 格式，
        其中 left/top 取较小值，width/height 取两点差的绝对值，
        这样即使坐标顺序颠倒也能正确描述同一个矩形区域。

        :param x_1: 第一个点的 x 坐标 (int)
        :param y_1: 第一个点的 y 坐标 (int)
        :param x_2: 第二个点的 x 坐标 (int)
        :param y_2: 第二个点的 y 坐标 (int)
        :return: {"left": left, "top": top, "width": width, "height": height}
    """
    left = min(x_1, x_2)
    top = min(y_1, y_2)
    width = abs(x_2 - x_1)
    height = abs(y_2 - y_1)
    return {"left": left, "top": top, "width": width, "height": height}


def capture_region(x_1, y_1, x_2, y_2, output_path="screenshot.png"):
    """截取屏幕上指定矩形区域，并保存为 PNG 图片。

        将传入的对角坐标转换为 mss 所需的区域字典，校验宽高有效性，
        确保输出目录存在，然后调用 mss 抓取屏幕并写入 PNG 文件。

        :param x_1: 矩形左上角 x 坐标 (int)
        :param y_1: 矩形左上角 y 坐标 (int)
        :param x_2: 矩形右下角 x 坐标 (int)
        :param y_2: 矩形右下角 y 坐标 (int)
        :param output_path: 截图保存路径，默认为当前目录下的 screenshot.png (str)
        :return: output_path：保存后的截图文件的绝对路径 (str)
        :raises ValueError: 当计算出的截图区域宽度或高度小于等于 0 时抛出。
    """
    region = transform_pos(x_1, y_1, x_2, y_2)
    if region["width"] <= 0 or region["height"] <= 0:
        raise ValueError("截图区域宽度和高度必须大于 0。")

    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with mss.MSS() as sct:
        shot = sct.grab(region)
        mss.tools.to_png(shot.rgb, shot.size, output=output_path)

    return output_path


if __name__ == "__main__":
    save_path = capture_region(1200, 878, 1270, 949, "screenshots/SC_04_start_btn.png")
    print(f"截图已保存到：{save_path}")










