# 情侣套件功能扩展与 EXE 打包 Spec

## Why
当前情侣套件（桌面相框 + 悄悄话信箱）已融合为统一托盘应用，但仍存在三类短板：(1) 配置只能手改 JSON，普通用户无法操作；(2) 每次切图都重跑 PIL 管线，大图场景卡顿；(3) 数据写在源码目录，打包成 exe 后写入受限、无法分发。本次扩展目标是补齐 GUI 配置、性能优化、数据迁移与打包，使其成为可分发的 Windows 桌面应用。

## What Changes
- 数据目录迁移到 `%APPDATA%\CoupleSuite\`（config + 相框配置 + 信箱 data），为 exe 分发奠基
- 新增设置窗口：相框/信箱/同步/纪念日/自启动 全图形化配置，取代手改 JSON
- 新增图片缓存层：按 (路径, 尺寸, 选项) 缓存 QPixmap，并后台预生成下一张缩略图
- 新增开机自启动（写注册表 Run 键，设置窗口可开关）
- 新增数据备份/导出与恢复（zip 打包相框 images + 信箱 data，便于换机迁移）
- 新增多相册分组：支持多个图片目录，托盘可切换相册
- 新增首次运行引导：设置双方昵称、图片目录、（可选）对方 IP
- 新增统计看板：在一起天数、信件总数、照片数、下个纪念日倒计时
- PyInstaller 打包为 exe（onedir 模式 + 应用图标 + 资源打包）
- **BREAKING**：`config.py` 中 `CONFIG_PATH` / `DATA_DIR` 改为 AppData 路径；首次启动自动迁移旧数据

## Impact
- Affected specs: 相框配置、信箱配置、统一托盘菜单
- Affected code:
  - `DesktopPhotoFrame/config.py`、`DesktopMailbox/config.py`（路径迁移 + 统一 AppData 根）
  - `DesktopPhotoFrame/image_processor.py`、`frame_window.py`（缓存层 + 预生成）
  - `tray.py`（新增设置/备份/相册切换/看板菜单项）
  - `launcher.py`（首次引导 + 自启动检查 + 设置窗口接入）
  - 新增 `settings_window.py`、`backup.py`、`stats_window.py`、`onboarding.py`、`app_paths.py`
  - 新增 `couple_suite.spec`（PyInstaller 打包配置）+ `assets/icon.ico`

## ADDED Requirements

### Requirement: 统一应用数据目录
系统 SHALL 将所有可写数据（配置、信箱 data、图片目录默认位置、缓存）存放在 `%APPDATA%\CoupleSuite\` 下，而非源码/exe 所在目录。

#### Scenario: 首次启动迁移
- WHEN 应用首次在新数据目录启动且发现旧 `DesktopPhotoFrame/config.json` / `DesktopMailbox/data/`
- THEN 系统自动把旧配置与数据迁移到新 AppData 目录，并保留原始内容
- AND 在新目录写一个 `.migrated` 标记，避免重复迁移

#### Scenario: 打包后写入
- WHEN 应用以 exe 形式运行（可能位于只读 Program Files）
- THEN 配置与数据读写均成功，不报权限错误

### Requirement: 设置窗口
系统 SHALL 提供一个图形化设置窗口，涵盖相框、信箱、同步、纪念日、自启动所有可配置项，保存后即时生效。

#### Scenario: 修改轮播间隔
- WHEN 用户在设置窗口把轮播间隔从 15 改为 30 并点保存
- THEN 相框立即按 30 秒间隔轮播，无需重启

#### Scenario: 切换同步开关
- WHEN 用户在设置窗口勾选"启用局域网同步"并填对方 IP 后保存
- THEN SyncHub 重启并开始监听，写信寄出时同步给对方

### Requirement: 图片缓存与预生成
系统 SHALL 缓存处理后的 QPixmap，并在后台预生成下一张图片的缩略图，避免切图时主线程卡顿。

#### Scenario: 命中缓存
- WHEN 同一张图以相同尺寸/选项再次显示（如切回上一张）
- THEN 直接从缓存读取 QPixmap，不重跑 PIL 管线

#### Scenario: 后台预生成
- WHEN 当前显示第 N 张
- THEN 后台线程预生成第 N+1 张的 QPixmap，切换时立即可用

#### Scenario: 缓存上限
- WHEN 缓存条目超过 50 张
- THEN 系统按 LRU 淘汰最久未用的条目，内存不无限增长

### Requirement: 开机自启动
系统 SHALL 支持开机自启动，通过设置窗口开关，写/删注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `CoupleSuite` 键。

#### Scenario: 开启自启
- WHEN 用户在设置窗口勾选"开机自启动"并保存
- THEN 注册表写入对应键值，下次开机自动启动应用

#### Scenario: 关闭自启
- WHEN 用户取消勾选并保存
- THEN 注册表对应键被删除

### Requirement: 数据备份与恢复
系统 SHALL 支持将相框图片目录与信箱 data 打包为 zip 导出，并支持从 zip 恢复。

#### Scenario: 导出备份
- WHEN 用户点"导出备份"
- THEN 系统弹出保存对话框，生成 `CoupleSuite_backup_YYYYMMDD.zip`，含 images/、data/、configs

#### Scenario: 恢复备份
- WHEN 用户点"恢复备份"并选择 zip
- THEN 系统解压并覆盖当前数据（覆盖前提示确认），恢复后刷新相框与信箱

### Requirement: 多相册分组
系统 SHALL 支持多个图片目录（相册），托盘菜单可切换当前轮播的相册。

#### Scenario: 添加相册
- WHEN 用户在设置窗口点"添加相册"并选择目录
- THEN 该目录加入相册列表，托盘"切换相册"子菜单出现新项

#### Scenario: 切换相册
- WHEN 用户在托盘子菜单选另一相册
- THEN 相框立即切换到该相册轮播

### Requirement: 首次运行引导
系统 SHALL 在首次运行（检测到无 config.json）时弹出引导窗口，设置双方昵称、图片目录、可选对方 IP。

#### Scenario: 完成引导
- WHEN 用户填完昵称、选好图片目录、点完成
- THEN 配置写入，相框与信箱按配置启动

#### Scenario: 跳过引导
- WHEN 用户点"跳过"
- THEN 用默认值启动，后续可在设置窗口修改

### Requirement: 统计看板
系统 SHALL 提供一个统计看板窗口，展示在一起天数、信件总数、未读数、照片数、下个纪念日倒计时。

#### Scenario: 查看看板
- WHEN 用户点托盘"📊 统计看板"
- THEN 弹出窗口显示：在一起 X 天（基于首个纪念日或自定义起始日）、信件 N 封（未读 M）、照片 P 张、距下个纪念日还有 D 天

### Requirement: EXE 打包
系统 SHALL 通过 PyInstaller 打包为 Windows exe（onedir 模式），包含应用图标与默认资源，可在未装 Python 的机器运行。

#### Scenario: 打包产物
- WHEN 执行 `pyinstaller couple_suite.spec`
- THEN 生成 `dist/CoupleSuite/CoupleSuite.exe`，双击可启动完整套件

#### Scenario: 无 Python 环境运行
- WHEN 在未安装 Python 的 Windows 机器双击 exe
- THEN 应用正常启动，托盘图标、相框、信箱均可用

## MODIFIED Requirements

### Requirement: 配置文件路径
配置文件 SHALL 存放在 `%APPDATA%\CoupleSuite\config\` 下（相框 `photo_frame.json`、信箱 `mailbox.json`、套件全局 `suite.json`），而非各包源码目录。`config.load()` / `config.save()` 自动指向新路径。

### Requirement: 统一托盘菜单
托盘菜单 SHALL 在原有"相框/信箱"两段基础上，新增"设置"、"切换相册 ▶"、"📊 统计看板"、"导出备份"、"恢复备份"菜单项。
