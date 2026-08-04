"""想你了 💗 全屏轻互动弹窗。

无边框、透明、置顶的爱心弹窗：在屏幕中央显示一个大粉色爱心，
通过 QPropertyAnimation 让窗口透明度 3 秒内 1.0 → 0.0 淡出后自动关闭。

使用：
    HeartPopup.show_heart()
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
)


class HeartPopup(QWidget):
    """全屏淡出爱心弹窗。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        # 完全透明背景 + 不抢鼠标
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # 居中铺满屏幕，让爱心画在屏幕中央
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # 淡出动画：windowOpacity 1.0 → 0.0，3 秒
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(3000)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.finished.connect(self.close)

    # ---------- 绘制 ----------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 以屏幕几何中心为基准画一个大爱心
        rect: QRect = self.rect()
        cx = rect.width() / 2.0
        cy = rect.height() / 2.0
        # 爱心整体大小（按屏幕短边的比例）
        size = min(rect.width(), rect.height()) * 0.5

        path = QPainterPath()
        # 以爱心朝下、两瓣在上的标准心形绘制
        # 使用三次贝塞尔曲线绘制对称心形
        w = size
        h = size
        # 顶部两个圆弧顶点
        top_y = cy - h * 0.25
        # 底部尖端
        bottom_y = cy + h * 0.55
        # 左右最宽点
        left_x = cx - w * 0.5
        right_x = cx + w * 0.5

        path.moveTo(cx, top_y)
        # 左半边：从顶部中央到左凸点再到底部尖端
        path.cubicTo(
            cx - w * 0.5, top_y - h * 0.35,
            left_x, top_y + h * 0.10,
            cx, bottom_y,
        )
        # 右半边：从底部尖端回到顶部中央
        path.cubicTo(
            right_x, top_y + h * 0.10,
            cx + w * 0.5, top_y - h * 0.35,
            cx, top_y,
        )
        path.closeSubpath()

        # 描边 + 填充，颜色用偏暖的粉色
        pen = QPen(QColor(255, 240, 245, 220))
        pen.setWidth(6)
        p.setPen(pen)
        p.setBrush(QColor(236, 90, 122, 235))
        p.drawPath(path)

    # ---------- 显示 ----------

    def showEvent(self, _event) -> None:
        # 显示后立即启动淡出
        # 用 QTimer.singleShot(0) 保证窗口先完成 show 再启动动画
        QTimer.singleShot(0, self._anim.start)

    @classmethod
    def show_heart(cls) -> None:
        """类方法：创建并显示一个爱心弹窗实例。"""
        inst = cls()
        inst.show()
