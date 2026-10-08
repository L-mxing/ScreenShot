import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 保证能导入同目录下的 screenshot_backend 模块
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from screenshot_backend import capture_region,transform_pos

class ScreenshotApp:
    def __init__(self,root:tk.Tk):
        self.root = root
        self.root.title("截图工具")

        self.root.resizable(False,False)

        # ---------- 状态变量 ----------
        self.var_x1 = tk.StringVar(value="1200")
        self.var_y1 = tk.StringVar(value="878")
        self.var_x2 = tk.StringVar(value="1270")
        self.var_y2 = tk.StringVar(value="949")
        self.var_path=tk.StringVar(
            value=os.path.join("screenshots","board.png")
        )
        self.var_size=tk.StringVar(value="区域尺寸：--")
        self.var_status = tk.StringVar(value="就绪")

        # 坐标变化时实时刷新尺寸提示
        for v in (self.var_x1,self.var_y1,self.var_x2,self.var_y2):
            v.trace_add("write", lambda *_: self._update_size())

        self._build_ui()
        self._update_size()
        self._center()

    def _build_ui(self):
        """界面构建"""

        # 主框架
        pad=dict(padx=6, pady=4)
        main=ttk.Frame(self.root,padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        # ============= 截图区域 ==============================================
        area=ttk.LabelFrame(main,text="截图区域（屏幕坐标）",padding=10)
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
        btns=ttk.Frame(area)
        btns.grid(row=0,column=4,rowspan=2,padx=(12,0))
        ttk.Button(btns,text="拾取区域",command=self._pick_region,width=10).grid(row=0,column=0,pady=2)
        ttk.Button(btns,text="全屏",width=10).grid(row=1,column=0,pady=2)

        # 字典格式坐标显示
        ttk.Label(
            area,textvariable=self.var_size,foreground="#555555"
        ).grid(row=2,column=0,columnspan=5,sticky="w",pady=(8,0))

        # =================================================================

        # ============== 保存路径 ==========================================
        pathbox=ttk.LabelFrame(main,text="保存路径",padding=10)
        pathbox.grid(row=1,column=0,sticky="ew",pady=(10,0))
        pathbox.columnconfigure(0,weight=1)

        # 路径输入框
        ttk.Entry(pathbox,textvariable=self.var_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )

        # 浏览路径按钮
        ttk.Button(pathbox,text="浏览",width=8).grid(row=0,column=1)
        # ==================================================================

        # --------------------- 操作按钮 -----------------------------------
        






    def _center(self):
        pass

    # -----------区域尺寸标签--------------
    def _read_coords(self):
        """读取并校验坐标，返回 (x1, y1, x2, y2)；失败抛 ValueError。"""
        return (
            int(float(self.var_x1.get().strip())),
            int(float(self.var_y1.get().strip())),
            int(float(self.var_x2.get().strip())),
            int(float(self.var_y2.get().strip())),
        )

    def _update_size(self):
        """实时显示 region 的宽高（复用后端的 transform_pos）"""
        try:
            x1,y1,x2,y2=self._read_coords()
        except ValueError:
            self.var_size.set("区域尺寸：-- （坐标需为数字）")
            return
        region=transform_pos(x1,y1,x2,y2)
        self.var_size.set(
            f"区域尺寸：{region['width']} × {region['height']} px"
            f"　(left={region['left']}, top={region['top']})"
        )

    # ---------------------------------------------------------


    def _pick_region(self):
        pass

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







