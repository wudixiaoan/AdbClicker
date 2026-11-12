"""通过官方 scrcpy 客户端提供支持鼠标操作的视频预览。"""

import logging
import os
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger(__name__)


def scrcpyPath():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent / "vendor"
    return base / "scrcpy" / "scrcpy.exe"


def previewCommand(client, displayId):
    return [str(scrcpyPath()), f"--serial={client.serial}", f"--display-id={displayId}",
            "--mouse=sdk", "--keyboard=disabled", "--no-clipboard-autosync",
            "--no-audio", "--max-size=1280", "--max-fps=30", "--video-bit-rate=4M",
            "--hwdec=disabled",
            "--no-window-aspect-ratio-lock", "--render-fit=letterbox",
            "--window-title=ADB Clicker - Live Preview", "--window-width=480"]


def runPreview(client, stopEvent, report):
    executable = scrcpyPath()
    if not executable.is_file():
        raise RuntimeError("缺少内置 scrcpy，请完整解压新版便携包并保留 scrcpy 文件夹")
    displays = client.displays(quiet=True)
    selected = next((item for item in displays if (
        item.physicalId == client.physicalDisplayId if client.physicalDisplayId else item.logicalId == 0)), None)
    if selected is None or selected.state != "ON":
        raise RuntimeError("所选屏幕不存在或未点亮，请刷新屏幕并选择已点亮的屏幕")
    if stopEvent.is_set():
        return
    environment = os.environ.copy()
    environment["ADB"] = client.executable
    environment["SCRCPY_SERVER_PATH"] = str(executable.parent / "scrcpy-server")
    logger.info("开始视频预览，逻辑屏幕=%s，物理屏幕=%s，最大帧率=30，鼠标控制已开启", selected.logicalId, selected.physicalId)
    process = subprocess.Popen(previewCommand(client, selected.logicalId), cwd=executable.parent,
                               env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        report("视频预览进程已启动，正在连接手机…")
        while True:
            if stopEvent.is_set():
                if process.poll() is None:
                    process.terminate()
                output, _ = process.communicate(timeout=5)
                break
            try:
                output, _ = process.communicate(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                continue
        if not stopEvent.is_set() and process.returncode:
            detail = output.decode("utf-8", errors="replace")[-2500:]
            raise RuntimeError(f"scrcpy 退出码 {process.returncode}：{detail}")
        logger.info("视频预览已结束，退出码=%s", process.returncode)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            process.stdout.close()
