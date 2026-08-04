"""豆瓣影视抓取：Playwright 同步搜索 + 海报下载。

所有函数在失败时返回 None，不抛异常，确保 UI 不会因抓取失败而崩溃。
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from typing import Optional

import app_paths

_SEARCH_URL = "https://search.douban.com/movie/subject_search?search_text={query}"
_PAGE_TIMEOUT_MS = 15000
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 在浏览器中执行的提取脚本：从第一个 /subject/<id>/ 链接解析信息
_EXTRACT_JS = r"""() => {
    const links = document.querySelectorAll('a[href*="/subject/"]');
    for (const a of links) {
        const m = a.href.match(/\/subject\/(\d+)/);
        if (!m) continue;
        const douban_id = m[1];
        let item = a.closest('.item') || a.closest('.result')
                  || a.closest('div') || a.parentElement;
        let title = (a.textContent || '').trim();
        let poster_url = '';
        let intro = '';
        if (item) {
            const img = item.querySelector('img');
            if (img) poster_url = img.src || img.getAttribute('data-src') || '';
            const introEl = item.querySelector('.cast, .abstract, p, .rating');
            if (introEl) intro = (introEl.textContent || '').trim();
        }
        if (title.length > 0) {
            return {douban_id, title, poster_url, intro};
        }
    }
    return null;
}"""


def search_movie(title: str) -> Optional[dict]:
    """搜索豆瓣，返回首个结果的 {douban_id, title, poster_url, intro}，失败返回 None。"""
    query = urllib.parse.quote(title)
    url = _SEARCH_URL.format(query=query)
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=_USER_AGENT)
                page.set_default_timeout(_PAGE_TIMEOUT_MS)
                page.goto(
                    url, timeout=_PAGE_TIMEOUT_MS, wait_until="domcontentloaded"
                )
                # 等待结果渲染（豆瓣搜索页是 JS 渲染）
                try:
                    page.wait_for_selector('a[href*="/subject/"]', timeout=_PAGE_TIMEOUT_MS)
                except Exception:
                    pass
                info = page.evaluate(_EXTRACT_JS)
                if not info or not info.get("douban_id"):
                    return None
                return {
                    "douban_id": str(info.get("douban_id", "")),
                    "title": (info.get("title") or "").strip() or title,
                    "poster_url": info.get("poster_url", "") or "",
                    "intro": (info.get("intro") or "").strip(),
                }
            finally:
                browser.close()
    except Exception:
        return None


def download_poster(url: str, douban_id: str) -> Optional[str]:
    """下载海报到 posters/{douban_id}.jpg，返回本地路径，失败返回 None。"""
    if not url or not douban_id:
        return None
    posters_dir = app_paths.MOVIES_DIR / "posters"
    posters_dir.mkdir(parents=True, exist_ok=True)
    dest = posters_dir / f"{douban_id}.jpg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_PAGE_TIMEOUT_MS / 1000) as resp:
            data = resp.read()
        if not data:
            return None
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        return None
