# Checklist

## SyncHub 协议扩展
- [ ] SyncHub 新增 event_received = Signal(str, dict, str, bytes, str) 信号
- [ ] on_received 按 meta.type 路由：无 type/letter → letter 流程；其他 → emit event_received
- [ ] send_event(event_type, payload, attachment, att_ext) 方法实现
- [ ] 云轮询 _cloud_poll_loop 也走新 on_received 路由
- [ ] send_event 构造的 meta 含 type + payload + sent_at 字段
- [ ] 向后兼容：无 type 的旧消息仍走 letter_store 流程

## launcher 集成
- [ ] launcher 把 hub 实例传递给各模块窗口构造函数
- [ ] launcher 连接 hub.event_received 到路由器函数
- [ ] 路由器按 type 分发到各模块 on_partner_event
- [ ] 各模块窗口 hub 属性默认 None 兼容旧调用

## 打卡互看
- [ ] store.py 新增 partner_records 持久化
- [ ] checkin_window.py 保存后调 hub.send_event("checkin", ...)
- [ ] DailyCheckin 新增 on_partner_event 写入 partner_records
- [ ] 右侧"TA 的心情"侧栏显示对方最近 7 天打卡
- [ ] 日历格子区分：自己粉色、对方蓝色

## 地图共建
- [ ] store.py 新增 source 字段（self/partner）
- [ ] map_window.py 保存城市后调 hub.send_event("map", ...)
- [ ] TravelMap 新增 on_partner_event 追加到本地 store
- [ ] map_renderer.py 按 source 用不同颜色画点
- [ ] 右上角图例显示（粉色=我、蓝色=TA）

## 相册共享
- [ ] config.py 新增 partner_albums 配置项
- [ ] gallery_window.py 网格窗口右键"共享给 TA"菜单
- [ ] 共享时逐张调 hub.send_event("photo", ...)
- [ ] DesktopPhotoFrame 新增 on_partner_event 存入 shared_photos
- [ ] 相册下拉新增"TA 共享"项

## 电影板互看
- [ ] store.py 新增 partner_status 字段
- [ ] board_window.py 标记后调 hub.send_event("movie", ...)
- [ ] MovieBoard 新增 on_partner_event 更新 partner_status
- [ ] 列表项旁显示对方状态徽章

## 音乐雷达互看
- [ ] store.py 新增 partner_radar 字段
- [ ] radar_window.py 抓取后调 hub.send_event("music", ...)
- [ ] MusicRadar 新增 on_partner_event 保存到 partner_radar
- [ ] "TA 的雷达"切换按钮可只读查看对方雷达

## 实时轻互动
- [ ] heart_popup.py 实现 HeartPopup 粉色心形 3 秒淡出
- [ ] tray.py 新增"💞 想你了"菜单项 + send_heart 信号
- [ ] launcher 连接 send_heart → hub.send_event("ping", {kind: "miss_you"})
- [ ] 路由器收到 ping/miss_you 时实例化 HeartPopup.show()
- [ ] SyncHub 每 30 秒自动发心跳（cloud/both 模式）
- [ ] 托盘旁在线状态小圆点 widget
- [ ] 收到 heartbeat 后 60 秒内绿色，否则灰色
- [ ] 路由器收到 ping/heartbeat 不弹窗只更新时间戳

## 联机五子棋
- [ ] Gomoku/ 包结构完整（__init__/board_widget/game_window/store）
- [ ] GomokuBoard 实现 15×15 棋盘绘制与点击落子
- [ ] 黑白交替落子，五连胜负判定（横/竖/斜）正确
- [ ] store.py 实现对局历史持久化（save/list/get）
- [ ] GameWindow 嵌入棋盘 + 工具栏（悔棋/重新开局/对局历史）+ 状态栏
- [ ] 落子后调 hub.send_event("gomoku_move", {row, col, color})
- [ ] 收到对方 gomoku_move 自动落子
- [ ] 悔棋流程：undo_request → 对方弹框 → undo_approve/undo_reject
- [ ] 重新开局：发 gomoku_ctrl/restart，双方清空黑先手
- [ ] 打开棋局发 gomoku_ctrl/open，对方未开窗口自动打开
- [ ] 对局历史窗口可只读回放棋谱
- [ ] 胜负判定后锁定棋盘 + 自动保存历史
- [ ] tray.py 新增"♟ 五子棋"菜单项 + open_gomoku 信号
- [ ] launcher 连接 open_gomoku → 按需创建 GameWindow（含 hub）

## 验证
- [ ] 编译全部修改文件通过
- [ ] SyncHub.send_event 后对方 event_received 正确 emit
- [ ] 打卡互看：对方日历右侧显示 TA 心情，格子颜色区分
- [ ] 地图共建：对方地图蓝色标注，图例正确
- [ ] 相册共享：对方"TA 共享"相册出现图片
- [ ] 电影板：对方列表项显示状态徽章
- [ ] 音乐雷达：对方"TA 的雷达"可切换
- [ ] 想你了：对方桌面浮心 3 秒消散
- [ ] 在线状态：心跳后变绿，60 秒后变灰
- [ ] 五子棋落子同步：我方落子后对方棋盘同步
- [ ] 五子棋五连判定正确，胜负后棋盘锁定
- [ ] 五子棋悔棋请求/应答流程正常
- [ ] 五子棋重新开局双方清空，对局历史可回放
- [ ] 向后兼容：无 type 旧信件仍走 letter 流程
