"""公共工具：日志、路径安全、附件大小校验。

供所有模块复用，避免重复实现和散落的 bare except。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Optional

# ---------- 日志 ----------

_logger: logging.Logger | None = None


def _log_file_namer(default_name: str) -> str:
    """TimedRotatingFileHandler 默认轮转名为 CoupleSuite.log.2026-08-05，
    重命名为 CoupleSuite-2026-08-05.log 更直观。
    """
    if ".log." in default_name:
        base, _, date = default_name.rpartition(".log.")
        return f"{base}-{date}.log"
    return default_name


def get_logger() -> logging.Logger:
    """返回应用级 logger，首次调用时配置。

    - stderr 控制台输出（打包后仍可见）
    - 文件输出：%APPDATA%/CoupleSuite/logs/CoupleSuite.log，按天滚动、保留 7 天
    - 级别 INFO，可被环境变量 COUPLE_LOG_LEVEL 覆盖
    """
    global _logger
    if _logger is not None:
        return _logger
    import os
    import sys

    logger = logging.getLogger("CoupleSuite")
    if not logger.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        # stderr 控制台
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        # 文件日志：按天滚动，保留 7 天
        try:
            from logging.handlers import TimedRotatingFileHandler
            log_dir = Path(
                os.environ.get("APPDATA", str(Path.home()))
            ) / "CoupleSuite" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = TimedRotatingFileHandler(
                log_dir / "CoupleSuite.log",
                when="midnight",
                backupCount=7,
                encoding="utf-8",
            )
            fh.setFormatter(fmt)
            fh.suffix = "%Y-%m-%d"
            fh.namer = _log_file_namer
            logger.addHandler(fh)
        except Exception:
            # 日志目录不可写时不影响程序运行，stderr 仍可用
            pass
    level_name = os.environ.get("COUPLE_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False
    _logger = logger
    return logger


def log_exception(msg: str, *args) -> None:
    """在 except 块中调用：记录异常 + traceback。"""
    get_logger().exception(msg, *args)


def log_warning(msg: str, *args) -> None:
    get_logger().warning(msg, *args)


def log_info(msg: str, *args) -> None:
    get_logger().info(msg, *args)


# ---------- 路径安全 ----------

# 文件名白名单：字母数字下划线短横点，最长 100 字符
_SAFE_NAME_RE = re.compile(r"[^\w.\-]")
# 允许的图片后缀（小写，含点）
_SAFE_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}


def safe_filename(name: str, fallback: str = "file") -> str:
    """把任意输入转为安全的纯文件名（去除路径分隔符和特殊字符）。

    - 取 Path(name).name 去掉目录部分
    - 把非法字符替换为下划线
    - 限制长度
    """
    if not isinstance(name, str) or not name:
        return fallback
    base = Path(name).name  # 去掉任何目录前缀
    if not base or base in (".", ".."):
        return fallback
    base = _SAFE_NAME_RE.sub("_", base)
    base = base.strip("._") or fallback
    return base[:100]


def safe_join(base: Path, user_input: str) -> Path | None:
    """把 user_input 安全拼到 base 下，路径遍历返回 None。

    用于读取场景：调用方需校验返回值非 None 后再使用。
    """
    if not user_input:
        return None
    try:
        base_resolved = base.resolve()
        target = (base / user_input).resolve()
    except (OSError, ValueError):
        return None
    # target 必须等于 base 或在 base 下
    if target != base_resolved and base_resolved not in target.parents:
        return None
    return target


def safe_image_ext(ext: str) -> str:
    """规范化图片后缀：返回小写含点形式，非图片后缀返回 .png。"""
    if not ext:
        return ".png"
    e = ext if ext.startswith(".") else "." + ext
    e = e.lower()
    return e if e in _SAFE_IMAGE_EXTS else ".png"


# ---------- 附件大小校验 ----------

# 单个附件上限：50 MB（局域网和云中转都用这个值）
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def check_attachment_size(data: bytes) -> Optional[str]:
    """校验附件字节大小，超限返回错误信息，正常返回 None。"""
    if data is None:
        return None
    n = len(data)
    if n > MAX_ATTACHMENT_BYTES:
        mb = n / (1024 * 1024)
        limit_mb = MAX_ATTACHMENT_BYTES / (1024 * 1024)
        return f"附件过大（{mb:.1f} MB > 上限 {limit_mb:.0f} MB），已拒绝"
    return None


# ---------- 原子写 JSON 存储 ----------


_ATOMIC_JSON_LOCKS: dict[str, threading.RLock] = {}
_ATOMIC_JSON_LOCKS_GUARD = threading.Lock()


def _lock_for_json_path(path: Path) -> threading.RLock:
    """Return one process-wide lock for each JSON path."""
    key = str(path.resolve())
    with _ATOMIC_JSON_LOCKS_GUARD:
        lock = _ATOMIC_JSON_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _ATOMIC_JSON_LOCKS[key] = lock
        return lock


def atomic_write_bytes(path, data: bytes) -> None:
    """Write bytes through a same-directory temporary file and atomic replace."""
    target = Path(path)
    lock = _lock_for_json_path(target)
    with lock:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_name = tmp.name
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_name, target)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


def atomic_copy_file(source, target) -> None:
    """Copy a file through a same-directory temporary file and replace."""
    source_path = Path(source)
    target_path = Path(target)
    lock = _lock_for_json_path(target_path)
    with lock:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target_path.parent,
                prefix=f".{target_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_name = tmp.name
            shutil.copy2(source_path, tmp_name)
            with open(tmp_name, "r+b") as tmp:
                os.fsync(tmp.fileno())
            os.replace(tmp_name, target_path)
        finally:
            if tmp_name:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass


class AtomicJsonStore:
    """线程安全的原子写 JSON 存储。

    使用临时文件 + os.replace 保证写入原子性,模块级锁串行化读改写。
    顶层可以是 dict 或 list(default 决定)。
    """

    def __init__(self, path, default=None):
        # path: Path 对象;default: 文件不存在/损坏时的默认值(通常 {} 或 [])
        self.path = Path(path)
        self.default = {} if default is None else default
        self._lock = _lock_for_json_path(self.path)

    def _default_value(self):
        # Callers may mutate a loaded default; never let that mutate the store.
        return deepcopy(self.default)

    def load(self):
        """加载 JSON,文件不存在或损坏返回 default(并 log_warning)。"""
        if not self.path.exists():
            return self._default_value()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            log_warning("JSON 文件损坏,返回默认值 %s: %s", self.path, e)
            return self._default_value()
        except UnicodeDecodeError as e:
            log_warning("invalid UTF-8 JSON, returning default %s: %s", self.path, e)
            return self._default_value()
        except OSError as e:
            log_warning("JSON 文件读取失败,返回默认值 %s: %s", self.path, e)
            return self._default_value()

    def save(self, data):
        """原子写入:写临时文件 .tmp -> os.replace 覆盖目标。"""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp:
                    tmp_name = tmp.name
                    json.dump(data, tmp, ensure_ascii=False, indent=2)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                os.replace(tmp_name, self.path)
            finally:
                if tmp_name:
                    try:
                        os.unlink(tmp_name)
                    except FileNotFoundError:
                        pass

    def update(self, **kwargs):
        """读改写:load -> update dict -> save。加锁串行化。"""
        with self._lock:
            data = self.load()
            if not isinstance(data, dict):
                # 顶层非 dict(如 list)无法 update,退化为空 dict
                data = {}
            data.update(kwargs)
            self.save(data)
            return data

    def get(self, key, default=None):
        """读取单个 key(仅 dict 顶层有意义)。"""
        data = self.load()
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    def set(self, key, value):
        """等价于 update 单个 key。"""
        return self.update(**{key: value})


# ---------- 错误文案翻译 ----------

def friendly_error(e: Exception, context: str = "") -> str:
    """把异常对象翻译成用户能看懂的中文提示。

    - PermissionError → "没有权限访问该文件/目录"
    - FileNotFoundError → "找不到指定的文件或目录"
    - ConnectionRefusedError → "无法连接到对方，请确认对方已启动并开启同步"
    - TimeoutError → "操作超时，请检查网络后重试"
    - OSError (磁盘满) → "磁盘空间不足或文件被占用"
    - 其他 → 兜底通用文案
    """
    msg = str(e).lower()
    if isinstance(e, PermissionError) or "permission denied" in msg:
        tip = "没有权限访问该文件或目录，请检查文件是否被其他程序占用"
    elif isinstance(e, FileNotFoundError) or "no such file" in msg:
        tip = "找不到指定的文件或目录，可能已被移动或删除"
    elif isinstance(e, ConnectionRefusedError) or "connection refused" in msg:
        tip = "无法连接到对方，请确认对方已启动软件并开启了同步"
    elif isinstance(e, TimeoutError) or "timed out" in msg or "timeout" in msg:
        tip = "操作超时，请检查网络连接后重试"
    elif isinstance(e, OSError):
        if "no space" in msg or "disk full" in msg or "enospc" in msg:
            tip = "磁盘空间不足，请清理后重试"
        else:
            tip = "文件操作失败，文件可能被占用或路径异常"
    elif isinstance(e, ValueError):
        tip = f"数据格式有误：{e}"
    else:
        tip = f"操作失败：{e}"
    if context:
        return f"{context}：{tip}"
    return tip
