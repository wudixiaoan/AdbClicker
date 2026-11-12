"""ADB 随机点击任务及可独立测试的配置模型。"""

from dataclasses import dataclass
import logging
import math
import random
import re
import struct
import subprocess

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Display:
    physicalId: str
    logicalId: int
    width: int
    height: int
    state: str

    @property
    def label(self):
        state = "已点亮" if self.state == "ON" else f"未点亮({self.state})"
        return f"屏幕 {self.logicalId} · {self.width}×{self.height} · {state} | {self.physicalId}"


def parseDisplays(output):
    displays = {}
    for line in output.splitlines():
        if "mBaseDisplayInfo=DisplayInfo{" not in line:
            continue
        logical = re.search(r"\bdisplayId\s+(\d+)", line)
        physical = re.search(r'\buniqueId\s+"local:(\d+)"', line)
        size = re.search(r"\breal\s+(\d+)\s*x\s*(\d+)", line)
        state = re.search(r"\bstate\s+(\w+)", line)
        if logical and physical and size and state:
            item = Display(physical[1], int(logical[1]), int(size[1]), int(size[2]), state[1])
            displays[item.logicalId] = item
    return sorted(displays.values(), key=lambda item: item.logicalId)


@dataclass(frozen=True)
class Region:
    name: str
    x1: int
    y1: int
    x2: int
    y2: int
    minClicks: int = 1
    maxClicks: int = 1

    def validate(self, width=None, height=None):
        values = (self.x1, self.y1, self.x2, self.y2, self.minClicks, self.maxClicks)
        if any(type(value) is not int for value in values):
            raise ValueError("坐标和点击次数必须是整数")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("区域名称不能为空")
        if not (0 <= self.x1 <= self.x2 and 0 <= self.y1 <= self.y2):
            raise ValueError(f"区域 {self.name}：坐标必须非负，左上角不能大于右下角")
        if not 1 <= self.minClicks <= self.maxClicks <= 10000:
            raise ValueError(f"区域 {self.name}：点击次数应为 1～10000，最小值不能大于最大值")
        if width is not None and (self.x2 >= width or self.y2 >= height):
            raise ValueError(f"区域 {self.name} 超出屏幕 {width}×{height}")


@dataclass(frozen=True)
class Settings:
    intervalMin: float = 20.0
    intervalMax: float = 22.0
    gapMin: float = 0.2
    gapMax: float = 0.5
    rounds: int = 0
    regionGapMin: float = 1.0
    regionGapMax: float = 2.0

    def validate(self):
        for label, low, high in (("轮间隔", self.intervalMin, self.intervalMax),
                                 ("点击间隔", self.gapMin, self.gapMax),
                                 ("区域间隔", self.regionGapMin, self.regionGapMax)):
            if not all(type(value) in (int, float) and math.isfinite(value) for value in (low, high)):
                raise ValueError(f"{label}必须是有限数字")
            if not 0.05 <= low <= high <= 86400:
                raise ValueError(f"{label}应为 0.05～86400 秒，最小值不能大于最大值")
        if type(self.rounds) is not int or not 0 <= self.rounds <= 1000000:
            raise ValueError("循环轮数应为 0～1000000，0 表示无限循环")


