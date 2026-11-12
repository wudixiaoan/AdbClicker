"""配置目录管理和原子写入。"""

import json
import logging
from pathlib import Path
import re
import sys
import tempfile

logger = logging.getLogger(__name__)


def defaultConfigDirectory():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "configs"


def writeConfig(path, config):
    path = Path(path)
    data = json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        logger.info("开始写入配置，路径=%s", path)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=".config-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
        logger.info("配置写入成功，路径=%s", path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ConfigStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    def path(self, name):
        name = name.strip()
        if (not name or name.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
                or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                                                   *[f"LPT{i}" for i in range(1, 10)]}):
            raise ValueError("配置名称无效，请使用普通文件名，不要包含路径或特殊字符")
        path = self.directory / f"{name}.json"
        if path.resolve().parent != self.directory:
            raise ValueError("配置文件必须位于指定配置目录内")
        return path

    def names(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        return sorted((path.stem for path in self.directory.glob("*.json")
                       if path.is_file() and path.resolve().parent == self.directory), key=str.casefold)

    def delete(self, name):
        path = self.path(name)
        logger.info("开始删除配置，路径=%s", path)
        path.unlink()
        logger.info("配置删除成功，路径=%s", path)
