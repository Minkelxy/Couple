"""双人影视追剧看板主窗口。

三栏（想看 / 在看 / 看完）+ 豆瓣抓取添加 + 右键评分短评 + 年度报告。
豆瓣抓取放在后台 QThread，失败优雅降级。
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from common_utils import log_exception

from . import report_generator, scraper, store

# (status, 名称, accent)
_COL_DEFS = [
    (store.STATUS_WANT, "想看", "#e85d75"),
    (store.STATUS_WATCHING, "在看", "#6b8fd6"),
    (store.STATUS_WATCHED, "看完", "#4f9b7a"),
]


def _btn_style() -> str:
    return ("QPushButton{background:#e85d75;color:#fff;border:none;"
            "border-radius:6px;padding:9px 16px;font-size:14px;font-weight:600;}"
            "QPushButton:hover{background:#d94f68;}"
            "QPushButton:disabled{background:#d9dee4;color:#fff;}")


def _secondary_btn_style() -> str:
    return ("QPushButton{background:#ffffff;color:#52616d;"
            "border:1px solid #d7dee8;border-radius:6px;padding:9px 16px;"
            "font-size:14px;}"
            "QPushButton:hover{background:#fff0f3;border-color:#e8a0ad;}"
            "QPushButton:disabled{background:#edf0f3;color:#aab3bd;}")


def handle_partner_event(
    meta: dict, content: str, attachment: bytes, att_ext: str
) -> None:
    """处理对方发来的影视状态事件：写入 partner_status。

    由 launcher 的事件路由器在收到 type=="movie" 时调用。
    """
    movie_id = meta.get("movie_id")
    if movie_id is None:
        return
    try:
        store.set_partner_status(
            movie_id,
            meta.get("status"),
            meta.get("rating"),
        )
    except OSError:
        log_exception("写入对方影视状态失败: %s", movie_id)
        raise


class _SearchWorker(QThread):
    """后台执行豆瓣搜索 + 海报下载，避免阻塞 UI。"""

    found = Signal(dict)
    failed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def run(self) -> None:
        try:
            info = scraper.search_movie(self._title)
            if not info:
                self.failed.emit()
                return
            poster_path = ""
            if info.get("poster_url") and info.get("douban_id"):
                poster_path = scraper.download_poster(
                    info["poster_url"], info["douban_id"]
                ) or ""
            info["poster_path"] = poster_path
            self.found.emit(info)
        except Exception:
            log_exception("影视搜索 worker 异常: %s", self._title)
            self.failed.emit()


class _MovieItemWidget(QWidget):
    """看板单个影片项：海报缩略图 60x80 + 标题 + 评分行。"""

    def __init__(self, movie: dict) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        poster = QLabel(self)
        poster.setFixedSize(60, 80)
        poster.setAlignment(Qt.AlignCenter)
        poster.setStyleSheet(
            "background:#eef2f6; border-radius:6px; color:#7b8794;"
            "font-size:11px;"
        )
        pm = self._load_poster(movie.get("poster_path", ""))
        if pm:
            poster.setPixmap(pm)
        else:
            poster.setText("暂无海报")
        lay.addWidget(poster)

        info = QWidget(self)
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(0, 0, 0, 0)
        info_lay.setSpacing(4)

        title = QLabel(movie.get("title", ""), info)
        title.setStyleSheet("font-size:14px; font-weight:700; color:#263238;")
        title.setWordWrap(True)
        info_lay.addWidget(title)

        rating = QLabel(self._rating_text(movie), info)
        rating.setStyleSheet("font-size:12px; color:#d84f68;")
        info_lay.addWidget(rating)

        # 对方状态徽章
        badge_text = self._partner_badge_text(movie.get("partner_status"))
        if badge_text:
            ps_lbl = QLabel(badge_text, info)
            ps_lbl.setStyleSheet(
                "font-size:11px; color:#52616d; background:#eef5f7;"
                "border-radius:4px; padding:1px 6px;"
            )
            info_lay.addWidget(ps_lbl)

        lay.addWidget(info, 1)

    @staticmethod
    def _load_poster(path: str) -> QPixmap | None:
        if not path:
            return None
        try:
            pm = QPixmap(path)
            if pm.isNull():
                return None
            return pm.scaled(
                60, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        except Exception:
            log_exception("加载海报失败: %s", path)
            return None

    @staticmethod
    def _rating_text(movie: dict) -> str:
        m = movie.get("rating_mine")
        p = movie.get("rating_partner")
        status = movie.get("status")
        if status == store.STATUS_WATCHED:
            parts = []
            if isinstance(m, int):
                parts.append(f"我:{m}")
            if isinstance(p, int):
                parts.append(f"对方:{p}")
            text = "  ".join(parts)
            if isinstance(m, int) and isinstance(p, int) and abs(m - p) >= 2:
                text = "分差较大  " + text
            return text or "未评分"
        bits = []
        if isinstance(m, int):
            bits.append(f"我:{m}")
        if isinstance(p, int):
            bits.append(f"对方:{p}")
        return "  ".join(bits)

    @staticmethod
    def _partner_badge_text(ps) -> str:
        """对方状态徽章文本，如 '对方: 想看 / 8' / '对方: 已看'。"""
        if not ps:
            return ""
        status = ps.get("status")
        rating = ps.get("rating")
        name_map = {"want": "想看", "watching": "在看", "watched": "已看"}
        name = name_map.get(status) if status else ""
        if isinstance(rating, int):
            return f"对方: {name} / {rating}" if name else f"对方: / {rating}"
        return f"对方: {name}" if name else ""


class _RatingDialog(QDialog):
    """评分短评对话框：我 / 对方两个标签页，各含 1-10 滑块 + 短评框。"""

    def __init__(self, movie: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("评分短评")
        self.resize(420, 380)
        self.setMinimumSize(380, 340)
        self._build(movie)

    def _build(self, movie: dict) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)

        title = QLabel(movie.get("title", ""), self)
        title.setStyleSheet("font-size:18px; font-weight:700; color:#263238;")
        v.addWidget(title)

        tabs = QTabWidget(self)
        self._mine = self._make_tab(movie.get("rating_mine"),
                                     movie.get("review_mine") or "")
        self._partner = self._make_tab(movie.get("rating_partner"),
                                        movie.get("review_partner") or "")
        tabs.addTab(self._mine["page"], "我")
        tabs.addTab(self._partner["page"], "对方")
        v.addWidget(tabs, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.setStyleSheet(
            "QPushButton{background:#ffffff;color:#52616d;border:1px solid #d7dee8;"
            "border-radius:6px;padding:8px 16px;}"
        )
        cancel.clicked.connect(self.reject)
        ok = QPushButton("保存", self)
        ok.setStyleSheet(_btn_style())
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        v.addLayout(btns)

    def _make_tab(self, rating, review: str) -> dict:
        page = QWidget(self)
        l = QVBoxLayout(page)
        l.setContentsMargins(0, 8, 0, 0)
        l.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("评分：", page))
        val = QLabel(str(rating) if isinstance(rating, int) else "7", page)
        val.setStyleSheet("color:#d84f68; font-weight:700;")
        row.addWidget(val)
        slider = QSlider(Qt.Horizontal, page)
        slider.setMinimum(1)
        slider.setMaximum(10)
        slider.setValue(int(rating) if isinstance(rating, int) else 7)
        slider.setToolTip("评分范围：1 到 10 分")
        slider.setMinimumWidth(180)
        slider.valueChanged.connect(lambda n: val.setText(str(n)))
        row.addWidget(QLabel("1", page))
        row.addWidget(slider, 1)
        row.addWidget(QLabel("10", page))
        l.addLayout(row)

        l.addWidget(QLabel("短评：", page))
        te = QTextEdit(page)
        te.setPlainText(review)
        l.addWidget(te, 1)
        return {"page": page, "slider": slider, "text": te}

    def mine_rating(self) -> int:
        return self._mine["slider"].value()

    def partner_rating(self) -> int:
        return self._partner["slider"].value()

    def mine_review(self) -> str:
        return self._mine["text"].toPlainText()

    def partner_review(self) -> str:
        return self._partner["text"].toPlainText()


class BoardWindow(QMainWindow):
    """影视看板主窗口。"""

    def __init__(self, hub=None) -> None:
        super().__init__()
        self.setWindowTitle("影视看板")
        self.resize(1160, 740)
        self.setMinimumSize(980, 640)
        self._hub = hub
        self._worker: QThread | None = None
        self._columns: dict[str, tuple[QListWidget, QLabel]] = {}
        self._build_ui()
        self.refresh()

    def set_hub(self, hub) -> None:
        """设置变更时热更新同步引用（避免使用已停止的旧 hub）。"""
        self._hub = hub

    # ===== UI 构建 =====
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        # 顶部标题与工具栏
        bar = QHBoxLayout()
        bar.setSpacing(10)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel("影视看板", central)
        title.setStyleSheet("font-size:24px; font-weight:700; color:#263238;")
        subtitle = QLabel("一起决定想看什么，也记录看完后的分数", central)
        subtitle.setStyleSheet("color:#7b8794; font-size:13px;")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        bar.addLayout(heading)
        bar.addStretch(1)

        add_btn = QPushButton("添加影视", central)
        add_btn.setStyleSheet(_btn_style())
        add_btn.clicked.connect(self._on_add)
        bar.addWidget(add_btn)
        self._add_btn = add_btn

        report_btn = QPushButton("生成年度报告", central)
        report_btn.setStyleSheet(_secondary_btn_style())
        report_btn.setToolTip("生成当前年度的观影统计报告")
        report_btn.clicked.connect(self._on_report)
        bar.addWidget(report_btn)
        root.addLayout(bar)

        # 三栏
        cols = QHBoxLayout()
        cols.setSpacing(12)
        for status, name, accent in _COL_DEFS:
            cols.addWidget(self._build_column(status, name, accent), 1)
        root.addLayout(cols, 1)

    def _build_column(self, status: str, name: str, accent: str) -> QWidget:
        col = QWidget(self)
        cl = QVBoxLayout(col)
        cl.setContentsMargins(10, 8, 10, 10)
        cl.setSpacing(8)
        col.setObjectName("movieColumn")
        col.setStyleSheet(
            f"QWidget#movieColumn{{background:#ffffff;border:1px solid #dfe5ec;"
            f"border-top:3px solid {accent};border-radius:8px;}}"
        )

        head = QHBoxLayout()
        head.setContentsMargins(2, 0, 2, 0)
        head.setSpacing(8)
        title = QLabel(name, col)
        title.setStyleSheet("font-size:16px; font-weight:700; color:#263238;")
        head.addWidget(title)
        badge = QLabel("0", col)
        badge.setStyleSheet(
            f"background:{accent}; color:#fff; border-radius:9px;"
            "padding:2px 8px; font-size:12px; min-width:14px;"
        )
        badge.setAlignment(Qt.AlignCenter)
        head.addWidget(badge)
        head.addStretch(1)
        cl.addLayout(head)

        lw = QListWidget(col)
        lw.setContextMenuPolicy(Qt.CustomContextMenu)
        lw.setStyleSheet(
            "QListWidget{background:#f7f9fb; border:none; border-radius:7px;}"
            "QListWidget::item{border-bottom:1px solid #e8edf2;}"
            "QListWidget::item:hover{background:#fff7f8;}"
            "QListWidget::item:selected{background:#ffe8ed;}"
            "QListWidget::item:disabled{color:#9aa5b1;}"
        )
        lw.setSpacing(4)
        lw.customContextMenuRequested.connect(
            lambda pos, lw=lw, status=status: self._on_context_menu(lw, status, pos)
        )
        cl.addWidget(lw)
        self._columns[status] = (lw, badge)
        return col

    # ===== 刷新 =====
    def refresh(self) -> None:
        all_ps = store.get_all_partner_status()
        for status, (lw, badge) in self._columns.items():
            lw.clear()
            items = store.list_by_status(status)
            badge.setText(str(len(items)))
            if not items:
                status_name = next(
                    (name for current, name, _accent in _COL_DEFS if current == status),
                    "当前栏目",
                )
                empty = QListWidgetItem(f"{status_name}暂无影片")
                empty.setFlags(Qt.NoItemFlags)
                empty.setTextAlignment(Qt.AlignCenter)
                empty.setForeground(QColor("#9aa5b1"))
                empty.setToolTip("点击顶部“添加影视”将影片加入看板")
                lw.addItem(empty)
                continue
            for m in items:
                m["partner_status"] = all_ps.get(str(m["id"]))
                item = QListWidgetItem(lw)
                item.setData(Qt.UserRole, m["id"])
                widget = _MovieItemWidget(m)
                item.setSizeHint(widget.sizeHint())
                lw.addItem(item)
                lw.setItemWidget(item, widget)

    # ===== 添加影视 =====
    def _on_add(self) -> None:
        title, ok = QInputDialog.getText(self, "添加影视", "输入片名：")
        if not ok or not title.strip():
            return
        title = title.strip()
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "提示", "上一个搜索还在进行中…")
            return
        # 搜索中：按钮变 loading 状态
        self._add_btn.setEnabled(False)
        self._add_btn.setText("搜索中...")
        self.statusBar().showMessage(f"正在搜索：{title}")
        worker = _SearchWorker(title)
        worker.found.connect(self._on_search_found)
        worker.failed.connect(lambda t=title: self._on_search_failed(t))
        # finished 时自动 deleteLater，并清理引用，避免 QThread 对象泄漏
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._clear_worker_ref)
        self._worker = worker
        worker.start()

    def _clear_worker_ref(self) -> None:
        self._worker = None
        # 恢复添加按钮
        self._add_btn.setEnabled(True)
        self._add_btn.setText("添加影视")
        self.statusBar().showMessage("可以继续添加影视", 3000)

    def _on_search_found(self, info: dict) -> None:
        store.add(
            info.get("title", ""),
            douban_id=info.get("douban_id", ""),
            poster_path=info.get("poster_path", ""),
            intro=info.get("intro", ""),
        )
        self.refresh()
        self.statusBar().showMessage(f"已添加：{info.get('title', '')}", 4000)
        QMessageBox.information(
            self, "已添加", f"已加入想看：{info.get('title', '')}"
        )

    def _on_search_failed(self, title: str) -> None:
        self.statusBar().showMessage(f"未找到：{title}，可手动添加", 5000)
        btn = QMessageBox.question(
            self, "未找到",
            f"未在豆瓣找到「{title}」，是否手动添加？",
        )
        if btn == QMessageBox.Yes:
            store.add(title)
            self.refresh()

    # ===== 右键菜单 =====
    def _on_context_menu(self, lw: QListWidget, status: str, pos) -> None:
        item = lw.itemAt(pos)
        if item is None:
            return
        movie_id = item.data(Qt.UserRole)
        movie = store.get(movie_id)
        if not movie:
            return

        menu = QMenu(self)
        for s, name, _accent in _COL_DEFS:
            if s == status:
                continue
            act = QAction(f"移到{name}", self)
            act.triggered.connect(
                lambda checked=False, s=s, mid=movie_id: self._move(mid, s)
            )
            menu.addAction(act)
        menu.addSeparator()
        rate_act = QAction("评分与短评", self)
        rate_act.triggered.connect(
            lambda checked=False, mid=movie_id: self._edit_rating(mid)
        )
        menu.addAction(rate_act)
        menu.addSeparator()
        del_act = QAction("删除", self)
        del_act.triggered.connect(
            lambda checked=False, mid=movie_id: self._delete(mid)
        )
        menu.addAction(del_act)
        menu.exec(lw.viewport().mapToGlobal(pos))

    def _move(self, movie_id: int, status: str) -> None:
        store.update_status(movie_id, status)
        self._notify_partner(movie_id)
        self.refresh()

    def _delete(self, movie_id: int) -> None:
        movie = store.get(movie_id)
        name = movie.get("title", "") if movie else ""
        btn = QMessageBox.question(
            self, "删除确认", f"确定删除「{name}」吗？"
        )
        if btn == QMessageBox.Yes:
            store.delete(movie_id)
            self.refresh()

    def _edit_rating(self, movie_id: int) -> None:
        movie = store.get(movie_id)
        if not movie:
            return
        dlg = _RatingDialog(movie, self)
        if dlg.exec():
            store.update_rating(movie_id, "mine", dlg.mine_rating())
            store.update_rating(movie_id, "partner", dlg.partner_rating())
            store.update_review(movie_id, "mine", dlg.mine_review())
            store.update_review(movie_id, "partner", dlg.partner_review())
            self._notify_partner(movie_id)
            self.refresh()

    def _notify_partner(self, movie_id: int) -> None:
        """状态/评分变更后同步给对方。"""
        if not self._hub:
            return
        movie = store.get(movie_id)
        if not movie:
            return
        rating = movie.get("rating_mine")
        self._hub.send_event("movie", {
            "movie_id": str(movie_id),
            "title": movie.get("title", ""),
            "status": movie.get("status"),
            "rating": rating if isinstance(rating, int) else None,
        }, silent=True)

    # ===== 年度报告 =====
    def _on_report(self) -> None:
        year = datetime.now().year
        try:
            path = report_generator.generate_year_report(year)
        except Exception as e:
            from common_utils import friendly_error
            QMessageBox.warning(self, "生成失败", friendly_error(e, "年度报告生成失败"))
            return
        btn = QMessageBox.information(
            self, "报告已生成",
            f"{year} 年度观影报告已生成：\n{path}",
            QMessageBox.Open | QMessageBox.Close,
            QMessageBox.Open,
        )
        if btn == QMessageBox.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
