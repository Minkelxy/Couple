# 情侣套件四大新模块 Spec

## Why
情侣套件已有相框和信箱两个模块。之前规划的 6 个情侣项目点子中，打卡日历、影视追剧看板、旅行地图、听歌情绪雷达尚未实现。将这 4 个模块融入统一套件，使应用从"相框+信箱"升级为全方位情侣互动平台，覆盖日常打卡、共同观影、旅行记录、音乐共鸣四大场景。

## What Changes
- 新增「情侣打卡日历」模块：每日心情打卡（emoji+一句话+可选图片）、连续打卡天数、日历视图、心情曲线
- 新增「双人影视追剧看板」模块：想看/在看/看完三栏列表、评分短评、海报抓取（Playwright）、年度观影报告长图（Pillow）、双人评分对比
- 新增「情侣旅行地图」模块：在中国地图上标注去过的城市、附照片日期故事、解锁城市数、路线动画、愿望地图
- 新增「听歌情绪雷达」模块：抓取网易云最近听歌记录（Playwright）、情绪/曲风雷达图、共同 BGM、"今天你 vs 我"对照
- 统一托盘菜单新增 4 个分区：日历 / 影视 / 地图 / 音乐
- 每个模块作为独立包，数据存放在 AppData 对应子目录
- 打包配置更新 hiddenimports 和数据文件

## Impact
- Affected specs: 统一托盘菜单、AppData 数据目录、PyInstaller 打包
- Affected code:
  - 新增 `DailyCheckin/` 包（__init__.py, store.py, checkin_window.py, calendar_widget.py, mood_chart.py）
  - 新增 `MovieBoard/` 包（__init__.py, store.py, board_window.py, scraper.py, report_generator.py）
  - 新增 `TravelMap/` 包（__init__.py, store.py, map_window.py, map_renderer.py, city_picker.py）
  - 新增 `MusicRadar/` 包（__init__.py, store.py, scraper.py, radar_window.py, mood_analyzer.py）
  - 修改 `tray.py`（新增 4 个分区菜单和信号）
  - 修改 `launcher.py`（接入 4 个新模块窗口）
  - 修改 `couple_suite.spec`（新增 hiddenimports）
- 新增 AppData 子目录：checkin/、movies/、travel/、music/

## ADDED Requirements

### Requirement: 情侣打卡日历
系统 SHALL 提供每日心情打卡功能，用户可选择心情 emoji、写一句话、可选附图，系统记录打卡并计算连续天数。

#### Scenario: 每日打卡
- WHEN 用户在日历窗口点"今日打卡"
- THEN 弹出打卡编辑器，可选 5 种心情 emoji（😊😍😢😡😴）、写一句话、可选附图
- AND 保存后日历当天显示该 emoji，连续打卡天数 +1

#### Scenario: 日历视图
- WHEN 用户打开打卡日历窗口
- THEN 显示当月日历，已打卡日期显示对应 emoji，未打卡日期为空
- AND 可切换月份查看历史

#### Scenario: 心情曲线
- WHEN 用户点"查看心情趋势"
- THEN 显示最近 30 天的心情曲线图（emoji 映射为 1-5 分）

#### Scenario: 补卡
- WHEN 用户点击过去某天空白日期
- THEN 允许补卡（仅允许补过去 7 天内的日期）

### Requirement: 双人影视追剧看板
系统 SHALL 提供共同影视管理看板，分"想看/在看/看完"三栏，支持评分、短评、海报抓取。

#### Scenario: 添加影视
- WHEN 用户点"添加"并输入片名
- THEN 系统用 Playwright 抓取豆瓣海报和简介，加入"想看"栏

#### Scenario: 移动状态
- WHEN 用户把某部影视拖到"在看"或"看完"栏
- THEN 该影视状态更新，移到对应栏

#### Scenario: 评分与短评
- WHEN 用户对"看完"的影视点评分（1-10）并写短评
- THEN 评分和短评保存，看板显示双人评分对比（若双方都评过）

#### Scenario: 年度观影报告
- WHEN 用户点"生成年度报告"
- THEN 用 Pillow 生成一张长图，含已看数量、评分最高、类型分布、双人评分差异最大的影片

### Requirement: 情侣旅行地图
系统 SHALL 在中国地图上标注两人一起去过的城市，附照片、日期、故事，显示已解锁城市数。

#### Scenario: 添加城市
- WHEN 用户点"添加城市"并从预置城市列表选择
- THEN 地图上该城市出现标记，弹出编辑框填日期、故事、可选照片

#### Scenario: 地图渲染
- WHEN 用户打开旅行地图窗口
- THEN 显示中国地图底图，去过的城市显示粉色标记，未来想去的显示蓝色标记
- AND 底部显示"已解锁 N 个城市"

#### Scenario: 城市详情
- WHEN 用户点击地图上某城市标记
- THEN 弹出详情卡片，显示日期、故事、照片

#### Scenario: 路线动画
- WHEN 用户点"播放路线"
- THEN 按时间顺序在地图上依次点亮城市，连线显示旅行路线

### Requirement: 听歌情绪雷达
系统 SHALL 抓取网易云最近听歌记录，生成情绪/曲风雷达图，找出共同 BGM。

#### Scenario: 抓取听歌记录
- WHEN 用户点"更新听歌数据"并输入网易云用户 ID
- THEN 系统用 Playwright 抓取最近播放记录，缓存到本地

#### Scenario: 情绪雷达图
- WHEN 用户打开听歌雷达窗口
- THEN 显示六维雷达图（欢快/忧伤/激昂/舒缓/电子/民谣），双人数据叠加对比

#### Scenario: 共同 BGM
- WHEN 双方数据都已抓取
- THEN 系统找出两人都听过的歌曲列表，显示在"共同 BGM"区

#### Scenario: 今日对照
- WHEN 用户点"今天的你 vs 我"
- THEN 显示双方最近 24 小时听歌情绪对比卡片

### Requirement: 统一托盘菜单扩展
托盘菜单 SHALL 在原有相框/信箱/工具三段基础上，新增日历/影视/地图/音乐四个分区，每段含对应入口菜单项。

## MODIFIED Requirements

### Requirement: AppData 数据目录
AppData 下新增 4 个子目录：`checkin/`（打卡数据）、`movies/`（影视数据+海报缓存）、`travel/`（旅行数据+照片）、`music/`（听歌缓存）。`app_paths.ensure_dirs()` 创建这些目录。

### Requirement: PyInstaller 打包
`couple_suite.spec` 的 hiddenimports 新增 4 个包的所有子模块；excludes 中不再排除 matplotlib（旅行地图和心情曲线需要）。
