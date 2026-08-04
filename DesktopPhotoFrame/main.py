"""桌面相册入口。

- 桌面右下角出现一个透明置顶的小相册窗口，定时轮播 images/ 下的照片；
- 托盘图标(粉色爱心)右键菜单可控制 下一张/暂停/放大/边框/水印/选目录/退出；
- 左键拖动相册移动位置；双击切换放大/缩小。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

import config
from frame_window import FrameWindow
from tray import TrayController


def main() -> int:
    # 高 DPI 支持
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("DesktopPhotoFrame")
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，靠托盘退出

    cfg = config.load()

    # 首次运行：确保 images 目录存在，方便用户丢照片进去
    images_dir = Path(cfg["image_dir"])
    images_dir.mkdir(parents=True, exist_ok=True)

    window = FrameWindow(cfg)
    window.show()

    tray = TrayController(window)

    # 把托盘信号接到窗口方法上
    tray.next_requested.connect(window.show_next)
    tray.prev_requested.connect(window.show_prev)
    tray.shuffle_requested.connect(window.shuffle)
    tray.pause_toggled.connect(lambda: tray.update_pause_text(window.toggle_pause()))
    tray.zoom_toggled.connect(window.toggle_zoom)
    tray.polaroid_toggled.connect(lambda: tray.sync_polaroid(window.toggle_polaroid()))
    tray.watermark_toggled.connect(lambda: tray.sync_watermark(window.toggle_watermark()))
    tray.ken_burns_toggled.connect(lambda: tray.sync_ken_burns(window.toggle_ken_burns()))
    tray.image_dir_changed.connect(window.set_image_dir)
    tray.quit_requested.connect(app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
