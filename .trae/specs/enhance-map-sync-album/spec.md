# 地图数据修复 / 云中转同步 / 相册展示优化 Spec

## Why
当前套件存在三类待修复与增强点：旅行地图的城市照片仅存原路径未复制到 AppData，原图移动后数据损坏；信箱同步仅支持局域网 TCP 直连，跨网情侣无法使用；相框只有小浮窗轮播，缺少沉浸式浏览体验。本变更修复地图数据持久化、新增云服务器中转同步、优化相册照片展示。

## What Changes
- **修复地图数据**：城市照片选择后复制到 `travel/photos/` 并存相对路径，原图移动/删除不影响数据；同样修复打卡日历的附图存储
- **新增云中转同步**：在局域网 TCP 基础上新增 HTTP 云中转模式，信件通过云服务器中转投递，跨网络可用；保留局域网模式作为可选
- **相册展示优化**：新增全屏画廊窗口（沉浸式查看大图、键盘左右切换、ESC 退出）、缩略图网格浏览窗口（批量预览、点击放大、跳转相册管理）

## Impact
- Affected specs: 旅行地图存储、信箱同步、相框展示
- Affected code:
  - 修改 `TravelMap/map_window.py`（_pick_photo 复制图片到 AppData）
  - 修改 `DailyCheckin/checkin_window.py`（附图复制到 AppData）
  - 新增 `DesktopMailbox/cloud_sync.py`（HTTP 云中转客户端）
  - 修改 `DesktopMailbox/sync.py`（SyncHub 支持双模式：lan/cloud）
  - 修改 `DesktopMailbox/config.py`（新增 cloud_* 配置项）
  - 修改 `settings_window.py`（同步标签页新增云模式配置）
  - 新增 `DesktopPhotoFrame/gallery_window.py`（全屏画廊 + 缩略图网格）
  - 修改 `DesktopPhotoFrame/frame_window.py`（新增打开画廊入口）
  - 修改 `tray.py`（相框区新增"🖼 画廊浏览"菜单项）
  - 修改 `launcher.py`（连接画廊信号）

## ADDED Requirements

### Requirement: 城市照片持久化存储
系统 SHALL 在用户为城市选择照片时，将照片复制到 AppData 的 `travel/photos/` 目录，存储相对文件名而非原始绝对路径，确保原图移动或删除后地图数据仍完整。

#### Scenario: 添加城市照片
- **WHEN** 用户在编辑城市对话框选择一张照片
- **THEN** 系统将照片复制到 `%APPDATA%\CoupleSuite\travel\photos\{timestamp}_{filename}`
- **AND** 存储该相对文件名到 image_path 字段
- **AND** 详情卡片显示时从 AppData 加载照片

#### Scenario: 原图移动后仍可显示
- **WHEN** 用户添加城市照片后，原始照片文件被移动或删除
- **THEN** 城市详情卡片仍能正常显示照片（因为已复制到 AppData）

### Requirement: 打卡附图持久化存储
系统 SHALL 在用户为打卡记录选择附图时，将图片复制到 AppData 的 `checkin/images/` 目录，存储相对文件名，确保原图移动后打卡数据完整。

#### Scenario: 打卡附图
- **WHEN** 用户在打卡编辑器选择附图
- **THEN** 系统将图片复制到 `%APPDATA%\CoupleSuite\checkin\images\{timestamp}_{filename}`
- **AND** 存储相对文件名到 image_path 字段

### Requirement: 云服务器中转同步
系统 SHALL 提供基于 HTTP 的云中转同步模式，信件通过云服务器中转投递，使不同网络的情侣也能互寄信件。云模式与局域网模式可独立开关。

#### Scenario: 配置云同步
- **WHEN** 用户在设置→同步页选择"云中转模式"并填入服务器地址和情侣配对码
- **THEN** 系统保存配置，SyncHub 启动时优先使用云模式

#### Scenario: 云模式寄信
- **WHEN** 用户在云模式下寄出一封信
- **THEN** 系统将信件元数据+正文+附件 POST 到云服务器
- **AND** 服务器暂存信件，对方客户端轮询拉取
- **AND** 发送成功后通知用户"已通过云中转寄出"

#### Scenario: 云模式收信
- **WHEN** SyncHub 启动云模式时
- **THEN** 后台定时器每 30 秒向云服务器轮询新信件
- **AND** 拉取到新信件后本地加密落盘并弹出通知

#### Scenario: 云模式失败回退
- **WHEN** 云服务器不可达
- **THEN** 显示"云同步暂时不可用"提示，不崩溃，信件仍本地保存
- **AND** 下次轮询自动重试

### Requirement: 全屏画廊窗口
系统 SHALL 提供全屏画廊窗口，沉浸式查看当前相册的大图，支持键盘左右切换、ESC 退出、滚轮缩放。

#### Scenario: 打开画廊
- **WHEN** 用户点托盘"🖼 画廊浏览"
- **THEN** 弹出全屏画廊窗口，显示当前相册第一张照片的大图
- **AND** 窗口无边框覆盖整个屏幕，照片居中 contain 显示

#### Scenario: 键盘导航
- **WHEN** 用户按→/↓或空格
- **THEN** 切换到下一张
- **WHEN** 用户按←/↑
- **THEN** 切换到上一张
- **WHEN** 用户按 ESC
- **THEN** 关闭画廊窗口

#### Scenario: 滚轮缩放
- **WHEN** 用户在画廊中滚动滚轮
- **THEN** 照片在 1.0~3.0 倍之间缩放

### Requirement: 缩略图网格浏览
系统 SHALL 提供缩略图网格窗口，以瀑布流/网格形式批量预览相册所有照片，点击可放大查看或跳转。

#### Scenario: 打开网格浏览
- **WHEN** 用户在画廊窗口点"网格"按钮或托盘"🖼 画廊浏览"
- **THEN** 显示网格窗口，4 列缩略图，每张 200x200
- **AND** 双击某张可全屏查看

#### Scenario: 切换相册
- **WHEN** 用户在网格窗口顶部下拉选择相册
- **THEN** 网格刷新显示该相册的所有照片

## MODIFIED Requirements

### Requirement: 信箱同步中枢
SyncHub SHALL 支持两种同步模式：`lan`（局域网 TCP 直连，原实现）和 `cloud`（HTTP 云中转）。模式由配置 `sync_mode` 决定，默认 `lan`。两种模式可同时启用（双通道冗余），但至少启用其一才能同步。

### Requirement: 同步设置标签页
设置窗口同步标签页 SHALL 新增：模式选择（单选：局域网/云中转/两者）、云服务器地址输入框、情侣配对码输入框（用于服务器端配对识别）。选择"云中转"或"两者"时显示云配置项，选择"局域网"时隐藏。

### Requirement: 托盘相框区
托盘相框区 SHALL 新增"🖼 画廊浏览…"菜单项，打开全屏画廊窗口。
