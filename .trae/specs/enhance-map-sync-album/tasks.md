# Tasks

- [x] Task 1: 修复地图城市照片持久化存储
  - [x] SubTask 1.1: TravelMap/map_window.py 的 _EditCityDialog._pick_photo：选择照片后用 shutil.copy2 复制到 app_paths.TRAVEL_DIR/"photos"，文件名用 `f"{int(time.time())}_{Path(path).name}"`，存储相对文件名（仅文件名，非完整路径）
  - [x] SubTask 1.2: _EditCityDialog.__init__ 加载已有 image_path 时，若为纯文件名则拼接 `app_paths.TRAVEL_DIR/"photos"/filename` 得到完整路径用于显示
  - [x] SubTask 1.3: _DetailDialog 显示照片时同样从 AppData 拼接路径
  - [x] SubTask 1.4: store.add/update 存储 image_path 时保持纯文件名（不存完整路径）

- [x] Task 2: 修复打卡附图持久化存储
  - [x] SubTask 2.1: DailyCheckin/checkin_window.py 的打卡编辑器选图后复制到 app_paths.CHECKIN_DIR/"images"，存储纯文件名
  - [x] SubTask 2.2: 打卡编辑器加载已有附图时从 AppData 拼接路径显示
  - [x] SubTask 2.3: store.add_or_update 的 image_path 字段保持纯文件名

- [x] Task 3: 云中转同步 — 数据层与配置
  - [x] SubTask 3.1: DesktopMailbox/config.py 新增配置项：sync_mode（"lan"/"cloud"/"both"，默认 "lan"）、cloud_server（如 https://couple-relay.example.com）、cloud_pair_code（情侣配对码，双方填相同码）、cloud_poll_interval_sec（默认 30）
  - [x] SubTask 3.2: settings_window.py 同步标签页：新增模式单选（局域网/云中转/两者），云模式下显示服务器地址和配对码输入框

- [x] Task 4: 云中转同步 — 客户端实现
  - [x] SubTask 4.1: 新建 DesktopMailbox/cloud_sync.py：CloudSyncClient 类，含 send_letter(meta, content, attachment, att_ext) 和 poll_letters() 方法
  - [x] SubTask 4.2: send_letter 用 urllib.request 向 `{server}/api/send` POST JSON（meta+content_base64+attachment_base64+pair_code），失败返回 False 不抛异常
  - [x] SubTask 4.3: poll_letters 用 urllib.request 向 `{server}/api/poll?pair_code={code}&since={last_ts}` GET，返回新信件列表
  - [x] SubTask 4.4: 云服务器协议设计：响应 JSON 格式 {ok: bool, letters: [{meta, content, attachment_base64, attachment_ext}], server_ts: str}

- [x] Task 5: 云中转同步 — SyncHub 集成
  - [x] SubTask 5.1: DesktopMailbox/sync.py 的 SyncHub 新增 cloud_client 属性，根据 sync_mode 初始化
  - [x] SubTask 5.2: SyncHub.send_async 在 sync_mode 含 cloud 时调用 cloud_client.send_letter
  - [x] SubTask 5.3: SyncHub.start 在 sync_mode 含 cloud 时启动轮询定时器（threading.Timer 循环），每 cloud_poll_interval_sec 调 poll_letters，收到信件调 on_received
  - [x] SubTask 5.4: SyncHub.stop 停止云轮询定时器

- [x] Task 6: 全屏画廊窗口
  - [x] SubTask 6.1: 新建 DesktopPhotoFrame/gallery_window.py：GalleryWindow(QMainWindow)，全屏无边框，照片居中 contain 显示
  - [x] SubTask 6.2: 键盘事件：→/↓/空格下一张，←/↑上一张，ESC 关闭，滚轮 1.0~3.0 缩放
  - [x] SubTask 6.3: 顶部悬浮工具栏（鼠标移动显示，3 秒无操作隐藏）：上一张/下一张/网格浏览/退出按钮
  - [x] SubTask 6.4: 底部显示当前索引/总数 + 文件名

- [x] Task 7: 缩略图网格浏览
  - [x] SubTask 7.1: gallery_window.py 新增 GalleryGridWindow(QMainWindow)：QListWidget 网格模式（IconSize 200x200，4 列）
  - [x] SubTask 7.2: 顶部相册下拉选择器（QComboBox），切换相册刷新网格
  - [x] SubTask 7.3: 双击某张打开 GalleryWindow 全屏显示该图

- [x] Task 8: 托盘与 launcher 集成画廊
  - [x] SubTask 8.1: tray.py 相框区新增"🖼 画廊浏览…"菜单项 + open_gallery 信号
  - [x] SubTask 8.2: launcher.py 连接 open_gallery 信号，按需创建 GalleryGridWindow 复用

- [x] Task 9: 验证与冒烟测试
  - [x] SubTask 9.1: 编译全部修改文件通过
  - [x] SubTask 9.2: 地图：添加城市选照片→原图删除→详情仍显示照片
  - [x] SubTask 9.3: 打卡：添加附图→原图删除→打卡记录仍显示附图
  - [x] SubTask 9.4: 云同步配置可保存，模式切换 UI 正确显示/隐藏
  - [x] SubTask 9.5: CloudSyncClient 在服务器不可达时优雅返回 False 不崩溃
  - [x] SubTask 9.6: 画廊窗口全屏打开，键盘切换正常，ESC 退出
  - [x] SubTask 9.7: 缩略图网格显示当前相册所有照片，双击全屏
  - [x] SubTask 9.8: 托盘"画廊浏览"菜单项可打开网格窗口

# Task Dependencies
- Task 2 独立（可与 Task 1 并行）
- Task 3 依赖无（配置先行）
- Task 4 依赖 Task 3
- Task 5 依赖 Task 4
- Task 6 独立
- Task 7 依赖 Task 6
- Task 8 依赖 Task 7
- Task 9 依赖 Task 1-8 全部完成
- 并行组：Task 1+2（数据修复）/ Task 3+4+5（云同步）/ Task 6+7+8（画廊）三组可并行
