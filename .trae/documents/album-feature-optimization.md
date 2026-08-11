# 相册功能优化计划

## 概述

针对桌面相册模块（DesktopPhotoFrame）进行细节优化和功能增强，修复影响体验的关键 bug，并增加实用新功能。

## 当前状态分析

相册模块基础功能完备（轮播、Ken Burns、拍立得、水印、多相册、画廊、共享），但存在以下问题：

### 关键 Bug
1. **EXIF 方向未校正** — `image_processor.py:267-270` `Image.open` + `copy()` 未调用 `ImageOps.exif_transpose()`，手机竖图横躺
2. **空状态不可见** — `frame_window.py:465-469` `_show_placeholder` 仅设 tooltip，不绘制可见文字，空目录时窗口完全透明
3. **水印显示今天日期** — `image_processor.py:289` 用 `datetime.now()` 而非照片拍摄日期
4. **shuffle 可能重复** — `frame_window.py:331-334` 随机选索引不排除当前索引

### 缺失功能
5. **无照片收藏/星标** — 无法标记喜欢的照片
6. **无应用内删除** — 必须手动到文件夹删
7. **无"打开所在文件夹"** — 无法定位原图
8. **画廊无自动播放** — 全屏浏览只能手动切
9. **相框位置不持久化** — 拖动后重启回右下角
10. **画廊小图不填屏** — `gallery_window.py:65` `min(..., 1.0)` 导致小图周围大黑边

## 修改方案

### 第一组：修复关键 Bug（高优先级）

#### 1.1 EXIF 方向校正
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py#L266-L270)
**位置**: `process_to_pil()` 函数，`Image.open` 之后
**改动**: 在 `img = src_img.copy()` 之前加 `src_img = ImageOps.exif_transpose(src_img)`
```python
from PIL import ImageOps  # 顶部导入

# process_to_pil 内部：
with Image.open(src) as src_img:
    src_img.load()
    src_img = ImageOps.exif_transpose(src_img)  # 自动旋转
    img = src_img.copy()
```

#### 1.2 空状态可见提示
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py#L465-L469)
**位置**: `_show_placeholder()` 方法
**改动**: 在 `KenBurnsLabel` 上绘制可见文字（半透明背景 + 居中提示文本），而非仅设 tooltip
```python
def _show_placeholder(self, text: str) -> None:
    # 生成一个带提示文字的 pixmap 显示
    from PySide6.QtGui import QPainter, QFont, QColor, QPixmap, QPen
    from PySide6.QtCore import Qt, QRectF
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

#### 1.3 水印显示照片拍摄日期
**文件**: [image_processor.py](file:///workspace/DesktopPhotoFrame/image_processor.py#L288-L290)
**位置**: `process_to_pil()` 水印部分
**改动**: 优先使用 EXIF 拍摄日期，无 EXIF 时回退到今天日期
```python
if watermark:
    # 优先用照片拍摄日期，无 EXIF 时用今天
    exif_date = _read_exif_date(src)  # 新增辅助函数
    date_text = exif_date or datetime.now().strftime("%Y-%m-%d")
    img = add_watermark(img, date_text, accent_rgb=accent_rgb)
```
新增 `_read_exif_date(src)` 辅助函数，从 EXIF 读取 `DateTimeOriginal` 并格式化为 `YYYY-MM-DD`。

#### 1.4 shuffle 排除当前索引
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py#L331-L334)
**改动**: 随机选索引时排除当前
```python
def shuffle(self) -> None:
    if len(self._images) > 1:
        choices = [i for i in range(len(self._images)) if i != self._index]
        self._index = random.choice(choices)
        self._switch_to(self._images[self._index])
```

### 第二组：新增功能（中优先级）

#### 2.1 照片收藏/星标
**文件**: 
- [config.py](file:///workspace/DesktopPhotoFrame/config.py) — 新增 `favorites` 列表存储（文件名列表）
- [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py) — 托盘菜单加"收藏当前/取消收藏"，画廊加★标记
- [tray.py](file:///workspace/tray.py) — 相册菜单区加"⭐ 收藏当前"/"🎲 随机收藏"

**设计**: 
- config.py DEFAULTS 加 `"favorites": []`
- config.py 新增 `toggle_favorite(path)` / `list_favorites()` / `is_favorite(path)`
- frame_window.py 新增 `toggle_favorite()` 方法 + `show_favorites()` 方法（只播收藏列表）
- tray.py 相框区加两个菜单项

#### 2.2 应用内删除照片
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)
**改动**: 新增 `delete_current()` 方法，带确认对话框，删除后从列表移除并切到下一张
```python
def delete_current(self) -> None:
    if not self._images or self._index < 0:
        return
    src = self._images[self._index]
    btn = QMessageBox.question(self, "删除照片",
        f"确定删除「{src.name}」吗？\n此操作不可撤销。")
    if btn != QMessageBox.Yes:
        return
    try:
        src.unlink()
    except OSError as e:
        self.status_message.emit(f"删除失败：{e}")
        return
    del self._images[self._index]
    if not self._images:
        self._show_placeholder("相册已空")
        self._timer.stop()
    else:
        self._index = min(self._index, len(self._images) - 1)
        self._switch_to(self._images[self._index])
    self.status_message.emit(f"已删除 {src.name}")
