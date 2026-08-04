"""Pillow 图片处理：拍立得边框 + 日期水印 + 圆角 + EXIF + cover + 转 QPixmap。"""
from __future__ import annotations

import io
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PySide6.QtGui import QPixmap

import font_utils
from common_utils import log_exception

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tiff"}


def list_images(image_dir: str) -> list[Path]:
    """枚举目录下所有支持的图片文件，按文件名排序。"""
    root = Path(image_dir)
    if not root.exists():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """通过公共 font_utils 加载字体（带缓存）。"""
    return font_utils.load_font(size)[0]


def round_corners(img: Image.Image, radius: int) -> Image.Image:
    """给图片加圆角遮罩，保持 RGBA。"""
    if radius <= 0:
        return img.convert("RGBA")
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, img.size[0], img.size[1]), radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def apply_polaroid(img: Image.Image, padding: int = 24, bottom: int = 64) -> Image.Image:
    """加拍立得风格白边（底部更宽）。"""
    img = img.convert("RGBA")
    w, h = img.size
    new_w, new_h = w + padding * 2, h + padding + bottom
    canvas = Image.new("RGBA", (new_w, new_h), (255, 255, 255, 255))
    canvas.paste(img, (padding, padding), img if img.mode == "RGBA" else None)
    return canvas


