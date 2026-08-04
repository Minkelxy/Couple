# 跨模块联机互动 Spec

## Why
当前联机同步只服务于信箱一条通道（SyncHub.send_async 仅在 compose_window 被调用），其余 5 大模块（打卡/地图/电影/音乐/相册）全部单机，情侣互动性弱。SyncHub 协议本身是通用的（meta+content+attachment 任意 JSON），扩展其他模块联动只需复用同一通道加 `meta.type` 字段，无需重写同步底层。

## What Changes
- **SyncHub 协议扩展**：`meta.type` 字段区分消息类型（`letter`/`checkin`/`map`/`movie`/`music`/`photo`/`ping`），收方按 type 路由到不同处理函数；保持向后兼容（无 type 视为 letter）
- **打卡互看**：打卡保存后自动 sync 一条 `type=checkin` 消息（mood/note/date/image），对方收到后写入本地 store 并在日历右上角"TA 的心情"侧栏展示
- **地图共建**：城市标注保存后 sync 一条 `type=map` 消息（city/lat/lng/note/photo），对方收到后追加到本地 store 并以不同颜色标注（自己粉、对方蓝），地图右上角图例区分
- **相册共享**：相册目录右键"共享给 TA"将图片批量 sync（`type=photo`，每张一条），对方收到后存入 `AppData/SharedPhotos/{pair_code}/` 并自动加入"TA 共享"相册
- **电影板互看**：标记想看/已看/评分后 sync `type=movie`（movie_id/title/my_status/my_rating），对方收到后在自己的电影板对应条目旁显示对方状态徽章
- **音乐雷达互看**：年度雷达抓取完成后 sync `type=music`（top5 歌曲/歌手/雷达维度），对方收到后可在自己雷达窗口点"TA 的雷达"切换查看
- **实时轻互动**：托盘新增"💞 想你了"按钮，点击向对方发 `type=ping, kind=miss_you`，对方收到后桌面浮出一个粉色心形动画 3 秒后消散；附带在线状态指示（托盘图标旁小圆点：绿=最近 60 秒心跳、灰=离线）
- **联机五子棋**：新增 Gomoku 模块，15×15 棋盘，双方通过 SyncHub 实时同步落子（`type=gomoku_move`），支持悔棋请求/应答（`type=gomoku_ctrl`）、胜负判定、对局历史记录；托盘新增"♟ 五子棋"菜单项打开游戏窗口

## Impact
- Affected specs: 信箱同步、打卡、旅行地图、相册、电影板、音乐雷达、托盘、五子棋
- Affected code:
  - 修改 `DesktopMailbox/sync.py`（SyncHub 新增 type 路由 + `event_received` 信号 + `send_event` 通用方法）
  - 修改 `DesktopMailbox/cloud_sync.py`（meta 字段透传 type，无协议变更）
  - 修改 `launcher.py`（启动时把 hub 分发给各模块窗口 + 连接 event_received 到路由器）
  - 修改 `DailyCheckin/store.py`（新增 partner_records 表/字段区分来源）
  - 修改 `DailyCheckin/checkin_window.py`（保存后调 hub.send_event + 右侧"TA 心情"侧栏）
  - 修改 `DailyCheckin/calendar_widget.py`（自己的打卡粉色、对方的蓝色区分）
  - 修改 `TravelMap/store.py`（新增 source 字段：self/partner）
  - 修改 `TravelMap/map_window.py`（保存后 sync + 收到 partner 城市追加显示，蓝色标注）
  - 修改 `TravelMap/map_renderer.py`（按 source 用不同颜色画点）
  - 修改 `DesktopPhotoFrame/config.py`（新增 partner_albums 列表）
  - 修改 `DesktopPhotoFrame/gallery_window.py`（相册下拉新增"TA 共享"项 + 右键共享菜单）
  - 修改 `MovieBoard/store.py`（新增 partner_status 字段）
  - 修改 `MovieBoard/board_window.py`（评分后 sync + 列表项显示对方状态徽章）
  - 修改 `MusicRadar/store.py`（新增 partner_radar 字段）
  - 修改 `MusicRadar/radar_window.py`（抓取后 sync + "TA 的雷达"切换按钮）
  - 修改 `tray.py`（新增"💞 想你了"菜单项 + 在线状态小圆点 widget + "♟ 五子棋"菜单项）
  - 新增 `DesktopPhotoFrame/heart_popup.py`（收到 miss_you 时桌面浮心动画）
  - 新增 `Gomoku/` 包（__init__.py / board_widget.py / game_window.py / store.py），实现 15×15 棋盘、落子同步、悔棋、胜负判定、对局历史

