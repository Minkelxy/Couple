# Tasks

- [x] Task 1: SyncHub 协议扩展 — 类型路由与通用发送
  - [x] SubTask 1.1: DesktopMailbox/sync.py 的 SyncHub 新增 `event_received = Signal(str, dict, str, bytes, str)` 信号（type, meta, content, attachment, att_ext）
  - [x] SubTask 1.2: SyncHub.on_received 检查 meta.get("type")：无 type 或 type=="letter" 走原 letter 流程；其他 type emit event_received 信号
  - [x] SubTask 1.3: SyncHub 新增 `send_event(event_type, payload, attachment=None, att_ext="")` 方法：构造 meta={type:event_type, **payload, sent_at:now.isoformat()} 并调 send_async
  - [x] SubTask 1.4: 云轮询 _cloud_poll_loop 同样走新 on_received（type 路由生效）
  - [x] SubTask 1.5: 编译验证 sync.py 无语法错误

- [x] Task 2: launcher 集成 — hub 分发与事件路由器
  - [x] SubTask 2.1: launcher.py 把 hub 实例传递给 DailyCheckin/TravelMap/MovieBoard/MusicRadar/DesktopPhotoFrame 各模块窗口构造函数（新增 hub 参数）
  - [x] SubTask 2.2: launcher.py 连接 hub.event_received 到路由器函数：按 type 分发到各模块的 on_partner_event 方法
  - [x] SubTask 2.3: 各模块窗口新增 hub 属性（默认 None 兼容旧调用）
  - [x] SubTask 2.4: 启动后冒烟：hub 启动无报错，event_received 信号已连接

- [x] Task 3: 打卡互看
  - [x] SubTask 3.1: DailyCheckin/store.py 新增 partner_records 持久化（独立 JSON 文件 partner_checkins.json 或同表 source 字段）
  - [x] SubTask 3.2: DailyCheckin/checkin_window.py 保存打卡后调 hub.send_event("checkin", {date, mood, note, image_filename}, attachment=图片字节)（hub 为 None 时跳过）
  - [x] SubTask 3.3: DailyCheckin 模块新增 on_partner_event(meta, content, attachment) 方法：写入 partner_records
  - [x] SubTask 3.4: DailyCheckin/checkin_window.py 右侧新增"TA 的心情"侧栏：显示对方最近 7 天打卡（mood emoji + 备注）
  - [x] SubTask 3.5: DailyCheckin/calendar_widget.py 日历格子区分来源：自己粉色、对方蓝色

- [x] Task 4: 地图共建
  - [x] SubTask 4.1: TravelMap/store.py 新增 source 字段（self/partner），读写兼容
  - [x] SubTask 4.2: TravelMap/map_window.py 保存城市后调 hub.send_event("map", {city, lat, lng, note, photo_filename}, attachment=照片字节)
  - [x] SubTask 4.3: TravelMap 模块新增 on_partner_event：追加到本地 store（source=partner）
  - [x] SubTask 4.4: TravelMap/map_renderer.py 按 source 用不同颜色画点（self=粉色、partner=蓝色）
  - [x] SubTask 4.5: TravelMap/map_window.py 右上角新增图例（粉色=我、蓝色=TA）

- [x] Task 5: 相册共享
  - [x] SubTask 5.1: DesktopPhotoFrame/config.py 新增 partner_albums 列表配置项
  - [x] SubTask 5.2: DesktopPhotoFrame/gallery_window.py 网格窗口右键菜单新增"共享给 TA"
  - [x] SubTask 5.3: 共享时逐张调 hub.send_event("photo", {filename, album_name}, attachment=图片字节, att_ext=后缀)
  - [x] SubTask 5.4: DesktopPhotoFrame 模块新增 on_partner_event：存入 app_paths.DATA_DIR/shared_photos/，追加到 partner_albums
  - [x] SubTask 5.5: gallery_window.py 相册下拉新增"TA 共享"项，可浏览对方共享图片

- [x] Task 6: 电影板互看
  - [x] SubTask 6.1: MovieBoard/store.py 新增 partner_status 字段（dict: movie_id → {status, rating}）
  - [x] SubTask 6.2: MovieBoard/board_window.py 标记状态/评分后调 hub.send_event("movie", {movie_id, title, status, rating})
  - [x] SubTask 6.3: MovieBoard 模块新增 on_partner_event：更新 partner_status
  - [x] SubTask 6.4: board_window.py 列表项旁显示对方状态徽章（如"TA: 想看 ⭐8"）

- [x] Task 7: 音乐雷达互看
  - [x] SubTask 7.1: MusicRadar/store.py 新增 partner_radar 字段（存储对方雷达数据）
  - [x] SubTask 7.2: MusicRadar/radar_window.py 抓取完成后调 hub.send_event("music", {top_songs, top_artists, radar_dims})
  - [x] SubTask 7.3: MusicRadar 模块新增 on_partner_event：保存到 partner_radar
  - [x] SubTask 7.4: radar_window.py 新增"TA 的雷达"切换按钮，点击后只读显示对方雷达图

