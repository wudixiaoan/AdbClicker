"""ADB 随机点击任务及可独立测试的配置模型。"""

from dataclasses import dataclass
import logging
import math
import random
import struct
import subprocess

logger = logging.getLogger(__name__)


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
    def __init__(self, executable="adb", serial=""):
        self.executable = executable
        self.serial = serial

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

    def screenshot(self):
        data = self.run("exec-out", "screencap", "-p", binary=True)
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("设备未返回有效 PNG 截图")
        width, height = struct.unpack(">II", data[16:24])
        if not width or not height:
            raise RuntimeError("截图尺寸无效")
        logger.info("读取截图完成，尺寸=%s×%s", width, height)
        return data, width, height

    def tap(self, x, y):
        self.run("shell", "input", "tap", str(x), str(y))


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
