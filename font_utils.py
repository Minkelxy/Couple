"""公共字体加载工具：Windows 中文字体优先列表 + LRU 缓存。

替代 image_processor / report_generator / map_renderer 中重复的字体加载逻辑。
"""
from __future__ import annotations

import functools
from pathlib import Path

from PIL import ImageFont

from common_utils import get_logger

# Windows 常见中文字体路径，按优先级尝试
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑粗
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
]

# macOS / Linux 候选（开发环境兜底）
_FONT_CANDIDATES += [
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@functools.lru_cache(maxsize=16)
def _resolve_font_path() -> str | None:
    """找到第一个存在的候选字体路径，缓存结果。"""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


@functools.lru_cache(maxsize=32)
def load_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """加载指定字号字体，返回 (font, has_cjk)。

    has_cjk 为 True 表示找到了中文字体，False 表示回退到 PIL 默认（可能乱码，
    调用方可据此切换英文文案）。
    """
    path = _resolve_font_path()
    if path is not None:
        try:
            return ImageFont.truetype(path, size), True
        except OSError as e:
            get_logger().warning("加载字体失败 %s: %s", path, e)
    return ImageFont.load_default(), False


def clear_cache() -> None:
    """清空字体缓存（一般在测试或字体目录变更时调用）。"""
    _resolve_font_path.cache_clear()
    load_font.cache_clear()
