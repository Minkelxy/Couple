# 基于评审的功能优化与补充 Spec

## Why
项目评审发现多项用户可感知的功能缺陷(五子棋满盘卡死、老协议无法对弈、竖拍照片横躺、延时信件静默丢失通知、豆瓣抓取失败即放弃)以及数据可靠性问题(JSON 非原子写导致配置损坏、云游标先存后处理导致崩溃丢信、同步无防重放/幂等导致重复信件与重复落子)。本 spec 聚焦这些直接影响用户体验的功能层问题,不涉及纯架构重构(拆 AppController、抽公共函数)与纯安全加固(DPAPI、TLS、限流、密钥轮换)——后者留作后续独立 spec。

## What Changes
- 五子棋:新增和棋判定与和棋信号;兼容老协议 `kind == "move"`;落子追加写入棋谱 JSONL 以支持断线重连恢复
- 延时信件:启动时对"关机期间到期且尚未通知过"的信件补发通知;纪念日当天首次启动若已过投递时间则立即补投递(已有逻辑保留),并修复 `anniv_id` 变更导致同年重复投递
- 图片处理:统一 EXIF 方向转置(打卡照片、画廊缩略图);新增 `Image.MAX_IMAGE_PIXELS` 解压炸弹保护
- 豆瓣爬虫:搜索/海报下载新增 2 次指数退避重试;海报下载补 `Referer` 头
- 五子棋窗口:`_destroyed` 标志初始值修正为 `False`,销毁时才置 `True`,消除每次打开重复弹"如何开启"对话框
- 数据可靠性:抽取 `common_utils.AtomicJsonStore` 基类,统一 5 处 JSON 持久化为原子写;云游标改为处理完所有信件后再保存
- 同步防重放与幂等:签名摘要加入 nonce;接收端维护"已见过签名"LRU 去重;信件落盘按 `message_id` 幂等去重
- 数据迁移:`migration` 失败时不写 `.migrated` 标记并记录日志,避免数据永久丢失
- 心情曲线(**补充功能**):新增对方心情曲线对照显示

## Impact
- Affected specs: 五子棋对弈、信箱延时投递、纪念日提醒、相册图片处理、影视看板抓取、同步协议、打卡心情图表
- Affected code:
  - `Gomoku/board_widget.py`、`Gomoku/game_window.py`、`Gomoku/store.py`
  - `DesktopMailbox/notifier.py`、`DesktopMailbox/anniversary.py`、`DesktopMailbox/letter_store.py`、`DesktopMailbox/sync.py`、`DesktopMailbox/cloud_sync.py`
  - `DailyCheckin/checkin_window.py`、`DailyCheckin/mood_chart.py`、`DailyCheckin/store.py`
  - `DesktopPhotoFrame/gallery_window.py`、`DesktopPhotoFrame/image_processor.py`
  - `MovieBoard/scraper.py`
  - `TravelMap/store.py`、`DesktopPhotoFrame/config.py`、`MovieBoard/store.py`
  - `common_utils.py`、`identity.py`、`migration.py`、`launcher.py`

## ADDED Requirements

### Requirement: 五子棋和棋判定
系统 SHALL 在每次落子后检查棋盘是否已满且无胜负,若满盘无胜则触发和棋结束流程,发出 `game_over` 信号并保存对局历史,避免用户卡在满盘状态。

#### Scenario: 棋盘下满无胜负
- **WHEN** 第 225 手落子后 `_check_win` 返回 0 且 `len(_moves) == 225`
- **THEN** 设置 `_winner = 0`(和棋标记),发出 `game_over` 信号,保存对局历史,UI 显示"和棋"

#### Scenario: 正常胜负不受影响
- **WHEN** 落子后 `_check_win` 返回非 0
- **THEN** 沿用现有胜负流程,不触发和棋判定

### Requirement: 五子棋老协议兼容
系统 SHALL 兼容接收 `kind == "move"` 的旧版客户端消息,将其视为 `gomoku_move` 处理,避免老客户端升级后无法对弈。

#### Scenario: 接收老客户端走子
- **WHEN** 收到 `kind == "move"` 的事件
- **THEN** 按 `gomoku_move` 相同的 session/回合/坐标校验流程处理,正常落子

### Requirement: 五子棋棋谱追加持久化
系统 SHALL 在每次落子后以追加(JSONL)方式写入当前对局棋谱文件,使断线重连或应用崩溃后可恢复最近棋盘状态。

#### Scenario: 落子追加写入
- **WHEN** 本地或对方落子成功
- **THEN** 将 `{session_id, color, row, col, ts, source}` 一行 JSON 追加写入 `gomoku/<session_id>.jsonl`
- **AND** 对局结束时仍保存全量 moves 作为最终归档

#### Scenario: 断线重连恢复
- **WHEN** 对局进行中应用重启并重新建立同步
- **THEN** 读取对应 session 的 JSONL 回放最近棋盘状态(若存在)

### Requirement: 延时信件关机期间到期补通知
系统 SHALL 在应用启动时识别"到期时间早于本次启动时间且尚未通知过"的信件,并对其发出到期通知,而非静默吞掉。

#### Scenario: 关机期间到期的信件
- **WHEN** 应用启动且存在 `deliver_at <= now` 且 `read == false` 且未在 `_already_notified` 中的信件
- **THEN** 对这些信件发出 `letters_due` 信号触发通知( toast + 读信窗口),而非仅更新托盘未读数

#### Scenario: 启动瞬间已到期但用户已读
- **WHEN** 信件 `read == true`
- **THEN** 不发出通知(沿用现有行为)

