# 相册功能优化与新增功能实施计划

## 概述

对桌面相册模块（DesktopPhotoFrame）进行细节优化和功能增强：修复 4 个影响体验的关键 Bug，落地原计划的 6 项功能（收藏/删除/打开文件夹/画廊自动播放/位置持久化/画廊小图填屏），并按用户新增要求加入 3 项功能（EXIF 信息浮层、设为桌面壁纸、手动旋转）。共 **13 项改动**，涉及 4 个文件。

## 当前状态分析

### 已有基础（无需改动）
- `common_utils.py` 已有 `friendly_error()`、`log_exception/warning/info`、Toast 分级通知
- `tray.py` 已有 `show_success/show_warning/show_error`、相册子菜单、画廊入口
- `config.py` 已有多相册管理（`albums`/`partner_albums`/`add_album`/`remove_album`/`list_albums`）
- `image_processor.py` 已有 `read_exif_info()`（仅返回日期+机型）、LRU 缓存、PIL 预取

### 待修复的关键 Bug
1. **EXIF 方向未校正** — [image_processor.py:267-270](file:///workspace/DesktopPhotoFrame/image_processor.py#L267-L270) `Image.open`+`copy()` 未调用 `ImageOps.exif_transpose()`，手机竖图横躺
2. **空状态不可见** — [frame_window.py:465-469](file:///workspace/DesktopPhotoFrame/frame_window.py#L465-L469) `_show_placeholder` 仅设 tooltip，不绘制可见文字，空目录时窗口完全透明
3. **水印显示今天日期** — [image_processor.py:288-289](file:///workspace/DesktopPhotoFrame/image_processor.py#L288-L289) 用 `datetime.now()` 而非照片拍摄日期
4. **shuffle 可能重复** — [frame_window.py:331-334](file:///workspace/DesktopPhotoFrame/frame_window.py#L331-L334) 随机选索引不排除当前索引

### 待新增的功能
5. **无照片收藏/星标** — 无法标记喜欢的照片
6. **无应用内删除** — 必须手动到文件夹删
7. **无"打开所在文件夹"** — 无法定位原图
8. **画廊无自动播放** — 全屏浏览只能手动切
9. **相框位置不持久化** — 拖动后重启回右下角
10. **画廊小图不填屏** — [gallery_window.py:65](file:///workspace/DesktopPhotoFrame/gallery_window.py#L65) `min(..., 1.0)` 导致小图周围大黑边

### 用户新增需求
11. **照片右键信息浮层** — 画廊全屏时显示完整 EXIF 详情（光圈/快门/ISO/GPS 等）
12. **设为桌面壁纸** — 右键菜单直接设为 Windows 桌面背景
13. **手动旋转照片** — 右键菜单旋转 90°，写回原图

## 修改方案

### 第一组：修复关键 Bug（高优先级）

#### 1.1 EXIF 方向校正
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py#L10)
**位置**: 顶部导入 + `process_to_pil()` 函数 line 267-270
**改动**:
- 顶部 `from PIL import Image, ImageDraw, ImageFilter, ImageFont` 改为加 `ImageOps`：
  ```python
  from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
  ```
- `process_to_pil()` 内 `Image.open` 之后、`copy()` 之前加一行：
  ```python
  with Image.open(src) as src_img:
      src_img.load()
      src_img = ImageOps.exif_transpose(src_img)  # 自动按 EXIF 方向旋转
      img = src_img.copy()
  ```
**为什么**: Pillow 的 `Image.open` 不自动应用 EXIF Orientation 标签，导致手机竖拍照片显示为横躺。`ImageOps.exif_transpose` 读取 EXIF 0x0112 并旋转像素，旋转后清除该标签，保证后续处理一致。无需新增依赖。

#### 1.2 空状态可见提示
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py#L465-L469)
**位置**: `_show_placeholder()` 方法
**改动**: 重写为绘制可见提示文字的 pixmap，而非仅设 tooltip：
```python
def _show_placeholder(self, text: str) -> None:
    from PySide6.QtGui import QFont
    pm = QPixmap(self._label.width(), self._label.height())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(200, 200, 200, 180)))
    p.setFont(QFont("Microsoft YaHei", 11))
    p.drawText(QRectF(0, 0, pm.width(), pm.height()), Qt.AlignCenter, text)
    p.end()
    self._label.set_image(pm, kb_enabled=False)
    self._label.setToolTip(text)
```
**导入补充**: `QPainter`/`QPen`/`QPixmap` 已在 frame_window.py 顶部导入（line 23-31），`QFont`/`QRectF`/`Qt` 需新增导入。实际：`QRectF` 已在 line 17 导入，`Qt` 已在 line 19 导入，只需新增 `QFont` 到 `PySide6.QtGui` 导入块。
**为什么**: 空目录时窗口完全透明，用户以为软件没启动。绘制半透明居中提示文字，用户能直观看到"把照片放进目录"。

#### 1.3 水印显示照片拍摄日期
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py#L288-L290)
**位置**: `process_to_pil()` 水印部分
**改动**:
- 新增辅助函数 `_read_exif_date(src)`（放在 `read_exif_info` 附近）：
  ```python
  def _read_exif_date(src: Path) -> str:
      """读 EXIF DateTimeOriginal，返回 'YYYY-MM-DD' 或空串。"""
      try:
          with Image.open(src) as im:
              exif = im.getexif()
      except Exception:
          return ""
      if not exif:
          return ""
      date = exif.get(_EXIF_DATE_ORIG) or exif.get(_EXIF_DATE_DIG)
      if not date:
          return ""
      # 形如 "2023:08:14 18:22:05" → "2023-08-14"
      return str(date).replace(":", "-", 2).split(" ", 1)[0]
  ```
- `process_to_pil()` 水印逻辑改为：
  ```python
  if watermark:
      date_text = _read_exif_date(src) or datetime.now().strftime("%Y-%m-%d")
      img = add_watermark(img, date_text, accent_rgb=accent_rgb)
  ```
**为什么**: 水印应反映照片拍摄日期（有纪念意义），而非"今天"的日期。无 EXIF 时回退到今天，避免空水印。

#### 1.4 shuffle 排除当前索引
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py#L331-L334)
**改动**:
```python
def shuffle(self) -> None:
    if len(self._images) > 1:
        choices = [i for i in range(len(self._images)) if i != self._index]
        self._index = random.choice(choices)
        self._switch_to(self._images[self._index])
```
**为什么**: 当前 `random.randrange(len)` 可能选中当前索引，导致"随机一张"看着没变。

---

### 第二组：原计划新增功能（中优先级）

#### 2.1 照片收藏/星标
**文件**:
- [config.py](file:///workspace/DesktopPhotoFrame/config.py) — 新增 favorites 存储
- [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py) — 新增收藏逻辑 + 只看收藏模式
- [tray.py](file:///workspace/tray.py) — 相册菜单加收藏相关项

**config.py 改动**:
- `DEFAULTS` 加 `"favorites": []`（文件绝对路径列表）
- `load()` 加类型校正：`data["favorites"] = [str(p) for p in data.get("favorites", []) if p]`
- 新增函数：
  ```python
  def toggle_favorite(path: str) -> bool:
      """切换收藏状态，返回切换后是否为收藏。"""
      data = load()
      favs = set(data.get("favorites", []))
      is_fav = path in favs
      if is_fav:
          favs.discard(path)
      else:
          favs.add(path)
      data["favorites"] = sorted(favs)
      save(data)
      return not is_fav

  def is_favorite(path: str) -> bool:
      return path in set(load().get("favorites", []))

  def list_favorites() -> list[str]:
      return load().get("favorites", [])
  ```

**frame_window.py 改动**:
- `__init__` 加 `self._favorites_only = False`
- 新增方法：
  ```python
  def toggle_favorite_current(self) -> None:
      if not self._images or self._index < 0:
          return
      src = str(self._images[self._index])
      is_fav = config.toggle_favorite(src)
      self.status_message.emit("⭐ 已收藏" if is_fav else "已取消收藏")

  def toggle_favorites_only(self) -> bool:
      self._favorites_only = not self._favorites_only
      self.reload()
      self.status_message.emit("只看收藏" if self._favorites_only else "显示全部")
      return self._favorites_only
  ```
- `reload()` 内 `self._images = ip.list_images(...)` 之后加过滤：
  ```python
  if self._favorites_only:
      favs = set(config.list_favorites())
      self._images = [p for p in self._images if str(p) in favs]
  ```

**tray.py 改动**:
- 新增信号：`pf_toggle_favorite = Signal()`、`pf_favorites_only = Signal()`
- 相册菜单区（`_act_shuffle` 之后、separator 之前）加两个 QAction：
  ```python
  self._act_fav = QAction("⭐ 收藏当前", menu)
  self._act_fav.triggered.connect(self.pf_toggle_favorite)
  menu.addAction(self._act_fav)

  self._act_fav_only = QAction("只看收藏", menu)
  self._act_fav_only.setCheckable(True)
  self._act_fav_only.triggered.connect(self._on_favorites_only)
  menu.addAction(self._act_fav_only)
  ```
- 新增槽 `_on_favorites_only`：
  ```python
  def _on_favorites_only(self) -> None:
      on = self._pf_window.toggle_favorites_only()
      self._act_fav_only.setChecked(on)
  ```
- `launcher.py` 连接：`tray.pf_toggle_favorite.connect(pf_window.toggle_favorite_current)`

#### 2.2 应用内删除照片
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)、[tray.py](file:///workspace/tray.py)

**frame_window.py 改动**:
- 顶部导入加 `from PySide6.QtWidgets import QMessageBox`（与现有 `QGraphicsDropShadowEffect, QVBoxLayout, QWidget` 同块）
- 新增方法：
  ```python
  def delete_current(self) -> None:
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
      # 同步从收藏列表移除
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
  ```

**tray.py 改动**:
- 新增信号 `pf_delete = Signal()`
- 相册菜单区加 `self._act_delete = QAction("🗑 删除当前照片", menu)`，连接 `pf_delete`
- `launcher.py` 连接：`tray.pf_delete.connect(pf_window.delete_current)`

#### 2.3 打开所在文件夹
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)、[tray.py](file:///workspace/tray.py)

**frame_window.py 改动**:
- 顶部导入加 `import subprocess`、`import sys`
- 新增方法：
  ```python
  def open_in_explorer(self) -> None:
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
  ```

**tray.py 改动**:
- 新增信号 `pf_open_folder = Signal()`
- 相册菜单区加 `self._act_folder = QAction("📂 打开所在文件夹", menu)`，连接 `pf_open_folder`
- `launcher.py` 连接：`tray.pf_open_folder.connect(pf_window.open_in_explorer)`

#### 2.4 画廊自动播放（幻灯片）
**文件**: [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py)

**GalleryWindow 改动**:
- `__init__` 加 `self._auto_play = False`、`self._auto_timer = QTimer(self)`、`self._auto_timer.setInterval(5000)`、`self._auto_timer.timeout.connect(self.show_next)`
- `_build_ui()` 工具栏按钮加 `btn_play = QPushButton("▶ 自动播放")`，`btn_play.clicked.connect(self._toggle_auto_play)`，存 `self._btn_play = btn_play`
- 新增方法：
  ```python
  def _toggle_auto_play(self) -> None:
      self._auto_play = not self._auto_play
      if self._auto_play:
          self._auto_timer.start()
          self._btn_play.setText("⏸ 停止")
      else:
          self._auto_timer.stop()
          self._btn_play.setText("▶ 自动播放")

  def closeEvent(self, e) -> None:
      if hasattr(self, "_auto_timer"):
          self._auto_timer.stop()
      super().closeEvent(e)
  ```
- 工具栏布局调整：`btn_prev`、`btn_play`、`btn_next`、`btn_grid`、`btn_exit`

#### 2.5 相框位置持久化
**文件**: [config.py](file:///workspace/DesktopPhotoFrame/config.py)、[frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)

**config.py 改动**:
- `DEFAULTS` 加 `"window_x": None, "window_y": None`
- `load()` 加校正：保留 None 或 int，其他转 int：
  ```python
  for k in ("window_x", "window_y"):
      v = data.get(k)
      if v is not None:
          try:
              data[k] = int(v)
          except (TypeError, ValueError):
              data[k] = None
  ```
- 新增便捷函数：
  ```python
  def save_window_pos(x: int, y: int) -> None:
      update(window_x=int(x), window_y=int(y))
  ```

**frame_window.py 改动**:
- `_place_initial()` 读取持久化位置：
  ```python
  def _place_initial(self) -> None:
      saved_x = self._cfg.get("window_x")
      saved_y = self._cfg.get("window_y")
      screen = self.screen().availableGeometry()
      if saved_x is not None and saved_y is not None:
          # 边界检查：位置必须在某屏幕内（避免拖到外接显示器后拔了找不到）
          if (screen.left() <= saved_x <= screen.right()
                  and screen.top() <= saved_y <= screen.bottom()):
              self.move(int(saved_x), int(saved_y))
              return
      # 默认右下角
      w, h = self.width(), self.height()
      self.move(screen.right() - w - 40, screen.bottom() - h - 40)
  ```
- `mouseReleaseEvent` 拖动结束时保存位置：
  ```python
  def mouseReleaseEvent(self, e: QMouseEvent) -> None:
      if self._drag_offset is not None:
          # 拖动结束，持久化位置
          try:
              config.save_window_pos(self.x(), self.y())
          except Exception:
              log_warning("保存相框位置失败")
      self._drag_offset = None
      e.accept()
  ```

#### 2.6 画廊小图填屏
**文件**: [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py#L61-L68)
**位置**: `_fit_to_screen()` 函数
**改动**: 去掉 `1.0` 上限，让小图也能放大填屏（但保持等比，仍可能有单边留白，由 QLabel 居中处理）：
```python
def _fit_to_screen(img: Image.Image, max_w: int, max_h: int, zoom: float = 1.0) -> QPixmap:
    img = img.convert("RGBA")
    w, h = img.size
    # 去掉 min(..., 1.0)：小图也按屏幕放大（cover 模式会裁剪，contain 仍留白）
    # 用 cover 模式填满屏幕，避免黑边
    scale = min(max_w / w, max_h / h) * zoom
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    # 居中裁剪到屏幕尺寸，避免超出
    left = max(0, (nw - max_w) // 2)
    top = max(0, (nh - max_h) // 2)
    img = img.crop((left, top, left + max_w, top + max_h))
    return ip.pil_to_pixmap(img)
```
**为什么**: 原 `min(..., 1.0)` 限制小图不放大，导致小图周围大黑边。改为 cover 模式填满屏幕，牺牲少量边缘换取沉浸感。zoom>1 时仍可放大查看细节。

---

### 第三组：用户新增功能（中优先级）

#### 3.1 照片右键信息浮层（EXIF 详情）
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py)、[gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py)

**image_processor.py 改动**:
- 新增 EXIF 标签常量：
  ```python
  _EXIF_ORIENTATION = 0x0112
  _EXIF_FNUMBER = 0x829D       # 光圈 F
  _EXIF_EXPOSURE = 0x829A      # 快门（秒）
  _EXIF_ISO = 0x8827          # ISO
  _EXIF_FOCAL = 0x920A         # 焦距 mm
  _EXIF_GPS = 0x8825          # GPS IFD
  ```
- 新增函数 `read_exif_details(src) -> dict`，返回结构化 EXIF：
  ```python
  def read_exif_details(src: Path) -> dict:
      """读取完整 EXIF 信息，返回 dict；读取失败返回空 dict。"""
      try:
          with Image.open(src) as im:
              exif = im.getexif()
      except Exception:
          return {}
      if not exif:
          return {}
      info = {}
      # 日期
      date = exif.get(_EXIF_DATE_ORIG) or exif.get(_EXIF_DATE_DIG)
      if date:
          info["拍摄日期"] = str(date).replace(":", "-", 2).split(" ", 1)[0]
      # 机型
      make = (exif.get(_EXIF_MAKE) or "").strip()
      model = (exif.get(_EXIF_MODEL) or "").strip()
      if make or model:
          info["机型"] = f"{make} {model}".strip()
      # 光圈
      fnum = exif.get(_EXIF_FNUMBER)
      if fnum:
          info["光圈"] = f"f/{float(fnum):.1f}"
      # 快门
      exp = exif.get(_EXIF_EXPOSURE)
      if exp:
          try:
              v = float(exp)
              info["快门"] = f"1/{int(1/v)}" if v < 1 else f"{v:.1f}s"
          except (TypeError, ValueError):
              pass
      # ISO
      iso = exif.get(_EXIF_ISO)
      if iso:
          info["ISO"] = str(iso)
      # 焦距
      focal = exif.get(_EXIF_FOCAL)
      if focal:
          info["焦距"] = f"{float(focal):.0f}mm"
      # GPS（简化：只标"有位置"，完整解析留给后续）
      if exif.get(_EXIF_GPS):
          info["GPS"] = "有位置信息"
      return info
  ```

**gallery_window.py 改动**:
- `GalleryWindow.__init__` 加 `self._info_label: QLabel | None = None`
- `_build_ui()` 加一个隐藏的信息浮层 QLabel（半透明背景，左上角）：
  ```python
  self._info_label = QLabel(central)
  self._info_label.setStyleSheet(
      "QLabel{background:rgba(0,0,0,180);color:#fff;padding:12px 16px;"
      "font-size:13px;border-radius:8px;}"
  )
  self._info_label.setParent(central)
  self._info_label.move(16, 60)
  self._info_label.hide()
  ```
- 工具栏加按钮 `btn_info = QPushButton("ℹ 信息")`，`btn_info.clicked.connect(self._toggle_info)`
- 新增方法：
  ```python
  def _toggle_info(self) -> None:
      if self._info_label.isVisible():
          self._info_label.hide()
          return
      if not self._images:
          return
      src = self._images[self._index]
      info = ip.read_exif_details(src)
      if not info:
          self._info_label.setText("无 EXIF 信息")
      else:
          lines = [f"{k}：{v}" for k, v in info.items()]
          lines.insert(0, f"📷 {src.name}")
          self._info_label.setText("\n".join(lines))
      self._info_label.adjustSize()
      self._info_label.show()
      # 5 秒后自动隐藏
      QTimer.singleShot(5000, self._info_label.hide)
  ```
- `show_next`/`show_prev` 切换时隐藏信息浮层：`self._info_label.hide()`

#### 3.2 设为桌面壁纸
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)、[tray.py](file:///workspace/tray.py)

**frame_window.py 改动**:
- 新增方法（仅 Windows 生效，其他平台提示）：
  ```python
  def set_as_wallpaper(self) -> None:
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
  ```

**tray.py 改动**:
- 新增信号 `pf_wallpaper = Signal()`
- 相册菜单区加 `self._act_wallpaper = QAction("🖼 设为桌面壁纸", menu)`，连接 `pf_wallpaper`
- `launcher.py` 连接：`tray.pf_wallpaper.connect(pf_window.set_as_wallpaper)`

#### 3.3 手动旋转照片
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py)、[frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)、[tray.py](file:///workspace/tray.py)

**image_processor.py 改动**:
- 新增函数 `rotate_image_in_place(src, degrees=90)`：
  ```python
  def rotate_image_in_place(src: Path, degrees: int = 90) -> bool:
      """原地旋转图片（顺时针 degrees 度），写回原文件。返回是否成功。

      策略：先 exif_transpose 应用已有方向 → rotate 像素 → 保存并清除 EXIF Orientation。
      JPEG 用原质量保存，其他格式用默认。
      """
      try:
          with Image.open(src) as im:
              im.load()
              im = ImageOps.exif_transpose(im)  # 先应用现有方向
              im = im.rotate(-degrees, expand=True)  # 顺时针 = 负角度
              # 保留 EXIF 但清除 Orientation（已应用）
              exif = im.getexif() if hasattr(im, "getexif") else None
              if exif and 0x0112 in exif:
                  exif[0x0112] = 1  # Normal
              save_kwargs = {}
              if exif:
                  save_kwargs["exif"] = exif.tobytes() if hasattr(exif, "tobytes") else None
              fmt = im.format or "JPEG"
              im.save(src, format=fmt, **{
                  k: v for k, v in save_kwargs.items() if v is not None
              })
          return True
      except Exception:
          log_exception("旋转图片失败: %s", src)
          return False
  ```

**frame_window.py 改动**:
- 新增方法：
  ```python
  def rotate_current(self) -> None:
      if not self._images or self._index < 0:
          return
      src = self._images[self._index]
      if not ip.rotate_image_in_place(src, 90):
          self.status_message.emit("旋转失败")
          return
      # 清缓存强制重新加载
      try:
          ip.get_cache().clear()
      except Exception:
          pass
      self._switch_to(src)
      self.status_message.emit(f"已旋转 90°：{src.name}")
  ```

**tray.py 改动**:
- 新增信号 `pf_rotate = Signal()`
- 相册菜单区加 `self._act_rotate = QAction("🔄 旋转 90°", menu)`，连接 `pf_rotate`
- `launcher.py` 连接：`tray.pf_rotate.connect(pf_window.rotate_current)`

---

### 托盘菜单最终结构

```
— 相册 —
下一张 →
上一张 ←
随机一张 🎲
———————
⭐ 收藏当前
☑ 只看收藏
🗑 删除当前照片
📂 打开所在文件夹
🔄 旋转 90°
🖼 设为桌面壁纸
———————
暂停
放大/缩小 (双击)
———————
☑ 拍立得边框
☑ 日期水印
☑ Ken Burns 动画
☑ 模糊背景填充
切换相册 ▶
选择图片目录…
🖼 画廊浏览…
（后续信箱/日历/影视/地图/互动/工具区不变）
```

## 假设与决策

1. **不新增第三方依赖** — EXIF 方向/旋转用 Pillow 内置 `ImageOps`，壁纸用 Windows `ctypes`
2. **收藏数据存配置文件** — 用 `photo_frame.json` 的 `favorites` 列表（绝对路径），不新建数据库
3. **删除照片不可撤销** — 直接 `unlink()`，但有确认对话框；同步从收藏列表移除
4. **位置持久化范围** — 只存 x/y 坐标，不存窗口尺寸（尺寸仍由设置控制）；带屏幕边界检查
5. **画廊自动播放间隔** — 固定 5 秒，不做设置项（保持简洁）
6. **画廊小图填屏用 cover 模式** — 会裁剪边缘，但无黑边；zoom>1 时仍可看细节
7. **旋转写回原文件** — 先 exif_transpose 再 rotate，保存时清除 EXIF Orientation；JPEG 保留其他 EXIF
8. **壁纸功能仅 Windows** — 用 `SystemParametersInfoW`，非 Windows 平台提示不支持
9. **信息浮层在画廊全屏** — 左上角半透明面板，5 秒自动隐藏，切换图片时也隐藏
10. **画廊自动播放与信息浮层不冲突** — 自动播放时信息浮层按 5 秒自动隐藏，不影响切图
11. **新菜单项集中在"相册"区** — 放在"随机一张"之后、原有"暂停"之前，作为"当前照片操作"组

## 涉及文件清单

| 文件 | 改动项 |
|------|--------|
| [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py) | 1.1 EXIF 校正、1.3 水印日期、3.1 read_exif_details、3.3 rotate_image_in_place |
| [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py) | 1.2 空状态、1.4 shuffle、2.1 收藏、2.2 删除、2.3 打开文件夹、2.5 位置持久化、3.2 壁纸、3.3 旋转 |
| [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py) | 2.4 自动播放、2.6 小图填屏、3.1 信息浮层 |
| [config.py](file:///workspace/DesktopPhotoFrame/config.py) | 2.1 favorites、2.5 window_x/y |
| [tray.py](file:///workspace/tray.py) | 2.1/2.2/2.3/3.2/3.3 新菜单项 + 信号 |
| [launcher.py](file:///workspace/launcher.py) | 连接新信号到 frame_window 方法 |

## 验证步骤

### 1. 语法检查
```bash
python -m py_compile DesktopPhotoFrame/image_processor.py
python -m py_compile DesktopPhotoFrame/frame_window.py
python -m py_compile DesktopPhotoFrame/gallery_window.py
python -m py_compile DesktopPhotoFrame/config.py
python -m py_compile tray.py
python -m py_compile launcher.py
```

### 2. 手动验证清单
- [ ] 放一张手机竖拍照片到相册目录，确认方向正确（不横躺）
- [ ] 清空相册目录，相框显示可见提示文字"把照片放进目录：..."（非透明空白）
- [ ] 照片水印显示拍摄日期（如 2023-08-14），而非今天日期
- [ ] 连续点"随机一张"3 次，确认不会连续出现同一张
- [ ] 右键托盘→⭐ 收藏当前→托盘弹出"已收藏"→点"只看收藏"→只显示收藏的照片
- [ ] 右键托盘→🗑 删除当前照片→确认对话框→照片被删除、相框自动切到下一张、文件确实从磁盘消失
- [ ] 右键托盘→📂 打开所在文件夹→资源管理器弹出并选中照片
- [ ] 画廊全屏→点"▶ 自动播放"→每 5 秒自动切图→点"⏸ 停止"
- [ ] 拖动相框到屏幕中央→重启应用→相框出现在上次拖动的位置
- [ ] 画廊全屏看一张小尺寸图→小图放大填满屏幕（无大黑边）
- [ ] 画廊全屏→点"ℹ 信息"→左上角浮层显示 EXIF 详情（光圈/快门/ISO 等）→5 秒后自动隐藏
- [ ] 右键托盘→🖼 设为桌面壁纸→桌面背景变为该照片（仅 Windows）
- [ ] 右键托盘→🔄 旋转 90°→照片顺时针旋转 90°、写回原文件、相框立即刷新

### 3. 边界场景
- [ ] 相册为空时点"收藏/删除/旋转/壁纸"→不崩溃，无操作
- [ ] "只看收藏"模式下没有收藏照片→显示空状态提示
- [ ] 旋转只读文件→提示"旋转失败"，不崩溃
- [ ] 拖到外接显示器后拔掉→重启后位置回退到主屏右下角（边界检查）
- [ ] 非 Windows 平台点"设为壁纸"→提示"仅支持 Windows"

### 4. 提交
- `git add` 6 个修改文件 + 计划文档
- commit message: `feat(album): 相册优化 — 修 4 Bug + 加 9 功能（收藏/删除/文件夹/自动播放/位置持久/填屏/EXIF 浮层/壁纸/旋转）`
- push 到 origin/main
