"""无边框透明置顶相框窗口：拖拽移动、双击放大、滚轮缩放、定时轮播、
淡入淡出切换、Ken Burns 缓慢平移、纪念日主题色、EXIF 悬浮信息。"""
from __future__ import annotations

import random
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    Property,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QMessageBox,
    QApplication,
    QVBoxLayout,
    QWidget,
)

from common_utils import log_exception, log_warning

from . import config
from . import image_processor as ip


def _stop_anim(anim: QPropertyAnimation | None) -> None:
    """安全停止并释放一个 QPropertyAnimation：断开所有信号引用（避免 lambda 捕获对象泄漏）。"""
    if anim is not None:
        try:
            anim.stop()
        except RuntimeError:
            # C++ 对象已被销毁
            return
        try:
            # 断开 finished/stateChanged 等所有信号，释放 lambda 闭包引用
            # PySide6 无 disconnect(context) 重载，逐个断开已知信号
            try:
                anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                anim.stateChanged.disconnect()
            except (RuntimeError, TypeError):
                pass
        except Exception:
            pass


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 6:
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            pass
    return 230, 90, 122


class KenBurnsLabel(QWidget):
    """自定义图片显示组件：圆角 clip + Ken Burns 缓慢平移动画。

    - 开启 Ken Burns 时，pixmap（已 cover 放大）在窗口内随机方向缓慢平移；
    - 关闭或图比窗口小则居中静态显示；
    - 圆角通过 QPainterPath clip 实现，图本身不裁圆角。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._offset = QPointF(0, 0)
        self._kb_enabled = False
        self._radius = 18
        self._anim: QPropertyAnimation | None = None

    def set_radius(self, r: int) -> None:
        self._radius = max(0, r)
        self.update()

    def set_image(self, pm: QPixmap, kb_enabled: bool) -> None:
        self._kb_enabled = kb_enabled and not pm.isNull()
        self._pixmap = pm
        # 停掉旧动画
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._offset = QPointF(0, 0)
        self.update()
        if self._kb_enabled:
            self._start_kb()

    def clear_image(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._pixmap = QPixmap()
        self.update()

    def _start_kb(self) -> None:
        pw, ph = self._pixmap.width(), self._pixmap.height()
        w, h = self.width(), self.height()
        dx = pw - w
        dy = ph - h
        if dx <= 0 and dy <= 0:
            return  # 图不比窗口大，无法平移
        # 随机起点与终点（在可平移范围内）
        sx, sy = (random.uniform(0, dx) if dx > 0 else 0,
                  random.uniform(0, dy) if dy > 0 else 0)
        ex, ey = (random.uniform(0, dx) if dx > 0 else 0,
                  random.uniform(0, dy) if dy > 0 else 0)
        # 保证有移动量
        if abs(ex - sx) < 5 and abs(ey - sy) < 5:
            ex = dx - sx if dx > 0 else 0
            ey = dy - sy if dy > 0 else 0
        self._offset = QPointF(sx, sy)
        anim = QPropertyAnimation(self, b"offset", self)
        anim.setDuration(8000 + random.randint(0, 4000))
        anim.setStartValue(QPointF(sx, sy))
        anim.setEndValue(QPointF(ex, ey))
        anim.setLoopCount(-1)  # 来回循环（下一段切换时会重启）
        anim.setEasingCurve(QEasingCurve.InOutSine)
        anim.start()
        self._anim = anim

    def get_offset(self) -> QPointF:
        return self._offset

    def set_offset(self, value: QPointF) -> None:
        self._offset = value
        self.update()

    offset = Property(QPointF, get_offset, set_offset)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # 圆角 clip
        if self._radius > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                                self._radius, self._radius)
            p.setClipPath(path)
        if self._pixmap.isNull():
            return
        # 居中绘制（offset 仅 Ken Burns 时非 0）
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if not self._kb_enabled:
            # 静态居中
            x = (self.width() - pw) / 2
            y = (self.height() - ph) / 2
            p.drawPixmap(QPointF(x, y), self._pixmap)
        else:
            p.drawPixmap(self._offset, self._pixmap)

        # A subtle edge keeps the rounded frame legible against bright wallpaper.
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 105), 1))
        inset = 0.5
        p.drawRoundedRect(
            QRectF(inset, inset, self.width() - 1, self.height() - 1),
            self._radius,
            self._radius,
        )

    def resizeEvent(self, _e) -> None:
        self.update()


class FrameWindow(QWidget):
    """桌面相框主体窗口。"""

    status_message = Signal(str)  # 给托盘发通知用

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self._cfg = cfg
        self._images: list[Path] = []
        self._index = -1
        self._paused = False
        self._zoomed = False
        self._manual_zoom = 1.0  # 滚轮缩放倍数（1.0~3.0）
        self._drag_offset: QPointF | None = None
        self._fade_anim: QPropertyAnimation | None = None
        # pixmap 暂存：避免 fade_out.finished 的 lambda 闭包捕获导致 pixmap 泄漏
        self._pending_pixmap: QPixmap | None = None
        self._pending_kb = False
        self._prefetch_thread: threading.Thread | None = None
        # 预取任务取消令牌：每次启动新预取时自增，旧线程读到变化即退出
        self._prefetch_token = 0
        # 预取线程读取的快照（避免子线程读主线程可变数据）
        self._prefetch_lock = threading.Lock()
        # 只看收藏模式（reload 时按收藏列表过滤）
        self._favorites_only = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._build_ui()
        self._build_timer()

        self.reload(cfg)
        self._place_initial()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = KenBurnsLabel(self)
        self._label.set_radius(self._cfg.get("corner_radius", 18))
        layout.addWidget(self._label)

        # 阴影：让相框像浮在桌面上；纪念日用主题色
        self._shadow = QGraphicsDropShadowEffect(self._label)
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 6)
        self._apply_theme()
        self._label.setGraphicsEffect(self._shadow)

        self._apply_size()

    def _apply_theme(self) -> None:
        """纪念日当天用主题色做阴影，否则用黑色。"""
        accent = self._today_accent_rgb()
        if accent is not None:
            self._shadow.setColor(QColor(accent[0], accent[1], accent[2], 200))
            self._shadow.setBlurRadius(36)
        else:
            self._shadow.setColor(QColor(0, 0, 0, 160))
            self._shadow.setBlurRadius(28)

    def _today_accent_rgb(self) -> tuple[int, int, int] | None:
        """今天是否纪念日，是则返回主题色 RGB。"""
        today = datetime.now().strftime("%m-%d")
        if today in self._cfg.get("anniversaries", []):
            return _hex_to_rgb(self._cfg.get("theme_color", "#e65a7a"))
        return None

    def _apply_size(self) -> None:
        cfg = self._cfg
        base = cfg["zoom_factor"] if self._zoomed else 1.0
        total = base * self._manual_zoom
        w = int(cfg["window_width"] * total)
        h = int(cfg["window_height"] * total)
        # 限制最大，避免滚轮放到超大
        w = min(w, 1600)
        h = min(h, 2000)
        self.setFixedSize(QSize(w, h))
        self._label.setFixedSize(QSize(w, h))

    def _place_initial(self) -> None:
        screen = self.screen().availableGeometry()
        saved_x = self._cfg.get("window_x")
        saved_y = self._cfg.get("window_y")
        # 有持久化位置且在某屏幕可见范围内：恢复位置
        if saved_x is not None and saved_y is not None:
            if (screen.left() <= saved_x <= screen.right()
                    and screen.top() <= saved_y <= screen.bottom()):
                self.move(int(saved_x), int(saved_y))
                return
        # 默认右下角
        w, h = self.width(), self.height()
        margin = 40
        self.move(screen.right() - w - margin, screen.bottom() - h - margin)

    # ---------- 计时器 ----------

    def _build_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.CoarseTimer)
        self._timer.timeout.connect(self.show_next)
        self._apply_interval()

    def _apply_interval(self) -> None:
        self._timer.setInterval(self._cfg["interval_sec"] * 1000)

    # ---------- 数据 ----------

    def reload(self, cfg: dict | None = None) -> None:
        if cfg is not None:
            self._cfg = cfg
        self._images = ip.list_images(self._cfg["image_dir"])
        # 只看收藏模式：仅保留收藏列表中的照片
        if self._favorites_only:
            favs = set(config.list_favorites())
            self._images = [p for p in self._images if str(p) in favs]
        self._apply_interval()
        self._label.set_radius(self._cfg.get("corner_radius", 18))
        self._apply_theme()
        self._apply_size()
        if not self._images:
            self._show_placeholder("把照片放进目录：\n" + self._cfg["image_dir"])
            self._timer.stop()
            return
        self._index = -1
        self.show_next()
        if not self._paused:
            self._timer.start()

    def set_image_dir(self, path: str) -> None:
        self._cfg = config.update(image_dir=path)
        self.status_message.emit(f"图片目录：{path}")
        self.reload()

    def switch_album(self, path: str) -> None:
        """切换到指定相册目录。"""
        self._cfg = config.update(image_dir=path)
        self.status_message.emit(f"已切换相册：{path}")
        # 切相册时让旧的预取任务失效，避免写入旧图缓存
        self._prefetch_token += 1
        # 清缓存避免旧尺寸图复用
        try:
            from .image_processor import get_cache
            get_cache().clear()
        except Exception:
            log_exception("清空 pixmap 缓存失败")
        self.reload()

    # ---------- 切换图片 ----------

    def show_next(self) -> None:
        if not self._images:
            return
        self._index = (self._index + 1) % len(self._images)
        self._switch_to(self._images[self._index])

    def show_prev(self) -> None:
        if not self._images:
            return
        self._index = (self._index - 1) % len(self._images)
        self._switch_to(self._images[self._index])

    def shuffle(self) -> None:
        if len(self._images) > 1:
            # 排除当前索引，避免连续出现同一张
            choices = [i for i in range(len(self._images)) if i != self._index]
            self._index = random.choice(choices)
            self._switch_to(self._images[self._index])

    def _switch_to(self, src: Path) -> None:
        cfg = self._cfg
        accent = self._today_accent_rgb()
        kb = bool(cfg.get("ken_burns", True))
        # 模糊背景仅在非 Ken Burns 时生效
        blur_bg = (not kb) and bool(cfg.get("blur_background", False))
        pixmap = ip.process_image(
            src,
            target_w=self._label.width(),
            target_h=self._label.height(),
            polaroid=cfg["polaroid_frame"],
            watermark=cfg["show_watermark"],
            corner_radius=cfg["corner_radius"],
            ken_burns=kb,
            accent_rgb=accent,
            blur_background=blur_bg,
        )
        if pixmap is None or pixmap.isNull():
            self._show_placeholder(f"无法加载：\n{src.name}")
            return
        # EXIF 悬浮信息
        exif = ip.read_exif_info(src)
        tip = f"{src.name}"
        if exif:
            tip += f"\n📷 {exif}"
        self._label.setToolTip(tip)
        self._fade_switch(pixmap, kb)

    def _fade_switch(self, pixmap: QPixmap, kb: bool) -> None:
        # 先把 pixmap 存在 self 上，避免 lambda 闭包捕获（长运行会累积泄漏）
        self._pending_pixmap = pixmap
        self._pending_kb = bool(kb)
        # 覆盖前先停止旧动画，避免并发修改 windowOpacity 造成闪烁
        _stop_anim(self._fade_anim)
        self._fade_anim = None
        fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        fade_out.setDuration(160)
        fade_out.setStartValue(self.windowOpacity() or 1.0)
        fade_out.setEndValue(0.0)
        fade_out.finished.connect(self._on_fade_out_done)
        fade_out.start()
        self._fade_anim = fade_out

    def _on_fade_out_done(self) -> None:
        """fade_out 完成回调：从 self._pending_* 取图，避免 lambda 闭包捕获 pixmap。"""
        pm = self._pending_pixmap
        kb = self._pending_kb
        self._pending_pixmap = None
        self._pending_kb = False
        if pm is None:
            return
        self._apply_pixmap(pm, kb)

    def _apply_pixmap(self, pixmap: QPixmap, kb: bool) -> None:
        self._label.set_image(pixmap, kb_enabled=kb)
        _stop_anim(self._fade_anim)
        fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        fade_in.setDuration(220)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.start()
        self._fade_anim = fade_in
        # 淡入动画启动后，后台预生成下一张（写入 PIL 预生成缓存）
        self._prefetch_next()

    def _prefetch_next(self) -> None:
        """后台 daemon 线程预生成下一张图片的 PIL Image，存入 ip._pil_prefetch。

        主线程 process_image 会自动消费该缓存，跳过 PIL 处理；QPixmap 转换仍
        在主线程完成，保证线程安全。列表为空或只有一张时不预生成。

        线程安全：
        - 启动前对所需参数取快照（不再读主线程可变数据）
        - 用自增 token 取消旧任务：若启动后用户切了相册，token 会变，旧线程
          检测到后放弃写入缓存
        """
        if len(self._images) <= 1:
            return
        next_index = (self._index + 1) % len(self._images)
        # 快照所有参数，子线程不再读 self._cfg / self._images
        next_src = self._images[next_index]
        cfg = dict(self._cfg)
        accent = self._today_accent_rgb()
        kb = bool(cfg.get("ken_burns", True))
        blur_bg = (not kb) and bool(cfg.get("blur_background", False))
        target_w = self._label.width()
        target_h = self._label.height()
        polaroid = cfg["polaroid_frame"]
        watermark = cfg["show_watermark"]
        corner_radius = cfg["corner_radius"]

        self._prefetch_token += 1
        my_token = self._prefetch_token

        def _worker() -> None:
            try:
                result = ip.process_to_pil(
                    next_src,
                    target_w=target_w,
                    target_h=target_h,
                    polaroid=polaroid,
                    watermark=watermark,
                    corner_radius=corner_radius,
                    ken_burns=kb,
                    accent_rgb=accent,
                    blur_background=blur_bg,
                )
                if result is None:
                    return
                # token 变化说明已发起新的预取或切了相册，丢弃本次结果
                with self._prefetch_lock:
                    if my_token != self._prefetch_token:
                        return
                ip._pil_prefetch.put(
                    next_src, target_w, target_h, result[0],
                    polaroid=polaroid,
                    watermark=watermark,
                    corner_radius=corner_radius,
                    ken_burns=kb,
                    accent_rgb=accent,
                    blur_background=blur_bg,
                )
            except Exception:
                log_exception("预取图片失败: %s", next_src)

        t = threading.Thread(target=_worker, daemon=True)
        self._prefetch_thread = t
        t.start()

    def _show_placeholder(self, text: str) -> None:
        # 绘制可见提示文字的 pixmap，而非仅设 tooltip（空目录时窗口完全透明会让用户以为软件没启动）
        pm = QPixmap(self._label.width(), self._label.height())
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(200, 200, 200, 180)))
        watermark_font = QApplication.font()
        watermark_font.setPointSize(11)
        p.setFont(watermark_font)
        p.drawText(QRectF(0, 0, pm.width(), pm.height()), Qt.AlignCenter, text)
        p.end()
        self._label.set_image(pm, kb_enabled=False)
        self._label.setToolTip(text)

    # ---------- 控制 ----------

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        if self._paused:
            self._timer.stop()
        else:
            self._timer.start()
        self.status_message.emit("已暂停" if self._paused else "继续播放")
        return self._paused

    def toggle_zoom(self) -> None:
        g = self.geometry()
        cx, cy = g.center().x(), g.center().y()
        self._zoomed = not self._zoomed
        # 双击切换时重置滚轮缩放
        self._manual_zoom = 1.0
        self._apply_size()
        new_g = QRect(0, 0, self.width(), self.height())
        new_g.moveCenter(QPoint(cx, cy))
        self.setGeometry(new_g)
        if 0 <= self._index < len(self._images):
            self._switch_to(self._images[self._index])

    def toggle_polaroid(self) -> bool:
        new = not self._cfg["polaroid_frame"]
        self._cfg = config.update(polaroid_frame=new)
        self._rerender_current()
        self.status_message.emit("拍立得边框：开" if new else "拍立得边框：关")
        return new

    def toggle_watermark(self) -> bool:
        new = not self._cfg["show_watermark"]
        self._cfg = config.update(show_watermark=new)
        self._rerender_current()
        self.status_message.emit("日期水印：开" if new else "日期水印：关")
        return new

    def toggle_ken_burns(self) -> bool:
        new = not self._cfg.get("ken_burns", True)
        self._cfg = config.update(ken_burns=new)
        self._rerender_current()
        self.status_message.emit("Ken Burns 动画：开" if new else "Ken Burns 动画：关")
        return new

    def toggle_blur_background(self) -> bool:
        """切换模糊背景填充。Ken Burns 开启时此项不生效。"""
        new = not self._cfg.get("blur_background", False)
        self._cfg = config.update(blur_background=new)
        # 清缓存避免旧尺寸/旧模式图复用
        try:
            ip.get_cache().clear()
        except Exception:
            log_exception("清空 pixmap 缓存失败")
        self._rerender_current()
        if new:
            msg = "模糊背景填充：开"
            if self._cfg.get("ken_burns", True):
                msg += "（需关闭 Ken Burns 才能生效）"
        else:
            msg = "模糊背景填充：关"
        self.status_message.emit(msg)
        return new

    def _rerender_current(self) -> None:
        if 0 <= self._index < len(self._images):
            self._switch_to(self._images[self._index])

    # ---------- 当前照片操作（收藏/删除/文件夹/壁纸/旋转） ----------

    def toggle_favorite_current(self) -> None:
        """收藏/取消收藏当前照片。"""
        if not self._images or self._index < 0:
            return
        src = str(self._images[self._index])
        is_fav = config.toggle_favorite(src)
        self.status_message.emit("⭐ 已收藏" if is_fav else "已取消收藏")

    def toggle_favorites_only(self) -> bool:
        """切换只看收藏模式，返回切换后状态。"""
        self._favorites_only = not self._favorites_only
        self.reload()
        self.status_message.emit("只看收藏" if self._favorites_only else "显示全部")
        return self._favorites_only

    def delete_current(self) -> None:
        """删除当前照片（带确认对话框，不可撤销）。"""
        if not self._images or self._index < 0:
            return
        src = self._images[self._index]
        btn = QMessageBox.question(
            self, "删除照片",
            f"确定删除「{src.name}」吗？\n此操作不可撤销，文件将从磁盘移除。"
        )
        if btn != QMessageBox.Yes:
            return
        try:
            src.unlink()
        except OSError as e:
            self.status_message.emit(f"删除失败：{e}")
            return
        # 同步从收藏列表移除（避免只看收藏模式下残留无效项）
        try:
            if config.is_favorite(str(src)):
                config.toggle_favorite(str(src))
        except Exception:
            pass
        del self._images[self._index]
        # 清 pixmap 缓存避免复用已删图的旧 pixmap
        try:
            ip.get_cache().clear()
        except Exception:
            pass
        if not self._images:
            self._show_placeholder("相册已空")
            self._timer.stop()
        else:
            self._index = min(self._index, len(self._images) - 1)
            self._switch_to(self._images[self._index])
        self.status_message.emit(f"已删除 {src.name}")

    def open_in_explorer(self) -> None:
        """在系统文件管理器中定位当前照片。"""
        if not self._images or self._index < 0:
            return
        src = self._images[self._index]
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(src)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(src)])
            else:
                subprocess.Popen(["xdg-open", str(src.parent)])
        except OSError as e:
            self.status_message.emit(f"打开失败：{e}")

    def set_as_wallpaper(self) -> None:
        """设为桌面壁纸（仅 Windows）。"""
        if not self._images or self._index < 0:
            return
        src = self._images[self._index]
        if sys.platform != "win32":
            self.status_message.emit("设为壁纸仅支持 Windows")
            return
        try:
            import ctypes
            # SPI_SETDESKWALLPAPER=20, SPIF_UPDATEINIFILE|SPIF_SENDCHANGE=3
            result = ctypes.windll.user32.SystemParametersInfoW(20, 0, str(src), 3)
            if result:
                self.status_message.emit(f"已设为桌面壁纸：{src.name}")
            else:
                self.status_message.emit("设为壁纸失败")
        except Exception as e:
            self.status_message.emit(f"设为壁纸失败：{e}")

    def rotate_current(self) -> None:
        """顺时针旋转当前照片 90°，写回原文件并刷新显示。"""
        if not self._images or self._index < 0:
            return
        src = self._images[self._index]
        if not ip.rotate_image_in_place(src, 90):
            self.status_message.emit("旋转失败")
            return
        # 清缓存强制重新加载（文件已变）
        try:
            ip.get_cache().clear()
        except Exception:
            pass
        self._switch_to(src)
        self.status_message.emit(f"已旋转 90°：{src.name}")

    # ---------- 鼠标交互 ----------

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._drag_offset is not None:
            # 拖动结束，持久化相框位置
            try:
                config.save_window_pos(self.x(), self.y())
            except Exception:
                log_warning("保存相框位置失败")
        self._drag_offset = None
        e.accept()

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.toggle_zoom()
            e.accept()

    def wheelEvent(self, e: QWheelEvent) -> None:
        """滚轮缩放：在 1.0~3.0 之间步进 0.1。"""
        if not self._cfg.get("wheel_zoom_enabled", True):
            return
        delta = e.angleDelta().y()
        if delta == 0:
            return
        step = 0.1 if delta > 0 else -0.1
        old = self._manual_zoom
        self._manual_zoom = max(1.0, min(3.0, round(self._manual_zoom + step, 2)))
        if self._manual_zoom == old:
            return
        # 以鼠标为中心缩放
        g = self.geometry()
        anchor = e.globalPosition().toPoint()
        ratio_x = (anchor.x() - g.left()) / g.width() if g.width() else 0
        ratio_y = (anchor.y() - g.top()) / g.height() if g.height() else 0
        self._apply_size()
        new_w, new_h = self.width(), self.height()
        new_left = anchor.x() - int(new_w * ratio_x)
        new_top = anchor.y() - int(new_h * ratio_y)
        self.setGeometry(new_left, new_top, new_w, new_h)
        self._rerender_current()
        e.accept()

    def paintEvent(self, _e) -> None:
        pass
