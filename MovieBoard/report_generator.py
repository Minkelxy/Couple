"""年度观影报告生成：用 Pillow 绘制轻量长图。

内容含：已看数量、评分最高影片、类型分布（文字列表）、双人评分差异最大影片。
中文字体优先加载 Windows 自带字体，失败则降级为英文，避免 PIL 默认字体乱码。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

import app_paths
import font_utils
from . import store

_WIDTH = 800
_MARGIN_X = 60
_BG_TOP = (245, 247, 250)      # #f5f7fa
_BG_BOTTOM = (255, 255, 255)   # #ffffff
_PINK = (232, 93, 117)         # #e85d75
_DARK = (38, 50, 56)            # #263238
_GRAY = (123, 135, 148)        # #7b8794

# 常见影视类型关键词（用于从简介里解析类型分布）
_GENRES = [
    "剧情", "喜剧", "爱情", "动作", "科幻", "悬疑", "惊悚", "恐怖",
    "动画", "纪录片", "历史", "战争", "犯罪", "冒险", "奇幻", "家庭",
    "音乐", "传记", "武侠", "古装", "歌舞", "短片",
]


def _load_font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """通过公共 font_utils 加载字体（带 LRU 缓存）。"""
    return font_utils.load_font(size)


def _gradient_bg(height: int) -> Image.Image:
    """生成竖向浅灰白背景图（800 x height）。"""
    height = max(height, 320)
    col = Image.new("RGB", (1, height), _BG_TOP)
    px = col.load()
    for y in range(height):
        t = y / max(1, height - 1)
        r = int(_BG_TOP[0] + (_BG_BOTTOM[0] - _BG_TOP[0]) * t)
        g = int(_BG_TOP[1] + (_BG_BOTTOM[1] - _BG_TOP[1]) * t)
        b = int(_BG_TOP[2] + (_BG_BOTTOM[2] - _BG_TOP[2]) * t)
        px[0, y] = (r, g, b)
    return col.resize((_WIDTH, height))


def _wrap(text: str, font, max_width: float) -> list[str]:
    """按字符宽度换行（适配中文无空格场景）。"""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for ch in paragraph:
            test = cur + ch
            if font.getlength(test) > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    return lines


def _line_height(font) -> int:
    size = getattr(font, "size", 16)
    return int(size * 1.5)


def _year_of(movie: dict) -> Optional[int]:
    added = movie.get("added_at") or ""
    try:
        return datetime.fromisoformat(added).year
    except (ValueError, TypeError):
        return None


def _avg_rating(movie: dict) -> Optional[float]:
    vals = [v for v in (movie.get("rating_mine"), movie.get("rating_partner"))
            if isinstance(v, int)]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _best_rated(watched: list[dict]) -> Optional[dict]:
    best: Optional[tuple[float, dict]] = None
    for m in watched:
        a = _avg_rating(m)
        if a is None:
            continue
        if best is None or a > best[0]:
            best = (a, m)
    if not best:
        return None
    return {"title": best[1].get("title", ""), "score": round(best[0], 1)}


def _genre_dist(watched: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for m in watched:
        intro = m.get("intro") or ""
        for g in _GENRES:
            if g in intro:
                counts[g] = counts.get(g, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]


def _max_diff(watched: list[dict]) -> Optional[dict]:
    best: Optional[dict] = None
    for m in watched:
        a = m.get("rating_mine")
        b = m.get("rating_partner")
        if isinstance(a, int) and isinstance(b, int):
            gap = abs(a - b)
            if best is None or gap > best["gap"]:
                best = {
                    "title": m.get("title", ""),
                    "mine": a,
                    "partner": b,
                    "gap": gap,
                }
    return best


def generate_year_report(year: int) -> str:
    """生成 {year} 年度观影报告长图，返回保存路径。"""
    watched = [
        m for m in store.list_all()
        if m.get("status") == store.STATUS_WATCHED and _year_of(m) == year
    ]

    f_title, has_cjk = _load_font(36)
    f_sub = _load_font(16)[0]
    f_head = _load_font(22)[0]
    f_body = _load_font(18)[0]

    def t(zh: str, en: str) -> str:
        return zh if has_cjk else en

    count = len(watched)
    best = _best_rated(watched)
    genres = _genre_dist(watched)
    diff = _max_diff(watched)

    content_w = _WIDTH - _MARGIN_X * 2
    # block: dict(text, font, color, align, space_before, wrap)
    blocks: list[dict] = []
    blocks.append({
        "text": t(f"我们的 {year} 观影报告", f"Our {year} Movie Report"),
        "font": f_title, "color": _PINK, "align": "center",
        "space_before": 50, "wrap": True,
    })
    blocks.append({
        "text": "CoupleSuite · " + t("影视看板", "Movie Board"),
        "font": f_sub, "color": _GRAY, "align": "center",
        "space_before": 8, "wrap": False,
    })
    blocks.append({
        "text": t("🎬 本年观影总结", "Movie Summary"),
        "font": f_head, "color": _PINK, "align": "left",
        "space_before": 36, "wrap": False,
    })
    blocks.append({
        "text": t(f"今年已看：{count} 部", f"Watched this year: {count}"),
        "font": f_body, "color": _DARK, "align": "left",
        "space_before": 14, "wrap": True,
    })
    if best:
        blocks.append({
            "text": t(f"评分最高：{best['title']}（{best['score']} 分）",
                      f"Top rated: {best['title']} ({best['score']})"),
            "font": f_body, "color": _DARK, "align": "left",
            "space_before": 8, "wrap": True,
        })
    else:
        blocks.append({
            "text": t("评分最高：暂无评分数据", "Top rated: no ratings yet"),
            "font": f_body, "color": _GRAY, "align": "left",
            "space_before": 8, "wrap": True,
        })
    blocks.append({
        "text": t("🏷 类型分布", "Genre Distribution"),
        "font": f_head, "color": _PINK, "align": "left",
        "space_before": 30, "wrap": False,
    })
    if genres:
        for g, c in genres:
            blocks.append({
                "text": t(f"{g}：{c} 部", f"{g}: {c}"),
                "font": f_body, "color": _DARK, "align": "left",
                "space_before": 8, "wrap": True,
            })
    else:
        blocks.append({
            "text": t("暂无类型数据", "No genre data"),
            "font": f_body, "color": _GRAY, "align": "left",
            "space_before": 8, "wrap": True,
        })
    blocks.append({
        "text": t("💥 评分差异之最", "Biggest Rating Gap"),
        "font": f_head, "color": _PINK, "align": "left",
        "space_before": 30, "wrap": False,
    })
    if diff:
        blocks.append({
            "text": t(
                f"{diff['title']}（我 {diff['mine']} vs 对方 {diff['partner']}，差 {diff['gap']} 分）",
                f"{diff['title']} (Me {diff['mine']} vs TA {diff['partner']}, gap {diff['gap']})",
            ),
            "font": f_body, "color": _DARK, "align": "left",
            "space_before": 14, "wrap": True,
        })
    else:
        blocks.append({
            "text": t("暂无双方评分数据", "No dual-rating data yet"),
            "font": f_body, "color": _GRAY, "align": "left",
            "space_before": 14, "wrap": True,
        })

    # 两遍：先测高，再绘制
    total_h = 0
    for b in blocks:
        total_h += b["space_before"]
        lines = _wrap(b["text"], b["font"], content_w) if b["wrap"] else [b["text"]]
        total_h += len(lines) * _line_height(b["font"])
    total_h += 50  # 底部留白

    img = _gradient_bg(total_h)
    draw = ImageDraw.Draw(img)
    y = 0
    for b in blocks:
        y += b["space_before"]
        lines = _wrap(b["text"], b["font"], content_w) if b["wrap"] else [b["text"]]
        for line in lines:
            if b["align"] == "center":
                w = b["font"].getlength(line)
                x = (_WIDTH - w) / 2
            else:
                x = _MARGIN_X
            draw.text((x, y), line, font=b["font"], fill=b["color"])
            y += _line_height(b["font"])

    dest = app_paths.MOVIES_DIR / f"report_{year}.png"
    img.save(dest)
    return str(dest)