### Requirement: 纪念日同年重复投递防护
系统 SHALL 在纪念日 `anniv_id` 变更(如用户编辑 id 字段或删除 id 回退到 date)后,仍按纪念日内容防同年重复投递,而非因 sent_log key 变化导致同年再次投递。

#### Scenario: anniv_id 变更后同年不再重复
- **WHEN** 同一纪念日内容在同年内因 id 变更导致 sent_log key 不匹配
- **THEN** 通过基于 `(规范化 date + title)` 的稳定 key 兜底去重,跳过同年重复投递

### Requirement: 图片 EXIF 方向统一转置
系统 SHALL 在所有展示用户照片的入口(相册处理、画廊缩略图、打卡照片)统一调用 `ImageOps.exif_transpose`,避免竖拍照片横躺显示。

#### Scenario: 打卡照片竖拍
- **WHEN** 用户选择竖拍带 Orientation 标签的打卡照片
- **THEN** 保存前先做 EXIF 转置,历史中显示方向正确

#### Scenario: 画廊缩略图竖拍
- **WHEN** 缩略图 worker 处理竖拍照片
- **THEN** 生成缩略图前做 EXIF 转置,网格中方向正确

### Requirement: 解压炸弹保护
系统 SHALL 设置 `Image.MAX_IMAGE_PIXELS` 上限,在解码超大图前抛出 `DecompressionBombError`,避免 OOM 崩溃。

#### Scenario: 用户放入超大原图
- **WHEN** 用户照片目录含 100MP+ 原图
- **THEN** 解码时抛出受控异常并被捕获,跳过该图并记录日志,应用不崩溃

### Requirement: 豆瓣抓取重试与 Referer
系统 SHALL 对豆瓣搜索与海报下载实施指数退避重试(最多 2 次),并为海报下载补充 `Referer` 头,提升抓取成功率。

#### Scenario: 豆瓣返回空页面
- **WHEN** 搜索结果页解析为空
- **THEN** 间隔递增后重试最多 2 次;全部失败才返回 None

#### Scenario: 海报 CDN 请求
- **WHEN** 下载海报
- **THEN** 请求头包含 `Referer: https://movie.douban.com/`,降低 403 概率

### Requirement: JSON 持久化原子写
系统 SHALL 通过 `common_utils.AtomicJsonStore` 基类为所有 JSON 配置/数据存储提供原子写(临时文件 + `os.replace`),避免断电或崩溃导致文件半写损坏。

#### Scenario: 写入中途崩溃
- **WHEN** 写入过程中应用崩溃或断电
- **THEN** 目标文件保持上一个完整版本,下次加载正常

#### Scenario: 并发读改写
- **WHEN** 多处调用同一 store 的 update
- **THEN** 通过模块级锁串行化读改写,不丢失更新

### Requirement: 云游标处理顺序保证
系统 SHALL 在成功处理完一批信件后再保存云游标,避免处理过程中崩溃导致信件永久丢失。

#### Scenario: 处理中信件异常
- **WHEN** `on_received` 处理某封信时抛异常
- **THEN** 游标未前进,下次轮询重新拉取该批信件(已落盘的由幂等去重处理)

### Requirement: 同步消息防重放与幂等
系统 SHALL 在签名摘要中加入随机 nonce,接收端对"已见过签名"做 LRU 去重,并对信件落盘按 `message_id` 幂等去重,防止重放导致重复信件或重复落子。

#### Scenario: 重放已见过的签名消息
- **WHEN** 接收端收到签名已在 LRU 缓存中的消息
- **THEN** 直接丢弃,不落盘、不触发事件

#### Scenario: 重放信件
- **WHEN** 收到 `message_id` 已存在于本地的信件
- **THEN** 跳过落盘,不产生重复信件

#### Scenario: 重放五子棋走子
- **WHEN** 收到 nonce 已见过的 `gomoku_move`
- **THEN** 丢弃,不重复落子

### Requirement: 数据迁移失败保护
系统 SHALL 在迁移步骤失败时不写入 `.migrated` 标记文件并记录异常日志,确保下次启动可重新尝试迁移,避免数据永久丢失。

#### Scenario: 迁移步骤抛异常
- **WHEN** 任一迁移步骤抛出异常
- **THEN** 记录 `log_exception`,不写 `.migrated` 标记,下次启动重新尝试

### Requirement: 心情曲线对方对照(补充)
系统 SHALL 在心情曲线图表中同时绘制自己与对方的最近心情趋势,以不同颜色区分,便于情侣对照。

#### Scenario: 双方都有打卡记录
- **WHEN** 自己与对方在近 30 天均有心情打卡
- **THEN** 同一图表绘制两条折线,图例标注"我"与"对方"

#### Scenario: 仅一方有记录
- **WHEN** 仅自己或仅对方有记录
- **THEN** 仅绘制有数据的一方,不报错

## MODIFIED Requirements

### Requirement: 五子棋窗口生命周期
五子棋窗口的 `_destroyed` 标志初始值 SHALL 为 `False`,仅在窗口实际销毁时置 `True`,使"如何开启"对话框仅在首次打开时弹出。

### Requirement: 云端轮询游标管理
云端轮询 SHALL 在 `on_received` 处理完所有信件后才调用 `_save_cursor`,而非处理前保存。

### Requirement: 信件签名摘要
信件签名摘要 SHALL 在原有 `canon_meta + content + attachment + att_ext` 基础上加入 `meta.nonce` 字段参与哈希,且 `nonce` 由发送方生成并随消息传输。

### Requirement: 信件元数据
信件元数据 SHALL 新增 `message_id` 字段(发送方生成的 UUID),用于接收端幂等去重;该字段参与签名摘要。

## REMOVED Requirements
无。
