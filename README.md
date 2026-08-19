# 桌面相册

一款常驻系统托盘的桌面伴侣应用，集相册轮播、信箱、打卡日历、影视看板、旅行地图、五子棋于一体。支持双机局域网/云中转同步，让两台电脑像在身边一样。

## 功能一览

| 模块 | 说明 |
|------|------|
| 桌面相册 | 透明置顶窗口轮播照片，支持拍立得边框、日期水印、Ken Burns 动画、模糊背景填充、滚轮缩放、双击重置 |
| 画廊浏览 | 网格浏览所有相册，右键共享当前相册给对方 |
| 信箱 | 写信、延时投递、收件箱、附件加密存储（Fernet），支持纪念日自动提醒 |
| 打卡日历 | 月历打卡、心情曲线、连续打卡统计、对方打卡侧栏 |
| 影视看板 | 豆瓣抓取海报/简介、评分记录、对比报告（可选 Playwright 抓取） |
| 旅行地图 | 中国省级边界离线地图（DataV GeoJSON）、城市标记、足迹图层、对方共享 |
| 五子棋 | 双人对战、悔棋、同步走子 |
| 想你了 | 一键向对方发送心跳通知 |

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+（开发用；运行打包版无需 Python）

### 开发运行

```bash
pip install PySide6 Pillow cryptography matplotlib
python launcher.py
```

首次运行会弹出引导窗口，设置昵称、照片目录、可选同步。

### 打包

```bash
pip install pyinstaller
python -m PyInstaller couple_suite.spec --noconfirm
```

产物在 `dist/CoupleSuite/`，双击 `CoupleSuite.exe` 即可运行。

## 同步方式

支持三种模式，在「设置 → 同步」中切换：

### 1. 局域网直连（lan）

两台电脑连同一 WiFi，互相填对方 IP。默认端口 52014。

- 优点：零配置、零延迟、零成本
- 缺点：必须同一局域网

### 2. 云中转（cloud）

部署一个轻量 HTTP 中转服务器（`relay_server.py`），双机通过配对码收发。

```bash
pip install -r relay-requirements.txt
python relay_server.py                         # 开发
COUPLE_RELAY_DB=/srv/couple/letters.db gunicorn --workers 2 --bind 127.0.0.1:5000 relay_server:app
```

Ubuntu 生产部署模板位于 `deploy/`，包括 systemd 服务、环境变量示例和 nginx 反向代理配置。推荐流程：

```bash
sudo useradd --system --home /opt/couple-relay --shell /usr/sbin/nologin couple-relay
sudo install -d -o couple-relay -g couple-relay /opt/couple-relay /var/lib/couple-relay
sudo cp relay_server.py relay_backup.py relay-requirements.txt /opt/couple-relay/
sudo python3 -m venv /opt/couple-relay/.venv
sudo /opt/couple-relay/.venv/bin/pip install -r /opt/couple-relay/relay-requirements.txt
sudo install -d -o couple-relay -g couple-relay /var/backups/couple-relay
sudo chown -R couple-relay:couple-relay /opt/couple-relay /var/lib/couple-relay /var/backups/couple-relay
sudo install -m 0644 deploy/couple-relay.service /etc/systemd/system/couple-relay.service
sudo install -m 0644 deploy/couple-relay-backup.service /etc/systemd/system/couple-relay-backup.service
sudo install -m 0644 deploy/couple-relay-backup.timer /etc/systemd/system/couple-relay-backup.timer
sudo install -m 0600 deploy/couple-relay.env.example /etc/couple-relay.env
sudo systemctl daemon-reload
sudo systemctl enable --now couple-relay
sudo systemctl enable --now couple-relay-backup.timer
```

服务只监听 `127.0.0.1:5000`，公网访问应经过 nginx + HTTPS；`/health` 可用于 systemd 外部监控和 nginx 上游检查。备份 timer 每日使用 SQLite online backup 创建一致副本，默认保留最近 14 份。生产环境不要开启 legacy `pair_code` 模式。

恢复备份前必须停止 relay，避免运行中的连接重新生成旧 WAL 文件：

```bash
sudo systemctl stop couple-relay
sudo /opt/couple-relay/.venv/bin/python /opt/couple-relay/relay_backup.py restore \
  /var/backups/couple-relay/letters-YYYYMMDD-HHMMSS.db
sudo systemctl start couple-relay
```

Ubuntu 服务器建议把 `COUPLE_RELAY_DB` 指向持久化数据盘，并使用 nginx + HTTPS 反向代理。配对会话和信件都保存在 SQLite；配对状态不依赖单个 Gunicorn worker，服务重载或 worker 切换不会中断两台 Windows 客户端的配对流程。
旧版 `pair_code` 接口默认关闭；仅在迁移旧客户端时临时设置 `COUPLE_RELAY_ALLOW_LEGACY_PAIR_CODE=1`，迁移完成后应立即移除。

接口约定：

- `POST /api/send` — 发送信件
- `GET /api/poll?pair_code={code}&since={ts}` — 增量拉取
- `GET /health` — 健康检查

详见 [relay_server.py](relay_server.py) 文档字符串。生产环境建议套 nginx + HTTPS。

### 3. 双模式（both）

同时启用局域网和云中转，优先走局域网，失败回退云端。

## 目录结构

```
Couple/
├── launcher.py              # 统一入口
├── tray.py                  # 统一托盘控制器
├── app_paths.py             # %APPDATA%/CoupleSuite 路径管理
├── onboarding.py            # 首次运行引导
├── settings_window.py       # 设置窗口
├── stats_window.py          # 统计看板
├── backup.py                # 导出/恢复备份
├── migration.py             # 旧数据迁移
├── relay_server.py          # 云中转服务器（Flask）
├── couple_suite.spec        # PyInstaller 配置
├── DesktopPhotoFrame/       # 桌面相册模块
├── DesktopMailbox/          # 信箱模块（含同步）
├── DailyCheckin/            # 打卡日历模块
├── MovieBoard/              # 影视看板模块
├── TravelMap/               # 旅行地图模块
├── Gomoku/                  # 五子棋模块
└── assets/
    ├── china_geo.json       # 中国省级边界 GeoJSON
    ├── default_album/       # 内置示例相册
    └── icon.ico             # 应用图标
```

## 数据存储

所有用户数据存放在 `%APPDATA%/CoupleSuite/`：

| 路径 | 内容 |
|------|------|
| `config/` | 各模块配置 JSON |
| `data/letters/` | 加密信件 |
| `images/` | 默认照片目录 |
| `checkin/` | 打卡记录 |
| `movies/` | 影视数据 + 海报 |
| `travel/` | 地图城市标记 |
| `cache/` | 缓存 |

可通过托盘菜单「导出备份」打包全部数据，「恢复备份」还原。

## 技术栈

- **GUI**: PySide6 (Qt6)
- **绘图**: QPainter 自绘地图、matplotlib 雷达图/曲线
- **地图数据**: DataV.GeoAtlas 省级边界 GeoJSON（离线）
- **加密**: cryptography.fernet（信件附件）
- **同步**: TCP socket（局域网）+ HTTP（云中转）
- **打包**: PyInstaller onedir

## 许可

私有项目，未公开发布。
