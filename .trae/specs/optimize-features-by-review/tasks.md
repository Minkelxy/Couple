# Tasks

## 阶段一:五子棋健壮性
- [x] Task 1: 五子棋和棋判定与结束流程
  - [x] 1.1: 在 `Gomoku/board_widget.py` `place_stone` 落子后,若 `_check_win` 返回 0 且 `len(_moves) == SIZE*SIZE`,设置 `_winner = 0` 并发出 `game_over` 信号
  - [x] 1.2: 在 `Gomoku/game_window.py` `_on_game_over` 中区分 `_winner == 0` 的和棋分支,UI 显示"和棋",保存对局历史
- [x] Task 2: 五子棋老协议 `kind == "move"` 兼容
  - [x] 2.1: 在 `Gomoku/game_window.py` `handle_partner_event` 中,对 `kind in ("gomoku_move", "move")` 走相同的 session/回合/坐标校验与落子流程
- [x] Task 3: 五子棋棋谱 JSONL 追加写与断线重连
  - [x] 3.1: 在 `Gomoku/store.py` 新增 `append_move(session_id, move_dict)` 追加写入 `<session_id>.jsonl`
  - [x] 3.2: 在 `Gomoku/game_window.py` 本地与对方落子成功后调用 `append_move`
  - [x] 3.3: 在 `Gomoku/store.py` 新增 `load_moves(session_id)` 读取 JSONL 回放棋盘
  - [x] 3.4: 对局结束时仍调用现有 `save_game` 保存全量归档
  - [x] 3.5: 新建对局时若存在同 session 的 JSONL,提供恢复入口(读取并回放)

## 阶段二:延时信件与纪念日
- [x] Task 4: 延时信件关机期间到期补通知
  - [x] 4.1: 在 `DesktopMailbox/notifier.py` `DueChecker.start` 中,不再把所有已到期信件无脑加入 `_already_notified`;改为仅对"已读"或"本次启动前已被处理过"的加入,对未读且未通知的到期信件正常发出 `letters_due`
  - [x] 4.2: 验证启动瞬间不会对历史已读信件重复通知
- [x] Task 5: 纪念日同年重复投递防护
  - [x] 5.1: 在 `DesktopMailbox/anniversary.py` sent_log key 计算中,新增基于 `(规范化 date + title)` 的稳定兜底 key;`anniv_id` 变更时仍能命中同年已投递记录

## 阶段三:图片处理
- [x] Task 6: EXIF 方向统一转置
  - [x] 6.1: 在 `DailyCheckin/checkin_window.py` `_pick_image` 中,`shutil.copy2` 前用 PIL 打开并 `ImageOps.exif_transpose` 后保存
  - [x] 6.2: 在 `DesktopPhotoFrame/gallery_window.py` `_ThumbWorker.run` 生成缩略图前调用 `exif_transpose`
- [x] Task 7: 解压炸弹保护
  - [x] 7.1: 在 `DesktopPhotoFrame/image_processor.py` 模块加载时设置 `Image.MAX_IMAGE_PIXELS = 50_000_000`
  - [x] 7.2: 在 `process_to_pil` 的 except 中捕获 `DecompressionBombError`,记录日志并跳过该图

## 阶段四:豆瓣爬虫
- [x] Task 8: 豆瓣抓取重试与 Referer
  - [x] 8.1: 在 `MovieBoard/scraper.py` `search_movie` 中包裹指数退避重试(最多 2 次,间隔 1s/2s),空结果或异常均触发重试
  - [x] 8.2: 在 `download_poster` 请求头中加入 `Referer: https://movie.douban.com/`
  - [x] 8.3: 区分网络异常与无结果,网络异常才重试

## 阶段五:数据可靠性
- [x] Task 9: 抽取 AtomicJsonStore 基类
  - [x] 9.1: 在 `common_utils.py` 新增 `AtomicJsonStore` 类,封装 `load/save/update/get/set`,内部用临时文件 + `os.replace` 原子写,模块级锁串行化读改写
  - [x] 9.2: 改造 `DesktopPhotoFrame/config.py` 使用 `AtomicJsonStore`
  - [x] 9.3: 改造 `DailyCheckin/store.py` 的 partner JSON 持久化使用 `AtomicJsonStore`
  - [x] 9.4: 改造 `MovieBoard/store.py` 的 partner_status JSON 持久化使用 `AtomicJsonStore`
  - [x] 9.5: 改造 `TravelMap/store.py` 使用 `AtomicJsonStore`
  - [x] 9.6: 改造 `Gomoku/store.py` 对局 JSON 保存使用原子写
