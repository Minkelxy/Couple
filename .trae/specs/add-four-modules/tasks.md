# Tasks

- [x] Task 1: 基础设施 — app_paths 扩展 + 4 个包骨架
  - [x] SubTask 1.1: app_paths.py 新增 checkin/movies/travel/music 四个子目录定义，ensure_dirs() 创建
  - [x] SubTask 1.2: 创建 DailyCheckin/、MovieBoard/、TravelMap/、MusicRadar/ 四个包，各含 __init__.py

- [x] Task 2: 情侣打卡日历 — 数据层
  - [x] SubTask 2.1: DailyCheckin/store.py：SQLite 存储打卡记录（date, mood, text, image_path），含 add/get_by_date/get_range/get_streak 方法
  - [x] SubTask 2.2: 心情 emoji 映射：😊=5 😍=4 😢=3 😡=2 😴=1

- [x] Task 3: 情侣打卡日历 — UI 层
  - [x] SubTask 3.1: DailyCheckin/calendar_widget.py：月历组件，已打卡日期显示 emoji，可切换月份
  - [x] SubTask 3.2: DailyCheckin/checkin_window.py：主窗口含日历 + 今日打卡按钮 + 打卡编辑器（emoji 选择+一句话+附图）
  - [x] SubTask 3.3: DailyCheckin/mood_chart.py：最近 30 天心情曲线（matplotlib 嵌 QWidget）
  - [x] SubTask 3.4: 连续打卡天数显示 + 补卡（仅过去 7 天）

- [x] Task 4: 双人影视追剧看板 — 数据层
  - [x] SubTask 4.1: MovieBoard/store.py：SQLite 存储（title, status, poster_path, rating, review, douban_id, added_at）
  - [x] SubTask 4.2: 状态枚举：want/watching/watched

- [x] Task 5: 双人影视追剧看板 — 抓取与报告
  - [x] SubTask 5.1: MovieBoard/scraper.py：Playwright 抓豆瓣搜索结果（海报 URL + 简介 + 豆瓣 ID），下载海报到 movies/posters/
  - [x] SubTask 5.2: MovieBoard/report_generator.py：Pillow 生年度观影报告长图（数量/最高分/类型分布/评分差异）

- [x] Task 6: 双人影视追剧看板 — UI 层
  - [x] SubTask 6.1: MovieBoard/board_window.py：三栏布局（想看/在看/看完），每项含海报缩略图+标题+评分
  - [x] SubTask 6.2: 添加影视对话框（输入片名→抓取→预览→确认添加）
  - [x] SubTask 6.3: 右键菜单：移动状态/评分短评/删除；评分对比显示
  - [x] SubTask 6.4: "生成年度报告"按钮

- [x] Task 7: 情侣旅行地图 — 数据层
  - [x] SubTask 7.1: TravelMap/store.py：JSON 存储（city_name, lat, lng, date, story, image_path, type: visited/wish）
  - [x] SubTask 7.2: TravelMap/city_picker.py：预置中国主要城市列表（名称+经纬度），搜索选择

- [x] Task 8: 情侣旅行地图 — 渲染与 UI
  - [x] SubTask 8.1: TravelMap/map_renderer.py：Pillow 在中国底图上绘制城市标记（粉色=去过，蓝色=愿望），返回 QPixmap
  - [x] SubTask 8.2: TravelMap/map_window.py：主窗口含地图 + 底部统计 + 添加城市按钮 + 路线动画播放
  - [x] SubTask 8.3: 点击城市标记弹出详情卡片（日期/故事/照片）
  - [x] SubTask 8.4: 路线动画：按时间顺序依次点亮城市并连线

- [x] Task 9: 听歌情绪雷达 — 数据层
  - [x] SubTask 9.1: MusicRadar/store.py：JSON 缓存听歌记录（song, artist, play_count, timestamp）
  - [x] SubTask 9.2: MusicRadar/mood_analyzer.py：根据歌名/歌手关键词推断情绪维度（欢快/忧伤/激昂/舒缓/电子/民谣）

- [x] Task 10: 听歌情绪雷达 — 抓取与 UI
  - [x] SubTask 10.1: MusicRadar/scraper.py：Playwright 抓网易云用户最近听歌记录（需用户 ID）
  - [x] SubTask 10.2: MusicRadar/radar_window.py：六维雷达图（matplotlib）双人叠加 + 共同 BGM 列表 + 今日对照卡片
  - [x] SubTask 10.3: "更新听歌数据"按钮（输入网易云用户 ID）

- [x] Task 11: 统一托盘与 launcher 集成
  - [x] SubTask 11.1: tray.py 新增 4 个分区菜单（日历/影视/地图/音乐），各含一个打开窗口菜单项 + 4 个信号
  - [x] SubTask 11.2: launcher.py 接入 4 个新模块窗口，连接信号，窗口按需创建复用

- [x] Task 12: PyInstaller 打包更新
  - [x] SubTask 12.1: couple_suite.spec 新增 4 个包的 hiddenimports，移除 matplotlib 的 excludes
  - [x] SubTask 12.2: 重新打包验证 exe 可启动且 4 个模块窗口可打开

- [x] Task 13: 验证与冒烟测试
  - [x] SubTask 13.1: 编译全部新文件通过
  - [x] SubTask 13.2: launcher.py 启动无运行时错误，托盘含 4 个新区
  - [x] SubTask 13.3: 打卡日历：打卡→日历显示→心情曲线渲染
  - [x] SubTask 13.4: 影视看板：添加→抓取→三栏移动→评分
  - [x] SubTask 13.5: 旅行地图：添加城市→地图标记→详情卡片
  - [x] SubTask 13.6: 听歌雷达：雷达图渲染（无抓取也能用模拟数据）

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 2
- Task 4 依赖 Task 1
- Task 5 依赖 Task 4（独立于 Task 6，可并行）
- Task 6 依赖 Task 4
- Task 7 依赖 Task 1
- Task 8 依赖 Task 7
- Task 9 依赖 Task 1
- Task 10 依赖 Task 9
- Task 11 依赖 Task 3、6、8、10（所有模块就绪后集成）
- Task 12 依赖 Task 11
- Task 13 依赖 Task 12
- 并行组：Task 2+3 / Task 4+5+6 / Task 7+8 / Task 9+10 四组可并行