## ADDED Requirements

### Requirement: 同步消息类型路由
SyncHub SHALL 在 meta 中支持 `type` 字段区分消息类型，收方按 type 路由到对应模块的处理器。无 type 字段时视为 `letter`（向后兼容）。

#### Scenario: 收到带 type 的消息
- **WHEN** SyncHub.on_received 收到 meta 含 `type=checkin`
- **THEN** 不写 letter_store，而是 emit `event_received(type, meta, content, attachment)` 信号
- **AND** 由 launcher 中注册的路由器分发到 DailyCheckin 模块

#### Scenario: 向后兼容旧信件
- **WHEN** 收到的 meta 没有 type 字段
- **THEN** 走原 letter 流程（letter_store.write_letter + letter_received 信号）

### Requirement: 通用事件发送方法
SyncHub SHALL 提供 `send_event(event_type: str, payload: dict, attachment: bytes = None, att_ext: str = "")` 方法，自动构造 `{type: event_type, **payload}` 的 meta 并复用现有 lan/cloud 通道发送。

#### Scenario: 调用 send_event
- **WHEN** 模块调用 `hub.send_event("checkin", {"date": "2026-08-03", "mood": 5})`
- **THEN** SyncHub 走 send_async 同样流程，meta 含 `type=checkin` + payload 字段

### Requirement: 打卡互看
打卡保存后系统 SHALL 自动同步给对方，对方收到后在自己的日历右侧栏看到"TA 的心情"。

#### Scenario: 我打卡后对方看到
- **WHEN** 我完成打卡保存
- **THEN** 系统调 `hub.send_event("checkin", {date, mood, note, image_filename})`（附图可选）
- **AND** 对方 SyncHub 收到 event_received(type=checkin)
- **AND** 对方 DailyCheckin.store 写入 partner_records 表
- **AND** 对方日历右侧"TA 的心情"侧栏显示对方今日 mood + 备注

#### Scenario: 区分自己与对方打卡
- **WHEN** 日历展示某日打卡
- **THEN** 自己的打卡用粉色背景、对方的用蓝色背景，区分来源

### Requirement: 地图共建
城市标注保存后 SHALL 同步给对方，对方地图上以不同颜色显示该城市。

#### Scenario: 我添加城市对方看到
- **WHEN** 我添加一个城市标注（含照片）
- **THEN** 系统调 `hub.send_event("map", {city, lat, lng, note, photo_filename})`
- **AND** 对方收到后追加到本地 store（source=partner）
- **AND** 对方地图上该城市用蓝色标注（自己的仍用粉色）

#### Scenario: 地图图例
- **WHEN** 地图窗口打开
- **THEN** 右上角显示图例：粉色=我、蓝色=TA

### Requirement: 相册共享
用户 SHALL 能将本地相册图片批量共享给对方，对方收到后自动加入"TA 共享"相册。