- [x] Task 8: 实时轻互动 — 想你了 + 在线状态
  - [x] SubTask 8.1: 新建 DesktopPhotoFrame/heart_popup.py：HeartPopup(QWidget) 无边框透明置顶，paintEvent 画粉色心形，QPropertyAnimation 3 秒淡出后 close
  - [x] SubTask 8.2: tray.py 新增"💞 想你了"菜单项 + send_heart 信号
  - [x] SubTask 8.3: launcher.py 连接 tray.send_heart → hub.send_event("ping", {kind: "miss_you"})
  - [x] SubTask 8.4: launcher.py 路由器收到 type=ping/kind=miss_you 时实例化 HeartPopup.show()
  - [x] SubTask 8.5: SyncHub 新增心跳：每 30 秒自动 send_event("ping", {kind: "heartbeat"})（仅 cloud/both 模式）
  - [x] SubTask 8.6: 托盘图标旁新增在线状态小圆点 widget：收到对方 heartbeat 后 60 秒内显示绿色，否则灰色
  - [x] SubTask 8.7: 路由器收到 type=ping/kind=heartbeat 时更新 last_heartbeat 时间戳，不弹窗

- [x] Task 9: 联机五子棋
  - [x] SubTask 9.1: 新建 Gomoku/ 包：__init__.py / board_widget.py / game_window.py / store.py
  - [x] SubTask 9.2: Gomoku/board_widget.py 实现 GomokuBoard(QWidget)：15×15 棋盘绘制、点击落子、黑白交替、五连胜负判定（横/竖/斜）
  - [x] SubTask 9.3: Gomoku/store.py 实现对局历史持久化：save_game(winner, moves, played_at)、list_games()、get_game(id)
  - [x] SubTask 9.4: Gomoku/game_window.py 实现 GameWindow(QMainWindow)：嵌入棋盘 + 工具栏（悔棋/重新开局/对局历史）+ 状态栏（当前轮次/提示）
  - [x] SubTask 9.5: 落子后调 hub.send_event("gomoku_move", {row, col, color})；收到对方 gomoku_move 自动落子
  - [x] SubTask 9.6: 悔棋流程：点悔棋 → 发 gomoku_ctrl/undo_request → 对方弹对话框 → 同意发 undo_approve（双方各退一步）/ 拒绝发 undo_reject
  - [x] SubTask 9.7: 重新开局：发 gomoku_ctrl/restart，双方清空棋盘黑先手
  - [x] SubTask 9.8: 打开棋局时发 gomoku_ctrl/open，对方未开窗口则自动打开
  - [x] SubTask 9.9: 对局历史窗口：列出历史对局（时间/胜负/步数），点击可只读回放棋谱
  - [x] SubTask 9.10: 胜负判定后锁定棋盘 + 自动保存到历史记录
  - [x] SubTask 9.11: tray.py 新增"♟ 五子棋"菜单项 + open_gomoku 信号
  - [x] SubTask 9.12: launcher.py 连接 tray.open_gomoku → 按需创建 GameWindow（含 hub 实例）

- [x] Task 10: 验证与冒烟测试
  - [x] SubTask 10.1: 编译全部修改文件通过
  - [x] SubTask 10.2: SyncHub.send_event 发送后对方 event_received 信号正确 emit（type 路由正确）
  - [x] SubTask 10.3: 打卡保存后对方日历右侧"TA 的心情"显示，日历格子颜色区分正确
  - [x] SubTask 10.4: 地图添加城市后对方地图显示蓝色标注，图例正确
  - [x] SubTask 10.5: 画廊右键共享后对方"TA 共享"相册出现图片
  - [x] SubTask 10.6: 电影板评分后对方列表项显示状态徽章
  - [x] SubTask 10.7: 音乐雷达抓取后对方"TA 的雷达"按钮可切换查看
  - [x] SubTask 10.8: 点"想你了"后对方桌面浮出心形动画 3 秒消散
  - [x] SubTask 10.9: 在线状态小圆点：对方心跳后变绿，60 秒后变灰
  - [x] SubTask 10.10: 五子棋：我方落子后对方棋盘同步落子，五连判定正确，胜负锁定
  - [x] SubTask 10.11: 五子棋：悔棋请求/应答流程正常
  - [x] SubTask 10.12: 五子棋：重新开局双方棋盘清空，对局历史可回放
  - [x] SubTask 10.13: 向后兼容：收到无 type 的旧信件仍走 letter 流程

# Task Dependencies
- Task 1 是基础（SyncHub 协议扩展），所有其他任务依赖它
- Task 2 依赖 Task 1（launcher 路由器需要 event_received 信号）
- Task 3-9 依赖 Task 2（各模块需要 hub 实例和路由器连接）
- Task 10 依赖 Task 1-9 全部完成
- 并行组：Task 3+4+5+6+7+8+9 在 Task 2 完成后可并行（各模块独立）
