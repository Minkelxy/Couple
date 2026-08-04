# Tasks

- [x] Task 1: 建立统一应用数据目录基础设施
  - [x] SubTask 1.1: 新建 `app_paths.py`，定义 `%APPDATA%\CoupleSuite\` 下子目录结构（config/、data/、images/、cache/）
  - [x] SubTask 1.2: 实现首次启动旧数据迁移逻辑（迁移 DesktopPhotoFrame/config.json、DesktopMailbox/data 到 AppData，写 `.migrated` 标记）

- [x] Task 2: 改造两个 config.py 指向 AppData 路径
  - [x] SubTask 2.1: `DesktopPhotoFrame/config.py` 的 CONFIG_PATH 改为 app_paths 下的 `config/photo_frame.json`，默认 image_dir 改为 AppData 下 images
  - [x] SubTask 2.2: `DesktopMailbox/config.py` 的 CONFIG_PATH/DATA_DIR 改为 app_paths 下路径
  - [x] SubTask 2.3: launcher.py 接入 app_paths 初始化（ensure_dirs + 迁移）

- [x] Task 3: 实现图片缓存层
  - [x] SubTask 3.1: 在 image_processor.py 加 `PixmapCache`（LRU，上限 50），按 (path, w, h, polaroid, watermark, corner, kb, accent) 做 key
  - [x] SubTask 3.2: process_image 先查缓存命中则直接返回，未命中才跑管线并写入缓存
  - [x] SubTask 3.3: frame_window 切图后用线程后台预生成下一张 PIL Image 入缓存

- [x] Task 4: 实现设置窗口
  - [x] SubTask 4.1: 新建 `settings_window.py`，含标签页：相框/信箱/同步/纪念日/通用
  - [x] SubTask 4.2: 相框页：轮播间隔、窗口尺寸、边框/水印/Ken Burns/滚轮缩放开关、主题色、纪念日列表、相册管理（增删切换）
  - [x] SubTask 4.3: 信箱页：双方昵称、检查间隔
  - [x] SubTask 4.4: 同步页：启用开关、对方 IP/端口、本机端口
  - [x] SubTask 4.5: 通用页：开机自启动开关；保存按钮触发各组件即时生效（重载配置、重启 SyncHub、重启定时器）

- [x] Task 5: 实现开机自启动
  - [x] SubTask 5.1: 新建 `autostart.py`，提供 enable()/disable()/is_enabled()，操作注册表 HKCU Run 键
  - [x] SubTask 5.2: 设置窗口通用页绑定自启动开关状态

- [x] Task 6: 实现数据备份与恢复
  - [x] SubTask 6.1: 新建 `backup.py`，export_backup() 把 images/ + data/ + configs 打包 zip（文件名带日期）
  - [x] SubTask 6.2: restore_backup(zip_path) 解压覆盖（覆盖前 QMessageBox 确认），恢复后通知 launcher 刷新

- [x] Task 7: 实现多相册分组
  - [x] SubTask 7.1: 相框 config 加 `albums: list[{name, path}]`，`image_dir` 改为当前选中相册的 path
  - [x] SubTask 7.2: 托盘加"切换相册 ▶"子菜单，动态列出相册，选中切换
  - [x] SubTask 7.3: 设置窗口相册管理：添加（选目录+命名）、删除、设为当前

- [x] Task 8: 实现首次运行引导
  - [x] SubTask 8.1: 新建 `onboarding.py`，检测无 suite.json 时弹出引导窗口
  - [x] SubTask 8.2: 引导步骤：昵称 → 图片目录 →（可选）对方 IP → 完成/跳过
  - [x] SubTask 8.3: launcher.py 启动时检查并触发引导

- [x] Task 9: 实现统计看板
  - [x] SubTask 9.1: 新建 `stats_window.py`，计算在一起天数（取首个纪念日或 suite.json 的 together_since）、信件总数、未读数、照片数、下个纪念日倒计时
  - [x] SubTask 9.2: 托盘加"📊 统计看板"菜单项打开窗口

- [x] Task 10: 扩展统一托盘菜单
  - [x] SubTask 10.1: tray.py 新增菜单项：设置、切换相册子菜单、统计看板、导出备份、恢复备份
  - [x] SubTask 10.2: launcher.py 连接新菜单信号到对应窗口/功能

- [x] Task 11: PyInstaller 打包为 exe
  - [x] SubTask 11.1: 生成应用图标 `assets/icon.ico`（爱心图标）
  - [x] SubTask 11.2: 编写 `couple_suite.spec`（onedir，entry=launcher.py，含 PySide6/Pillow/cryptography hiddenimports，icon，excludes 减少体积）
  - [x] SubTask 11.3: 打包并验证 dist/CoupleSuite/CoupleSuite.exe 可启动

- [x] Task 12: 验证与冒烟测试
  - [x] SubTask 12.1: 编译全部 .py 通过
  - [x] SubTask 12.2: 启动 launcher.py 无运行时错误，相框+信箱+托盘正常
  - [x] SubTask 12.3: 设置窗口改配置后即时生效（间隔/同步/自启动）
  - [x] SubTask 12.4: 缓存命中验证（LRU 50 上限淘汰生效）
  - [x] SubTask 12.5: 备份导出+恢复回环验证
  - [x] SubTask 12.6: exe 启动验证正常无报错

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 独立（可与 Task 4-9 并行）
- Task 4 依赖 Task 2（配置路径就绪）
- Task 5 独立
- Task 6 依赖 Task 2（数据路径就绪）
- Task 7 依赖 Task 2
- Task 8 依赖 Task 2
- Task 9 依赖 Task 2
- Task 10 依赖 Task 4、6、7、9（菜单项指向已实现功能）
- Task 11 依赖 Task 1-10 全部完成
- Task 12 依赖 Task 11