class AdbClient:
    def __init__(self, executable="adb", serial="", physicalDisplayId=""):
        self.executable = executable
        self.serial = serial
        self.physicalDisplayId = physicalDisplayId
        self.logicalDisplayId = None

    def run(self, *args, binary=False, device=True):
        command = [self.executable]
        if device:
            if not self.serial:
                raise ValueError("请先选择设备")
            command += ["-s", self.serial]
        command += args
        logger.debug("执行 ADB 命令，参数=%s", args)
        try:
            result = subprocess.run(command, capture_output=True, timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.exception("ADB 执行失败")
            raise RuntimeError(f"ADB 执行失败：{exc}") from exc
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            logger.error("ADB 返回失败，退出码=%s，详情=%s", result.returncode, detail)
            raise RuntimeError(detail or f"ADB 退出码 {result.returncode}")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def devices(self):
        output = self.run("devices", device=False)
        devices = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == "device":
                devices.append(parts[0])
            elif len(parts) == 2 and parts[1] in ("offline", "unauthorized"):
                logger.warning("设备不可用，设备=%s，状态=%s", *parts)
        logger.info("设备刷新完成，可用设备数=%s", len(devices))
        return devices

    def displays(self):
        displays = parseDisplays(self.run("shell", "dumpsys", "display"))
        if not displays:
            raise RuntimeError("无法识别设备的物理屏幕与逻辑屏幕映射，请检查 dumpsys display 输出")
        logger.info("屏幕刷新完成，可选屏幕数=%s", len(displays))
        return displays

    def screenshot(self):
        # 折叠后物理屏与逻辑屏的映射可能互换，每次采集都重新解析。
        self.logicalDisplayId = None
        displays = self.displays()
        selected = next((item for item in displays if (
            item.physicalId == self.physicalDisplayId if self.physicalDisplayId else item.logicalId == 0)), None)
        if selected is None:
            raise RuntimeError("所选屏幕已不可用，请刷新屏幕列表后重新选择")
        if selected.state != "ON":
            raise RuntimeError("所选屏幕未点亮，请在手机上切换到该屏幕，或选择已点亮的屏幕后重新采集")
        logger.info("采集所选屏幕，物理屏幕=%s，逻辑屏幕=%s，尺寸=%s×%s",
                    selected.physicalId, selected.logicalId, selected.width, selected.height)
        data = self.run("exec-out", "screencap", "-p", "-d", selected.physicalId, binary=True)
        # 部分设备会将多显示屏警告写入 stdout，exec-out 会把它与 PNG 一起返回。
        pngOffset = data.find(b"\x89PNG\r\n\x1a\n")
        if pngOffset < 0:
            logger.error("截图缺少 PNG 标识，返回字节数=%s，数据头=%s", len(data), data[:32].hex())
            raise RuntimeError(f"设备未返回有效 PNG 截图（返回 {len(data)} 字节，未找到 PNG 标识）")
        if pngOffset:
            logger.warning("截图包含前置提示，已跳过 %s 字节并提取 PNG 图片", pngOffset)
            data = data[pngOffset:]
        if len(data) < 33 or data[8:16] != b"\x00\x00\x00\x0dIHDR":
            raise RuntimeError("设备返回的 PNG 截图头不完整或格式无效")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height:
            raise RuntimeError("截图尺寸无效")
        self.logicalDisplayId = selected.logicalId
        logger.info("读取截图完成，尺寸=%s×%s", width, height)
        return data, width, height

    def tap(self, x, y):
        if self.logicalDisplayId is None:
            raise RuntimeError("请先采集屏幕，确认点击目标屏幕")
        self.run("shell", "input", "-d", str(self.logicalDisplayId), "tap", str(x), str(y))


def runTask(client, regions, settings, stopEvent, report, rng=None):
    """每轮等待后按区域顺序点击；停止后不再发送新的点击。"""
    rng = rng or random.Random()
    settings.validate()
    if not regions:
        raise ValueError("请至少添加一个区域")
    _, width, height = client.screenshot()
    for region in regions:
        region.validate(width, height)
    roundIndex = 0
    totalClicks = 0
    while not stopEvent.is_set() and (settings.rounds == 0 or roundIndex < settings.rounds):
        delay = rng.uniform(settings.intervalMin, settings.intervalMax)
        report(f"等待 {delay:.2f} 秒后开始第 {roundIndex + 1} 轮")
        if stopEvent.wait(delay):
            break
        roundIndex += 1
        logger.info("循环开始，轮次=%s，区域数=%s", roundIndex, len(regions))
        for regionIndex, region in enumerate(regions):
            if regionIndex:
                regionDelay = rng.uniform(settings.regionGapMin, settings.regionGapMax)
                report(f"区域间等待 {regionDelay:.2f} 秒，接下来执行 {region.name}")
                if stopEvent.wait(regionDelay):
                    return totalClicks
            count = rng.randint(region.minClicks, region.maxClicks)
            logger.info("区域点击开始，轮次=%s，区域=%s，次数=%s", roundIndex, region.name, count)
            for clickIndex in range(count):
                if clickIndex and stopEvent.wait(rng.uniform(settings.gapMin, settings.gapMax)):
                    return totalClicks
                if stopEvent.is_set():
                    return totalClicks
                x = rng.randint(region.x1, region.x2)
                y = rng.randint(region.y1, region.y2)
                client.tap(x, y)
                totalClicks += 1
                report(f"第 {roundIndex} 轮 · {region.name} · {clickIndex + 1}/{count} · ({x}, {y}) · 总计 {totalClicks} 次")
                logger.info("点击完成，区域=%s，坐标=(%s,%s)，累计=%s", region.name, x, y, totalClicks)
        logger.info("循环完成，轮次=%s，累计点击=%s", roundIndex, totalClicks)
    return totalClicks
