"""公共字体加载工具：跨平台中文字体优先列表 + LRU 缓存。

替代 image_processor / report_generator / map_renderer 中重复的字体加载逻辑。
"""
from __future__ import annotations

import functools
from pathlib import Path

from PIL import ImageFont

from common_utils import get_logger

# CJK 字体路径，按优先级尝试
_CJK_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑粗
    r"C:\Windows\Fonts\simhei.ttf",    # 黑体
    r"C:\Windows\Fonts\simsun.ttc",    # 宋体
]

# macOS / Linux 常见 CJK 字体
_CJK_FONT_CANDIDATES += [
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# 非 CJK 回退字体：用于英文输出，不能标记为 has_cjk=True。
_FALLBACK_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@functools.lru_cache(maxsize=16)
def _resolve_font_path() -> str | None:
    """找到第一个存在的 CJK 字体路径，缓存结果。"""
    for path in _CJK_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


@functools.lru_cache(maxsize=1)
def _resolve_fallback_font_path() -> str | None:
    """找到普通拉丁字体回退路径，缓存结果。"""
    for path in _FALLBACK_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


@functools.lru_cache(maxsize=32)
def load_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """加载指定字号字体，返回 (font, has_cjk)。

    has_cjk 为 True 表示找到了中文字体，False 表示使用普通拉丁字体回退，
    调用方可据此切换英文文案）。
    """
    cjk_path = _resolve_font_path()
    if cjk_path is not None:
        try:
            return ImageFont.truetype(cjk_path, size), True
        except OSError as e:
            get_logger().warning("加载 CJK 字体失败 %s: %s", cjk_path, e)
    fallback_path = _resolve_fallback_font_path()
    if fallback_path is not None:
        try:
            return ImageFont.truetype(fallback_path, size), False
        except OSError as e:
            get_logger().warning("加载回退字体失败 %s: %s", fallback_path, e)
    return ImageFont.load_default(), False


def get_cjk_font_path() -> str | None:
    """Return the discovered CJK font path for libraries needing a file path."""
    return _resolve_font_path()


def clear_cache() -> None:
    """清空字体缓存（一般在测试或字体目录变更时调用）。"""
    _resolve_font_path.cache_clear()
    _resolve_fallback_font_path.cache_clear()
    load_font.cache_clear()