#### Scenario: 共享相册
- **WHEN** 我在画廊网格窗口右键某相册选"共享给 TA"
- **THEN** 系统逐张调 `hub.send_event("photo", {filename, album_name}, attachment=图片字节)`
- **AND** 对方收到后存入 `%APPDATA%\CoupleSuite\shared_photos\{pair_code}\`
- **AND** 对方相册下拉新增"TA 共享"项，可浏览这些图片

### Requirement: 电影板互看
标记电影状态/评分后 SHALL 同步给对方，对方电影板对应条目旁显示对方状态徽章。

#### Scenario: 我标记电影想看
- **WHEN** 我把某电影标为"想看"或打分
- **THEN** 系统调 `hub.send_event("movie", {movie_id, title, status, rating})`
- **AND** 对方收到后在自己的电影板该条目旁显示徽章（如"TA: 想看 ⭐8"）

### Requirement: 音乐雷达互看
年度雷达抓取完成后 SHALL 同步给对方，对方可切换查看我的雷达。

#### Scenario: 我抓取雷达后对方查看
- **WHEN** 我的音乐雷达完成抓取
- **THEN** 系统调 `hub.send_event("music", {top_songs, top_artists, radar_dims})`
- **AND** 对方雷达窗口出现"TA 的雷达"切换按钮
- **AND** 点击后显示我的雷达图（只读）

### Requirement: 实时轻互动 — 想你了
托盘 SHALL 提供"💞 想你了"菜单项，点击后对方桌面浮出粉色心形动画。

#### Scenario: 发送想你了
- **WHEN** 我点托盘"💞 想你了"
- **THEN** 系统调 `hub.send_event("ping", {kind: "miss_you"})`
- **AND** 对方收到后桌面中央浮出一个粉色心形 QWidget，3 秒淡出消散

### Requirement: 在线状态指示
托盘 SHALL 显示对方在线状态小圆点（基于最近 60 秒心跳）。

#### Scenario: 对方在线
- **WHEN** 对方 60 秒内向我们发过任意消息（含心跳）
- **THEN** 我方托盘旁显示绿色小圆点

#### Scenario: 对方离线
- **WHEN** 对方超过 60 秒无消息
- **THEN** 小圆点变灰

### Requirement: 联机五子棋
系统 SHALL 提供联机五子棋模块，15×15 棋盘，双方通过 SyncHub 实时同步落子，支持悔棋请求/应答、胜负判定、对局历史记录。

#### Scenario: 打开棋局
- **WHEN** 用户点托盘"♟ 五子棋"
- **THEN** 打开 Gomoku 窗口，显示 15×15 空棋盘
- **AND** 自动向对方发 `type=gomoku_ctrl, kind=open`（对方若未开窗口则收到后自动打开）

#### Scenario: 落子同步
- **WHEN** 当前轮到我，我在棋盘空位点击
- **THEN** 本地落子（黑棋），调 `hub.send_event("gomoku_move", {row, col, color: "black"})`
- **AND** 对方收到后自动落同位置黑棋，轮到对方
- **AND** 对方落子后发 `gomoku_move`（白棋），我方收到自动落子

#### Scenario: 胜负判定
- **WHEN** 任一方落子后形成五连（横/竖/斜）
- **THEN** 弹出胜负提示"黑/白胜！"
- **AND** 锁定棋盘不可再落子
- **AND** 自动保存对局到历史记录（含最终棋谱）

#### Scenario: 悔棋请求
- **WHEN** 我点"悔棋"按钮
- **THEN** 向对方发 `type=gomoku_ctrl, kind=undo_request`
- **AND** 对方弹出"TA 想悔棋，同意吗？"对话框
- **AND** 对方点"同意"→ 发 `gomoku_ctrl, kind=undo_approve`，双方各退一步
- **AND** 对方点"拒绝"→ 发 `gomoku_ctrl, kind=undo_reject`，我方收到提示

#### Scenario: 重新开局
- **WHEN** 任一方点"重新开局"
- **THEN** 向对方发 `gomoku_ctrl, kind=restart`
- **AND** 双方棋盘清空，黑先手

#### Scenario: 对局历史
- **WHEN** 用户在 Gomoku 窗口点"对局历史"
- **THEN** 显示历史对局列表（时间、胜负、步数）
- **AND** 点击某局可回看棋谱（只读回放）

#### Scenario: 对方未在线时落子
- **WHEN** 我落子后对方未在线（无心跳）
- **THEN** 落子仍 sync 出去（云中转暂存），对方上线轮询到后自动落子
- **AND** 棋盘提示"等待 TA 上线..."

## MODIFIED Requirements

### Requirement: SyncHub 信号
SyncHub SHALL 新增 `event_received = Signal(str, dict, str, bytes, str)` 信号（type, meta, content, attachment, att_ext），用于非 letter 类型的消息分发。原有 `letter_received` 信号保留不变。

### Requirement: launcher 启动流程
launcher SHALL 在启动时把 SyncHub 实例传递给各模块窗口（DailyCheckin/TravelMap/MovieBoard/MusicRadar/DesktopPhotoFrame/Gomoku），并连接 `event_received` 信号到各模块的事件处理函数。

## REMOVED Requirements
（无）
