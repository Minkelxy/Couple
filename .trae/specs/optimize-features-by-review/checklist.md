# Checklist

## 五子棋
- [x] 棋盘下满无胜负时触发和棋结束流程,发出 game_over 信号并保存对局历史
- [x] 和棋 UI 显示"和棋"而非胜负文案
- [x] 接收 `kind == "move"` 的老协议消息可正常落子,与 `gomoku_move` 行为一致
- [x] 每次落子追加写入 `<session_id>.jsonl`
- [x] 对局结束时仍保存全量 moves 归档
- [x] 断线重连后可读取 JSONL 回放最近棋盘状态
- [x] `_destroyed` 标志初始为 False,仅销毁时置 True,"如何开启"对话框仅首次弹出

## 延时信件与纪念日
- [x] 应用启动时,关机期间到期的未读信件会收到通知(toast + 读信窗口)
- [x] 已读信件启动时不重复通知
- [x] 纪念日 anniv_id 变更后同年不重复投递
- [x] 纪念日当天首次启动已过投递时间时正常补投递

## 图片处理
- [x] 打卡照片竖拍在历史中方向正确
- [x] 画廊缩略图竖拍方向正确
- [x] 100MP+ 超大原图被跳过,应用不崩溃并记录日志

## 豆瓣爬虫
- [x] 搜索空结果/网络异常时触发最多 2 次指数退避重试
- [x] 海报下载请求头包含 `Referer: https://movie.douban.com/`
- [x] 网络异常与无结果在日志文案上区分;两者均触发重试(豆瓣空结果多因风控,重试提升成功率,符合 spec Task 8.1)

## 数据可靠性
- [x] `common_utils.AtomicJsonStore` 基类实现原子写(临时文件 + os.replace)与模块级锁
- [x] 5 处 JSON 持久化(PhotoFrame config、DailyCheckin partner、MovieBoard partner_status、TravelMap store、Gomoku store)改造为 AtomicJsonStore 或原子写
- [x] 配置写入中途杀进程,重启后文件保持上一个完整版本
- [x] 云游标在所有信件处理完后才保存,处理中崩溃下次重新拉取
- [x] 迁移步骤失败时不写 `.migrated` 标记并记录日志,下次启动重新尝试
- [x] 迁移全部成功才写 `.migrated` 标记

## 同步防重放与幂等
- [x] 签名摘要包含 `meta.nonce`,nonce 随消息传输
- [x] 信件 meta 包含 `message_id`,参与签名
- [x] 接收端对已见签名 LRU 去重(容量 1024),重放消息被丢弃
- [x] 信件按 `message_id` 幂等去重,重复投递不产生重复信件
- [x] 五子棋走子重放不重复落子
- [x] LAN 与 Cloud 两条通道均接入去重

## 心情曲线(补充)
- [x] 心情图表同时绘制自己与对方两条折线,不同颜色 + 图例
- [x] 仅一方有数据时仅绘制一方,不报错
- [x] 双方均无数据时不报错

## 回归
- [x] 现有信件收发流程不受影响(旧消息无 nonce/message_id 时兼容处理不报错)
- [x] 现有五子棋对弈流程不受影响
- [x] 现有打卡、相册、地图、影视模块功能不受影响