def add_watermark(img: Image.Image, text: str, accent_rgb: tuple[int, int, int] | None = None) -> Image.Image:
    """在右下角加日期水印。accent_rgb 给定则用主题色半透明底。"""
    img = img.convert("RGBA")
    w, h = img.size
    font = _load_font(max(14, min(28, w // 20)))
    draw = ImageDraw.Draw(img)
    # 透明黑底 + 白字，提高对比度；纪念日用主题色
    if accent_rgb is None:
        bg = (0, 0, 0, 140)
    else:
        bg = (accent_rgb[0], accent_rgb[1], accent_rgb[2], 175)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = 10
    rx0, ry0 = w - tw - margin * 2 - 4, h - th - margin * 2 - 4
    rx1, ry1 = w - 4, h - 4
    draw.rounded_rectangle((rx0, ry0, rx1, ry1), radius=6, fill=bg)
    draw.text((rx0 + margin, ry0 + margin - 2), text, font=font, fill=(255, 255, 255, 235))
    return img


def fit_into(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """等比缩放到目标尺寸内。"""
    img = img.convert("RGBA")
    w, h = img.size
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return img
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size, Image.LANCZOS)


def fit_cover(img: Image.Image, target_w: int, target_h: int, scale: float = 1.15) -> Image.Image:
    """cover 模式：等比放大填满目标区域并居中裁剪，比目标大 scale 倍（供 Ken Burns 平移）。"""
    img = img.convert("RGBA")
    w, h = img.size
    tw, th = int(target_w * scale), int(target_h * scale)
    s = max(tw / w, th / h)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    img = img.resize((nw, nh), Image.LANCZOS)
    # 居中裁剪到 tw x th
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def fit_with_blur_background(
    img: Image.Image,
    target_w: int,
    target_h: int,
    blur_radius: int = 30,
    dim: int = 40,
) -> Image.Image:
    """Instagram 风格：模糊放大背景 + 前景 contain 完整原图，无留白。

    - 背景：原图 cover 模式放大到 target_w × target_h + 高斯模糊 + 轻微变暗
    - 前景：原图 contain 等比缩放到 target_w × target_h 内（不放大）居中粘贴
    - 适合竖图在横屏 / 横图在竖屏时填充空白
    """
    img = img.convert("RGBA")
    w, h = img.size
    tw, th = max(1, int(target_w)), max(1, int(target_h))

    # 背景：cover 放大填满 + 模糊 + 变暗
    s_bg = max(tw / w, th / h)
    bw, bh = max(1, int(w * s_bg)), max(1, int(h * s_bg))
    bg = img.resize((bw, bh), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    # 居中裁剪到 tw × th
    left = (bw - tw) // 2
    top = (bh - th) // 2
    bg = bg.crop((left, top, left + tw, top + th))
    # 加半透明黑色叠层让前景更突出（dim 越大越暗）
    if dim > 0:
        overlay = Image.new("RGBA", (tw, th), (0, 0, 0, min(255, dim)))
        bg = Image.alpha_composite(bg, overlay)

    # 前景：contain 缩放（不放大，原图小于目标时保持原尺寸居中）
    scale_fg = min(tw / w, th / h, 1.0)
    fw, fh = max(1, int(w * scale_fg)), max(1, int(h * scale_fg))
    fg = img.resize((fw, fh), Image.LANCZOS)
    px = (tw - fw) // 2
    py = (th - fh) // 2
    bg.alpha_composite(fg, (px, py))
    return bg


# EXIF 标签
_EXIF_DATE_ORIG = 0x9003   # DateTimeOriginal
_EXIF_DATE_DIG = 0x9004    # DateTimeDigitized
_EXIF_MAKE = 0x010F
_EXIF_MODEL = 0x0110


def read_exif_info(src: Path) -> str:
    """读取拍摄日期 + 机型，返回简短字符串；无则空串。"""
    try:
        with Image.open(src) as im:
            exif = im.getexif()
    except Exception:
        log_exception("读取 EXIF 失败: %s", src)
        return ""
    if not exif:
        return ""
    parts: list[str] = []
    date = exif.get(_EXIF_DATE_ORIG) or exif.get(_EXIF_DATE_DIG)
    if date:
        # 形如 "2023:08:14 18:22:05"
        date = str(date).replace(":", "-", 2).split(" ", 1)[0]
        parts.append(date)
    make = (exif.get(_EXIF_MAKE) or "").strip()
    model = (exif.get(_EXIF_MODEL) or "").strip()
    if make or model:
        parts.append(f"{make} {model}".strip())
    return "  ·  ".join(parts)


class PixmapCache:
    """LRU QPixmap 缓存，按处理选项 key 命中。"""

    def __init__(self, capacity: int = 50):
        self._capacity = capacity
        self._cache: OrderedDict[tuple, QPixmap] = OrderedDict()

    def _make_key(self, src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_bg):
        return (str(src), target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_bg)

    def get(self, src, target_w, target_h, *, polaroid, watermark, corner_radius, ken_burns=False, accent_rgb=None, blur_background=False):
        key = self._make_key(src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_background)
        if key in self._cache:
            self._cache.move_to_end(key)  # LRU 更新
            return self._cache[key]
        return None

    def put(self, src, target_w, target_h, pixmap, *, polaroid, watermark, corner_radius, ken_burns=False, accent_rgb=None, blur_background=False):
        key = self._make_key(src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_background)
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        # LRU 淘汰
        while len(self._cache) > self._capacity:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()


class PilPrefetchCache:
    """预生成的 PIL Image 缓存，供主线程 process_image 取用。线程安全。

    后台预生成线程 put，主线程 process_image pop 消费；key 同 PixmapCache。
    """

    def __init__(self, capacity: int = 10):
        self._capacity = capacity
        self._cache: dict[tuple, Image.Image] = {}
        self._lock = threading.Lock()

    def _make_key(self, src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_bg):
        return (str(src), target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_bg)

    def put(self, src, target_w, target_h, img, *, polaroid, watermark, corner_radius, ken_burns=False, accent_rgb=None, blur_background=False):
        key = self._make_key(src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_background)
        with self._lock:
            if len(self._cache) >= self._capacity and key not in self._cache:
                # 淘汰最旧一项（dict 保持插入序）
                oldest = next(iter(self._cache), None)
                if oldest is not None:
                    self._cache.pop(oldest, None)
            self._cache[key] = img

    def pop(self, src, target_w, target_h, *, polaroid, watermark, corner_radius, ken_burns=False, accent_rgb=None, blur_background=False):
        key = self._make_key(src, target_w, target_h, polaroid, watermark, corner_radius, ken_burns, accent_rgb, blur_background)
        with self._lock:
            return self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


# 全局单例
_cache = PixmapCache(capacity=50)
_pil_prefetch = PilPrefetchCache(capacity=10)


def get_cache() -> PixmapCache:
    return _cache


def process_to_pil(
    src: Path,
    target_w: int,
    target_h: int,
    *,
    polaroid: bool,
    watermark: bool,
    corner_radius: int,
    ken_burns: bool = False,
    accent_rgb: tuple[int, int, int] | None = None,
    blur_background: bool = False,
) -> tuple[Image.Image, bool] | None:
    """纯 PIL 处理管线（线程安全，不碰 QPixmap）。

    加载 → 拍立得边框 → 缩放 → 水印 → 圆角。返回 (PIL Image, ken_burns 标志)；
    加载失败返回 None。ken_burns=True 时用 cover 模式放大 15% 供平移，且不画圆角。
    blur_background=True 且非 ken_burns 时用模糊背景填充（contain 前景 + 模糊 cover 背景），
    适合竖图在横屏 / 横图在竖屏时无留白。
    """
    try:
        with Image.open(src) as src_img:
            src_img.load()
            # 立刻 copy 出来，with 块退出后文件句柄被释放，img 仍可正常使用
            img = src_img.copy()
    except Exception:
        log_exception("打开图片失败: %s", src)
        return None

    # 先加拍立得边框（在原始分辨率下，避免边框被压缩）
    if polaroid:
        img = apply_polaroid(img)

    if ken_burns:
        # cover 模式：填满并放大，供 Ken Burns 平移；不画圆角（由 label clip）
        img = fit_cover(img, target_w, target_h, scale=1.15)
    elif blur_background:
        # 模糊背景填充：背景 cover+blur，前景 contain，无留白；不画圆角（已铺满）
        img = fit_with_blur_background(img, target_w, target_h)
    else:
        img = fit_into(img, target_w, target_h)

    if watermark:
        date_text = datetime.now().strftime("%Y-%m-%d")
        img = add_watermark(img, date_text, accent_rgb=accent_rgb)

    if corner_radius > 0 and not ken_burns and not blur_background:
        img = round_corners(img, corner_radius)

    return (img, ken_burns)


def pil_to_pixmap(img: Image.Image) -> QPixmap:
    """PIL Image 转 QPixmap（主线程调用），用 PNG 中转最稳。"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buf.getvalue())
    return pixmap


def process_image(
    src: Path,
    target_w: int,
    target_h: int,
    *,
    polaroid: bool,
    watermark: bool,
    corner_radius: int,
    ken_burns: bool = False,
    accent_rgb: tuple[int, int, int] | None = None,
    blur_background: bool = False,
) -> QPixmap | None:
    """完整处理管线：加载 → 拍立得边框 → 缩放 → 水印 → 圆角 → QPixmap。

    带 LRU QPixmap 缓存；未命中时优先消费后台预生成的 PIL Image（_pil_prefetch），
    再不行才跑完整 PIL 管线。ken_burns=True 时用 cover 模式放大 15% 供平移，
    且不画圆角（圆角交给显示组件 clip）。blur_background=True 且非 ken_burns 时
    用模糊背景填充（Instagram 风格，无留白），优先级低于 ken_burns。
    """
    # 1. 查 QPixmap LRU 缓存
    cached = _cache.get(
        src, target_w, target_h,
        polaroid=polaroid, watermark=watermark, corner_radius=corner_radius,
        ken_burns=ken_burns, accent_rgb=accent_rgb,
        blur_background=blur_background,
    )
    if cached is not None:
        return cached

    # 2. 查预生成的 PIL Image 缓存（后台线程预生成的）
    pil_img = _pil_prefetch.pop(
        src, target_w, target_h,
        polaroid=polaroid, watermark=watermark, corner_radius=corner_radius,
        ken_burns=ken_burns, accent_rgb=accent_rgb,
        blur_background=blur_background,
    )
    if pil_img is None:
        # 3. 跑完整 PIL 管线
        result = process_to_pil(
            src, target_w, target_h,
            polaroid=polaroid, watermark=watermark, corner_radius=corner_radius,
            ken_burns=ken_burns, accent_rgb=accent_rgb,
            blur_background=blur_background,
        )
        if result is None:
            return None
        pil_img = result[0]

    # 4. PIL -> QPixmap（主线程）+ 写缓存
    pixmap = pil_to_pixmap(pil_img)
    if not pixmap.isNull():
        _cache.put(
            src, target_w, target_h, pixmap,
            polaroid=polaroid, watermark=watermark, corner_radius=corner_radius,
            ken_burns=ken_burns, accent_rgb=accent_rgb,
            blur_background=blur_background,
        )
    return pixmap