- [x] Task 10: 云游标处理顺序修正
  - [x] 10.1: 在 `DesktopMailbox/sync.py` `_cloud_poll_loop` 中,将 `_save_cursor()` 移到 `for letter in letters: on_received(...)` 之后
- [x] Task 11: 数据迁移失败保护
  - [x] 11.1: 在 `migration.py` 各迁移步骤中,异常时 `log_exception` 并标记本次迁移失败
  - [x] 11.2: 仅当所有步骤成功才写 `.migrated` 标记

## 阶段六:同步防重放与幂等
- [x] Task 12: 签名摘要加入 nonce
  - [x] 12.1: 在 `identity.py` `sign_message` 中生成 `nonce = secrets.token_hex(8)` 写入 `meta["nonce"]`,并纳入 `_signing_digest` 哈希
  - [x] 12.2: `verify_message` 校验签名时 nonce 已在 meta 中参与摘要(无需额外校验逻辑,签名覆盖即可)
- [x] Task 13: 信件 message_id 幂等去重
  - [x] 13.1: 在 `identity.py` `sign_message` 中生成 `message_id = str(uuid.uuid4())` 写入 meta,纳入签名摘要
  - [x] 13.2: 在 `DesktopMailbox/letter_store.py` `write_letter` 中,若 meta 含 `message_id` 且本地已存在同 `message_id` 的信件,跳过写入
  - [x] 13.3: 在 `DesktopMailbox/letter_store.py` 维护 `message_id` 索引(可由 mailbox.json 派生)
- [x] Task 14: 接收端签名 LRU 去重
  - [x] 14.1: 在 `DesktopMailbox/sync.py` `SyncHub` 中维护 `_seen_sigs` LRU(容量 1024,基于签名 b64)
  - [x] 14.2: `on_received` 验签通过后先查 LRU,命中则丢弃,未命中则处理并加入 LRU
  - [x] 14.3: 在 `DesktopMailbox/cloud_sync.py` `_parse_one_inbound` 同样接入 LRU 去重

## 阶段七:五子棋窗口标志与心情曲线
- [x] Task 15: 五子棋窗口 `_destroyed` 标志修正
  - [x] 15.1: 在 `launcher.py` `open_gomoku` 中,新建/获取窗口时 `_destroyed` 初始设为 `False`
  - [x] 15.2: 仅在 `destroyed` 信号回调中置 `True`
- [x] Task 16: 心情曲线对方对照(补充功能)
  - [x] 16.1: 在 `DailyCheckin/store.py` 新增 `get_partner_recent(days=30)` 读取对方打卡记录
  - [x] 16.2: 在 `DailyCheckin/mood_chart.py` `update_data` 中同时绘制自己与对方两条折线,不同颜色 + 图例
  - [x] 16.3: 处理仅一方有数据的情况

## 阶段八:验证
- [x] Task 17: 手动验证与回归
  - [x] 17.1: 五子棋满盘触发和棋;老客户端消息可正常落子;断线重连回放
  - [x] 17.2: 关机期间到期信件启动后收到通知
  - [x] 17.3: 竖拍照片在打卡历史与画廊缩略图方向正确
  - [x] 17.4: 豆瓣搜索失败重试;海报下载带 Referer
  - [x] 17.5: 配置写入中途杀进程,重启后配置完整
  - [x] 17.6: 重放签名消息不产生重复信件/重复落子
  - [x] 17.7: 心情曲线显示双方对照

# Task Dependencies
- Task 12 → Task 14(nonce 签名是 LRU 去重的前提)
- Task 13 → Task 14(message_id 幂等与签名去重协同)
- Task 9 → Task 10、Task 11、Task 13(AtomicJsonStore 是其他可靠性的基础,但 Task 10/11/13 可并行,仅需 Task 9 先完成基类)
- Task 1、Task 2、Task 3 可并行(均属五子棋模块,但改动不同函数)
- Task 4、Task 5 可并行
- Task 6、Task 7 可并行
- Task 8 独立
- Task 15、Task 16 独立