```
**文件**: [tray.py](file:///workspace/tray.py) — 相框菜单区加"🗑 删除当前照片"

#### 2.3 打开所在文件夹
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py)
**改动**: 新增 `open_in_explorer()` 方法
```python
def open_in_explorer(self) -> None:
    if not self._images or self._index < 0:
        return
    src = self._images[self._index]
    import subprocess, sys
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(src)])
    else:
        subprocess.Popen(["xdg-open", str(src.parent)])
```
**文件**: [tray.py](file:///workspace/tray.py) — 相框菜单区加"📂 打开所在文件夹"

#### 2.4 画廊自动播放（幻灯片）
**文件**: [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py)
**位置**: `GalleryWindow` 类
**改动**: 
- 顶部工具栏加"▶ 自动播放"按钮
- 用 QTimer 定时切换（间隔 5 秒）
- 播放时按钮变"⏸ 停止"
- 到最后一张循环回第一张

#### 2.5 相框位置持久化
**文件**: 
- [config.py](file:///workspace/DesktopPhotoFrame/config.py) — DEFAULTS 加 `"window_x": null, "window_y": null`
- [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py) — `_place_initial()` 读取持久化位置；拖动结束（`mouseReleaseEvent`）时保存位置
```python
def _place_initial(self) -> None:
    saved_x = self._cfg.get("window_x")
    saved_y = self._cfg.get("window_y")
    if saved_x is not None and saved_y is not None:
        self.move(int(saved_x), int(saved_y))
    else:
        # 原逻辑：右下角
        screen = self.screen().availableGeometry()
        self.move(screen.right() - self.width() - 40,
                  screen.bottom() - self.height() - 40)
```

#### 2.6 画廊小图填屏
**文件**: [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py#L61-L68)
**位置**: `_fit_to_screen()` 函数
**改动**: 去掉 `1.0` 上限，让小图也能放大填屏
```python
def _fit_to_screen(w, h, max_w, max_h, zoom=1.0):
    scale = min(max_w / w, max_h / h) * zoom  # 去掉 min(..., 1.0)
    return int(w * scale), int(h * scale)
```

### 第三组：体验细节优化（低优先级）

#### 3.1 加载失败自动跳过
**文件**: [frame_window.py](file:///workspace/DesktopPhotoFrame/frame_window.py#L353-L355)
**改动**: 加载失败时不再卡在坏图上，自动跳到下一张（最多跳 3 次避免死循环）
```python
if pixmap is None or pixmap.isNull():
    self._show_placeholder(f"无法加载：\n{src.name}")
    # 3 秒后自动跳到下一张（避免卡在坏图上）
    if not hasattr(self, '_fail_count'):
        self._fail_count = 0
    self._fail_count += 1
    if self._fail_count < 3:
        QTimer.singleShot(2000, self.show_next)
    else:
        self._fail_count = 0
    return
# 成功加载后重置
self._fail_count = 0
```

#### 3.2 画廊缩放后平移
**文件**: [gallery_window.py](file:///workspace/DesktopPhotoFrame/gallery_window.py)
**改动**: 全屏画廊放大后支持鼠标拖动平移查看细节
- `_label` 改为 `QScrollArea` 包裹，或手动实现拖动偏移
- 放大后显示"拖动查看"提示

## 假设与决策

1. **不新增第三方依赖** — EXIF 方向用 Pillow 内置 `ImageOps.exif_transpose`，无需额外库
2. **收藏数据存配置文件** — 不新建数据库，用 config.json 里的 `favorites` 列表（文件路径列表）
3. **删除照片不可撤销** — 不进回收站，直接 `unlink()`，但有确认对话框
4. **位置持久化范围** — 只存 x/y 坐标，不存窗口尺寸（尺寸仍由设置控制）
5. **画廊自动播放间隔** — 固定 5 秒，不做设置项（保持简洁）
6. **第三组（3.1/3.2）为可选项** — 视实现复杂度决定是否纳入

## 验证步骤

1. `py_compile` 全部修改文件
2. 手动验证：
   - 放一张手机竖拍照片到相册目录，确认方向正确
   - 清空相册目录，确认相框显示可见提示文字（非透明空白）
   - 照片水印显示拍摄日期（而非今天）
   - 连续点"随机一张"，确认不会连续出现同一张
   - 右键托盘→收藏当前→切换到"只看收藏"模式
   - 右键托盘→删除当前照片→确认后照片被删除、相框自动切到下一张
   - 右键托盘→打开所在文件夹→资源管理器弹出并选中照片
   - 画廊全屏→点"自动播放"→每 5 秒自动切图→点"停止"
   - 拖动相框到屏幕中央→重启应用→相框出现在上次拖动的位置
   - 画廊全屏看小图→小图放大填满屏幕（无大黑边）
3. 提交并 push
