"""电脑端多区域 ADB 随机点击配置界面，仅使用 Python 标准库。"""

import base64
from dataclasses import asdict
import json
import logging
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from click_engine import AdbClient, Region, Settings, runTask

logger = logging.getLogger(__name__)


class QueueHandler(logging.Handler):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def emit(self, record):
        self.events.put(("log", self.format(record)))


class ClickerApp:
    def __init__(self, root):
        self.root = root
        root.title("ADB 多区域随机点击器")
        root.geometry("1000x870")
        root.minsize(900, 810)
        self.regions = []
        self.events = queue.Queue()
        self.stopEvent = threading.Event()
        self.worker = None
        self.busy = False
        self.closing = False
        self.controls = []
        self.values = {}
        self.displaySerial = ""
        handler = QueueHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        self.buildUi()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def field(self, parent, label, key, default, row, column, width=12):
        ttk.Label(parent, text=label).grid(row=row, column=column, padx=6, pady=5, sticky="w")
        value = tk.StringVar(value=str(default))
        self.values[key] = value
        entry = ttk.Entry(parent, textvariable=value, width=width)
        entry.grid(row=row, column=column + 1, padx=6, pady=5, sticky="ew")
        self.controls.append(entry)

    def button(self, parent, text, command):
        widget = ttk.Button(parent, text=text, command=command)
        widget.pack(side="left", padx=4, pady=5)
        self.controls.append(widget)
        return widget

    def buildUi(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="ADB 多区域随机点击器", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="每轮先随机等待 → 按列表顺序遍历区域 → 各区域随机次数、随机坐标点击").pack(anchor="w", pady=(4, 10))
        device = ttk.LabelFrame(outer, text="1. 连接 Android 设备", padding=8)
        device.pack(fill="x")
        self.field(device, "ADB 路径", "adb", "adb", 0, 0, 52)
        browse = ttk.Button(device, text="选择 adb.exe", command=self.browseAdb)
        browse.grid(row=0, column=2, padx=4)
        self.controls.append(browse)
        ttk.Label(device, text="设备").grid(row=1, column=0, padx=6, sticky="w")
        self.serial = tk.StringVar()
        self.deviceBox = ttk.Combobox(device, textvariable=self.serial, state="readonly", width=49)
        self.deviceBox.grid(row=1, column=1, padx=6, pady=5, sticky="ew")
        self.controls.append(self.deviceBox)
        refresh = ttk.Button(device, text="刷新设备", command=self.refresh)
        refresh.grid(row=1, column=2, padx=4)
        self.controls.append(refresh)
        ttk.Label(device, text="屏幕").grid(row=2, column=0, padx=6, sticky="w")
        self.screen = tk.StringVar(value="自动选择主屏")
        self.screenBox = ttk.Combobox(device, textvariable=self.screen, state="readonly", width=49,
                                      values=["自动选择主屏"])
        self.screenBox.grid(row=2, column=1, padx=6, pady=5, sticky="ew")
        self.controls.append(self.screenBox)
        refreshScreens = ttk.Button(device, text="刷新屏幕", command=self.refreshDisplays)
        refreshScreens.grid(row=2, column=2, padx=4)
        self.controls.append(refreshScreens)
        self.deviceBox.bind("<<ComboboxSelected>>", lambda _: self.resetDisplays())

        area = ttk.LabelFrame(outer, text="2. 点击区域（屏幕像素坐标，包含边界；按列表顺序执行）", padding=8)
        area.pack(fill="x", pady=8)
        self.tree = ttk.Treeview(area, columns=("name", "rect", "count"), show="headings", height=4, selectmode="browse")
        for key, label, width in (("name", "名称", 160), ("rect", "左上角 → 右下角", 400), ("count", "每轮点击次数", 150)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.selectRegion)
        editor = ttk.Frame(area)
        editor.pack(fill="x")
        for label, key, default, row, col in (("名称", "name", "区域 1", 0, 0), ("左 X", "x1", 0, 0, 2),
                ("上 Y", "y1", 0, 0, 4), ("右 X", "x2", 100, 1, 2), ("下 Y", "y2", 100, 1, 4),
                ("最少次数", "minClicks", 1, 2, 0), ("最多次数", "maxClicks", 3, 2, 2)):
            self.field(editor, label, key, default, row, col)
        buttons = ttk.Frame(area)
        buttons.pack(fill="x")
        for label, callback in (("采集屏幕并框选", self.capture), ("添加区域", self.addRegion),
                                ("更新选中", self.updateRegion), ("删除选中", self.removeRegion),
                                ("上移", lambda: self.moveRegion(-1)), ("下移", lambda: self.moveRegion(1))):
            self.button(buttons, label, callback)
        timing = ttk.LabelFrame(outer, text="3. 时间与循环", padding=8)
        timing.pack(fill="x")
        for label, key, default, row, col in (("轮间隔最小(秒)", "intervalMin", 20, 0, 0),
                ("最大(秒)", "intervalMax", 22, 0, 2), ("区域内点击间隔最小(秒)", "gapMin", 0.2, 1, 0),
                ("最大(秒)", "gapMax", 0.5, 1, 2),
                ("区域间隔最小(秒)", "regionGapMin", 1, 2, 0),
                ("最大(秒)", "regionGapMax", 2, 2, 2),
                ("循环轮数(0=无限)", "rounds", 0, 3, 0)):
            self.field(timing, label, key, default, row, col)
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=6)
        self.button(bar, "保存配置", self.saveConfig)
        self.button(bar, "加载配置", self.loadConfig)
        self.button(bar, "开始", self.start)
        self.stopButton = ttk.Button(bar, text="停止", command=self.stop, state="disabled")
        self.stopButton.pack(side="left", padx=8)
        self.status = tk.StringVar(value="就绪：连接设备并刷新，然后添加点击区域。")
        ttk.Label(outer, textvariable=self.status, wraplength=920).pack(anchor="w", pady=4)
        self.logBox = tk.Text(outer, height=6, state="disabled", font=("Consolas", 10))
        self.logBox.pack(fill="both", expand=True)

    def client(self):
        path = self.values["adb"].get().strip()
        if not path:
            raise ValueError("ADB 路径不能为空")
        if self.displaySerial != self.serial.get().strip():
            self.resetDisplays()
        displayId = self.screen.get().rsplit(" | ", 1)[-1] if self.screen.get() != "自动选择主屏" else ""
        if displayId and not displayId.isdecimal():
            raise ValueError("屏幕选择无效，请刷新屏幕后重新选择")
        return AdbClient(path, self.serial.get().strip(), displayId)

    def resetDisplays(self):
        self.displaySerial = self.serial.get().strip()
        self.screen.set("自动选择主屏")
        self.screenBox.configure(values=["自动选择主屏"])

    def refreshDisplays(self):
        try:
            client = self.client()
            if not client.serial:
                raise ValueError("请先刷新并选择设备")
            self.status.set("正在读取内屏、外屏等显示屏信息…")
            self.background(client.displays, "displays")
        except ValueError as exc:
            self.error(exc)

    def readRegion(self):
        region = Region(self.values["name"].get().strip(), **{
            key: int(self.values[key].get()) for key in ("x1", "y1", "x2", "y2", "minClicks", "maxClicks")})
        region.validate()
        return region

    def readSettings(self):
        settings = Settings(**{key: float(self.values[key].get()) for key in
                              ("intervalMin", "intervalMax", "gapMin", "gapMax", "regionGapMin", "regionGapMax")},
                            rounds=int(self.values["rounds"].get()))
        settings.validate()
        return settings

    def error(self, exc):
        logger.error("操作失败，原因=%s", exc)
        messagebox.showerror("操作失败", str(exc), parent=self.root)

    def redraw(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for index, region in enumerate(self.regions):
            self.tree.insert("", "end", iid=str(index), values=(region.name,
                f"({region.x1}, {region.y1}) → ({region.x2}, {region.y2})", f"{region.minClicks}～{region.maxClicks}"))
        if selected is not None:
            self.tree.selection_set(str(selected))

    def selectRegion(self, _event=None):
        if self.busy or not self.tree.selection():
            return
        for key, value in asdict(self.regions[int(self.tree.selection()[0])]).items():
            self.values[key].set(value)

    def addRegion(self):
        try:
            self.regions.append(self.readRegion())
            self.redraw()
            self.values["name"].set(f"区域 {len(self.regions) + 1}")
        except ValueError as exc:
            self.error(exc)

    def updateRegion(self):
        try:
            if not self.tree.selection():
                raise ValueError("请先选中需要更新的区域")
            index = int(self.tree.selection()[0])
            self.regions[index] = self.readRegion()
            self.redraw(index)
        except ValueError as exc:
            self.error(exc)

    def removeRegion(self):
        if self.tree.selection():
            del self.regions[int(self.tree.selection()[0])]
            self.redraw()

    def moveRegion(self, direction):
        if self.tree.selection():
            index = int(self.tree.selection()[0])
            target = index + direction
            if 0 <= target < len(self.regions):
                self.regions[index], self.regions[target] = self.regions[target], self.regions[index]
                self.redraw(target)

    def browseAdb(self):
        path = filedialog.askopenfilename(filetypes=[("ADB", "adb.exe"), ("所有文件", "*.*")])
        if path:
            self.values["adb"].set(path)

    def setBusy(self, busy, running=False):
        self.busy = busy
        for widget in self.controls:
            widget.configure(state="disabled" if busy else "normal")
        if not busy:
            self.deviceBox.configure(state="readonly")
            self.screenBox.configure(state="readonly")
        self.stopButton.configure(state="normal" if running else "disabled")

    def background(self, operation, event, running=False):
        self.setBusy(True, running)
        def work():
            try:
                self.events.put((event, operation()))
            except Exception as exc:
                logger.exception("后台操作失败")
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done", None))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def refresh(self):
        try:
            client = self.client()
            self.status.set("正在刷新设备…")
            self.background(client.devices, "devices")
        except ValueError as exc:
            self.error(exc)

    def capture(self):
        try:
            client = self.client()
            if not client.serial:
                raise ValueError("请先刷新并选择设备，再采集屏幕")
            self.status.set("正在读取设备截图…")
            self.background(client.screenshot, "screenshot")
        except ValueError as exc:
            self.error(exc)

    def showScreenshot(self, result):
        data, width, height = result
        window = tk.Toplevel(self.root)
        window.title(f"设备屏幕 · 拖动选取多个点击区域 · {width}×{height}")
        window.transient(self.root)
        window.grab_set()
        scale = max(1, math.ceil(width / max(300, self.root.winfo_screenwidth() - 120)),
                    math.ceil(height / max(100, self.root.winfo_screenheight() - 340)))
        ttk.Label(window, text="在屏幕图片上按住鼠标左键拖动，框选后点击“添加此区域”。可连续添加多个区域。",
                  wraplength=580).pack(padx=10, pady=8)
        photo = tk.PhotoImage(data=base64.b64encode(data)).subsample(scale)
        canvas = tk.Canvas(window, width=photo.width(), height=photo.height(), highlightthickness=0, cursor="crosshair")
        canvas.pack()
        canvas.image = photo
        canvas.create_image(0, 0, image=photo, anchor="nw")
        selection = {}
        hint = tk.StringVar(value="尚未选择区域。绿色框为已添加区域，红色框为当前选区。")
        ttk.Label(window, textvariable=hint, wraplength=580).pack(padx=10, pady=5)
        form = ttk.Frame(window)
        form.pack(padx=10, fill="x")
        name = tk.StringVar(value=f"区域 {len(self.regions) + 1}")
        minClicks = tk.StringVar(value=self.values["minClicks"].get())
        maxClicks = tk.StringVar(value=self.values["maxClicks"].get())
        for column, (label, variable, size) in enumerate((("名称", name, 16), ("最少次数", minClicks, 6), ("最多次数", maxClicks, 6))):
            ttk.Label(form, text=label).grid(row=0, column=column * 2, padx=3)
            ttk.Entry(form, textvariable=variable, width=size).grid(row=0, column=column * 2 + 1, padx=3)

        def drawRegions():
            canvas.delete("saved")
            for index, region in enumerate(self.regions):
                if region.x2 >= width or region.y2 >= height:
                    continue
                canvas.create_rectangle(region.x1 / scale, region.y1 / scale,
                                        (region.x2 + 1) / scale, (region.y2 + 1) / scale,
                                        outline="#00c853", width=2, tags="saved")
                canvas.create_text(region.x1 / scale + 3, region.y1 / scale + 3,
                                   text=f"{index + 1}. {region.name}", fill="#00c853", anchor="nw", tags="saved")

        drawRegions()
        def position(event):
            return max(0, min(event.x, photo.width() - 1)), max(0, min(event.y, photo.height() - 1))
        def press(event):
            canvas.delete("selection")
            selection.clear()
            addButton.configure(state="disabled")
            fillButton.configure(state="disabled")
            selection["start"] = position(event)
        def drag(event):
            if "start" in selection:
                canvas.delete("selection")
                canvas.create_rectangle(*selection["start"], *position(event), outline="#ff3b30", width=2, tags="selection")
        def release(event):
            if "start" not in selection:
                return
            startX, startY = selection["start"]
            endX, endY = position(event)
            selection["rect"] = (min(startX, endX) * scale, min(startY, endY) * scale,
                                 min(width - 1, (max(startX, endX) + 1) * scale - 1),
                                 min(height - 1, (max(startY, endY) + 1) * scale - 1))
            drag(event)
            x1, y1, x2, y2 = selection["rect"]
            hint.set(f"选区：({x1}, {y1}) → ({x2}, {y2})，大小 {x2 - x1 + 1}×{y2 - y1 + 1} 像素")
            addButton.configure(state="normal")
            fillButton.configure(state="normal")

        def addSelection():
            if "rect" not in selection:
                return
            try:
                region = Region(name.get().strip(), *selection["rect"], int(minClicks.get()), int(maxClicks.get()))
                region.validate(width, height)
            except ValueError as exc:
                messagebox.showerror("区域配置无效", str(exc), parent=window)
                return
            self.regions.append(region)
            self.redraw()
            drawRegions()
            canvas.delete("selection")
            selection.clear()
            addButton.configure(state="disabled")
            fillButton.configure(state="disabled")
            name.set(f"区域 {len(self.regions) + 1}")
            hint.set(f"已添加“{region.name}”，可继续拖动框选下一个区域。")
            self.status.set(f"已添加 {len(self.regions)} 个区域，可继续框选或关闭截图窗口。")
            logger.info("截图选区已添加，区域=%s，坐标=(%s,%s)-(%s,%s)",
                        region.name, region.x1, region.y1, region.x2, region.y2)

        def apply():
            if "rect" not in selection:
                return
            for key, value in zip(("x1", "y1", "x2", "y2"), selection["rect"]):
                self.values[key].set(value)
            window.destroy()
            self.status.set("坐标已填入编辑框，请点击“添加区域”或“更新选中”。")
        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", release)
        actions = ttk.Frame(window)
        actions.pack(pady=8)
        addButton = ttk.Button(actions, text="添加此区域", command=addSelection, state="disabled")
        addButton.pack(side="left", padx=4)
        fillButton = ttk.Button(actions, text="仅填入主界面坐标", command=apply, state="disabled")
        fillButton.pack(side="left", padx=4)
        ttk.Button(actions, text="完成框选", command=window.destroy).pack(side="left", padx=4)

    def start(self):
        try:
            settings = self.readSettings()
            regions = tuple(self.regions)
            if not regions:
                raise ValueError("请先添加至少一个区域")
            client = self.client()
            if not client.serial:
                raise ValueError("请刷新并选择设备")
            self.stopEvent.clear()
            self.status.set("正在校验屏幕与区域…")
            self.background(lambda: runTask(client, regions, settings, self.stopEvent,
                lambda text: self.events.put(("status", text))), "finished", running=True)
        except ValueError as exc:
            self.error(exc)

    def stop(self):
        self.stopEvent.set()
        self.stopButton.configure(state="disabled")
        self.status.set("正在停止，等待当前 ADB 命令结束（最长约 15 秒）…")
        logger.info("用户请求停止点击")

    def saveConfig(self):
        try:
            settings = self.readSettings()
            path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="clicker-config.json",
                                              filetypes=[("JSON 配置", "*.json")])
            if path:
                config = {"version": 1, "adb": self.values["adb"].get(), "serial": self.serial.get(),
                          "settings": asdict(settings), "regions": [asdict(region) for region in self.regions],
                          "physicalDisplayId": self.client().physicalDisplayId}
                logger.info("开始保存配置，路径=%s", path)
                Path(path).write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
                logger.info("配置保存成功")
        except (OSError, ValueError) as exc:
            self.error(exc)

    def loadConfig(self):
        path = filedialog.askopenfilename(filetypes=[("JSON 配置", "*.json")])
        if not path:
            return
        try:
            logger.info("开始读取配置，路径=%s", path)
            config = json.loads(Path(path).read_text(encoding="utf-8"))
            if config["version"] != 1:
                raise ValueError("不支持的配置版本")
            settings = Settings(**config["settings"])
            settings.validate()
            regions = [Region(**item) for item in config["regions"]]
            for region in regions:
                region.validate()
            if not isinstance(config["adb"], str) or not config["adb"].strip() or not isinstance(config["serial"], str):
                raise ValueError("ADB 路径或设备配置无效")
            displayId = config.get("physicalDisplayId", "")
            if not isinstance(displayId, str) or (displayId and not displayId.isdecimal()):
                raise ValueError("屏幕 ID 配置无效")
            self.regions = regions
            self.values["adb"].set(config["adb"])
            self.serial.set(config["serial"])
            self.resetDisplays()
            if displayId:
                self.screenBox.configure(values=["自动选择主屏", displayId])
                self.screen.set(displayId)
            for key, value in asdict(settings).items():
                self.values[key].set(value)
            self.redraw()
            self.status.set("配置已加载。开始前请确认设备与屏幕方向。")
            logger.info("配置读取成功，区域数=%s", len(regions))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.error(exc)

    def poll(self):
        for _ in range(300):
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                self.logBox.configure(state="normal")
                self.logBox.insert("end", value + "\n")
                if int(self.logBox.index("end-1c").split(".")[0]) > 1000:
                    self.logBox.delete("1.0", "101.0")
                self.logBox.see("end")
                self.logBox.configure(state="disabled")
            elif event == "done":
                self.setBusy(False)
            elif event == "error":
                self.status.set("操作失败，任务已停止。")
                if not self.closing:
                    self.error(value)
            elif event == "devices":
                self.deviceBox.configure(values=value)
                if self.serial.get() not in value:
                    self.serial.set(value[0] if value else "")
                    self.resetDisplays()
                self.status.set(f"找到 {len(value)} 台可用设备" if value else "未找到可用设备，请检查 USB 调试及手机授权。")
            elif event == "displays":
                selectedId = self.client().physicalDisplayId
                self.screenBox.configure(values=["自动选择主屏"] + [item.label for item in value])
                selected = next((item for item in value if item.physicalId == selectedId), None)
                self.screen.set(selected.label if selected else "自动选择主屏")
                self.status.set(f"找到 {len(value)} 块屏幕，请按尺寸和点亮状态选择。折叠状态改变后请重新采集并框选。")
            elif event == "screenshot" and not self.closing:
                self.showScreenshot(value)
                self.status.set("截图已打开，请拖动框选。")
            elif event == "status":
                self.status.set(value)
            elif event == "finished":
                self.status.set(f"{'已停止' if self.stopEvent.is_set() else '任务完成'}，累计点击 {value} 次。")
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.stop()


if __name__ == "__main__":
    root = tk.Tk()
    ClickerApp(root)
    root.mainloop()
