"""豆瓣影视抓取：Playwright 同步搜索 + 海报下载。

所有函数在失败时返回 None，不抛异常，确保 UI 不会因抓取失败而崩溃。
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.request
from typing import Optional

import app_paths
from common_utils import (
    MAX_ATTACHMENT_BYTES,
    log_exception,
    log_warning,
    safe_filename,
)

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
        log_warning("playwright 未安装，无法抓取豆瓣")
        return None

    def _attempt_once() -> Optional[dict]:
        """单次抓取尝试：启动浏览器、加载页面、提取首个结果。

        每次调用都重新启动 playwright 与浏览器实例，避免复用已关闭的 browser。
        """
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
                    # 选择器未出现属于正常情况（无结果或慢），不记为错误
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

    # 指数退避重试：最多重试 2 次（总共 3 次尝试），间隔 1s、2s 递增
    # 触发重试条件：网络异常 或 解析结果为空（豆瓣风控常返回空页面）
    max_retries = 2
    for attempt in range(max_retries + 1):
        if attempt > 0:
            # 第 1 次重试前等 1s，第 2 次重试前等 2s
            time.sleep(attempt)
        try:
            result = _attempt_once()
        except Exception:
            # 网络异常（playwright timeout、连接错误等）→ 重试
            if attempt < max_retries:
                log_warning("豆瓣搜索网络异常，将重试（第 %d 次）: %s", attempt, title)
                continue
            log_exception("豆瓣搜索失败: %s", title)
            return None
        if result is not None:
            return result
        # 空结果（可能是风控空页面）→ 重试
        if attempt < max_retries:
            log_warning("豆瓣搜索无结果，将重试（第 %d 次）: %s", attempt, title)
            continue
        return None
    return None


def download_poster(url: str, douban_id: str) -> Optional[str]:
    """下载海报到 posters/{douban_id}.jpg，返回本地路径，失败返回 None。

    安全：流式读取并限制总大小（MAX_ATTACHMENT_BYTES），防止超大响应 OOM；
    douban_id 用 safe_filename 过滤（虽源自正则仅为数字，仍做防御）。
    """
    if not url or not douban_id:
        return None
    posters_dir = app_paths.MOVIES_DIR / "posters"
    posters_dir.mkdir(parents=True, exist_ok=True)
    safe_id = safe_filename(douban_id, fallback="poster")
    dest = posters_dir / f"{safe_id}.jpg"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            # Referer 指向豆瓣电影主站，降低海报 CDN 403 概率
            "Referer": "https://movie.douban.com/",
        })
        with urllib.request.urlopen(req, timeout=_PAGE_TIMEOUT_MS / 1000) as resp:
            # 分块读取，超限则中止，避免一次性 read() 撑爆内存
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ATTACHMENT_BYTES:
                    log_warning("海报过大（>%d 字节），已中止: %s", MAX_ATTACHMENT_BYTES, url)
                    return None
                chunks.append(chunk)
            data = b"".join(chunks)
        if not data:
            return None
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        log_exception("下载海报失败: %s", url)
        return None
